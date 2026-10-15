# AI 智能体详解（ERP_OPENCLAW）

本文深入 AI 采购助手的实现机制。总体架构见 [ARCHITECTURE.md](ARCHITECTURE.md)，接口契约见 [API_REFERENCE.md](API_REFERENCE.md)。

技术栈：DeepAgents（`create_deep_agent`）· LangGraph 1.x · LangChain · FastAPI · FastMCP · MongoDB。模型走 OpenAI 兼容接口，默认 DeepSeek（`deepseek-chat`）。

---

## 1. 目录结构

```
ERP_OPENCLAW/
├── .env / .env.example            环境变量（模型密钥、MongoDB、沙箱、MCP 地址）
├── langgraph.json                 LangGraph CLI 配置（graphs.agent → src/agent/main_agent.py:agent）
├── pyproject.toml                 包定义（模板遗留，实际依赖见 requirements.txt）
├── requirements.txt               真实依赖清单（pyproject.toml 是模板遗留，不可用）
├── start_web.py                   一键启动（后端 8090 + 前端 3000，含就绪轮询）
├── readme.txt                     手工记录的 pip 安装命令
├── frontend/                      Vue 3 聊天界面（见 FRONTEND.md）
├── mcp工具列表.txt                 诊断快照：远程可视化 MCP 的 27 个 generate_* 工具 repr（含完整 JSON Schema）
├── motorparts_db.sql              诊断快照：同上内容（文件名有误导性，**不是 SQL 文件、不是数据库导出**）
└── src/
    ├── agent/
    │   ├── main_agent.py          ★ 入口：9 阶段初始化流水线 + 懒加载代理
    │   ├── config.py              模型实例、Store、Checkpointer、路径常量
    │   ├── env_utils.py           统一环境变量读取（.env → os.environ）
    │   ├── schema.py              数据结构：ProcurementContext、Message、SSE 事件等
    │   ├── middleware_config.py   子 Agent 中间件工厂
    │   ├── log_utils.py           日志工具
    │   ├── mcp_tools_bean.py      MCP 工具 Bean（与 mcp_server 下同名文件一致）
    │   ├── backends/
    │   │   ├── sandbox_setup.py       沙箱创建、目录预建、技能播种、venv 预装
    │   │   ├── local_sandbox.py       LocalWslSandboxBackend（WSL 实现）
    │   │   └── custom_opensandbox.py  OpenSandboxBackend（容器实现）
    │   ├── middlewares/
    │   │   ├── context_injection.py   注入 user_id/username
    │   │   ├── memory_update.py       自动维护 recent_suppliers/recent_queries
    │   │   ├── skills_sync.py         本地技能 → 沙箱增量同步
    │   │   ├── user_skills_restore.py StoreBackend → 沙箱技能恢复
    │   │   └── tools_summarization.py 摘要中间件工厂
    │   ├── subagents/
    │   │   ├── loader.py              YAML → SubAgent dict，工具名解析
    │   │   └── configs/
    │   │       ├── procurement_analyst.yaml
    │   │       └── procurement_order.yaml
    │   ├── tools/
    │   │   ├── mcp_client.py          MultiServerMCPClient 连接与分组
    │   │   ├── chart_generator.py     26 图 → 1 工具合并
    │   │   ├── hitl_tools.py          request_order_info（interrupt）
    │   │   ├── assign_skill.py        技能分配 + StoreBackend 持久化
    │   │   ├── download_sandbox_file.py  沙箱文件下载到本地
    │   │   └── web_search.py          智谱 Web Search
    │   └── memory/
    │       ├── AGENTS.md              ★ 全局行为准则（上传到沙箱 /AGENTS.md）
    │       └── prompts.py             主 Agent 系统提示词
    ├── api_view/
    │   ├── web_main.py            FastAPI 应用 + lifespan + CORS
    │   ├── web_config.py          API 元信息与路径
    │   ├── agent_loader.py        ★ Agent 单例 + 会话查询 + 展示消息存取
    │   └── api/
    │       ├── chat.py            ★ SSE 流式对话与中断恢复
    │       └── history.py         会话列表/消息/删除
    ├── mcp_server/
    │   ├── server_main.py         FastMCP 实例与工具注册
    │   ├── server_config.py       JAVA_API_BASE_URL / MCP_HOST / PORT / PATH
    │   ├── http_base.py           lifespan 中创建 httpx.AsyncClient
    │   └── tools/
    │       ├── suppliers_tools.py  supplier_query
    │       ├── parts_tools.py      part_query / part_search / part_by_supplier
    │       ├── order_tools.py      order_create / order_update / order_search_details
    │       └── inventory_tools.py  inventory_warning
    ├── skills/                    技能包（见 §6）
    ├── download/                  下载产物（历史分析报告样例）
    └── test/                      验证脚本（见 DEVELOPMENT_GUIDE.md）
```

---

## 2. 初始化流水线（`main_agent.py`）

`create_main_agent(config, sandbox_id=None)` 是唯一的图工厂，每次调用都完整走一遍初始化流水线。

> **关于"几个阶段"**：源码自身有三套说法——函数 docstring 写"11 阶段"，`logger.info` 写 `Phase N/10`，而实际的阶段常量只有 **Phase 1 到 Phase 9**（另有 1.4、1.5、3.6 三个小数子步骤）。**没有 Phase 10**。本文按实际执行顺序列出 9 个编号阶段（共 12 个代码块）。

