# 前端说明

本仓库包含**两个完全独立的前端工程**，定位与技术栈都不同：

| 工程 | 位置 | 定位 | 技术栈 | 是否连后端 |
|------|------|------|--------|-----------|
| **AI 聊天界面** | `ERP_OPENCLAW/frontend/` | 生产可用：AI 采购助手的对话界面 | Vue 3 + Vite 5 | **是**（`/api` 代理到 8090） |
| **电商演示页** | `MotorcyclePartsProcurementSystem/ecommerce-demo/` | 纯静态 UI 参考稿 | 生成式静态 HTML | **否**（不连任何后端） |

> ERP 后端（Java）**不提供任何页面**：`src/main/resources` 下只有 `application.yml`，没有 `static/` 或 `templates/`，也没有 `@Controller` 返回视图。后端只提供 REST API。

---

## 第一部分：AI 聊天界面（Vue 3）

## 1. 技术栈与工程结构

```json
// package.json
{
  "name": "deepagent-chat-frontend",
  "type": "module",
  "scripts": { "dev": "vite", "build": "vite build", "preview": "vite preview" },
  "dependencies": {
    "axios": "^1.6.8",          // 已声明，但实际网络请求用 fetch
    "highlight.js": "^11.11.1", // 代码块语法高亮
    "markdown-it": "^14.1.1",   // Markdown 渲染
    "vue": "^3.4.21"
  },
  "devDependencies": { "@vitejs/plugin-vue": "^5.0.4", "vite": "^5.2.8" }
}
```

```
frontend/
├── index.html                     入口 HTML
├── vite.config.js                 开发服务器 + /api 代理
├── package.json
└── src/
    ├── main.js                    createApp 挂载
    ├── App.vue                    ★ 根组件：全部状态与业务编排（547 行）
    ├── api/
    │   ├── chat.js                ★ SSE 流式对话 + 中断恢复（287 行）
    │   └── history.js             会话列表 / 消息 / 删除 / 改名
    ├── components/
    │   ├── Sidebar.vue            会话侧边栏（列表、搜索、新建、删除）
    │   ├── ChatArea.vue           消息流容器（自动滚动、流式光标）
    │   ├── MessageItem.vue        单条消息渲染（角色标签、工具面板、图片）
    │   ├── MarkdownRenderer.vue   Markdown + 代码高亮 + 图片内联样式
    │   ├── ToolCallPanel.vue      工具调用面板（折叠、图标、参数格式化）
    │   ├── InputArea.vue          输入框（自适应高度、发送、停止、开关）
    │   └── InterruptBanner.vue    ★ 人工介入横幅（两种中断形态，470 行）
    ├── Assets/HaiG.jpeg           背景图
    └── styles/main.css            全局样式
```

**没有引入 Vue Router、Pinia/Vuex、UI 组件库、TypeScript、ESLint。** 全部状态集中在 `App.vue` 的 `ref` 里，通过 props/emit 下发。这是一个刻意保持轻量的单页应用。

## 2. 开发与构建

```powershell
cd ERP_OPENCLAW/frontend
npm install
npm run dev        # → http://127.0.0.1:3000
npm run build      # → dist/
npm run preview    # 本地预览构建产物
```

### 2.1 Vite 配置要点

```js
server: {
  host: '127.0.0.1',    // 显式绑定 IPv4 回环
  port: 3000,
  strictPort: true,     // 端口占用直接报错，不静默切 3001
  proxy: {
    '/api': { target: 'http://localhost:8090', changeOrigin: true }
    // 无 rewrite —— 后端路由本身已带 /api 前缀
  }
}
```

`host: '127.0.0.1'` 是有意为之：Vite 默认只监听 `localhost`，在 Windows 上常被解析为 IPv6 的 `::1`，导致按 IPv4 探测（`http://127.0.0.1:3000`）的工具/脚本误判为"未启动"。绑定 IPv4 后两种写法都可用。若需局域网访问，改成 `'0.0.0.0'`。

`strictPort: true` 保证端口被占用时立刻失败——否则 Vite 会静默切到 3001，而文档与代理配置里写的都是 3000。

**前端代码统一使用相对路径 `/api/...`**，不要硬编码后端地址。

## 3. 状态管理（`App.vue`）

