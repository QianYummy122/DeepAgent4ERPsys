# AgentToMotorcycleERP — 摩托车零部件采购 ERP 与 AI 采购智能体

![alt text](展示图.jpeg)

本仓库是一个「传统 ERP 后端 + AI 采购智能体」的学习用工程：用 Spring Boot 实现摩托车零部件采购的业务系统（供应商 / 零部件 / 采购订单 / 库存 / 客户 / 物流 / 统计），再在其之上叠加一个基于 DeepAgents + LangGraph 的 AI 采购助手，让用户用自然语言完成比价分析、行情调研、订单创建与修改。

```
用户  ──▶  Vue 3 聊天前端 ──▶  FastAPI (SSE 流式) ──▶  DeepAgent (LangGraph)
                                                          │
                                          ┌───────────────┼────────────────┐
                                          ▼               ▼                ▼
                                    ERP MCP 桥接     可视化 MCP        沙箱 (WSL/OpenSandbox)
                                          │          (26 种图表)      Python 数据分析
                                          ▼
                                  Spring Boot ERP 后端 ──▶ MySQL
```

---

## 一、仓库包含什么

仓库根目录下有两个相互独立、可分别运行、又通过 HTTP/MCP 协作的子项目。

| 目录 | 名称 | 角色 | 技术栈 |
|------|------|------|--------|
| [`MotorcyclePartsProcurementSystem/`](MotorcyclePartsProcurementSystem/) | 摩托车零部件采购管理系统 | 业务后端（系统 of record），提供 ERP 全部 REST 接口与 MySQL 数据 | Java 17 · Spring Boot 3.1.10 · MyBatis-Plus 3.5.3.1 · MySQL 8 · springdoc-openapi 2.0.2 |
| [`ERP_OPENCLAW/`](ERP_OPENCLAW/) | ERP 采购智能助手（OpenClaw） | AI 助手：对话编排、子 Agent 分工、MCP 工具调用、沙箱分析、前端聊天界面 | Python 3.10+ · DeepAgents · LangGraph 1.x · FastAPI · FastMCP · MongoDB · Vue 3 + Vite 5 |

**为什么拆成两个工程**：ERP 后端负责"数据正确"（事务、逻辑删除、统一响应契约），AI 助手负责"交互智能"（理解需求、多步分析、生成报告）。两者只通过 REST API 耦合，AI 侧永远不直连 MySQL——所有业务数据都经由 MCP 桥接调用 Java 接口获取，避免出现两套数据访问逻辑。

> 需要注意：ERP 后端的**自动建表不含外键**（只有手动执行 `docs/database_schema.sql` 时才建），因此"数据正确"目前主要靠应用层校验而非数据库约束。详见 [DATABASE.md](docs/DATABASE.md) §1.6。

> 仓库根目录还存在两处**非工程代码**内容：[`MotorcyclePartsProcurementSystem/ecommerce-demo/`](MotorcyclePartsProcurementSystem/ecommerce-demo/) 为纯静态前端演示页（不连后端，仅作 UI 参考），[`ERP_OPENCLAW/src/download/`](ERP_OPENCLAW/src/download/) 为智能体生成的历史分析报告样例。
>
> 另有两个易被误解的文件，均在 `ERP_OPENCLAW/` 下：`mcp工具列表.txt` 与 **`motorparts_db.sql`** —— 后者虽然叫 `.sql`，但**不是 SQL 文件也不是数据库导出**，两者内容同源，都是远程可视化 MCP 那 27 个 `generate_*` 工具的 Python `repr` 快照（含完整 JSON Schema），属诊断留存。

---

## 二、核心业务能力（ERP 后端）

| 模块 | 能力 |
|------|------|
| 供应商管理 | 档案 CRUD、按名称/状态/信用评级检索、合作状态与信用评级变更（A/B/C/D） |
| 零部件管理 | 档案 CRUD、按名称/分类/供应商检索、采购单价调整、按供应商反查零部件 |
| 采购订单 | 创建（自动汇总金额）、整体更新、逻辑删除、分页多条件查询、状态流转（1 待审核 → 2 已审核 → 3 采购中 → 4 已入库 / 5 已取消）、订单明细按零部件名 + 时间范围联表搜索 |
| 库存管理 | 入库/出库、安全库存维护、库存预警列表（`current_quantity < safety_stock`，严格小于）、库存盘点汇总（`/inventory/check` 的 `warningItems` 却用 `≤`，两处口径不一致） |
| 客户管理 | 档案 CRUD、客户类型（经销商/零售店/个人）、折扣等级、类型与折扣变更 |
| 物流管理 | 物流单 CRUD、按订单查询、状态更新、发货信息与收货信息登记 |
| 统计分析 | 仪表盘汇总、供应商分布、零部件分类与价格区间分布、库存状态分布、月度采购趋势 |

