# 系统架构

本文描述 AgentToMotorcycleERP 的整体架构、模块职责、关键调用链路与设计决策。阅读前建议先看 [根 README](../README.md) 了解项目全貌。

---

## 1. 架构总览

系统由**两个独立部署单元**与**四个外部依赖**组成。

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                              浏览器 (localhost:3000)                          │
│   Vue 3 SPA — 会话侧边栏 / 消息流 / 工具调用面板 / 人工介入横幅                │
└───────────────────────────────┬──────────────────────────────────────────────┘
                                │  fetch + ReadableStream (SSE over POST)
                                │  /api/chat/stream · /api/chat/{id}/resume
                                │  /api/history/*
┌───────────────────────────────▼──────────────────────────────────────────────┐
│  部署单元 A：AI 助手后端  ERP_OPENCLAW  (FastAPI, :8090)                       │
│                                                                              │
│  api_view/                         agent/                                    │
│   ├ web_main.py   FastAPI 应用      ├ main_agent.py   9 阶段初始化流水线        │
│   ├ agent_loader.py 单例+脚本存取    ├ config.py       模型/Store/Checkpointer  │
│   └ api/chat.py  SSE 流式核心        ├ middleware_config.py  子 Agent 中间件    │
│      api/history.py 会话管理         ├ middlewares/    7 个中间件               │
│                                     ├ subagents/      YAML 子 Agent 加载器     │
│                                     ├ tools/          MCP 客户端 + 本地工具     │
│                                     ├ backends/       WSL / OpenSandbox 后端   │
│                                     ├ skills/         技能包（沙箱同步源）      │
│                                     └ memory/         AGENTS.md + 系统提示词    │
└──────┬─────────────────┬───────────────────────┬─────────────────────────────┘
       │                 │                       │
       │ MCP             │ MCP                   │ checkpointer / 展示消息
       │ streamable-http │ streamable-http       │
┌──────▼──────────┐ ┌────▼──────────────────┐ ┌─▼───────────────────────────┐
│ 部署单元 B       │ │ 外部服务               │ │ MongoDB                     │
│ MCP 桥接 :8000   │ │ 可视化 MCP (远程)      │ │  langchain_db.checkpoints   │
│ fastmcp          │ │ 26 种图表生成          │ │  langchain_db.               │
│ 8 个 ERP 工具    │ │ (ModelScope)          │ │    session_display_messages │
└──────┬──────────┘ └───────────────────────┘ └─────────────────────────────┘
       │ httpx.AsyncClient (连接池 100)
       │ REST /api/**
┌──────▼───────────────────────────────────────────────────────────────────────┐
│  部署单元 C：ERP 业务后端  MotorcyclePartsProcurementSystem  (:8080)           │
│  Controller (7) → Service (7 + impl) → Mapper (8, MyBatis-Plus) → MySQL 8     │
│  统一响应 Result<T> / PageResult<T>；逻辑删除；DDL 与种子数据自举              │
└──────────────────────────────────────────────────────────────────────────────┘
       │
       │
┌──────▼──────────────────────┐   ┌────────────────────────────────────────────┐
│ MySQL  motorparts_db        │   │ 沙箱执行环境（二选一）                       │
│ 8 张业务表 + 3 个视图         │   │  local: 本机 WSL 发行版 (root)              │
└─────────────────────────────┘   │  opensandbox: 独立容器服务                  │
                                  │  预置 /opt/skills-venv + 技能文件            │
                                  └────────────────────────────────────────────┘
```

### 1.1 部署单元与端口

| 单元 | 目录 | 默认端口 | 关键端点 |
|------|------|----------|----------|
| Vue 前端 | `ERP_OPENCLAW/frontend` | 3000 | Vite dev server，`/api` 代理到 8090 |
| AI 助手后端 | `ERP_OPENCLAW/src/api_view` | 8090 | `/api/chat/stream`、`/api/history`、`/health`、`/docs` |
| MCP 桥接 | `ERP_OPENCLAW/src/mcp_server` | 8000 | `/mcp`（streamable-http） |
| ERP 后端 | `MotorcyclePartsProcurementSystem` | 8080 | `/api/**`、`/swagger-ui/index.html` |
| MySQL | 外部依赖 | 3306 | 库 `motorparts_db` |
| MongoDB | 外部依赖 | 27017 | 库 `langchain_db` |

---

## 2. 为什么这样分层

### 2.1 两个工程而不是一个

| 关注点 | ERP 后端（Java） | AI 助手（Python） |
|--------|------------------|-------------------|
| 语言生态 | 事务、ORM、强类型领域模型成熟 | LLM/Agent/数据分析生态成熟 |
| 变更频率 | 低（业务规则稳定） | 高（提示词、工具、模型频繁迭代） |
| 失败影响 | 数据一致性风险，需严格 | 回答质量下降，可降级 |
| 扩缩容 | 按业务并发 | 按对话并发 + 沙箱资源 |

强行合并会导致「改一句提示词要重新编译 Java」以及「Agent 出问题牵连业务库」。因此拆为两个工程，**唯一耦合面是 REST 契约**。

### 2.2 为什么中间还有一层 MCP 桥接

AI 侧本可以自己写 `httpx` 直接调 Java。选择再加一层 FastMCP 的理由：

1. **工具即接口**：MCP 的 `@mcp.tool` 自动从 Python 类型注解 + docstring 生成 JSON Schema，LLM 直接消费；无需手写 Function Calling 声明。
2. **协议解耦**：未来把 Java 后端换成 .NET/Go，只需改 `mcp_server/tools/*.py` 里的 URL，Agent 侧零改动。
3. **按业务分组分发**：`mcp_client.py` 用工具名前缀（`supplier_` / `part_` / `inventory_` / `order_`）把工具分给不同子 Agent——工具名的命名规范直接成了权限边界。
4. **返回值裁剪**：MCP 工具只把 Java 的 `data` 字段回给 LLM（丢掉 `code`/`message`/`timestamp`），减少无意义 token 消耗。

### 2.3 为什么需要沙箱

分析类任务要真的"算"——比较 10 家供应商报价、算价差百分比、画分布图。让 LLM 心算会出错，所以给它一个能跑 Python 的 Linux 环境。两种模式对应两类用户：

- `SANDBOX_MODE=local`：复用本机 WSL 发行版，**零部署成本**，路径语义与容器一致（`/skills`、`/analysis`、`/opt/skills-venv`），代价是隔离性弱（root 执行）。
- `SANDBOX_MODE=opensandbox`：连独立 OpenSandbox 服务，真隔离 + 可配网络策略，代价是要自己部署服务。

两者实现同一套 `BaseSandbox` 协议（`execute` / `upload_files` / `download_files`），因此 `sandbox_setup.py` 只需按模式选择实现，上层完全无感。

---

## 3. ERP 后端架构（Java）

### 3.1 分层

```
controller/   HTTP 边界：参数校验、DTO 组装、Result 包装
   │          7 个控制器，54 个端点
service/      业务规则与事务边界
   │          接口 + impl；@Transactional(rollbackFor = Exception.class)
mapper/       MyBatis-Plus BaseMapper；复杂查询用 LambdaQueryWrapper 在 Service 内拼装
   │          仅 2 处自定义 SQL：physicalDeleteById / physicalDeleteByOrderId
entity/       领域模型，全部继承 BaseEntity
dto/          跨层聚合视图（InventoryWithPart / PartWithSupplier / ...）
common/       Result / PageResult / enums / exception
config/       MyBatisPlusConfig / SwaggerConfig / WebMvcConfig / DdlApplicationRunnerConfig
init/         DatabaseInitializer / SparkPlugDataInitializer（实现 ApplicationRunner）
```

### 3.2 关键约定

**统一响应**：所有控制器返回 `Result<T>`，构造方式只有 `Result.success(...)` 与 `Result.error(...)` 两条路径，`code` 取自 `ResultCode` 枚举（200 成功 / 400 参数错误 / 500 失败 / 600-605 业务码）。分页统一 `PageResult<T>`，由 `PageResult.from(IPage)` 从 MyBatis-Plus 的 `Page` 转换。

**逻辑删除**：`BaseEntity.deleted` 标注 `@TableLogic`，MyBatis-Plus 自动为所有查询追加 `deleted = 0`、删除时改为 `UPDATE ... SET deleted = 1`。因此：
- 删除接口（`DELETE /delete/{id}`）都不会真正删行；
- 但**订单更新是例外**：`PurchaseOrderServiceImpl.updateById` 用自定义 `@Delete` 做**物理删除再插入**（见 3.3）。

**字段自动填充**：`MyBatisPlusConfig.metaObjectHandler` 负责 `createTime` / `updateTime` / `deleted`。不过多个控制器在 `create` 里仍显式 `setDeleted(0)` / `setCreateTime(now)`，属冗余但无副作用。

**时间格式**：`BaseEntity` 用 `@JsonFormat("yyyy-MM-dd'T'HH:mm:ss.SSS")` + 自定义序列化/反序列化器（`CustomLocalDateTimeSerializer` / `CustomLocalDateTimeDeserializer`）。**注意实际输出不是注解里写的 ISO 格式**——显式的 `@JsonSerialize` 覆盖了 `@JsonFormat`，序列化器硬编码输出 `yyyy-MM-dd HH:mm:ss`（空格分隔、无毫秒）。反序列化则是宽容的：统一分隔符后依次尝试 4 种格式，因此 `yyyy-MM-ddTHH:mm:ss.SSS` 这类输入也能被接受——**这正是 MCP 工具生成 `orderTime` 时用 ISO 格式却仍能工作的原因**（见 `mcp_server/tools/order_tools.py::_prepare_request`）。完整实测结果见 [API_REFERENCE.md](API_REFERENCE.md) §1.4。

**数据库自举**：`DatabaseInitializer implements ApplicationRunner`，启动时依次 `createDatabase()` → `createTables()`（8 张 `CREATE TABLE IF NOT EXISTS`）→ `insertSampleData()`（先 `SELECT COUNT(*) FROM user`，非空则跳过）。受 `motorparts.init.enabled` 与 `motorparts.init.insert-sample-data` 两个开关控制。

### 3.3 订单更新的"物理删除 + 重新插入"语义

这是全项目最需要留意的实现：

```java
// PurchaseOrderServiceImpl.updateById (简化)
orderDetailMapper.physicalDeleteByOrderId(orderId);  // DELETE FROM order_detail WHERE order_id=?
baseMapper.physicalDeleteById(orderId);              // DELETE FROM purchase_order WHERE id=?
order.setDeleted(0); order.setCreateTime(now); order.setUpdateTime(now);
baseMapper.insert(order);                            // 重新 INSERT（id 由传入值决定）
// 再逐条插入明细
```

**后果**：
- 该接口不是"部分更新"，而是**整体替换**——未提交的字段会被写成 `null`（或由 service 补默认值）；
- 因此 MCP 的 `order_update` 工具必须先 `GET /orders/get/{id}` 读出完整订单，合并后再 `PUT`，否则会清空字段。工具 docstring 里明确写了这一点。
- 外键 `fk_logistics_order` 为 `ON DELETE CASCADE`，**物理删除订单会连带删除其物流记录**。
- 由于 `id` 由调用方显式传入并重新插入，自增主键不会推进；`createTime` 被刷新为当前时间。

### 3.4 订单状态机

`OrderStatusEnum`：`1 待审核` → `2 已审核` → `3 采购中` → `4 已入库`，另有 `5 已取消`。

- 状态通过 `PATCH /api/orders/update-status/{id}?status=N` 修改；`PurchaseOrderServiceImpl.updateOrderStatus` **不校验状态转移合法性**（`OrderStatusEnum.isValid` 存在但未在此路径调用），任意状态可跳到任意状态。
- 唯一副作用：`status == 4` 时自动写入 `actualDeliveryDate = LocalDate.now()`。
- 状态枚举定义在 `OrderStatusEnum`，但状态码 `1..5` 也硬编码在 `mcp_server/tools/order_tools.py` docstring 与子 Agent YAML 提示词中——**三处需同步修改**。

### 3.5 库存与预警

`InventoryServiceImpl` 提供 `inbound(partId, quantity, warehouseLocation)` / `outbound(partId, quantity)`，维护 `currentQuantity` 与 `lastInboundTime` / `lastOutboundTime`；出库不足时返回 `null`/失败，控制器转成 `ResultCode.INSUFFICIENT_INVENTORY(603)`。

"预警"在不同位置有两种口径，注意区分：

| 位置 | 判定条件 |
|------|----------|
| `InventoryServiceImpl.getWarningListWithPart`（`GET /inventory/warning`） | `currentQuantity <= safetyStock` |
| `StatisticsController.getInventoryStatistics`（`GET /statistics/inventory`） | `currentQuantity <= safetyStock` |
| `inventory_warning_view`（SQL 视图） | 三档：`<= part.stock_warning_value` 为"严重不足"，`<= safety_stock` 为"不足"，否则"充足" |

即 MCP 工具 `inventory_warning` 走的是**两档口径**，SQL 视图的"严重不足"档位未被 Java 代码使用。

---

## 4. AI 助手架构（Python）

### 4.1 Agent 初始化流水线

`agent/main_agent.py::create_main_agent()` 是唯一入口，采用 **async graph factory** 模式——每次调用都创建新沙箱、重新装载工具。源码把它拆成 **9 个编号阶段**（其中若干带小数子步骤，故实际代码块更多）。下表按执行顺序列出：

| Phase | 动作 | 产物 |
|-------|------|------|
| 1 | `setup_sandbox(SANDBOX_CONFIG, sandbox_id)` | 沙箱后端（创建目录、播种技能、建 venv、预装包） |
| 1.4 | 上传 `src/agent/memory/AGENTS.md` 到沙箱 `/AGENTS.md` | 只读全局准则 |
| 1.5 | 组装 `CompositeBackend` | `/memories/` → StoreBackend（按 `user_id` 命名空间）；`/persisted-skills/` → StoreBackend（`("skills",)`）；其余 → 沙箱 |
| 2 | `load_mcp_tools()` | 4 组工具：all / analyst / order / chart |
| 3 | `create_generate_chart_tool(chart_tools)` | 26 个可视化 `generate_*` 工具合并为 1 个 `generate_visualization`（`generate_spreadsheet` 不合并，作为独立工具保留） |
| 3.6 | `create_assign_skill_tool` / `create_download_tool` | `assign_skill`、`download_sandbox_file` |
| 4 | 构建 `available_tools` 工具池 | analyst + order + extra + 可视化 + `web_search` + `request_order_info` + `assign_skill` + `download_sandbox_file` |
| 5 | `load_subagent_configs()` | 从 `subagents/configs/*.yaml` 读取原始配置 |
| 6 | `create_analyst_middleware` / `create_order_middleware` | 子 Agent 专属中间件 |
| 7 | `resolve_subagent_tools(configs, available_tools, extra_middleware)` | 工具名（子串匹配）→ 工具对象 |
| 8 | 组装主 Agent 中间件栈（7 个） | 见 4.2 |
| 9 | `create_deep_agent(...)` | 编译后的 `StateGraph` |

**容错策略**：MCP 连接失败分两级——`erp-api` 失败**直接抛错**（业务工具是核心，缺失即无意义），`analysis`（远程可视化）失败**仅告警继续**（图表是增强能力，不该阻塞启动）。

**懒加载代理**：模块级 `agent = _AgentProxy()` 兼容两种初始化场景——同步控制台脚本（`agent_test.py`）用 `get_agent()`，FastAPI 的 `lifespan` 用 `await get_agent_async()`。代理在首次属性访问时触发初始化。

### 4.2 中间件栈

主 Agent（`main_agent.py` Phase 8，顺序即执行顺序）：

| # | 中间件 | 钩子 | 作用 |
|---|--------|------|------|
| 1 | `ContextInjectionMiddleware` | `before_agent` | 把 `runtime.context` 的 `user_id`/`username` 以 `SystemMessage` 注入，并告知偏好文件路径 |
| 2 | `SkillsSyncMiddleware` | `before_agent` | 比对 MD5，把本地 `src/skills/` 变更推送到沙箱 `/skills/`，变更时注入系统通知 |
| 3 | `UserSkillsRestoreMiddleware` | `abefore_agent` | 从 StoreBackend 读取持久化技能并写入 `/skills/{scope}/...` |
| 4 | `create_summarization_middleware` | 内置 | 上下文达 85% 自动摘要 + 提供 `compact_conversation` 工具 |
| 5 | `MemoryUpdateMiddleware` | `aafter_agent` | LLM 抽取供应商与需求摘要，合并进 `/memories/{user_id}/preferences.md` |
| 6 | `ModelCallLimitMiddleware(run_limit=50)` | — | 防止模型调用无限循环 |
| 7 | `ToolCallLimitMiddleware(run_limit=200)` | — | 防止工具调用爆炸 |

子 Agent 中间件（`middleware_config.py`）：

- `procurement-analyst`：摘要中间件 + `ModelCallLimit(50)` + `ToolCallLimit(200)`——分析任务链路长，额度高。
- `procurement-order`：仅 `ModelCallLimit(20)` + `ToolCallLimit(50)`——订单操作是简单 API 调用，不需要摘要。

### 4.3 子 Agent 与委派

| 子 Agent | 触发关键词 | 工具 | 技能路径 | 人工确认 |
|----------|-----------|------|----------|----------|
| `procurement-analyst` | 分析、对比、报告、建议、评估、行情、比价、筛选 | 6 个 ERP 查询 + `generate_visualization` + `web_search` | `/skills/procurement/` | 无 |
| `procurement-order` | 下单、创建订单、修改采购单、更新订单、取消订单、订单状态 | `order_create`、`order_update`、`order_search_details`、`web_search`、`request_order_info` | `/skills/order/` | `order_create` / `order_update` 需 `approve`/`reject` |

主 Agent 自身**不持有任何 ERP 业务工具**——`create_deep_agent(tools=[web_search, assign_skill, download_sandbox_file])`。这是刻意的架构约束：ERP 写操作必须经过带审批中断的订单子 Agent，主 Agent 无法绕过。

工具名 → 工具的匹配用**子串匹配**（`if pattern in tool_name`），因此 YAML 里写 `supplier_` 能一次匹配所有 `supplier_*` 工具。副作用是可能过度匹配（例如写 `part_` 也会命中 `part_by_supplier`），需要注意命名。

### 4.4 后端服务层

`api_view/agent_loader.py` 是**单例**（`__new__` 控制），职责有三：

1. **Agent 生命周期**：`initialize()` 里 `await get_agent_async()`，失败时回滚关闭 MongoClient 防止连接泄漏。checkpointer 不在这里创建——由 `agent/config.py` 的 `CHECKPOINTER` 统一持有。
2. **会话元数据查询**：`get_all_thread_ids()` 从 checkpoint 集合 `distinct("thread_id")`；`get_session_updated_at()` 借 MongoDB `ObjectId.generation_time` 反推时间。
3. **展示消息存取**：`save_display_messages` / `get_display_messages` 操作 `session_display_messages` 集合。

**为什么需要单独一套展示消息**：LangGraph 的 checkpointer 只序列化图的内部状态（`messages`），而子 Agent 的消息经 `task` 工具折叠后**不会完整保留在主图的 messages 里**。为了刷新页面后仍能看到子 Agent 的中间过程，SSE 流在推送的同时累积一份"展示消息"并落库。这是一个务实的补偿设计。

为避免单文档超过 MongoDB 16 MB 上限，`save_display_messages` 改为**每条消息一个文档**（`{thread_id, index, message, updated_at}`，索引 `(thread_id, index)`），并对 `text`/`content`/`args` 三个字段做 500 000 字符截断。

### 4.5 SSE 流式协议

`api/chat.py::stream_chat_response` 用 `agent.astream(..., stream_mode=["messages", "values"], subgraphs=True, version="v2")` 同时订阅两种流：

- **values 流** → 检测中断（必须在 messages 处理之前，否则中断会被消息流淹没）；
- **messages 流** → 推送 token、工具开始、工具参数、工具结果。

来源识别：从 `chunk["ns"]` 中找以 `tools:` 开头的段，即为子 Agent 名（`extract_subagent_name`）；无则标为 `main`。前端据此给消息打上「主助手 / 采购分析专家 / 采购订单专家」标签。

**必须过滤的三类消息**（`chat.py` 中注释详述）：`ToolMessage`（已作为 tool_result 处理，重复输出）、`SystemMessage`（中间件注入的内部上下文，泄漏会让界面凭空多出用户没问过的文字，且会污染历史）、`HumanMessage`（用户自己发的，回显无意义）。

两层中断的判定：

| 层 | 触发源 | `interrupt.value` 特征 | 前端 UI |
|----|--------|------------------------|---------|
| 数据补充 | `request_order_info` 工具调用 `interrupt()` | 含 `type == "order_info_request"` | 自由文本输入框，恢复体 `{"supplement": "..."}` |
| 审批 | 子 Agent YAML 的 `interrupt_on` | 含 `action_requests` | 批准/驳回按钮，恢复体 `{"decisions":[{"type":"approve"}]}` |

中断后：兜底把所有 `calling` 工具标 `done` → 清理空 assistant 消息 → 保存部分展示消息 → 发 `done`（带 `interrupted: true`）→ **结束本次流**，等前端 `POST /api/chat/{thread_id}/resume` 再恢复。

恢复模式用 `Command(resume=resume_data)` 作为 input，且 `display_messages` 从库里读回（而非新建），以保证追加而非覆盖。

### 4.6 记忆体系

| 层 | 存储位置 | 生命周期 | 维护者 |
|----|----------|----------|--------|
| 全局准则 | 沙箱 `/AGENTS.md`，源文件 `agent/memory/AGENTS.md` | 进程内，每次启动重传 | 开发者（Agent 只读） |
| 系统提示词 | `agent/memory/prompts.py::system_prompt` | 编译进图 | 开发者 |
| 用户偏好 | StoreBackend `/memories/{user_id}/preferences.md` | 跨会话（进程内 Store） | Agent 显式写 + 中间件自动写 |
| 技能 | StoreBackend `("skills",)` 命名空间 | 跨会话（进程内 Store） | `assign_skill` 工具 |
| 对话状态 | MongoDB `checkpoints` | 跨进程重启 | MongoDBSaver |
| 展示消息 | MongoDB `session_display_messages` | 跨进程重启 | SSE 流 + AgentLoader |

用户隔离由 `CompositeBackend` 的 `StoreBackend(namespace=_user_memories_namespace)` 回调实现——运行时从 `runtime.context.user_id` 解析命名空间，缺失时回退 `"laoxiao"`。**注意**：`STORE = InMemoryStore()`（`config.py`），因此偏好与持久化技能**只存活于当前进程**；要真正跨重启需替换为持久化 Store 实现（如 Postgres/Redis Store）。

`MemoryUpdateMiddleware` 的触发条件较克制：先排除问候语/功能询问等无意义消息，再要求命中 ERP 关键词（或委派过 `task`），然后才调 LLM 抽取。合并策略是"先删除旧的 `recent_suppliers`/`recent_queries` 块，再追加合并结果"，供应商保留 10 条、查询摘要保留 5 条。

### 4.7 技能体系

```
src/skills/                        沙箱 /skills/
├── main/                          ├── main/
│   └── skill-management/          │   └── skill-management/    ← 主 Agent 用
├── procurement/                   ├── procurement/             ← analyst 用
│   ├── procurement-analysis/      │   ├── procurement-analysis/
│   ├── supplier-price-urls/       │   ├── supplier-price-urls/
│   ├── web-content-fetcher/       │   └── web-scraper/
│   ├── web-scraper/               └── order/                   ← order 用
│   └── chart_params.md
└── order/  (空，等待 assign_skill 填充)
```

三条技能流转路径：

1. **预置技能**：`setup_sandbox._seed_files` 首次播种（按内容比对跳过未变文件）→ 之后由 `SkillsSyncMiddleware` 每轮增量同步（MD5 缓存 + 沙箱侧比对）。
2. **新技能安装**：主 Agent 激活 `skill-management` 技能 → 沙箱内下载 ZIP 或生成 SKILL.md → 沙箱内测试 → `assign_skill(skill_name, agent_name)` 复制到 `/skills/{scope}/` 并写入 StoreBackend。
3. **技能恢复**：`UserSkillsRestoreMiddleware` 每轮从 StoreBackend `asearch(("skills",))`，把 key `{scope}/{name}/...` 映射到 `/skills/{scope}/{name}/...` 上传。

`SCOPE_MAP`（`config.py`）是唯一的 Agent↔scope 映射表：`main→main`、`procurement-analyst→procurement`、`procurement-order→order`。

---

## 5. 端到端请求链路

以用户说「对比一下博世和电装的刹车片价格，出个报告」为例：

```
1  浏览器  App.vue handleSend()
      POST /api/chat/stream  {message, thread_id}
2  FastAPI  chat_stream() → StreamingResponse(stream_chat_response(...))
3  agent_loader.create_config(thread_id) → {configurable:{thread_id, user_id:"laoxiao"}}
4  agent.astream(input, config, context={"user_id":"yummyQian",...},
                 stream_mode=["messages","values"], subgraphs=True)
5  主 Agent 开始运行：
      ContextInjectionMiddleware 注入【系统上下文】SystemMessage（含 user_id 与偏好路径）
      SkillsSyncMiddleware 比对并同步技能（无变更则静默）
      UserSkillsRestoreMiddleware 从 Store 恢复持久化技能
6  主 Agent 读 /memories/yummyQian/preferences.md → 得知用户偏好 bar 图 / CNY
7  主 Agent 判定为分析任务 → 调 task 工具委派 procurement-analyst
      （委派 description 按 AGENTS.md 模板：任务目标/用户偏好/需求正文/输出要求）
8  子 Agent 启动：
      ls /skills/procurement/ 发现可用技能
      read_file /skills/procurement/procurement-analysis/SKILL.md
9  数据收集：
      supplier_query("博世") → MCP → GET /api/suppliers/search?name=博世
      part_query(category="制动类") → MCP → GET /api/parts/page?...
      order_search_details(partName="刹车片") → MCP → GET /api/orders/search-details
      web-scraper 抓取 supplier-price-urls 命中的报价页 → /analysis/temp/*.md
10 分析执行：execute("python analyze.py") 在沙箱 WSL 内跑 pandas 计算价差
11 生成图表：首次 read_file /skills/procurement/chart_params.md
      generate_visualization(chart_type="bar", chart_config={...})
      → 远程可视化 MCP → 返回图片 URL
12 写报告：write_file("/analysis/report_20260523_...md")（沙箱内）
13 子 Agent 返回【报告路径】【摘要】【结论】【建议】给主 Agent
14 主 Agent 若报告 > 2000 字 → 调 compact_conversation
      组织用户友好回复 → 结束
15 SSE 全程把 token / tool_start / tool_args / tool_result / done 推给前端
      （source 字段区分 main / procurement-analyst）
16 流结束时 save_display_messages(thread_id, all_messages) 落库
      MemoryUpdateMiddleware 抽取「博世、电装」「刹车片价格对比」写入偏好文件
      MongoDBSaver 已持久化 checkpoint
17 浏览器渲染 Markdown + 图表缩略图；侧边栏 loadSessions() 刷新
```

若用户在步骤 7 之后要求"顺便下单 50 套"：

```
主 Agent → task → procurement-order
  子 Agent 校验 schema：partId / quantity / unitPrice 是否齐全
  缺失 → request_order_info(...) → interrupt → SSE interrupt 事件（order_info_supplement）
  前端 InterruptBanner 显示缺失字段与已收集数据 → 用户输入自由文本
  POST /api/chat/{id}/resume  {"resume":{"supplement":"物料ID=100，数量50，单价25.5"}}
  → 子 Agent 解析自由文本 → 补齐 → 再校验 → 通过
  调 order_create → 触发 interrupt_on 审批 → SSE interrupt 事件（hitl_approval）
  前端显示批准/驳回 → {"resume":{"decisions":[{"type":"approve"}]}}
  → MCP order_create → POST /api/orders/create → Java 落库
  → 子 Agent 返回【操作结果】【订单信息】
```

---

## 6. 关键设计决策汇总

| 决策 | 选择 | 理由 | 代价 |
|------|------|------|------|
| 服务拆分 | Java ERP + Python Agent，经 REST 耦合 | 变更频率与失败域不同 | 需要维护 REST 契约与 MCP 映射 |
| 工具接入方式 | MCP（FastMCP + langchain-mcp-adapters） | Schema 自动生成、协议解耦、按前缀分发权限 | 多一跳网络调用 |
| 主 Agent 持工具 | 不持有任何 ERP 业务工具 | 强制走审批中断，杜绝绕过 | 简单查询也要委派，多一次 LLM 往返 |
| 工具裁剪 | 26 个可视化工具合并为 1 个 | 工具列表过长会显著降低模型选择准确率 | 需维护 `chart_params.md` 参考文件 |
| 沙箱双模式 | local(WSL) / opensandbox | 兼顾"零部署试用"与"生产隔离" | 两套实现需保持协议一致 |
| 对话持久化 | MongoDB checkpointer | 支持 HITL 跨请求恢复与重启续聊 | 引入外部依赖 |
| 展示消息 | 独立集合逐条存储 | checkpoint 丢失子 Agent 消息；避免 16 MB 单文档上限 | 数据双写，需保持一致 |
| 用户记忆 | LangGraph Store（当前 InMemoryStore） | 与文件 API 统一，Agent 用 `read_file` 即可 | 进程重启即丢失（待替换持久 Store） |
| 技能分发 | 磁盘 + 沙箱 + Store 三处，MD5/内容比对同步 | 支持运行期新增技能且可跨会话保留 | 三处状态需一致，调试成本高 |
| 订单更新 | 物理删除 + 重新插入 | 规避逻辑删除下的明细全量替换复杂度 | 违反"部分更新"直觉，破坏外键级联，工具侧必须读-合并-写 |
| 前端流式 | `fetch` + `ReadableStream` 而非 `EventSource` | `EventSource` 只支持 GET，无法提交消息体 | 需手写 SSE 行解析与缓冲区管理 |

---

## 7. 扩展点

| 想做的事 | 改哪里 |
|----------|--------|
| 新增一个 ERP 业务工具 | `mcp_server/tools/` 加分组文件 → `server_main.py` 注册 → `subagents/configs/*.yaml` 的 `tools` 加名称（子串匹配） |
| 新增一个子 Agent | `agent/subagents/configs/` 加 YAML（`name`/`description`/`system_prompt`/`tools` 必填）→ 如需专属中间件则改 `middleware_config.py` 与 `main_agent.py` Phase 6 |
| 新增技能 | 放进 `src/skills/{scope}/{name}/SKILL.md`（预置），或让 Agent 走 `skill-management` 流程安装 |
| 新增图表类型 | 远程可视化 MCP 提供即可自动被合并；同时更新 `chart_generator.CHART_TYPE_GUIDE` 与 `_COMPACT_TABLE` |
| 换模型 | `.env` 的 `MAIN_MODEL_NAME` / `SUMMARY_MODEL_NAME`（OpenAI 兼容接口均可，默认 DeepSeek） |
| 把记忆改为持久化 | `agent/config.py` 的 `STORE = InMemoryStore()` 替换为持久 Store 实现 |
| 新增 ERP 业务模块 | Java 侧加 entity/mapper/service/controller → `docs/database_schema.sql` 同步 → MCP 侧加工具 |

---

## 8. 相关文档

- [安装与部署](SETUP_AND_DEPLOYMENT.md) — 把上面这套跑起来
- [API 参考](API_REFERENCE.md) — REST/MCP/SSE 契约细节
- [数据库设计](DATABASE.md) — 表结构与模拟数据
- [AI 智能体详解](AI_AGENT.md) — Agent 内部机制深入
- [前端说明](FRONTEND.md) — 两个前端工程
- [开发指南](DEVELOPMENT_GUIDE.md) — 工作流、约定与已知技术债