| 状态 | 类型 | 说明 |
|------|------|------|
| `sessions` | `ref([])` | 会话列表（挂载时 `getSessions(1, 100)` 拉取） |
| `currentThreadId` | `ref(null)` | 当前会话 ID；`null` 表示新对话，首条消息后由服务端 `done` 事件回填 |
| `messages` | `ref([])` | **混合消息列表**：user / assistant / tool 按时间顺序交错 |
| `isStreaming` | `ref(false)` | 是否正在流式输出 |
| `isResuming` | `ref(false)` | 是否正在处理中断恢复 |
| `showToolCalls` | `ref(true)` | 是否展示工具调用 |
| `interruptData` | `ref(null)` | 中断数据；`null` = 无中断，非空 = 展示 `InterruptBanner` 并隐藏输入框 |
| `abortController` | 模块级变量 | 用于取消流式请求（`let`，非 ref） |

**消息列表设计**：不是"一问一答"的两两结构，而是把 assistant 文本与工具调用交错成一条时间线：

```
[user] → [assistant 文本] → [tool 调用] → [assistant 文本] → [tool 调用] → ...
```

工具消息用 `tool_status` 字段区分 `'calling'`（进行中）与 `'done'`（已完成），前端据此渲染加载态。

## 4. SSE 消费（`api/chat.js`）

### 4.1 为什么用 fetch 而不是 EventSource

浏览器原生 `EventSource` **只支持 GET**，无法提交消息体。因此改用 `fetch` + `response.body.getReader()` 手动读取流并解析 SSE 行。

```js
const reader = response.body.getReader()
const decoder = new TextDecoder()
let buffer = ''
while (true) {
  const { done, value } = await reader.read()
  if (done) break
  buffer += decoder.decode(value, { stream: true })
  const lines = buffer.split('\n')
  buffer = lines.pop()              // 保留未完成的行
  for (const line of lines) {
    if (!line.trim() || !line.startsWith('data:')) continue
    const data = JSON.parse(line.slice(5).trim())
    switch (data.type) { /* ... */ }
  }
}
```

`decoder.decode(value, { stream: true })` 与 `buffer` 的组合处理了两类边界：多字节 UTF-8 字符被拆包、SSE 事件被拆到多个网络分片。

### 4.2 事件分发

| `data.type` | 前端动作 |
|-------------|----------|
| `token` | 累积到 `fullContent`，回调 `onToken(content, source)` |
| `tool_start` | 构造工具对象压入 `toolStack`，回调 `onToolStart` |
| `tool_args` | 追加到 `toolStack` 栈顶的 `args`，回调 `onToolArgs` |
| `tool_result` | 弹出栈顶，填充 `text`/`images`，推入 `toolCalls`，回调 `onToolResult` |
| `tool_end` | 回调 `onToolEnd` |
| `interrupt` | 回调 `onInterrupt`，**立即 return**（流在此结束） |
| `done` | 回调 `onDone`，return 结果对象 |
| `error` | 抛出 `Error(data.message)` |

### 4.3 工具调用栈（嵌套支持）

关键难点：主 Agent 调 `task` 委派子 Agent，子 Agent 内部再调工具——这是**两层嵌套的工具调用**。事件流里只能看到扁平的 `tool_start` / `tool_args` / `tool_result`，靠一个**栈**来配对：

```js
toolStack.push(newTool)        // tool_start 压栈
toolStack[toolStack.length-1].args += data.args   // tool_args 改栈顶
const finished = toolStack.pop()                  // tool_result 弹栈
```

> ⚠️ **服务端与前端各维护一份同样的栈**（`api/chat.py` 的 `tool_call_stack` 与 `api/chat.js` 的 `toolStack`），逻辑必须保持一致。修改事件协议时要同步改两处。这是当前设计的一处脆弱点。

### 4.4 中断（Human-in-the-Loop）

```js
case 'interrupt':
  callbacks.onInterrupt?.(data)
  return { thread_id: data.thread_id || threadId, content: fullContent,
           tool_calls: toolCalls, interrupted: true, interrupt_data: data }
```

收到 `interrupt` 事件时**立即返回**，不再等待 `done`——因为服务端在中断后就会结束本次流。前端据此展示 `InterruptBanner` 并隐藏输入框。