接口统一返回 `Result<T>`（`code` / `message` / `data` / `timestamp`），分页返回 `PageResult<T>`（`current` / `size` / `total` / `pages` / `records`）。共 **54 个 REST 端点**，覆盖 7 个控制器。

> 系统当前**没有认证与授权层**：无登录接口、无 Spring Security、无拦截器，所有端点匿名可访问（含下单与改库存）。定位为内部演示/教学系统，不可直接暴露公网。

详见 [API 接口文档](MotorcyclePartsProcurementSystem/docs/API_DOCUMENTATION.md) 与本文档集的 [API 参考](docs/API_REFERENCE.md)。

---

## 三、核心 AI 能力（ERP_OPENCLAW）

- **主从 Agent 编排**：主 Agent 只做"调度与对话"，把分析类任务委派给 `procurement-analyst`，把订单类任务委派给 `procurement-order`；子 Agent 定义在 YAML 中，新增/调整无需改代码。
- **MCP 工具桥接**：本地 FastMCP 服务把 Java REST 接口封装为 `supplier_query`、`part_query`、`part_search`、`part_by_supplier`、`order_search_details`、`order_create`、`order_update`、`inventory_warning` 共 8 个工具；远程可视化 MCP 提供 26 种图表，被合并为单一入口 `generate_visualization`。
- **代码执行沙箱**：`local`（本机 WSL 发行版）或 `opensandbox`（独立部署）两种模式，沙箱内预置 `numpy/pandas/matplotlib/requests/beautifulsoup4`，Agent 可写 Python 做真实数据分析。
- **双层 Human-in-the-Loop**：
  1. 数据补充中断 —— `request_order_info` 在订单字段缺失时暂停，等用户用自由文本补齐；
  2. 审批中断 —— `order_create` / `order_update` 执行前暂停，等用户 `approve` / `reject`。
- **长期记忆**：`/memories/{user_id}/preferences.md` 保存输出格式、图表类型、货币、语言偏好；`recent_suppliers` / `recent_queries` 由 `MemoryUpdateMiddleware` 在每轮 ERP 对话后自动抽取与合并。
- **技能（Skills）体系**：预置技能由 `SkillsSyncMiddleware` 从本地同步进沙箱，用户新增技能经测试后由 `assign_skill` 持久化到 StoreBackend，会话开始时由 `UserSkillsRestoreMiddleware` 自动恢复。
- **上下文治理**：工具结果超 20k tokens 自动 offload 到文件系统；上下文达 85% 自动摘要，另提供 `compact_conversation` 工具供 Agent 主动压缩。

---

## 四、快速启动

最小可用路径（Windows 推荐 `SANDBOX_MODE=local`，无需部署 OpenSandbox）：

```powershell
# 1) 基础依赖：JDK 17、Maven、MySQL 8、MongoDB、Node.js 18+、Python 3.10+、WSL2（沙箱模式 local 需要）

# 2) 启动 ERP 后端（首次启动自动建库建表并插入模拟数据）
cd MotorcyclePartsProcurementSystem
mvn spring-boot:run               # → http://localhost:8080
                                  #   Swagger: /swagger-ui/index.html · OpenAPI: /v3/api-docs

# 3) 启动 ERP MCP 桥接（把 Java REST 暴露为 MCP 工具）
cd ..\ERP_OPENCLAW
copy .env.example .env            # 填入 DEEPSEEK_API_KEY 等
$env:PYTHONPATH = "$PWD\src"      # 必需：代码使用顶层包名导入
python -m mcp_server.server_main  # → http://127.0.0.1:8000/mcp

# 4) 启动 AI 助手后端 + 前端（一条命令拉起两个进程）
python start_web.py               # 后端 :8090  /  前端 :3000
```

访问 <http://localhost:3000> 开始对话。Agent 首次初始化需要 30–60 秒（创建沙箱、装载技能、预装 Python 依赖）。

