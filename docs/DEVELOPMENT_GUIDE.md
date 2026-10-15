# 开发指南

面向在本仓库上继续开发的工程师。环境搭建见 [SETUP_AND_DEPLOYMENT.md](SETUP_AND_DEPLOYMENT.md)，架构与设计理由见 [ARCHITECTURE.md](ARCHITECTURE.md)。

---

## 1. 仓库布局速览

```
AgentToMotorcycleERP/
├── README.md                      项目总览与文档索引
├── docs/                          ★ 本文档集
├── MotorcyclePartsProcurementSystem/   Java ERP 后端（Spring Boot 3.1.10 / Java 17）
└── ERP_OPENCLAW/                       AI 采购助手（Python + Vue 3）
```

两个子项目**各自独立构建**，没有 Maven/Gradle 多模块或 monorepo 工具的约束。修改时注意不要假设根目录有统一的构建入口。

---

## 2. 开发环境准备（最小集）

| 组件 | 版本 | 用途 |
|------|------|------|
| JDK | 17 | ERP 后端（`pom.xml` 的 `java.version=17`） |
| Maven | 3.6+ | ERP 后端构建 |
| MySQL | 8.0+ | ERP 数据库 |
| Node.js | 18+ | 前端构建（Vite 5 要求） |
| Python | 3.10+ | AI 助手（`pyproject.toml` 的 `requires-python`） |
| MongoDB | 5.0+ | 对话持久化 |
| WSL2 + 一个发行版 | Ubuntu-20.04（默认） | 沙箱（`SANDBOX_MODE=local` 时需要） |

详细安装与配置步骤见 [SETUP_AND_DEPLOYMENT.md](SETUP_AND_DEPLOYMENT.md)。

---

## 3. 开发工作流

### 3.1 推荐的启动顺序

依赖有方向性，必须按此顺序：

```
① MySQL            （ERP 后端的依赖）
② Java ERP 后端     :8080   ← 首次启动会自建库表并插入种子数据
③ MCP 桥接          :8000   ← 依赖 ②（工具调用时才真正连，但启动时会验证）
④ MongoDB          （AI 后端的依赖）
⑤ AI 助手后端       :8090   ← 启动时会连 ③ 与 ④，并创建沙箱
⑥ 前端 dev server   :3000   ← 代理 /api 到 ⑤
```

第 ⑤ 步的 Agent 初始化需要 **30–60 秒**（创建沙箱、播种技能、建 venv 并预装 5 个 Python 包）。首次运行更慢。

`python start_web.py` 会一并拉起 ⑤ 与 ⑥，并轮询 `/health` 直到 Agent 就绪（最长等 180 秒），然后打印访问地址。它**不会**启动 ②③④，需要自己先准备好。

### 3.2 分开启动（推荐用于调试）

```powershell
# 终端 1 — Java ERP 后端
cd MotorcyclePartsProcurementSystem
mvn spring-boot:run

# 终端 2 — MCP 桥接
cd ERP_OPENCLAW
$env:PYTHONPATH = "$PWD\src"
python -m mcp_server.server_main

# 终端 3 — AI 助手后端（热重载）
cd ERP_OPENCLAW
$env:PYTHONPATH = "$PWD\src"
uvicorn api_view.web_main:app --reload --host 0.0.0.0 --port 8090

# 终端 4 — 前端（热重载）
cd ERP_OPENCLAW\frontend
npm run dev
```

> **`PYTHONPATH` 很关键**：代码里用的是 `from agent.config import ...`、`from api_view.web_main import ...` 这类**顶层包名**导入，而源码在 `src/` 下。`start_web.py` 会自动注入 `src` 到 `PYTHONPATH`；手动启动时必须自己设置。

### 3.3 前端开发

Vite 已配置 `/api` 代理到 `http://localhost:8090`（`vite.config.js`），因此前端代码里统一用相对路径 `/api/...`，不要硬编码后端地址。