```python
async def create_main_agent(config=None, *, sandbox_id=None):
    # Phase 1   沙箱：setup_sandbox(SANDBOX_CONFIG, sandbox_id)
    #             └─ _create_sandbox → local(WSL) 或 opensandbox
    #             └─ _ensure_dirs   → /analysis/temp /data /skills
    #             └─ _seed_files    → 技能播种（内容比对，跳过未变文件）
    #             └─ _create_venv   → /opt/skills-venv + 预装 5 个包
    # Phase 1.4 上传 AGENTS.md 到沙箱 /AGENTS.md
    # Phase 1.5 组装 CompositeBackend（/memories/ 与 /persisted-skills/ → StoreBackend）
    # Phase 2   load_mcp_tools() → all / analyst / order / chart 四组
    # Phase 3   create_generate_chart_tool() → 26 个可视化工具合并为 generate_visualization
    # Phase 3.6 create_assign_skill_tool() / create_download_tool()
    # Phase 4   构建 available_tools 工具池
    # Phase 5   load_subagent_configs() 读 YAML
    # Phase 6   create_analyst_middleware() / create_order_middleware()
    # Phase 7   resolve_subagent_tools() 工具名 → 工具对象
    # Phase 8   主 Agent 中间件栈（7 个）
    # Phase 9   create_deep_agent(...) 编译并返回图
```

### 2.1 `create_deep_agent` 的实际参数

```python
agent_graph = create_deep_agent(
    model=MAIN_MODEL,                         # ChatOpenAI → DeepSeek
    system_prompt=system_prompt,              # memory/prompts.py
    skills=["/skills/main/"],                 # 主 Agent 的技能 scope
    memory=[AGENTS_MD_FILENAME],              # "/AGENTS.md"
    tools=[web_search, assign_skill, download_sandbox_file],   # 无 ERP 业务工具
    subagents=subagents,                      # 两个 YAML 子 Agent
    middleware=main_middleware,               # 7 个中间件
    backend=backend,                          # CompositeBackend
    store=STORE,                              # InMemoryStore
    checkpointer=CHECKPOINTER,                # MongoDBSaver
    context_schema=ProcurementContext,        # 运行时上下文类型
)
```

**关键设计：主 Agent 不持有任何 MCP 业务工具。** `tools` 列表只有 3 个通用工具。这是架构层面的强制约束——ERP 写操作必须经过带 `interrupt_on` 审批的 `procurement-order` 子 Agent，主 Agent 无法绕过审批直接下单。

### 2.2 懒加载代理

模块级导出 `agent = _AgentProxy()`，兼容两种初始化场景：

| 场景 | 调用方式 | 说明 |
|------|----------|------|
| 同步脚本（`agent_test.py`） | `get_agent()` | 无运行中的事件循环时用 `asyncio.run(_create_agent())` |
| 异步服务（FastAPI lifespan） | `await get_agent_async()` | 在已有事件循环中直接 `await` |

`_AgentProxy.__getattr__` 在首次属性访问时触发初始化；若检测到事件循环正在运行却用了同步入口，会抛出带指引的 `RuntimeError`。

### 2.3 模型配置（`config.py`）

| 实例 | 模型 | temperature | max_tokens | 用途 |
|------|------|-------------|------------|------|
| `MAIN_MODEL` | `MAIN_MODEL_NAME`（默认 `deepseek-chat`） | **1.1** | 8192 | 主 Agent 与子 Agent 默认模型 |
| `SUMMARY_MODEL` | `SUMMARY_MODEL_NAME` | 0.3 | 8192 | 摘要、中间件实体抽取 |
| `FALLBACK_MODEL` | `glm-4-plus`（智谱） | 1.0 | 8192 | 备用；**未配 `ZHIPU_API_KEY` 时为 `None`** |

三者都带 `extra_body={"thinking": {"type": "disabled"}}`（关闭 DeepSeek 的思考模式输出）。主模型 temperature 取 1.1（偏高，鼓励分析类任务的多样性），摘要模型取 0.3（要求稳定输出）。

---

## 3. 中间件详解

### 3.1 `ContextInjectionMiddleware`

`before_agent` 钩子，把运行时上下文以 `SystemMessage` 注入：

```
【系统上下文】
当前用户 user_id: yummyQian
当前用户 username: yummyQian
用户偏好文件路径: /memories/yummyQian/preferences.md

请首先使用 read_file 读取上述偏好文件了解用户偏好。
（recent_suppliers 和 recent_queries 由系统自动维护，你无需手动更新）
```

`runtime.context` 为 `None` 或缺 `user_id` 时跳过并记 warning。`abefore_agent` 直接复用同步实现。

> **注意**：这条 `SystemMessage` 会被 `chat.py` 的 token 过滤规则排除（见 [API_REFERENCE.md](API_REFERENCE.md) §3.4），不会泄漏到前端。

### 3.2 `SkillsSyncMiddleware`

`before_agent` 钩子，把 `src/skills/` 下的变更推送到沙箱 `/skills/`。三级短路以降低开销：

1. **本地 MD5 缓存**（`self._last_hashes`）—— 本地内容未变则跳过；
2. **沙箱 `test -f`** —— 先确认文件存在，避免 `download_files` 对 404 打 ERROR 日志；
3. **沙箱内容 MD5 比对** —— 远端一致则只更新缓存不上传。

有变更时返回一条 `SystemMessage` 通知（"以下技能包已更新：…请使用 `ls /skills/` 查看详情"），让 Agent 感知新能力。异步版本通过 `run_in_executor` 把同步 IO 移出事件循环。

### 3.3 `UserSkillsRestoreMiddleware`

`abefore_agent` 钩子（**仅异步**，同步版本空实现）。从 StoreBackend 读取 `("skills",)` 命名空间下的所有条目，把 key 映射回沙箱路径后上传：

```
StoreBackend key: {scope}/{skill_name}/...   →   沙箱 /skills/{scope}/{skill_name}/...
```

### 3.4 摘要中间件