恢复用 `resumeChat(threadId, resumeData, callbacks, signal)`，走 `POST /api/chat/{threadId}/resume`，请求体 `{ resume: resumeData }`。回调集与 `streamChat` 完全相同（含 `onInterrupt`），因为**恢复后仍可能再次中断**（典型：先数据补充 → 再审批）。

### 4.5 取消

传入 `AbortController.signal`。被取消时 `error.name === 'AbortError'`，前端返回已收集的内容并带 `aborted: true`，`onDone` 里把最后一条空 assistant 消息填成「（对话已停止）」。

> ⚠️ 取消只断开**前端**连接。服务端的 SSE 生成器可能继续跑完这次 Agent 运行，模型额度照常消耗。

## 5. 人工介入 UI（`InterruptBanner.vue`）

这是前端最复杂的组件，因为它要处理两种形态完全不同的中断。

### 5.1 形态一：数据补充 `order_info_supplement`

| 项 | 内容 |
|----|------|
| 触发 | `procurement-order` 子 Agent 调 `request_order_info` → `interrupt()` |
| 展示 | 「缺少的字段」（`missing_fields`）+「已收集的数据」（`collected_data`）+ 自由文本输入框 |
| 提交 | `emit('resume', { supplement: text })` |
| 校验 | 文本非空才允许提交（`!supplementText.trim() \|\| submitting` 时禁用按钮） |

`interruptData` 用到的字段：`missing_fields`、`collected_data`。

辅助函数：`formatCollectedData(data)`、`formatFieldName(key)`、`formatFieldValue(key, val)` —— 把子 Agent 传来的键值描述格式化成可读的中文标签。

### 5.2 形态二：审批 `hitl_approval`

| 项 | 内容 |
|----|------|
| 触发 | 子 Agent YAML 的 `interrupt_on`（`order_create` / `order_update`） |
| 展示 | 遍历 `action_requests`，逐个渲染操作名称、参数、说明；配「批准」/「驳回」按钮 |
| 提交 | `emit('resume', { decisions: [{ type: 'approve' }] })` 或 `{ type: 'reject' }` |

辅助函数：`formatActionName(name)`（把 `order_create` 变成「创建订单」）、`displayArgs(args)`（格式化参数 JSON）。

### 5.3 视觉区分

根元素绑定动态 class（`bannerClass`）：`banner-supplement`（数据补充，蓝色系）与 `banner-approval`（审批，橙色系），让用户在视觉上立刻区分"要我补数据"还是"要我审批"。

### 5.4 与 `App.vue` 的联动

```vue
<InterruptBanner v-if="interruptData" :interrupt-data="interruptData"
                 :submitting="isResuming" @resume="handleResume" />
<InputArea v-if="!interruptData" ... />
```

中断期间**输入框被隐藏**——强制用户先在横幅里做出决策。`handleResume` 里 `if (isResuming.value || !currentThreadId.value) return` 防重复提交。

`onInterrupt` 回调中还做了两件收尾：把所有 `calling` 工具标记 `done`（否则会一直转圈）、过滤掉空 `content` 的 assistant 消息。

## 6. 消息渲染

### 6.1 `ChatArea.vue`

- `displayMessages` computed 过滤出需要展示的消息；
- 自动滚动到底部（`messageListRef` + `scrollToBottom`）；
- `isStreamingForMessage(msg)` 判断某条消息是否正在流式输出，用于显示光标动画。

### 6.2 `MessageItem.vue`

按 `role` 与 `source` 渲染差异化外观：

| 函数 | 作用 |
|------|------|
| `getRoleLabel(source)` | `main` → 「主助手」，`procurement-analyst` → 「采购分析专家」，`procurement-order` → 「采购订单专家」 |
| `getRoleIcon(source)` | 对应图标 |
| `getLabelBarClass(source)` / `getAvatarClass(source)` | 对应配色 |
| `formatToolName(name)` | `supplier_query` → 可读名称 |
| `getToolIcon(name)` | 按工具名选图标 |
| `formatArgs(args)` | 格式化工具参数 JSON |
| `cleanText(text)` | 清理工具结果文本 |

工具消息通过 `ToolCallPanel` 展示，分「参数」/「结果」两个可折叠区块（`expandedSections` 默认展开 `result`）。图片（`images` 数组）点击后用 `window.open` 新窗口查看。