`vite.config.js` 显式绑定了 `host: '127.0.0.1'` 与 `strictPort: true`：
- 绑定 IPv4 回环是为了避免 Windows 上 `localhost` 解析到 `::1` 导致 `http://127.0.0.1:3000` 探测失败；
- `strictPort` 让端口被占用时直接报错，而不是静默切到 3001 让文档里的地址失效。

### 3.4 后端开发（Java）

```powershell
cd MotorcyclePartsProcurementSystem
mvn clean compile                  # 编译
mvn spring-boot:run                # 运行
mvn test                           # 跑测试
mvn clean package                  # 打包
java -jar target/MotorcyclePartsProcurementSystem-1.0.0.jar
```

改代码后 Spring Boot DevTools 未引入，需手动重启（或用 IDE 的自动重启）。

---

## 4. 验证脚本（`ERP_OPENCLAW/src/test/`）

仓库自带 8 个验证脚本，**按依赖层次从底向上**使用。全部需要设置 `PYTHONPATH` 或在 `ERP_OPENCLAW` 目录下运行。

| 脚本 | 验证目标 | 前置依赖 | 说明 |
|------|----------|----------|------|
| `verify_local_sandbox.py` | `LocalWslSandboxBackend` 的 `execute` / `upload_files` / `download_files` 三项核心能力 | WSL 发行版 | 最底层，先跑这个确认沙箱可用 |
| `setup_sandbox_only.py` | 沙箱初始化全流程（建目录 + 播种技能 + 建 venv 装依赖） | WSL 发行版 | 单独执行便于观察进度，因为首次 venv 安装很慢 |
| `verify_agent_build.py` | `create_main_agent()` 的 9 个阶段能否走通（**不调用大模型**） | MongoDB + MCP 桥接 + Java 后端 + 沙箱 | 会打印图节点数、checkpointer/store 是否存在 |
| `verify_mcp_bridge.py` | 通过 MCP 客户端逐个调用 ERP 工具，打印实际回传内容摘要 | Java 后端 + MCP 桥接 | 只读工具，安全 |
| `verify_mcp_write.py` | `order_create` / `order_update` 完整链路（创建 → 更新 → 清理） | Java 后端 + MCP 桥接 | **会写数据**，注意它会创建并删除测试订单 |
| `test_all_tools.py` | MCP 工具全量测试；两种模式：`mcp_client`（`fastmcp.Client` 内存模式直连服务端）与 `agent_client`（`MultiServerMCPClient` 经 HTTP） | Java 后端（两种模式都需要） | `python -m test.test_all_tools` |
| `test_mcp.py` | 单个工具的调用示例 | — | **已过时**：调用的 `order_update` 参数结构（`update_data`）与当前实现不符，仅作参考 |
| `agent_test.py` | 端到端跑 Agent（含大模型调用、HITL 中断交互） | 全部依赖 | 最上层，最慢，消耗模型额度 |

推荐首次搭建环境时的排查顺序：

```
verify_local_sandbox.py  →  setup_sandbox_only.py  →  verify_mcp_bridge.py
    →  verify_agent_build.py  →  agent_test.py
```

哪一步失败就说明该层的依赖没准备好，避免一上来跑完整 Agent 后对着长日志排查。

---

## 5. 代码约定

### 5.1 Java 侧

**命名与分层**：`Controller → Service(接口) → ServiceImpl → Mapper → Entity`。DTO 放在 `dto/`（跨层聚合视图），不要放在 `entity/`。

**响应包装**：控制器一律返回 `Result<T>`，分页返回 `Result<PageResult<T>>`。使用 `Result.success(...)` / `Result.error(ResultCode.XXX)`，不要自己 `new Result<>(...)`。注意**业务失败也返回 HTTP 200**，错误只体现在响应体 `code` 上（`GlobalExceptionHandler` 从不设置 HTTP 状态）。

**新增一个业务模块的清单**：