`build_summarization_middleware(backend, model)` 包装 DeepAgents 的 `create_summarization_tool_middleware`，提供两项能力：

- **自动摘要**：上下文接近模型上限（约 85%）时压缩历史，完整历史持久化到文件系统；
- **主动摘要**：暴露 `compact_conversation` 工具，Agent 可在关键节点主动调用。

`AGENTS.md` 明确要求：收到子 Agent 长报告（> 约 2000 字）后**必须**调用 `compact_conversation`；对话超 6 轮且距上次压缩超 3 轮时主动压缩。

### 3.5 `MemoryUpdateMiddleware`

`aafter_agent` 钩子（异步）。这是唯一会写用户记忆文件的自动化组件。

**触发判定**（`_is_meaningful_erp_exchange`，两道闸）：

1. **排除无意义消息**：命中 `_SKIP_PATTERNS`（`你好`、`在吗`、`你能做什么`、`我的偏好`…）则跳过；
2. **要求命中 ERP 关键词**：`_TRIGGER_KEYWORDS` 含 供应商/物料/采购/订单/价格/分析/对比/比价/报价/评估/筛选/推荐/行情/预算/库存/交货/交期/质量/成本/招标 及英文 `supplier`/`part`/`order`/`price`/`analysis`。若未命中，兜底检查 messages 中是否调用过 `task` 工具（委派过子 Agent 也算有效交互）。

**抽取**：用 `SUMMARY_MODEL` 发一个英文学术式提示词，要求**只返回 JSON**：

```json
{"suppliers": ["CompanyA", "CompanyB"], "query": "brief summary"}
```

解析时用"第一个 `{` 到最后一个 `}`"的宽松截取，失败则记 warning 并跳过（不影响主流程）。

**合并**（`_merge_preferences`）：
1. 定位并解析现有的 `recent_suppliers:` / `recent_queries:` 块（同时支持 inline `[a, b]` 与多行 `- xxx` 两种格式）；
2. 从原内容中删除这两个块（按起始位置**降序**处理避免索引偏移）；
3. 新值在前、旧值去重后追加，供应商上限 **10** 条、查询上限 **5** 条；
4. 重新追加两个块（空列表写作 `recent_suppliers: []`）。

写入用 `_create_file_value` 构造 `{"content": [行数组], "created_at", "modified_at"}`，与 `deepagents.backends.utils.create_file_data` 的格式保持一致，这样 `read_file` 能正常读取。

### 3.6 调用限制

主 Agent 与 `procurement-analyst`：`ModelCallLimitMiddleware(run_limit=50)` + `ToolCallLimitMiddleware(run_limit=200)`。
`procurement-order`：`run_limit=20` / `50`（订单操作链路短）。

---

## 4. 子 Agent

### 4.1 加载机制（`subagents/loader.py`）

`load_subagent_configs()` 扫描 `subagents/configs/*.yaml`（按文件名排序），校验必填字段后返回原始 dict。

**必填字段**：`name`、`description`、`system_prompt`、`tools`（须为非空列表、`system_prompt` 须为非空字符串）。**可选字段**：`model`、`skills`、`interrupt_on`、`middleware`。

`resolve_subagent_tools(configs, available_tools, extra_middleware)` 完成名称到对象的解析：

```python
for pattern in config.get("tools", []):
    for tool_name, tool_obj in tool_index.items():
        if pattern in tool_name:          # ← 子串匹配
            resolved_tools.append(tool_obj)
```

**子串匹配的能力与风险**：
- 能力：写 `supplier_` 一次匹配所有 `supplier_*` 工具，新增同类工具无需改配置；
- 风险：写 `part_` 会同时命中 `part_query`、`part_search`、`part_by_supplier`；写 `order_` 会命中 `order_search_details`。未匹配到任何工具时会打印 `[WARNING]` 但**不报错**——配置写错只会在运行期表现为"子 Agent 少了工具"，需留意启动日志。

去重按工具 `name` 保序进行。最后合并 `extra_middleware[config["name"]]` 并组装成 `SubAgent` dict。

### 4.2 `procurement-analyst`（采购分析专家）

| 项 | 值 |
|----|-----|
| 触发语义 | 分析、对比、报告、建议、评估、行情、比价、筛选 |
| 工具 | `supplier_query`、`part_query`、`part_search`、`part_by_supplier`、`order_search_details`、`inventory_warning`、`generate_visualization`、`web_search` |
| 技能 | `/skills/procurement/` |
| 中间件 | 摘要 + `ModelCallLimit(50)` + `ToolCallLimit(200)` |
| 人工确认 | 无 |

**工作流（来自 `system_prompt` + `procurement-analysis/SKILL.md`）**：

```
启动    ls /skills/procurement/ 扫描可用技能
        read_file(".../procurement-analysis/SKILL.md") 加载操作手册
        读取已被注入的【用户偏好】区块并严格遵循
第1步   理解需求（提取任务目标/用户偏好/需求正文）
第2步   收集数据
        2a ERP 内部（必须）：supplier_query / part_query / part_search /
                             part_by_supplier / order_search_details / inventory_warning
        2b 外部（不可跳过）：
             激活 supplier-price-urls 技能 → 读 data/url_mapping.yaml 找报价 URL
             找到 → execute("python /skills/procurement/web-scraper/scrape_page.py --url '<URL>'")
                    结果存 /analysis/temp/{filename}.md → read_file 提取价格/型号/品牌
             未找到 → web_search 搜索市场价格与规格
第3步   执行分析：写 Python 脚本 → execute 运行（pandas/numpy 已预装）
第4步   生成图表：首次先 read_file chart_params.md → 循环调 generate_visualization
第5步   生成报告：write_file("/analysis/report_{timestamp}.md")
返回    【报告路径】【摘要】【结论】【建议】
```