### 6.3 `MarkdownRenderer.vue`

```
markdown-it 渲染 + highlight.js 代码高亮
```

两个额外处理：

1. **图片内联样式注入**：`IMG_INLINE_STYLE` 给所有 `<img>` 加上 `max-width:100%; max-height:360px; border-radius:12px; box-shadow; margin:14px 0`，避免 Agent 生成的大图撑破布局；
2. **图片托管域名识别**：`isKnownImageHost(url)` / `shouldRenderAsImage(src)` 判断某个 URL 是否应作为图片渲染（有些图片 URL 不以扩展名结尾，例如可视化 MCP 返回的图片链接），`buildImgTag(src, alt)` 负责生成标签。

## 7. 侧边栏与历史

`Sidebar.vue`：

| 功能 | 实现 |
|------|------|
| 会话列表 | props `sessions` |
| 搜索过滤 | `searchKeyword` + `filteredSessions` computed |
| 时间格式化 | `formatTime(timestamp)`（今天显示时分，更早显示日期） |
| 新建对话 | `emit('new-chat')` |
| 选择会话 | `emit('select-session', threadId)` |
| 删除会话 | `emit('delete-session', threadId)`，二次确认 |

`App.vue` 的对应处理：

- `handleSelectSession`：切换前 `interruptData.value = null`（清掉上一个会话的中断状态），再 `loadMessages`；
- `handleNewChat`：中止进行中的请求、重置所有状态；
- `handleDeleteSession`：调 `deleteSession` → 重新拉列表 → 若删的是当前会话则新建对话。

### 7.1 标题编辑未实现

`api/history.js` 有 `updateSessionTitle(threadId, title)`（`PATCH /api/history/{thread_id}?title=...`），但**服务端是占位实现**，固定返回 `{"success":true,"message":"标题更新功能待实现"}`。因此界面上的标题始终是自动生成的（该会话第一条用户消息的前 50 字符）。

## 8. 已知问题

| # | 问题 | 说明 |
|---|------|------|
| 1 | `AbortController` 只断前端 | 服务端 Agent 可能继续跑完，模型额度照常消耗 |
| 2 | 工具调用栈双份实现 | `chat.py` 与 `api/chat.js` 各一份，协议变更必须同步 |
| 3 | 状态全在 `App.vue` | 547 行单文件承载全部业务逻辑；`handleSend` 与 `handleResume` 的回调集几乎完全重复（约 120 行 × 2），可抽取为共享工厂函数 |
| 4 | 会话标题不可编辑 | 依赖未实现的服务端 PATCH 接口 |
| 5 | `axios` 已声明但未使用 | 实际请求全部走原生 `fetch`（因为需要读取流） |
| 6 | 无路由 | 单页应用，无 URL 状态；刷新后回到默认视图（会话需手动选择） |
| 7 | 无错误边界 | 组件抛错会影响整个应用；错误只打 `console.error` |
| 8 | 流式渲染性能 | 每个 token 都触发一次数组元素修改 + 重渲染，长回复时可能卡顿 |

---

## 第二部分：电商演示页（ecommerce-demo）

## 9. 定位与状态

一个**中文、完全静态**的摩托车配件商城 UI 样稿（`摩托配件商城`），用于展示目录页与商品详情页的视觉设计。

| 问题 | 结论 |
|------|------|
| 是否连接后端 | **完全没有**。204 个 HTML 文件中 0 处 `fetch` / `XMLHttpRequest` / `axios` / `<form>` / `<script src>`；全文搜索 `localhost:8080` 与 `/api/` 均无命中 |
| 是否有状态存储 | 无 localStorage、无 cookie、无服务端。可直接 `file://` 打开 |
| 外部网络依赖 | 仅图片与图标：2,066 处 Unsplash 图片 URL（11 张原始照片的多种尺寸）+ 205 处 bootcdn 的 Font Awesome 6.4.0 CSS |
| 项目 README 的定性 | 「仅用于展示大致前端（用于为后续前端开发提供参考），不对接任何后端业务、数据库。」（`README.md` 第 227–229 行，全文**唯一**一处提及） |
| 被后端引用 | 无。全项目搜索 `ecommerce-demo` 只有 README 与 `index.html` 页脚的一处陈旧绝对路径 |