```
① entity/Xxx.java           extends BaseEntity，@TableName("xxx")，字段用 @TableField 映射下划线列名
② mapper/XxxMapper.java     @Mapper interface XxxMapper extends BaseMapper<Xxx>
③ service/XxxService.java   接口，extends IService<Xxx>
④ service/impl/XxxServiceImpl.java  @Service，extends ServiceImpl<XxxMapper, Xxx>
⑤ controller/XxxController.java     @RestController @RequestMapping("/api/xxxs")
⑥ init/DatabaseInitializer.createTables()  加 CREATE TABLE IF NOT EXISTS（这是**实际生效**的 DDL）
⑦ docs/database_schema.sql                 同步同一张表 + 索引 + 视图（该脚本是**手工执行**的文档）
⑧ （如需 AI 访问）mcp_server/tools/ 加工具 + 在子 Agent YAML 中授权
```

> ⑥ 与 ⑦ 是**同一张表的两个来源，必须同时更新**——否则会出现"应用建的库缺约束、文档 SQL 与实际不符"的双重漂移。两处的差异清单见 [DATABASE.md](DATABASE.md) §1.6。

**时间字段**：新实体继承 `BaseEntity` 即自动获得 `deleted`/`createTime`/`updateTime`。**但不要照抄 `@JsonFormat` 的值**——`BaseEntity` 上的 `@JsonFormat("yyyy-MM-dd'T'HH:mm:ss.SSS")` 是被 `@JsonSerialize` 覆盖的死注解，实际输出是 `yyyy-MM-dd HH:mm:ss`。若给新字段加时间序列化，参考 `BaseEntity` 的写法（三个注解齐全）以保持一致。详见 [API_REFERENCE.md](API_REFERENCE.md) §1.4。

**逻辑删除**：用 `@TableLogic`（已在 `BaseEntity` 上），删除走 `removeById`。若确需物理删除，参考 `PurchaseOrderMapper.physicalDeleteById` 的 `@Delete` 自定义 SQL 写法，并**注意两个环境的差异**：只有手动执行过 `database_schema.sql` 的库才有 `ON DELETE CASCADE` 外键，默认（应用建表）的库里物理删除会留下孤儿行。

**事务**：涉及多表写入的方法加 `@Transactional(rollbackFor = Exception.class)`（`PurchaseOrderServiceImpl` 的 `createOrder` / `updateById` 是范例）。

**注意 `@RequestParam` 的默认值**：分页端点的 `current` / `size` 用 `@RequestParam(defaultValue = "1")` 形式，保持全项目一致。

### 5.2 Python 侧

**导入风格**：使用顶层包名（`from agent.config import ...`、`from mcp_server.tools...`），配合 `PYTHONPATH=src`。不要改成相对导入，否则 `langgraph.json` 的入口与 `mcp_server` 的模块路径都会失效。

**配置读取**：所有可外部化的配置走 `agent/env_utils.py`（AI 侧）或 `mcp_server/server_config.py`（MCP 侧），不要在业务代码里硬编码地址或密钥。两者都用 `load_dotenv(dotenv_path=<项目根>/.env, override=True)` 显式指定 `.env` 路径，避免因启动目录不同而加载失败。

**惰性初始化外部客户端**：可选依赖的服务（如 `web_search` 的智谱客户端）必须惰性创建。`web_search.py` 的注释记录了教训——早期版本在模块导入时就 `ZhipuAiClient(api_key=...)`，未配 Key 时整个 `agent.tools` 包导入失败，连带智能体无法启动。

**MCP 工具的写法约定**：

```python
GROUP_NAME = "warehouse"           # 决定工具名前缀，也是子 Agent 的授权粒度

def register_warehouse_tools(mcp: FastMCP):
    @mcp.tool(name=f"{GROUP_NAME}_list")
    async def list_warehouses(ctx: Context = None) -> list:
        """一句话说明这个工具做什么（这段 docstring 会进 LLM 的工具描述）。"""
        http_client = ctx.request_context.lifespan_context.get("http_client")
        try:
            response = await http_client.get("/warehouses/page", params={...})
            response.raise_for_status()
            result = response.json()
            if result.get("code") != 200:
                return [f"API error: code={result.get('code')}"]
            return result.get("data", [])
        except Exception as e:
            return [f'没有查询到任何信息，而且报错: {e}']
```