**文件系统策略**：DeepAgents 内置自动 offload（工具结果 > 20k tokens 自动落盘）与自动摘要，因此子 Agent **只需显式写最终报告**，不要返回原始 JSON。

### 4.3 `procurement-order`（采购订单专家）

| 项 | 值 |
|----|-----|
| 触发语义 | 下单、创建订单、修改采购单、更新订单、取消订单、订单状态、交期变更 |
| 工具 | `order_create`、`order_update`、`order_search_details`、`web_search`、`request_order_info` |
| 技能 | `/skills/order/` |
| 中间件 | `ModelCallLimit(20)` + `ToolCallLimit(50)` |
| 人工确认 | `interrupt_on`: `order_create` / `order_update` → `allowed_decisions: ["approve","reject"]` |

**工作流（四步，含数据预校验）**：

```
第1步 提取已有数据（从任务描述与上下文）
第2步 Schema 校验
        orderDetail 每项的 partId / quantity / unitPrice 是否齐全？
        供应商信息是否明确？
        修改操作时 order_id 是否明确？
第3步 循环补充缺失数据
        缺失 → request_order_info(missing_fields, collected_data) → interrupt → 暂停
        人工输入自由文本 → 按规则解析 → 合并 → 重新校验
        解析规则：键值对（物料ID=100 / 数量: 50 / 单价25.5元）
                  日期（预计6月15日交货 → expectedDeliveryDate: 2026-06-15）
                  备注（备注：加急订单 → remark: 加急订单）
                  供应商（供应商是博世 → 查供应商 ID）
第4步 执行操作
        调 order_create / order_update → 自动触发审批 interrupt → approve 后真正执行
        成功 → 返回确认信息 / 失败 → 如实汇报（不重试超过 2 次）
```

**返回给主 Agent 的格式**：

```
【操作结果】成功 / 失败
【操作类型】创建订单 / 修改订单
【订单信息】订单编号 / 订单 ID / 供应商 ID / 订单金额 / 订单状态 / 其他变更
【备注】
```

**行为准则要点**：最小变更原则（不传 `None`）；`status` 必须 1–5；`totalAmount` 为正数；日期格式 `yyyy-MM-dd`，`orderTime` 用 `yyyy-MM-ddTHH:mm:ss.SSS`；**绝不编造订单编号、金额或任何业务数据**。

---

## 5. Human-in-the-Loop 机制

系统有**两层**人工介入，均由 LangGraph 的 `interrupt()` 实现，状态通过 MongoDBSaver 持久化，跨 HTTP 请求恢复。

### 5.1 第一层：数据补充（`request_order_info`）

`tools/hitl_tools.py`：

```python
@tool
def request_order_info(missing_fields: str, collected_data: str) -> str:
    response = interrupt({
        "type": "order_info_request",
        "missing_fields": missing_fields,
        "collected_data": collected_data,
    })
    return json.dumps(response, ensure_ascii=False)
```

由**子 Agent 的提示词**驱动何时调用（不是代码强制），因此依赖 `procurement_order.yaml` 中第三步的描述准确。

### 5.2 第二层：审批（`interrupt_on`）

子 Agent YAML 声明：

```yaml
interrupt_on:
  order_create:
    allowed_decisions: ["approve", "reject"]
  order_update:
    allowed_decisions: ["approve", "reject"]
```

由 DeepAgents 框架在工具执行前拦截，无需业务代码参与。

### 5.3 中断检测与恢复（`api/chat.py`）

**检测**：`astream(stream_mode=["messages", "values"])` 的 `values` 流中带 `interrupts` 字段时判定中断。**必须在处理 messages 之前判断**——否则中断信号会被后续消息流淹没。

**分发**：

```python
if "action_requests" in interrupt_value:          # 第二层：审批
    → {"interrupt_type": "hitl_approval", "action_requests": [...], "review_configs": [...]}
elif interrupt_value.get("type") == "order_info_request":   # 第一层：数据补充
    → {"interrupt_type": "order_info_supplement", "missing_fields": ..., "collected_data": ...}
else:                                              # 未知类型，透传
    → {"interrupt_type": "unknown", "interrupt_value": str(...)[:2000]}
```

**中断后的收尾**（顺序重要）：
1. 兜底把所有 `calling` 状态工具标记 `done`（否则前端会一直转圈）；
2. 过滤掉空 `content` 的 assistant 消息；
3. `save_display_messages(thread_id, cleaned)` 保存中断前的消息状态；
4. 发 `done` 事件并带 `"interrupted": True`；
5. `return` —— **结束本次流**，等前端调 `/resume`。

**恢复**：

```python
if resume_data is not None:
    display_messages = await agent_loader.get_display_messages(thread_id) or []  # 读回历史
    current_input = Command(resume=resume_data)                                   # 而非新消息
```

恢复模式下**不新建** `display_messages`，而是从库里读回，因此保存时是覆盖而非追加（避免历史被截断）。非恢复模式则把已有的历史 `+` 本轮消息一起保存。

**链式中断**：恢复后仍可能再次中断（典型：先数据补充 → 再审批）。前端在 `resumeChat` 的回调中也注册了 `onInterrupt`。

### 5.4 展示消息的累积与保存

`stream_chat_response` 在推送 SSE 的同时，同步维护一份 `display_messages` 列表：

| 事件 | 对 `display_messages` 的操作 |
|------|------------------------------|
| 初始化（非恢复） | 追加一条 user 消息 |
| `token` | 末条是 assistant 则追加 `content`，否则新建 assistant 消息（带 `source`） |
| `tool_start` | 追加 `{role:"tool", tool_status:"calling"}` |
| `tool_args` | 从后向前找最后一个 `calling` 工具，追加 `args` |
| `tool_result` | 按 `tool_call_id` 定位并填充 `text`/`images`，置 `done` |