> MongoDB 需在启动第 4 步**之前**就绪（AI 后端启动时会连接它）。

完整的依赖版本、环境变量、沙箱与数据库准备步骤见 [安装与部署](docs/SETUP_AND_DEPLOYMENT.md)。

---

## 五、文档索引

文档集中在根目录 [`docs/`](docs/)，与原有两个子项目的既有文档并存。

| 文档 | 内容 | 适合谁看 |
|------|------|----------|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | 系统架构、模块划分、请求全链路、Agent 初始化流水线、关键设计决策与权衡 | 架构师、新加入的开发者 |
| [SETUP_AND_DEPLOYMENT.md](docs/SETUP_AND_DEPLOYMENT.md) | 环境要求、依赖安装、配置项全量说明、两种沙箱模式部署、启动/停止、常见故障排查 | 需要把项目跑起来的人 |
| [API_REFERENCE.md](docs/API_REFERENCE.md) | 全部 54 个 ERP REST 端点 + FastAPI 对话接口 + MCP 工具清单 + SSE 事件协议 | 前端、Agent 开发者、接口联调 |
| [DATABASE.md](docs/DATABASE.md) | 8 张业务表结构、两种建表方式的差异、索引与视图、枚举取值、模拟数据生成规则、MongoDB 集合 | 后端、DBA |
| [AI_AGENT.md](docs/AI_AGENT.md) | DeepAgent 架构细节、中间件栈、子 Agent、技能、记忆、HITL 中断恢复、扩展指南 | AI 应用开发者 |
| [FRONTEND.md](docs/FRONTEND.md) | Vue 3 聊天界面（组件、状态、SSE 消费）与 ecommerce-demo 静态演示页 | 前端开发者 |
| [DEVELOPMENT_GUIDE.md](docs/DEVELOPMENT_GUIDE.md) | 本地开发工作流、代码约定、测试脚本、调试技巧、已知问题与技术债 | 所有贡献者 |

子项目既有文档（其中 [`MotorcyclePartsProcurementSystem/README.md`](MotorcyclePartsProcurementSystem/README.md) 与 [API_DOCUMENTATION.md](MotorcyclePartsProcurementSystem/docs/API_DOCUMENTATION.md) 均已按代码核实并修正；其余文档仍有少量不符，见下文"已知不一致"）：

- [MotorcyclePartsProcurementSystem/README.md](MotorcyclePartsProcurementSystem/README.md) — ERP 后端的模块说明、启动步骤与数据初始化规则
- [MotorcyclePartsProcurementSystem/docs/API_DOCUMENTATION.md](MotorcyclePartsProcurementSystem/docs/API_DOCUMENTATION.md) — 逐端点的完整请求/响应示例（含全部字段与错误码）
- [MotorcyclePartsProcurementSystem/docs/database_schema.sql](MotorcyclePartsProcurementSystem/docs/database_schema.sql) — 手工建表 SQL（**应用从不执行它**，见第六节）
- [MotorcyclePartsProcurementSystem/docs/数据来源说明.txt](MotorcyclePartsProcurementSystem/docs/数据来源说明.txt) — 模拟数据来源与免责声明
- [ERP_OPENCLAW/pyproject.toml](ERP_OPENCLAW/pyproject.toml) — 仍是 LangGraph 官方模板的元数据，**已不反映实际实现**（该目录下没有 README.md）

---


## 六、安全与合规须知

- ERP 后端**没有认证/授权层**，所有接口匿名可写（含创建订单、改库存）。当前定位是内部演示/教学系统，**不可直接暴露到公网**。
- `LocalWslSandboxBackend` 默认以 WSL 的 `root` 用户在**本机**执行任意命令，仅适合个人开发；生产必须切到 `SANDBOX_MODE=opensandbox` 并配置容器网络策略。
- 智能体拥有创建/修改采购订单的能力，因此 `order_create` / `order_update` 默认开启人工审批中断；请勿移除该 `interrupt_on` 配置。

---

## 七、许可

本项目仅供学习与参考使用（见 [MotorcyclePartsProcurementSystem/README.md](MotorcyclePartsProcurementSystem/README.md) 的「文档与许可」一节）。模拟数据中的企业名称仅作示例，不代表真实商业关系——见 [数据来源说明](MotorcyclePartsProcurementSystem/docs/数据来源说明.txt)。