四条硬约定：
1. 参数用 **snake_case**，内部映射到 Java 的 **camelCase**；
2. 只返回 `result["data"]`（丢掉 `code`/`message`/`timestamp`，省 token）；
3. 异常**捕获并转成可读字符串**，不向上抛（否则整个 Agent 运行会因一个工具失败而中断）；
4. 列表型工具返回 `list`，对象型返回 `dict`——类型要与 docstring 一致。

**子 Agent YAML**：`tools` 用**子串匹配**，所以写 `warehouse_` 能匹配所有 `warehouse_*`。这是有意设计（新增同类工具无需改配置），但也意味着前缀不要太短（`part_` 会连带命中 `part_by_supplier`）。配置未匹配到任何工具时只打印 `[WARNING]` 不报错，**改完 YAML 一定要看启动日志**。

**提示词分层**：常驻上下文的放 `memory/prompts.py` 与 `memory/AGENTS.md`；详细流程放技能目录的 `SKILL.md`（Agent 按需 `read_file`）。不要把长流程塞进系统提示词——会挤占每次调用的上下文预算。

### 5.3 前端侧

- 组件放 `src/components/`，一个文件一个组件，使用 `<script setup>` 组合式 API；
- 网络请求统一走 `src/api/`（`chat.js` / `history.js`），组件内不直接 `fetch`；
- SSE 解析逻辑在 `api/chat.js::_processStream` 中，**服务端与前端各维护一份工具调用栈**（`tool_call_stack` vs `toolStack`），修改事件协议时必须同步改两边；
- 样式用 `<style scoped>`，全局样式放 `src/styles/main.css`。

---

## 6. 调试技巧

### 6.1 SSE 流调试日志

`api/chat.py` 会把每次流的**所有 chunk** 写入 `%TEMP%\deepagent_debug\stream_{thread_id}_{timestamp}.log`：

```
[2026-05-23T14:30:00.123456] STREAM_START
  data: {"message": "...", "thread_id": "...", "is_resume": false}
[..] RAW_CHUNK
  data: {"ns": ["tools:procurement-analyst"], "source": "procurement-analyst"}
  token: {"type": "AIMessageChunk", "content_preview": "..."}
[..] TOOL_START / TOOL_RESULT / INTERRUPT_DETECTED / SAVE_DISPLAY / STREAM_DONE
```

排查顺序：`STREAM_START` 确认请求进来了 → `RAW_CHUNK` 看 token 与 `ns`（子 Agent 识别对不对）→ `INTERRUPT_DETECTED` 看中断是否被捕获 → `SAVE_DISPLAY` 确认落库。

写入失败被静默吞掉（`except: pass`），因此日志缺失本身也说明不了什么。**该目录会无限增长，长期开发需定期清理。**

### 6.2 用 curl 直接测 SSE

```powershell
# 流式对话（-N 关闭缓冲）
curl.exe -N -X POST http://localhost:8090/api/chat/stream `
  -H "Content-Type: application/json" `
  -d '{\"message\":\"你好\",\"thread_id\":null}'

# 会话列表
curl.exe http://localhost:8090/api/history

# Java 后端直测（绕过 MCP，确认接口本身没问题）
curl.exe "http://localhost:8080/api/parts/page?current=1&size=3"
curl.exe "http://localhost:8080/api/inventory/warning"
```

### 6.3 分层排错表