嵌套工具调用（主 Agent 调 `task`，子 Agent 内部再调工具）靠 **`tool_call_stack` 栈**管理：新的 `tool_start` 压栈，`tool_result` 弹栈。服务端与前端各维护一份同样的栈（`chat.py` 与 `frontend/src/api/chat.js`），逻辑必须保持一致。

---

## 6. 技能（Skills）体系

### 6.1 三层存储与流转

```
   ① 本地磁盘                      ② 沙箱                         ③ StoreBackend
   src/skills/{scope}/{name}/      /skills/{scope}/{name}/        ("skills",) 命名空间
          │                                │                              │
          │  SkillsSyncMiddleware          │                              │
          │  (MD5 增量, 每轮 before_agent) │                              │
          ├───────────────────────────────▶│                              │
          │                                │                              │
          │  setup_sandbox._seed_files     │                              │
          │  (首次播种, 内容比对)           │                              │
          ├───────────────────────────────▶│                              │
          │                                │  assign_skill 工具            │
          │                                ├─────────────────────────────▶│
          │                                │                              │
          │                                │  UserSkillsRestoreMiddleware │
          │                                │◀─────────────────────────────┤
          │                                │  (每轮 abefore_agent)         │
```

### 6.2 Scope 映射

`config.py`：

```python
SCOPE_MAP = {
    "main": "main",                          # 主 Agent
    "procurement-analyst": "procurement",    # 分析子 Agent
    "procurement-order": "order",            # 订单子 Agent
}
```

这是全项目唯一的 Agent↔scope 映射，`assign_skill` 工具与 `UserSkillsRestoreMiddleware` 都依赖它。

### 6.3 已内置的技能

| 技能 | 位置 | 作用 |
|------|------|------|
| `skill-management` | `main/` | 技能全生命周期管理：从 URL 下载 ZIP、创建新技能、沙箱内测试、`assign_skill` 分配、持久化。含 `scripts/download_skill.py` |
| `procurement-analysis` | `procurement/` | 采购分析主技能包：5 步分析流程、报告模板、图表类型速查表、返回格式约定 |
| `supplier-price-urls` | `procurement/` | 供应商报价 URL 映射（`data/url_mapping.yaml`：按零部件名 + 供应商名定位报价页） |
| `web-scraper` | `procurement/` | 沙箱内 HTTP 抓取（`scrape_page.py`，HTML → Markdown 存 `/analysis/temp/`），支持内网 URL |
| `web-content-fetcher` | `procurement/` | 网页内容抓取辅助（`fetch_content.py` / `fetch.sh`） |
| `chart_params.md` | `procurement/`（非技能目录） | 26 种可视化图表的完整参数 schema，由 `build_chart_params_md` 从 MCP 工具 schema 自动生成 |

### 6.4 新增技能的两种方式

**方式一：预置（开发者）** —— 直接把技能目录放进 `src/skills/{scope}/{name}/`，包含 `SKILL.md`（带 `name` / `description` frontmatter）。下次 Agent 启动时 `SkillsSyncMiddleware` 会自动同步到沙箱，子 Agent 通过 `ls` 渐进式发现。

**方式二：运行期安装（用户）** —— 对主 Agent 说"帮我装一个 XXX 技能"，触发 `skill-management` 技能的 5 阶段流程：

```
阶段1 下载解压   execute("python /skills/main/skill-management/scripts/download_skill.py '{url}'")
阶段2 创建模式   用户只描述需求时，生成 SKILL.md 并 write_file
阶段3 功能测试   py_compile 语法检查 + --help 可执行性验证（纯指引型技能跳过执行测试）
阶段4 分配持久化  assign_skill(skill_name, agent_name) → 复制到 scope + 写 StoreBackend + 清理压缩包
阶段5 未指定目标 提醒用户选择 procurement-analyst 或 procurement-order
```

> **文档与实现的偏差**：`SKILL.md` 里写的是 `assign_skill(skill_name, subagent_name)`，工具实际参数名是 `agent_name`。

### 6.5 `assign_skill` 工具实现

```python
async def assign_skill(skill_name: str, agent_name: str) -> str:
    scope = SCOPE_MAP[agent_name]                     # 校验目标 Agent
    source_dir = f"/skills/main/{skill_name}"         # 校验源技能存在（test -f SKILL.md）
    target_dir = f"/skills/{scope}/{skill_name}"
    if agent_name != "main":
        execute(f"mkdir -p {target_dir} && cp -r {source_dir}/* {target_dir}/")
    await _persist_skill(...)                         # find → download_files → store.aput
    _cleanup_packages(...)                            # rm -f *.zip *.tar.gz *.tar *.tgz ...
```

持久化时 key 的构造：`/skills/main/web-fetcher/SKILL.md` → `/{scope}/web-fetcher/SKILL.md`，value 为 `{"content": [内容], "created_at", "modified_at"}`。

---

## 7. 记忆与状态

### 7.1 五类状态的存放位置

| 状态 | 位置 | 生命周期 | 更新者 |
|------|------|----------|--------|
| 全局行为准则 | 沙箱 `/AGENTS.md` ← `memory/AGENTS.md` | 进程内（每次启动重传） | 开发者；Agent 只读 |
| 系统提示词 | `memory/prompts.py::system_prompt` | 编译进图 | 开发者 |
| 用户偏好 | Store `/memories/{user_id}/preferences.md` | **进程内**（InMemoryStore） | Agent 显式写 + `MemoryUpdateMiddleware` 自动写 |
| 持久化技能 | Store `("skills",)` | **进程内**（InMemoryStore） | `assign_skill` |
| 对话状态 / 展示消息 | MongoDB | 跨重启 | MongoDBSaver / AgentLoader |