**目录清单**：206 个文件（204 个 `.html` + 2 个 `.js`），无子目录、无图片/CSS/JS 资源文件、无 `package.json`，合计 4.74 MB。

| 页面族 | 数量 | 大小 | 生成时间戳 |
|--------|------|------|-----------|
| 生成式商品页 | 171 | 21–22 KB | 全部 `2026-05-07 16:35:16` |
| 非生成式商品页（11 个品类页 + 21 个品牌变体页） | 32 | 22–25 KB | 分散在多个时刻 |
| `index.html` | 1 | 190 KB | — |

## 10. 生成机制

### 10.1 入口与运行方式

```powershell
cd MotorcyclePartsProcurementSystem/ecommerce-demo
node generate-pages.js
```

纯 Node CommonJS，**无第三方依赖、无 `package.json`、无 CLI 参数、无 dry-run、无 watch 模式**。文件最后一行是 `generateAllPages();`，因此**加载即执行**，立即就地覆写文件。

- **读取**：`./brands-data.js`（导出 `BRANDS`、`PARTS_DATA`、`CATEGORY_MAP`）+ 生成器内部三张表：`CATEGORY_INFO`（6 项）、`IMAGE_MAP`（64 项）、`FILE_EXISTS_MAP`（80 项）
- **写出**：`fs.writeFileSync(path.join(__dirname, fileName), html, 'utf8')` —— 始终写入脚本所在目录，与 CWD 无关

### 10.2 文件名规则

```js
const fileName = `${partKey}-${brand.code}.html`;
```

`partKey` 是 `PARTS_DATA`/`BRANDS` 中的驼峰键（如 `brakeCaliper`、`licensePlateLight`），`brand.code` 是小写 ASCII slug（如 `brembo`、`cibie`）。示例：`brakeCaliper-brembo.html`、`driveBelt-gates.html`。

**生成器只产出"零件 × 品牌"的商品页，不存在单独的"品类页"生成规则。**

### 10.3 跳过规则（`FILE_EXISTS_MAP`）

对每个组合以 `skipKey = partKey + '_' + brand.code` 检查：

1. `FILE_EXISTS_MAP[skipKey]` 是字符串 → 该组合已有手工页面（如 `'sparkPlug_bosch' → 'spark-plug-bosch.html'`），跳过；
2. 否则若 `FILE_EXISTS_MAP[partKey]` 是对象 `{base, brands}`（仅两项：`sparkPlug → spark-plug.html [ngk]`、`chain → chain.html [did, gates, rk]`）→ 当 `base` 去掉 `.html` 等于 `partKey`，或 `brands` 包含该品牌时跳过。因此 `chain` 的**三个品牌全部跳过**（包括没有手工页的 RK），`sparkPlug` 只跳过 NGK；
3. 否则写出文件。

**数量核对**：64 个零件 × 3 个品牌 = 192 个组合，跳过 21 个，**写出 171 个**。经程序化校验，171 个文件的 `<title>` 与 `<h1>` 全部与模板输出一致。

### 10.4 覆盖范围

| 项 | 数量 |
|----|------|
| 品类 | 6（发动机类 12 个零件类型、车架类 10、电气类 12、制动类 10、传动类 10、外观件 10） |
| 零件类型 | 64 |
| 不同品牌编码 | 108（112 个不同显示名，因有 4 个编码被复用于不同名称） |
| 零件×品牌组合 | 192 |
| 生成页 / 手工页 | 171 / 32（+ `index.html`） |

### 10.5 输出**不是**逐字节可复现的

`Math.random()` 驱动 **库存量**（50–549）、**月销量**（500–2499）、**店铺评分**（4.7–4.9）以及每个「猜你喜欢」的价格。因此**每次运行都会改变这些数字**，只有价格、标题、规格与文案是确定的。

## 11. 数据模型（`brands-data.js`）

454 行，导出 `{ BRANDS, PARTS_DATA, CATEGORY_MAP }`。

### 11.1 `BRANDS`

按 64 个零件键组织，每个键对应**恰好 3 个**品牌对象（共 192 条）：