| 现象 | 先查这一层 | 具体动作 |
|------|-----------|----------|
| 前端报"获取会话列表失败" | AI 后端 ⑤ | `curl http://localhost:8090/health` |
| 对话无响应 / 报 MCP 连接失败 | MCP 桥接 ③ | `Test-NetConnection 127.0.0.1 -Port 8000` |
| MCP 工具返回 `API error: code=...` | Java 后端 ② | 直接用 curl 打同一个 Java 接口 |
| 启动报"沙箱配置失败" | WSL / OpenSandbox | `wsl -l -v`；核对 `.env` 的 `WSL_DISTRO` |
| 启动报 MongoDB 连接失败 | MongoDB ④ | `check_mongodb()`（`verify_agent_build.py` 第一步会调） |
| 图表生成失败但其他正常 | 远程可视化 MCP | **预期内降级**，检查 `ANALYSIS_MCP_URL` 可达性 |
| 界面出现用户没问过的文字 | `chat.py` 的 token 过滤 | 确认 `SystemMessage` 仍被排除 |
| 刷新后看不到子 Agent 的过程 | `session_display_messages` | 查 `SAVE_DISPLAY` 日志与集合内容 |

### 6.4 关键文件速查

| 想改…… | 打开 |
|--------|------|
| 主 Agent 的行为准则 | `ERP_OPENCLAW/src/agent/memory/AGENTS.md` |
| 主 Agent 的角色定位 | `ERP_OPENCLAW/src/agent/memory/prompts.py` |
| 子 Agent 的工具、技能、提示词、审批配置 | `ERP_OPENCLAW/src/agent/subagents/configs/*.yaml` |
| Agent 初始化流程 | `ERP_OPENCLAW/src/agent/main_agent.py` |
| SSE 事件的产生与过滤 | `ERP_OPENCLAW/src/api_view/api/chat.py` |
| 会话读写与展示消息 | `ERP_OPENCLAW/src/api_view/agent_loader.py` |
| MCP 工具的实现 | `ERP_OPENCLAW/src/mcp_server/tools/*.py` |
| 工具如何分组给子 Agent | `ERP_OPENCLAW/src/agent/tools/mcp_client.py` |
| 环境变量与默认值 | `ERP_OPENCLAW/src/agent/env_utils.py` + `.env.example` |
| SSE 事件的前端消费 | `ERP_OPENCLAW/frontend/src/api/chat.js` |
| 中断 UI | `ERP_OPENCLAW/frontend/src/components/InterruptBanner.vue` |
| 订单状态流转与金额计算 | `MotorcyclePartsProcurementSystem/src/main/java/com/motorparts/service/impl/PurchaseOrderServiceImpl.java` |
| 库存出入库与预警 | `.../service/impl/InventoryServiceImpl.java` |
| 表结构与种子数据 | `.../init/DatabaseInitializer.java` |
| 全局异常处理 | `.../common/exception/GlobalExceptionHandler.java` |

---

## 7. 已知问题与技术债

按"是否影响功能"排序。

### 7.1 影响功能