### 7.2 用户隔离

由 `CompositeBackend` 的 namespace 回调在**运行时**解析：

```python
def _user_memories_namespace(rt) -> tuple:
    context = getattr(rt, "context", None)
    user_id = getattr(context, "user_id", None) or "laoxiao"
    return (str(user_id),)
```

> **注意 deepagents 0.7 的破坏性变更**：`backend` 参数只接受**已实例化的后端对象**，不再接受工厂函数。因此用户隔离从"每个用户一个后端实例"改为"一个后端 + 运行时 namespace 回调"。`main_agent.py` 的注释对此有明确说明。

**当前的单用户现实**：`api/chat.py` 里 `context` 是硬编码的——

```python
context = {"user_id": "yummyQian", "username": "yummyQian"}
```

因此实际运行的系统中所有对话都归到同一个 `user_id`。要实现多用户，需要在请求体中加 `user_id` 并透传（见 §10 扩展指南）。

### 7.3 用户偏好文件格式

```yaml
preferred_output: chart          # "table" 或 "chart"
preferred_chart_type: bar        # "bar", "line", "pie", "radar"
preferred_currency: CNY          # "CNY", "USD", "EUR"
preferred_language: zh           # "zh", "en"
recent_suppliers:                # 最近使用/关注的供应商（最多 10 条，自动维护）
  - 博世
  - 大陆
recent_queries:                  # 最近 5 条分析需求摘要（自动维护）
  - 刹车片价格对比分析
  - Q2 线束采购预算评估
```

新用户首次对话时，Agent 会按 `AGENTS.md` 的指引用 `write_file` 创建此文件（默认值：`chart` / `bar` / `CNY` / `zh`）。

Agent **只应**在用户明确表达偏好变更时更新前 4 个字段；后 2 个字段由中间件维护，Agent 不应手动改。

---

## 8. 沙箱后端

### 8.1 两种模式的对比

| 维度 | `SANDBOX_MODE=local` | `SANDBOX_MODE=opensandbox` |
|------|----------------------|----------------------------|
| 执行环境 | 本机 WSL 发行版（默认 `Ubuntu-20.04`，用户 `root`） | 独立容器（默认镜像 `opensandbox/code-interpreter:v1.0.2`） |
| 部署成本 | 零（装好 WSL2 + 一个发行版即可） | 需自行部署 OpenSandbox 服务 |
| 隔离性 | 弱（root 在宿主机 WSL 内执行） | 强（容器隔离，可配网络策略） |
| 资源限制 | 无 | `cpu=2`、`memory=4Gi`、`timeout=2h` |
| 适用场景 | 个人开发、演示、离线环境 | 生产、多租户 |
| 实现类 | `LocalWslSandboxBackend` | `OpenSandboxBackend` |

两者都实现 `deepagents.backends.sandbox.BaseSandbox` 的 `execute` / `upload_files` / `download_files` / `id` 协议，因此上层完全无感。

### 8.2 `LocalWslSandboxBackend` 关键实现

**执行**：`wsl -d <distro> -u <user> -- bash -lc "<cmd>"`，并在命令前注入 PATH：

```python
SANDBOX_PATH = ("/opt/skills-venv/bin:"
                "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin")
wrapped = f'export PATH="{self.SANDBOX_PATH}:$PATH" && {command}'
```

因为直接使用 Linux 绝对路径（`/skills`、`/analysis`、`AGENTS.md`、`/opt/skills-venv`），**不需要任何路径映射**。

**文件传输**：走 base64（`base64 -w0` 下载 / `printf '%s' ... | base64 -d >` 上传），保证二进制安全与 UTF-8 正确性；路径经 `_sh_quote` 单引号转义防注入。

**发行版检测**：`wsl -l -q` 的输出是 **UTF-16LE**，代码先按 `utf-16-le` 解码、失败再退回 `utf-8`。发行版不存在时抛 `LocalSandboxError` 并提示 `wsl -l -v` 与 `WSL_DISTRO` 环境变量。

**超时**：默认 3600 s；超时返回 `exit_code=124` 而非抛异常。

### 8.3 沙箱初始化（`sandbox_setup.setup_sandbox`）

```
_ensure_dirs        mkdir -p /analysis/temp /data /skills
_seed_files         技能文件比对后上传（内容一致则跳过）
_create_venv        python3 -m venv /opt/skills-venv
                    pip install --upgrade pip（清华镜像）
                    预装 numpy pandas matplotlib requests beautifulsoup4
```

**venv 的 sentinel 机制**：每个包在 `/opt/skills-venv/.installed/{pkg}` 放一个哨兵文件。哨兵存在则跳过安装；哨兵缺失但 `pip show {pkg}` 成功则直接补哨兵、跳过联网。

> sentinel 刻意放在 venv 内部而非 `/tmp` —— WSL 重启会清空 `/tmp`，放那里会导致每次冷启动都重跑一遍 pip 解析。

**跳过 venv**：`SANDBOX_SETUP_VENV=0`（离线环境或不需要 Python 分析时）。镜像可通过 `SANDBOX_PYPI_INDEX` 覆盖（默认清华源）。

### 8.4 OpenSandbox 模式的资源与网络

```python
SandboxSync.create(
    image, entrypoint=["/opt/opensandbox/code-interpreter.sh"],
    env={"PYTHON_VERSION": "3.11"},
    resource={"cpu": "2", "memory": "4Gi"},
    timeout=timedelta(hours=2),
    connection_config=config,
    # network_policy=NetworkPolicy(defaultAction="deny", egress=[...])  ← 已注释
)
```