```js
pistonRing: [
  { name: 'GUGGI古奇', code: 'guggi', color: '#8B4513', origin: '意大利', price: 280, retailPrice: 380 },
  { name: 'NHK',        code: 'nhk',   color: '#FF6600', origin: '日本',   price: 320, retailPrice: 450 },
  { name: 'RING',       code: 'ring',  color: '#4169E1', origin: '美国',   price: 260, retailPrice: 360 }
]
```

| 键 | 类型 | 用途 |
|----|------|------|
| `name` | string | 显示名，用于标题、`<h1>`、徽标、店铺名、详情文案 |
| `code` | string | 小写 ASCII slug，用于输出文件名 |
| `color` | `'#RRGGBB'` | 注入页面 CSS 两处（`.product-badge` 背景、`.shop-name i` 颜色） |
| `origin` | string | 中文国家/地区（意大利/日本/台湾…） |
| `price` | integer | 现价（人民币元，实测区间 15–4580） |
| `retailPrice` | integer | 划线原价，恒大于 `price` |

### 11.2 `PARTS_DATA`

同样的 64 个键 → `{ code, name, model, spec, unit }`：

```js
sparkPlug:   { code: 'EC4003', name: '火花塞',   model: 'NGK',    spec: 'C7HSA', unit: '个' },
clutchPlate: { code: 'PC2010', name: '离合器片', model: 'CB400',  spec: '400cc', unit: '套' }
```

`code` 前缀与品类对应：`PC2xxx` 发动机类、`FC3xxx` 车架类、`EC4xxx` 电气类、`BC5xxx` 制动类、`TC6xxx` 传动类、`AC7xxx` 外观件 —— **与 `DatabaseInitializer.java` 的 `PARTS_DATA` 编号方案一致**（这是两者唯一的关联）。

### 11.3 `CATEGORY_MAP`

64 项，零件键 → 6 个中文品类标签之一。

### 11.4 数据文件中**没有**的东西

图片路径、库存、销量、评分、折扣、SKU、型号变体、详情文案。这些全部硬编码或随机化在 `generate-pages.js` 内部（`IMAGE_MAP` 就在生成器里，不在数据文件里）。

## 12. 页面模板

生成页由 `generatePage()`（第 206–521 行）产出。区块顺序：

| # | 区块 | 内容 |
|---|------|------|
| 1 | `<head>` | charset、viewport、`<title>【{brand.name}】摩托车{partData.name} {partData.model} {brand.origin}</title>`、Font Awesome CDN、约 90 条规则的内联 `<style>`（品牌色被插值进去）。**无 meta description、无 favicon** |
| 2 | 顶栏 | `position: sticky`，只有 Logo「摩托配件商城」。**无导航菜单、无站内搜索、无购物车、无登录** |
| 3 | 面包屑 | `首页 → index.html`（可用）；`摩托车配件` 与品类栏是 `href="#"` 死链 |
| 4 | 商品主区 | 两栏网格 `450px 1fr`：左侧 450×450 主图 + 4 个缩略图 + 品牌徽标；右侧 `<h1>`、副标题、服务/配送/销量（配送文案固定「预计2-4个工作日送达 \| 运费：免运费」）、价格区（现价 + 划线原价 + 折扣徽标，折扣为 `Math.round(Math.round(price/retailPrice*10)/10*10) + '折'`）、**6 行**规格表、可选的「选择型号」块（仅 7 个零件键有）、「购买数量」块（单/两/五件，后两档 −5% / −12%）、数量步进器（1–99，显示随机库存）、立即购买/加入购物车、4 项服务承诺 |
| 5 | 店铺区 | `{brand.name}配件专营店` + 随机商品评分（4.7–4.9）/ 服务态度 4.9 / 发货速度 4.8 |
| 6 | 详情区 | 4 个 `.detail-tab`（商品详情/规格参数/适用车型/安装指南，**纯装饰，无点击处理**）+ 生成的文案：产品介绍、产品特点（7 个零件键为专属，其余 4 条通用）、参数表、适用车型（**所有 171 页共用同一份硬编码的 Honda/Yamaha/Suzuki/Kawasaki/CFMOTO 列表**）、安装注意事项（4 条固定） |
| 7 | 猜你喜欢 | 5 张卡片：`index.html` + 该品类 `relatedFiles` 的前 4 个，价格随机 |
| 8 | 悬浮客服按钮 | 右下角圆形，纯装饰 |
| 9 | 页脚 | 4 个 `href="#"` 链接 + `Copyright © 2024 摩托配件商城` |
| 10 | 内联 `<script>` | 缩略图切换（把 `src` 里的 `w=200` 改成 `w=800`）、`.select-option` 选中态切换、数量 −/+ |