| # | 问题 | 位置 | 影响 | 建议 |
|---|------|------|------|------|
| 1 | `STORE = InMemoryStore()` | `agent/config.py` | 用户偏好与持久化技能**重启即丢** | 换 `PostgresStore` / `RedisStore` |
| 2 | `context` 硬编码 `user_id="yummyQian"` | `api/chat.py::stream_chat_response` | 多用户隔离形同虚设，所有人共用一份偏好 | 请求体加 `user_id` 并透传 |
| 3 | 订单更新是"物理删除 + 重新插入" | `PurchaseOrderServiceImpl.updateById` | 未提交字段被清空；`createTime` 被刷新；主键被 `AUTO_INCREMENT` 重新分配；`deleted` 被强制重置为 0（**软删除的订单会被一次更新"复活"**） | 改为真正的 UPDATE；至少在调用侧固化"读-合并-写"约定 |
| 4 | 订单明细用**请求里的旧 id** 回插 | `PurchaseOrderServiceImpl.updateById` 第 6 步 | 订单行已拿到新 id，明细仍指向旧 id → 若 MySQL 未复用该 id，明细挂到错误的订单上 | 明细回插时改用 `order.getId()` |
| 5 | 未注册分页插件 | `application.yml` 的 `exclude` + `MyBatisPlusConfig` 手写 `MybatisSqlSessionFactoryBean` | **`MybatisPlusInterceptor` / `PaginationInnerInterceptor` 不存在**，6 个 `/page` 端点很可能返回全部匹配行而忽略 `size`（`PageResult.current`/`size` 仍回显请求值） | 补 `MybatisPlusInterceptor` Bean，或去掉 `exclude` 让自动配置生效；**集成前先实测确认** |
| 6 | `recreate-tables` 配置项无效 | `DatabaseInitializer` 未注入该属性 | 该键写进了 `application.yml` 却从未被读取，"设置后重新初始化"做不到；唯一触发重建的方式是清空 `user` 表 | 要么实现，要么从配置中移除 |
| 7 | 无认证/授权 | 全部控制器 | 任何匿名请求可创建订单、改库存、改信用评级 | 加 Spring Security + JWT；至少在网关层限制 |
| 8 | 数据源口令明文提交 | `application.yml`（且 `.gitignore` 虽忽略该文件却已被提交，`target/classes/` 与打包 jar 中也有副本） | 凭据泄漏风险 | 改环境变量 / 密钥管理服务，并轮换该口令 |
| 9 | 订单状态无任何校验 | `PurchaseOrderServiceImpl.updateOrderStatus` | 任意整数可写入，可从"已入库"倒回"待审核"，且不触发任何库存动作 | 加状态机校验 |
| 10 | 订单审批与库存完全解耦 | `updateOrderStatus` vs `InventoryService.inbound` | 把订单置为"已入库"**不会**增加库存；`inbound` 也从不回写订单 | 业务上需人工对账，或在状态流转里挂上库存动作 |
| 11 | 库存预警口径不一致 | `InventoryServiceImpl.getWarningListWithPart`（SQL `<`）vs `InventoryController.checkInventory` / `StatisticsController`（Java `<=`） | 同一个"预警"概念在两处结果可能差一条记录 | 统一为 `<=` 或 `<` |
| 12 | `part.stock_warning_value` 未被 Java 使用 | `Part` 实体、`inventory_warning_view` | 该字段只在 SQL 视图里作阈值，Java 预警只看 `inventory.safety_stock` | 明确二者语义，或统一 |
| 13 | 出库失败码不精确 | `InventoryController.outbound` | 参数非法、库存记录不存在、库存不足三种情况都返回 603「库存不足」 | 分别映射 400 / 602 / 603 |
| 14 | 并发出入库无保护 | `InventoryServiceImpl.inbound/outbound` | 读-改-写无 `@Version`、无 `SELECT … FOR UPDATE`，并发会丢失更新 | 加乐观锁或行锁 |

### 7.2 影响可维护性