网络策略代码**处于注释状态**（默认放行）。生产部署建议启用 `defaultAction="deny"` 并只放行必要域名（`pypi.org`、`*.github.com` 等）。

`ConnectionConfigSync` 设置 `request_timeout=60s`、`max_connections=20`、`use_server_proxy=True`。

### 8.5 沙箱内的目录约定

| 路径 | 用途 |
|------|------|
| `/AGENTS.md` | 全局行为准则（只读） |
| `/skills/{scope}/` | 技能包 |
| `/memories/{user_id}/` | 用户偏好（**经 CompositeBackend 路由到 Store，不在沙箱磁盘**） |
| `/persisted-skills/` | 持久化技能（**路由到 Store**） |
| `/analysis/` | 分析产物，报告写 `/analysis/report_{timestamp}.md` |
| `/analysis/temp/` | 网页抓取的中间 Markdown |
| `/data/` | 分析数据文件、图表 |
| `/opt/skills-venv/` | Python 虚拟环境（PATH 已注入） |

> `/memories/` 与 `/persisted-skills/` 虽以沙箱路径形式出现，但被 `CompositeBackend` 拦截并路由到 StoreBackend，**不会落在沙箱文件系统上**。

### 8.6 产物回传

沙箱内生成的文件通过 `download_sandbox_file(sandbox_path, local_filename="")` 工具下载到本地 `src/download/`：

- 路径必须以 `/` 开头（绝对路径校验）；
- `local_filename` 经 `Path(...).name` 处理，**防路径穿越**；
- 返回带文件大小的确认信息。

仓库 `src/download/` 下的 3 个 `report_*.md` 就是这条路径产生的结果样例。

---

## 9. 提示词工程要点

### 9.1 三层提示词结构

| 层 | 位置 | 内容 |
|----|------|------|
| 系统提示词 | `memory/prompts.py` | 角色定位（"你是协调者，不是执行者"）、启动动作、委派要求 |
| 行为准则 | `memory/AGENTS.md`（→ 沙箱 `/AGENTS.md`） | 对话生命周期 4 阶段、委派模板、记忆规范、上下文管理表、数据完整性、安全边界 |
| 技能手册 | `skills/{scope}/{name}/SKILL.md` | 具体任务的详细操作流程（按需 `read_file` 加载） |

这种分层的目的是**渐进式披露**：常驻上下文的只有系统提示词与 AGENTS.md，详细流程放在技能文件里按需读取，避免一次性占满上下文。

### 9.2 委派模板（`AGENTS.md` 强制）

主 Agent 调用 `task` 时，`description` **必须**包含固定结构：

```
【任务目标】（一句话）
【用户偏好】输出格式 / 图表类型 / 货币单位 / 用户名 / 用户ID
【分析需求正文】（用户完整原始需求）
【输出要求】报告路径 / 摘要（≤500字）/ 结论 3-5 条 / 采购建议
【重要提醒】开始前先 ls /skills/procurement/ 扫描技能目录
```

订单子 Agent 的模板则是【操作类型】【订单信息】【用户信息】。模板化让子 Agent 无需追问即可获得完整上下文。

### 9.3 不委派的判定标准

`AGENTS.md` 给出的判定线：**是否涉及当前 ERP 系统中的业务数据？**

- **是** → 委派对应子 Agent；
- **否** → 主 Agent 用 `web_search` 或已有知识直接回答。

明确列出不委派的场景：简单问候、功能询问、通用知识问答、技术概念解释、市场行情咨询、采购理论知识、已有记忆查询、技能管理操作。

### 9.4 防幻觉约束

`AGENTS.md` 的"数据完整性"节：

- 所有采购数据、供应商信息**必须**来自子 Agent 的分析结果，禁止编造；
- 子 Agent 返回 `error` → 如实说明并询问是否重试；
- MCP 工具返回空结果（"没有查询到任何信息"）→ 向用户说明而非编造；
- 价格、供应商名称、订单号等关键信息在回复中保持与数据源一致。

订单子 Agent 另有"绝不编造订单编号、金额或任何业务数据"。

### 9.5 上下文管理规则（`AGENTS.md`）

| 场景 | 要求动作 |
|------|----------|
| 收到子 Agent 长篇报告 | **必须**调用 `compact_conversation` |
| 对话超 6 轮且距上次压缩超 3 轮 | 主动调用 `compact_conversation` |
| 用户连续问多个不同方向的问题 | 主动调用 `compact_conversation` |
| 系统自动触发摘要 | 正常继续，无需额外操作 |

### 9.6 安全边界（`AGENTS.md`）

- 不修改 `/AGENTS.md`（只读）；
- 不访问其他用户的 `/memories/{other_user_id}/`；
- **所有订单操作必须经过 `procurement-order` 子 Agent，不得绕过**；
- 技能下载/创建必须在沙箱内完成，不得在本地或 StoreBackend 直接运行未验证的技能代码；
- 不清楚用户意图时先确认再委派，不要猜测。

---

## 10. 扩展指南

### 10.1 新增一个 ERP 业务工具

```
① mcp_server/tools/ 新建分组文件（或加入现有分组）
     GROUP_NAME = "warehouse"
     @mcp.tool(name=f"{GROUP_NAME}_list")
     async def list_warehouses(ctx: Context) -> list:
         http_client = ctx.request_context.lifespan_context.get("http_client")
         resp = await http_client.get("/warehouses/page", params={...})
         resp.raise_for_status()
         result = resp.json()
         if result.get("code") != 200:
             return [f"API error: code={result.get('code')}"]
         return result.get("data", [])
② server_main.py 中 import 并 register_xxx_tools(mcp)
③ subagents/configs/*.yaml 的 tools 列表加入名称（支持子串，如 "warehouse_"）
④ 重启 MCP 服务与 AI 助手后端
```