**注入方式**：全部是生成期的字符串插值（一个大 template literal），**没有运行期模板、JSON 或存储**。

### 12.1 响应式

171 个生成页与 `index.html` 各含**一个** `@media (max-width: 768px)` 块（商品网格变单列、图片高 300px、推荐区两列）。**32 个非生成页没有任何媒体查询，因此不适配移动端。**

### 12.2 真正可交互的部分

缩略图切换、型号/数量选项选择、数量步进器；`index.html` 另有 6 品类筛选（切换 `.category-section[data-category]` 的 `display`）与实时搜索。

**以下全部是装饰性的**（无事件处理）：立即购买、加入购物车、客服悬浮按钮、详情页签、所有页脚链接、面包屑中间两栏。

## 13. 三类页面的区别

| | 品类/零件页（11 个） | 生成式品牌页（171 个） | 非生成式品牌变体页（21 个） |
|---|---|---|---|
| 示例 | `tire.html`、`spark-plug.html`、`chain.html` | `brakeCaliper-brembo.html` | `spark-plug-denso.html`、`chain-gates.html` |
| 文件名 | 纯英文零件名词 | `{partKey}-{brand.code}.html` | 手工命名，带品牌后缀 |
| 面包屑 | `href="#"` + 中文品类名 | `首页 → index.html` 可用 | `href="#"` + 中文品类名 |
| 店铺名 | 品类级（「电气配件专营店」） | `{brand.name}配件专营店` | 品牌级 |
| 规格表 | 8 行手写 | 6 行（来自 `specsMap`） | 8 行手写、品牌专属 |
| 配送文案 | 各不相同（2-3 / 3-5 工作日，免运费/到付） | 固定 | 各不相同 |
| 详情文案 | 丰富、产品专属（对比表、热值指南…） | 模板生成 | 丰富、品牌专属（含品牌对比表） |
| 缩略图 | 4 张不同照片 | 4 张同一照片 | 4 张不同照片 |
| `@media` | 无 | 有 | 无 |

那 32 个非生成页的标记结构与内联脚本与生成器同源（三个 JS 处理器与 CSS 几乎一致），但标题/`<h1>` 不符合生成器模板；其中 4 个（`chain-gates.html`、`carburetor-mikuni.html`、`fairing-csun.html`、`headlight-showa.html`）文件名恰好符合命名规则，却是被 `FILE_EXISTS_MAP` 显式跳过的。**这 32 个页面由谁编写、是否由更早版本的生成器产出，无法从现有文件判定。**

## 14. 资源与依赖

| 类型 | 来源 | 数量 |
|------|------|------|
| 图片 | `https://images.unsplash.com/...` | 2,066 处引用，源自 **11 张**不同照片的 `w=800`/`w=300`/`w=200` 尺寸变体。**无本地图片文件** |
| 图标库 | `https://cdn.bootcdn.net/ajax/libs/font-awesome/6.4.0/css/all.min.css` | 205 处（204 个页面 + 生成器模板）—— 唯一的外部库 |
| 页面 CSS | 每页内联 `<style>` | 归一化后 4 种变体 |
| 脚本 | 全部内联 | **0 处 `<script src>`** |

**网络依赖**：仅美术资源（Unsplash 图片 + bootcdn 图标字体）。布局、文字与交互在 `file://` 下完全可用，无需服务器、无需构建。

## 15. 与 Spring Boot 后端的实际关系

**没有任何连接。** 具体证据：

- 204 个页面中无 API 调用、无表单提交、无 JSON 请求，也无 `localhost:8080` 或 `/api/`；
- 后端的 `src/main/resources` 里只有 `application.yml`——没有 `static/`、没有 `templates/`、没有 `addResourceHandlers`、没有返回视图的控制器；
- 唯一的后端"前端相关"配置是 `WebMvcConfig` 的全局 CORS（`addMapping("/**")` + `allowedOriginPatterns("*")` + 全方法 + `allowCredentials(true)`），它让未来的前端**能够**调用 API，但演示页自身并未调用；
- 演示目录位于 `pom.xml` 同级（在 `src/main/resources` 之外），因此 `packaging=jar` **不会**把它打包或提供服务；
- 该目录**未**列入 `.gitignore`。