| # | 问题 | 位置 | 说明 |
|---|------|------|------|
| 15 | `mcp_tools_bean.py` 重复两份 | `src/agent/` 与 `src/mcp_server/` | 已确认两文件 **MD5 完全相同**（`57103832A31C25A8973F7EE920E533CC`）；改一处必须改另一处，或删掉一份 |
| 16 | 建表逻辑有两份且差异大 | `DatabaseInitializer.createTables()` vs `docs/database_schema.sql` | 应用建的库**没有外键、没有 `uk_order_part`、没有视图、只有 11 个二级索引/唯一键**；详见 [DATABASE.md](DATABASE.md) §1.6 |
| 17 | `database_schema.sql` 的索引块在 MySQL 8 上语法错误 | `docs/database_schema.sql` 末尾 | `CREATE INDEX IF NOT EXISTS` 是 MariaDB 扩展；该块整体报错 |
| 18 | 先跑 SQL 会让种子数据完全跳过 | `database_schema.sql` 的 4 条 `INSERT INTO user` + `insertSampleData()` 的 `COUNT(*) FROM user` 短路 | 得到"空表 + 4 用户"的库 |
| 19 | 5 个枚举类从未被使用 | `common/enums/` 的 `OrderStatusEnum`、`PartCategoryEnum`、`CustomerTypeEnum`、`SupplierStatusEnum`、`UserRoleEnum` | 状态/分类/角色在业务代码里全是裸 `Integer`/`String` 字面量；`isValid()` 从未被调用 |
| 20 | `UserService` / `UserMapper` 是死代码 | `service/`、`mapper/`、`entity/User.java` | 无 `UserController`，从未被注入——用户管理无法通过 HTTP 访问 |
| 21 | `BusinessException` 从未被抛出 | `common/exception/` | `handleBusinessException` 是死代码；失败一律靠 `boolean` 返回值 |
| 22 | 6 个 `ResultCode` 永不可达 | `ResultCode` 的 401/403/404/600/604/605 | 代码里没有任何路径会产生它们（`BusinessException` 从未实例化、`Result.unauthorized/forbidden/notFound` 无调用方、状态更新无校验）；调用方不应针对这些码写分支 |
| 23 | `mybatis-plus.*` YAML 全部不生效 | `application.yml` | 自动配置被排除，手写工厂不读这些属性；日志里的 SQL 来自 `com.motorparts: debug` 而非 `log-impl: StdOutImpl` |
| 24 | 大量惰性配置块 | `application.yml` | `motorparts.upload.*`、`motorparts.system.*`、`spring.jpa.*`、`spring.messages.basename: i18n/messages`（`i18n/` 目录不存在）均无人读取 |
| 25 | `DdlApplicationRunnerConfig` 是空实现 | `config/` | 仅用于规避启动期 bean 查找错误，注释自陈 |
| 26 | `OrderDetail.id` 声明为 `IdType.INPUT` | `entity/OrderDetail.java` | 注释称"应用层生成"，但无人生成，DB 列是 `AUTO_INCREMENT` |
| 27 | `DatabaseInitializer.insertSampleData` 的 `@Transactional` 无效 | 同类内 `run()` 自调用 | 代理被绕过，中途失败会留下部分数据 |
| 28 | 更新类接口大多无事务 | 各 `updateStatus` / `updatePrice` 等 | 仅 4 个 service 方法有 `@Transactional` |
| 29 | `PageResult.records` 可能少于 `size` 而 `total` 不变 | `InventoryServiceImpl.pageInventoriesWithPart` | `partName` 在分页后于 Java 侧过滤 |
| 30 | `Collectors.toMap` 无 merge 函数 | `searchOrderDetails`、`getWarningListWithPart` | 若唯一约束缺失（应用建表时确实缺 `uk_order_part`）遇重复键会抛 `IllegalStateException` |
| 31 | 零测试 | `src/test/java` 不存在（`spring-boot-starter-test` 已声明） | 无回归保护 |
| 32 | 多套订单编号规则并存 | `DatabaseInitializer`（`PO{年}{6位}`）、`SparkPlugDataInitializer`（`PO{年}{月}{4位}-{毫秒}`）、MCP 工具（`PO{年月日}{3位}`）、文档示例（`PO202605060001`） | 无统一生成器；`createOrder` 要求调用方自带编号 |
| 33 | `test_mcp.py` 已过时 | `src/test/` | 调用的 `order_update` 参数结构（`update_data` 包裹）与当前扁平参数实现不符，直接跑会失败 |
| 34 | `SKILL.md` 与实现参数名不符 | `skills/main/skill-management/SKILL.md` | 文档写 `assign_skill(skill_name, subagent_name)`，实现是 `agent_name` |
| 35 | `ERP_OPENCLAW/pyproject.toml` 仍是 LangGraph 模板 | 项目根 | 依赖声明与实际实现不符（真实依赖见 `requirements.txt`），`pip install -e .` 装不出可用环境；其 `readme = "README.md"` 指向的文件在该目录下并不存在 |
| 36 | 大量控制台 `print` 而非 `logging` | `agent_loader.py`、`mcp_client.py`、`sandbox_setup.py`、`chat.py` | 生产环境无法按级别过滤或输出到文件；`main_agent.py` 只在 `APP_ENV=production` 时写文件 |
| 37 | 调试日志无限增长 | `chat.py` 写 `%TEMP%/deepagent_debug/` | 无清理机制 |
| 38 | MCP 工具子串匹配可能过度匹配 | `subagents/loader.py` | `part_` 会命中 `part_by_supplier`；未匹配只告警 |
| 39 | 状态码 `1..5` 硬编码在三处 | `OrderStatusEnum`、`order_tools.py` docstring、`procurement_order.yaml` | 改枚举需同步三处 |
| 40 | `GET /statistics/monthly-trend` 参数名不统一 | `StatisticsController` | 用 `startDateParam`/`endDateParam`，与其他端点的 `startDate`/`endDate` 不一致 |
| 41 | `GET /api/history/{thread_id}` 的 PATCH 是占位实现 | `history.py` | 返回"标题更新功能待实现" |
| 42 | `LocalDateTime` 的输出格式**因类而异** | `CustomLocalDateTimeSerializer`（实体）与 DTO 上的 `@JsonFormat`/Jackson 默认 ISO | 同一个响应里可能同时出现 `yyyy-MM-dd HH:mm:ss`、`2026-05-23T14:30:00.000`、`2026-05-23T14:30:00` 三种写法；详见 [API_REFERENCE.md](API_REFERENCE.md) §1.4 |
| 43 | `totalAmount` 在不同接口里语义不一致 | `getOrderStatistics` 的 `BigDecimal.longValue()` 与 `/statistics/monthly-trend` | 前者截断为整数元（Long），后者保留小数的元（BigDecimal）——同名不同型，容易误用 |
| 44 | 库存统计存在 NPE 风险 | `StatisticsController.getInventoryStatistics`、`InventoryController.checkInventory` | `Integer` 开箱无 null 检查，而 `safety_stock` 可空 |