**约定**：工具参数用 snake_case，内部映射为 Java 的 camelCase；只返回 `data` 字段；异常捕获后转成可读字符串（不向上抛）；列表型返回 `list`，对象型返回 `dict`。

### 10.2 新增一个子 Agent

```
① subagents/configs/{name}.yaml
     name: procurement-logistics
     description: > 物流追踪专家。当用户需求涉及"物流""运单""到货""配送"时委派。
     tools: [order_search_details, web_search]
     skills: [/skills/logistics/]
     interrupt_on: { ... }        # 可选
     system_prompt: |
       ...
② 如需专属中间件：middleware_config.py 加工厂函数，main_agent.py Phase 6 的
   extra_middleware 字典加映射
③ 如需专属技能 scope：config.py 的 SCOPE_MAP 加映射，并在 src/skills/ 下建目录
④ 如需主 Agent 学会委派它：更新 memory/AGENTS.md 的任务分配规则与委派模板
```

### 10.3 支持多用户

当前 `api/chat.py` 硬编码了 `user_id`。改造步骤：

```python
# ① schema.py：ChatRequest 增加 user_id / username
class ChatRequest(BaseModel):
    message: str
    thread_id: Optional[str] = None
    user_id: str = "default_user"
    username: Optional[str] = None

# ② chat.py：stream_chat_response 接收并透传
context = {"user_id": user_id, "username": username or user_id}
```

前端在 `frontend/src/api/chat.js` 的请求体中带上 `user_id` 即可。`CompositeBackend` 的 namespace 回调与 `MemoryUpdateMiddleware` 都已按 `runtime.context.user_id` 工作，无需改动。

### 10.4 把记忆改为持久化

```python
# agent/config.py
from langgraph.store.postgres import PostgresStore     # 或 RedisStore
STORE = PostgresStore(connection_string=...)
```

替换后 `/memories/{user_id}/preferences.md` 与持久化技能即可跨进程重启保留。注意 `STORE` 同时被 `CompositeBackend`、`create_deep_agent(store=...)` 与 `MemoryUpdateMiddleware`（经 `runtime.store`）使用，改一处即可全局生效。

### 10.5 新增图表类型

远程可视化 MCP 提供新工具后：
1. `chart_generator.CHART_TYPE_GUIDE` 加条目（供提示词引用）；
2. `_COMPACT_TABLE` 加一行（工具描述速查表）；
3. `build_chart_params_md` 的 `groups` 列表归入合适分组；
4. 重新生成 `chart_params.md`。

若工具名不以 `_chart` / `_map` / `_diagram` / `_graph` 结尾，会被归入 `other_tools` 作为独立工具暴露，需相应调整 `_CHART_SUFFIXES` / `_KEEP_SUFFIXES`。

---

## 11. 已知限制与技术债

| 项 | 说明 | 影响 |
|----|------|------|
| `STORE = InMemoryStore()` | 用户偏好与持久化技能仅存活于当前进程 | 重启后偏好丢失、已安装技能消失 |
| `context` 硬编码 `user_id="yummyQian"` | 所有对话归同一用户 | 多用户隔离形同虚设 |
| `motorparts_db.sql` 命名误导 | 位于 `ERP_OPENCLAW/` 根目录、188 KB，**内容其实是可视化 MCP 工具的 `StructuredTool` repr，不是 SQL**（与 `mcp工具列表.txt` 同源） | 容易被误当数据库导出而误删或误入库；建议改名或删除 |
| MCP 工具子串匹配 | `part_` 会命中 `part_by_supplier`；配置写错只告警不报错 | 子 Agent 可能拿到非预期工具 |
| `mcp_tools_bean.py` 两处重复 | `src/agent/` 与 `src/mcp_server/` 下同名同大小文件 | 修改时易漏改一处 |
| `ERPMCP` 无重连 | MCP 掉线后需重启 AI 后端 | 运维需监控 |
| 展示消息潜在不一致 | 双写（checkpoint 与 display_messages），中断路径与正常路径保存逻辑不同 | 极端情况下历史与实际状态不符 |
| `assign_skill` 参数名 | `SKILL.md` 文档写 `subagent_name`，实现是 `agent_name` | 照文档调用会失败 |
| 调试日志无限增长 | `chat.py` 把每次流的所有 chunk 写入 `%TEMP%/deepagent_debug/*.log` | 长期运行占磁盘 |
| 前端 AbortController 语义 | 取消请求后服务端流可能仍在跑（SSE 无双向取消） | 后台仍消耗模型额度 |
| `pyproject.toml` 仍是模板 | `name = "agent"`、依赖只有 2 项、README 是 LangGraph 模板 | 无法直接 `pip install -e .` 得到完整环境 |

替代安装方式（见 `readme.txt` 与 `requirements.txt`）：

```powershell
pip install fastmcp httpx langchain-daytona deepagents dotenv langchain-openai zai-sdk `
            langchain-mcp-adapters pillow pyyaml "langgraph-cli[inmem]" opensandbox-code-interpreter
pip install fastapi uvicorn langgraph-checkpoint-mongodb
```

---

## 相关文档

- [ARCHITECTURE.md](ARCHITECTURE.md) — 端到端链路与设计决策
- [API_REFERENCE.md](API_REFERENCE.md) — SSE 事件协议、MCP 工具清单
- [SETUP_AND_DEPLOYMENT.md](SETUP_AND_DEPLOYMENT.md) — 环境变量全量说明
- [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) — 调试脚本与工作流