唯一的关联是**名义上的数据血缘**：`brands-data.js` 与 `index.html` 声明零件清单源自 `DatabaseInitializer.java` 的 `PARTS_DATA`，零件编码沿用同一套前缀方案。但品牌、价格、图片与文案只存在于演示页自己的文件里。

## 16. 使用须知与已知瑕疵

### 16.1 修改时的注意事项

1. **不要手工编辑那 171 个生成页。** `generate-pages.js` + `brands-data.js` 是唯一真源；`node generate-pages.js` 会**就地覆写全部 171 个文件**，无 dry-run、无备份、无构建流程。
2. **那 32 个非生成页在生成器之外**，必须直接编辑。其中 2 个作为 `base` 条目、21 个作为 `FILE_EXISTS_MAP` 的 target 条目——**删除或重命名它们会导致下次运行生成重复页面**。
3. **输出不可复现**：库存、月销、店铺评分、推荐价来自 `Math.random()`，每次运行都产生不同 diff。
4. **文件名不足以判断来源**：`chain-gates.html`、`carburetor-mikuni.html`、`fairing-csun.html`、`headlight-showa.html` 符合命名规则但不是生成器产物（标题不同）。判断依据是 `FILE_EXISTS_MAP`。

### 16.2 内容漂移（实测）

- `FILE_EXISTS_MAP` 的 **80 个键中有 60 个是死键**（引用的零件键或组合在 `PARTS_DATA × BRANDS` 中不存在，如 `*_tucano`、`tire_*`、`battery_yuasa`、`meter_kenda`、`clutchPlate_jianda`、`brakeShoe_nissan` 等）。实际只跳过 21 个组合。
- `index.html` 手工复制了一份数据，与 `brands-data.js` **在 68 张卡片中有 14 张不一致**：
  - 多出 `battery`、`brakeDisc`、`brakePad`（把前/后刹车片合并为一张 6 行卡）、`frame`、`tire`、`exhaust` —— 这些在 `PARTS_DATA` 中没有对应项；
  - 品牌名不一致：`WONDERTE` vs `WONDERTECH`、`DENSO电装` vs `DENSO`、`GATES盖茨` vs `GATES`、`CSUN旭升` vs `CSUN`；
  - `brakeShoe` 多一行 `NISSAN日清纺`；
  - `cylinderBlock`、`clutchPlate`、`frontShock`、`fairing` 各多一行，`frontFender`/`rearFender` 各少一行；
  - 68 张卡中有 8 张的「N品牌」徽标与自己实际的行数不符。

### 16.3 断链与硬编码

- 1,364 处 `href="*.html"` 中 **4 处断链**：`chain-rk.html`（`index.html` 链接它，但 `chain` 的 base 规则跳过了全部三个品牌，从未生成）、`carburetor.html` 与 `oil-pump.html`（分别被 `oil-pump-champion.html`、`piston-ring-guggi.html` 链接）。
- `index.html` 的宣传数字与实际不符：广告语「40+配件种类，200+品牌选择」，统计面板「6 品类 / 52 配件种类 / 40+ 精选品牌 / 200+ 品牌变体」；实际是 6 个品类、**68** 张卡片、**207** 行品牌。
- `index.html` 页脚含一处**来自另一台机器的绝对路径**（`d:\idea_space\MotorcyclePartsProcurementSystem\ecommerce-demo\`），不要当作本仓库路径。
- 所有页面带 `Copyright © 2024`。
- 图片 URL 在属性中使用裸 `&q=80`（未转义为 `&amp;`），属轻微 HTML 合法性问题。

---

## 相关文档

- [ARCHITECTURE.md](ARCHITECTURE.md) — 聊天界面在整体架构中的位置
- [API_REFERENCE.md](API_REFERENCE.md) — SSE 事件协议与 FastAPI 端点
- [AI_AGENT.md](AI_AGENT.md) — 中断机制的服务端实现
- [SETUP_AND_DEPLOYMENT.md](SETUP_AND_DEPLOYMENT.md) — 前端启动步骤与代理配置