### 7.3 前端侧

| # | 问题 | 说明 |
|---|------|------|
| 45 | `AbortController` 只断前端连接 | 服务端 SSE 生成器可能继续跑完，模型额度照常消耗 |
| 46 | `message_count` 是估算 | `history.py` 用 `len(messages) // 2`，工具消息多时不准 |
| 47 | 工具调用栈双份实现 | `chat.py` 与 `api/chat.js` 各一份，协议变更需同步 |
| 48 | 会话标题无法编辑 | 依赖未实现的 PATCH 接口 |
| 49 | `User.password` 无 `@JsonIgnore` | Java 侧；一旦有接口返回 `User`，口令哈希会直接泄漏 |

---

## 8. 提交前检查清单

```
□ Java 侧能 mvn clean compile 通过
□ 改了表结构 → DatabaseInitializer.createTables() 与 docs/database_schema.sql 都更新
□ 改了枚举取值 → 检查 API_REFERENCE.md 的枚举表、order_tools.py docstring、子 Agent YAML
□ 加了 MCP 工具 → server_main.py 已注册；相应子 Agent 的 YAML tools 已授权
□ 改了子 Agent YAML → 启动日志中确认工具匹配数量符合预期（无 [WARNING] 未匹配）
□ 改了 SSE 事件 → chat.py 与 frontend/src/api/chat.js 同步更新
□ 改了 mcp_tools_bean.py → 两份文件都改（或先合并为一份）
□ 改了环境变量 → .env.example 与 SETUP_AND_DEPLOYMENT.md 同步
□ 新增/变更接口 → 更新 API_REFERENCE.md 与（如涉及）docs/API_DOCUMENTATION.md
□ 无新增明文凭据
```

---

## 9. 相关文档

- [SETUP_AND_DEPLOYMENT.md](SETUP_AND_DEPLOYMENT.md) — 环境搭建与配置项
- [ARCHITECTURE.md](ARCHITECTURE.md) — 设计意图与权衡
- [API_REFERENCE.md](API_REFERENCE.md) — 接口契约速查
- [DATABASE.md](DATABASE.md) — 表结构与运维 SQL
- [AI_AGENT.md](AI_AGENT.md) — Agent 机制与扩展指南
- [FRONTEND.md](FRONTEND.md) — 前端工程说明
