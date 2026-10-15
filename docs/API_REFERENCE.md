# API 参考

本文汇总三类接口契约：

1. **ERP 后端 REST API**（Java，`http://localhost:8080`）— 54 个端点
2. **AI 助手后端 API**（FastAPI，`http://localhost:8090`）— 对话流、中断恢复、会话历史
3. **MCP 工具**（FastMCP，`http://127.0.0.1:8000/mcp`）— 8 个 ERP 工具 + 远程可视化工具

> 逐端点的完整请求/响应示例（含全部字段与错误分支）见既有的 [API_DOCUMENTATION.md](../MotorcyclePartsProcurementSystem/docs/API_DOCUMENTATION.md)（63 KB）。本文提供**速查表**、**契约要点**，以及既有文档未覆盖的 **MCP 与 SSE 协议**，并对既有文档中若干与代码不符之处做了更正（见 §1.4、§1.7、§5.3）。

---

## 第一部分：通用约定

### 1.1 统一响应信封 `Result<T>`

所有 ERP 端点（除 HTTP 层错误外）都返回 HTTP 200，业务状态由响应体 `code` 表达。

```json
{
  "code": 200,
  "message": "操作成功",
  "data": { },
  "timestamp": 1748000000000
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | Integer | 业务状态码，见 1.3 |
| `message` | String | 提示信息 |
| `data` | T | 业务数据，可能为 `null` |
| `timestamp` | Long | 服务端毫秒时间戳 |

`Result` 的静态工厂（`com.motorparts.common.Result`）：`success()`、`success(T)`、`error()`、`error(ResultCode)`、`error(String)`、`error(ResultCode, String)`、`error(Integer, String)`、`paramError()`、`paramError(String)`、`unauthorized()`、`forbidden()`、`notFound()`、`serverError()`。

### 1.2 分页信封 `PageResult<T>`

```json
{
  "code": 200,
  "message": "操作成功",
  "data": {
    "current": 1,
    "size": 10,
    "total": 120,
    "pages": 12,
    "records": [ ]
  },
  "timestamp": 1748000000000
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `current` | Long | 当前页码，从 1 开始 |
| `size` | Long | 每页条数 |
| `total` | Long | 总记录数 |
| `pages` | Long | 总页数 |
| `records` | List\<T\> | 当前页数据 |

**所有分页端点的参数约定一致**：`current`（默认 `1`）、`size`（默认 `10`），均为 `@RequestParam` 且带默认值，可省略。

> 注意：`PageResult.from(IPage)` 依赖 MyBatis-Plus 分页插件完成物理分页。当前 `application.yml` 排除了 `MybatisPlusAutoConfiguration`，插件是否生效需实测；若 `total` 等于全表行数而 `records` 只有 `size` 条，说明分页是在内存中截断的（见 [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) 技术债）。

### 1.3 业务状态码 `ResultCode`

| code | 枚举 | 消息 | 典型触发 |
|------|------|------|----------|
| 200 | `SUCCESS` | 操作成功 | 正常返回 |
| 400 | `PARAM_ERROR` | 参数错误 | 参数校验失败 |
| 401 | `UNAUTHORIZED` | 未授权 | 预留，当前无鉴权 |
| 403 | `FORBIDDEN` | 禁止访问 | 预留 |
| 404 | `NOT_FOUND` | 资源不存在 | 预留 |
| 500 | `ERROR` / `SERVER_ERROR` | 操作失败 / 服务器内部错误 | 服务层返回 false、未捕获异常 |
| 600 | `BUSINESS_ERROR` | 业务异常 | `BusinessException` |
| 601 | `DATA_EXISTS` | 数据已存在 | 订单编号重复、零件编码重复 |
| 602 | `DATA_NOT_EXISTS` | 数据不存在 | 按 ID 查不到记录 |
| 603 | `INSUFFICIENT_INVENTORY` | 库存不足 | 出库量 > 当前库存 |
| 604 | `ORDER_STATUS_ERROR` | 订单状态异常 | 预留（当前状态更新路径未校验） |
| 605 | `SUPPLIER_STATUS_ERROR` | 供应商状态异常 | 预留 |

### 1.4 时间与日期格式

> **重要更正**：既有的 `API_DOCUMENTATION.md` 示例把 `createTime` 写成 `"2026-05-06T10:00:00.000"`（ISO 带毫秒）。**实际不是这个格式。** `BaseEntity` 上的 `@JsonFormat(pattern = "yyyy-MM-dd'T'HH:mm:ss.SSS")` 会被 `@JsonSerialize(using = CustomLocalDateTimeSerializer.class)` 覆盖，而该序列化器硬编码输出 `yyyy-MM-dd HH:mm:ss`（空格分隔、**无毫秒**）。以下表格描述的是实际行为。

**输出格式（服务端 → 客户端）**

| 字段 | 格式 | 示例 |
|------|------|------|
| 所有 `LocalDateTime` 实体字段（`createTime`、`updateTime`、`orderTime`、`lastInboundTime`、`shipTime` 等） | `yyyy-MM-dd HH:mm:ss` | `2026-05-23 14:30:00` |
| `LocalDate` 字段（`expectedDeliveryDate`、`actualDeliveryDate`） | `yyyy-MM-dd` | `2026-06-15` |

**输入格式（客户端 → 服务端）**

| 场景 | 可接受格式 |
|------|-----------|
| JSON 请求体中的 `LocalDateTime`（经 `CustomLocalDateTimeDeserializer`） | 宽容解析，见下 |
| JSON 请求体中的 `LocalDate` | `yyyy-MM-dd` |
| 查询参数中的 `LocalDateTime`（`logistics/update-shipping`、`logistics/update-receiving`，经 `@DateTimeFormat`） | **仅** `yyyy-MM-dd HH:mm:ss`（空格，不是 `T`） |
| 查询参数中的 `LocalDate`（`orders/page`、`statistics` 等） | `yyyy-MM-dd` |
| `search-details` 的 `startDate`/`endDate`（字符串，手工解析） | `yyyy-MM-dd`（10 字符时补 `00:00:00`/`23:59:59`）或 `yyyy-MM-dd HH:mm:ss` |

`CustomLocalDateTimeDeserializer` 的处理流程：trim → 去掉结尾 `Z`/`z` → 把 `T`/`t` 替换为空格 → 在空格之后砍掉 `+`/`-` 时区偏移 → 依次尝试 `yyyy-MM-dd HH:mm:ss.SSS`、`yyyy-MM-dd HH:mm:ss`、`yyyy-MM-dd HH:mm`、`yyyy-MM-dd`。

实测**可接受**：`2026-05-06 10:00:00`、`2026-05-06 10:00:00.000`、`2026-05-06T10:00:00`、`2026-05-06T10:00:00.000`、`2026-05-06 10:00`、`2026-05-06T10:00:00Z`、`2026-05-06T10:00:00+08:00`、`2026-05-06 10:00:00+0800`、`2026-05-06T10:00:00.000+08:00[Asia/Shanghai]`；空串与 `null` → `null`。

实测**被拒绝**：`2026-05-06`（纯日期——格式列表里的 `yyyy-MM-dd` 这一项**永远匹配不上**，因为 `LocalDateTime.parse` 要求时间部分；这是实现缺陷而非文档问题）、`2026-05-06 10:00:00.1`、`.123456`、`2026/05/06 10:00:00`、`20260506 100000`。失败会抛 `HttpMessageNotReadableException` → 响应体 `code=400`。

**这对 MCP 工具的影响**：`mcp_server/tools/order_tools.py` 生成 `orderTime` 时用的是 `yyyy-MM-ddTHH:mm:ss.SSS`。这个格式**能被接受**（宽容解析），所以工具工作正常；但若要与服务端输出保持字节一致，应改用 `yyyy-MM-dd HH:mm:ss`。

> `spring.jackson.time-zone: UTC` 对 `LocalDateTime` **没有影响**（无时区类型），它只影响 zoned/instant 类型——而项目中没有任何此类字段。

### 1.5 认证与授权

**没有。** 全项目不存在：Spring Security 依赖、登录/登出端点、`UserController`、拦截器、Token 处理、`@PreAuthorize`。`WebMvcConfig` 只注册了全局 CORS（`addMapping("/**")` + `allowedOriginPatterns("*")` + 全部方法 + `allowCredentials(true)` + `maxAge(3600)`），没有任何拦截器。

后果：**所有 54 个端点匿名可读写**，包括创建订单、修改库存、改供应商信用评级。`Result.unauthorized()` / `forbidden()` / `notFound()` 三个工厂方法与 `ResultCode` 的 401/403/404 从未被任何代码路径触发。

`UserService` / `UserServiceImpl` / `UserMapper` 已完整实现（分页查询用户、按用户名查、创建用户、改状态、用户名查重），但**没有被任何控制器注入**——即用户管理能力目前无法通过 HTTP 访问。另外 `User.password` 没有 `@JsonIgnore`，一旦将来有接口返回 `User`，密码哈希会直接泄漏。

### 1.6 枚举取值

| 枚举 | 取值 |
|------|------|
| 订单状态 | `1` 待审核 · `2` 已审核 · `3` 采购中 · `4` 已入库 · `5` 已取消 |
| 供应商状态 | `1` 合作中 · `2` 已终止 · `3` 审核中 |
| 供应商信用评级 | `A` 优秀 · `B` 良好（默认） · `C` 一般 · `D` 较差 |
| 客户类型 | `1` 经销商 · `2` 零售店 · `3` 个人用户 |
| 客户折扣等级 | `1` 无折扣 · `2` 银牌 · `3` 金牌 · `4` 钻石 |
| 物流状态 | `1` 待发货 · `2` 运输中 · `3` 已签收 · `4` 异常 |
| 用户角色 | `admin` 管理员 · `purchase` 采购员 · `warehouse` 仓管员 · `sales` 销售员 |
| 零部件分类 | `发动机类` · `车架类` · `电气类` · `制动类` · `传动类` · `外观件` |
| 通用删除标志 | `0` 未删除 · `1` 已删除 |
| 用户状态 | `1` 正常 · `2` 禁用 |

---

## 第二部分：ERP REST API 速查表

Base URL：`http://localhost:8080`，全部路径以 `/api` 开头。共 **54 个端点**（7 个控制器）。

### 2.1 供应商 `/api/suppliers`

| 方法 | 路径 | 说明 | 主要参数 |
|------|------|------|----------|
| POST | `/create` | 创建供应商 | Body: `Supplier` |
| PUT | `/update/{id}` | 更新供应商 | Path: `id`；Body: `Supplier` |
| DELETE | `/delete/{id}` | 逻辑删除 | Path: `id` |
| GET | `/get/{id}` | 查单个 | Path: `id` |
| GET | `/page` | 分页查询 | `current=1` `size=10` `name?` `status?` `creditRating?` |
| GET | `/search` | 按名称模糊搜索 | `name`（**必填**） |
| PATCH | `/update-status/{id}` | 改合作状态 | Path: `id`；`status`（必填） |
| PATCH | `/update-credit-rating/{id}` | 改信用评级 | Path: `id`；`creditRating`（必填） |

### 2.2 零部件 `/api/parts`

| 方法 | 路径 | 说明 | 主要参数 |
|------|------|------|----------|
| POST | `/create` | 创建零部件 | Body: `Part`；`partCode` 重复则返回 601 |
| PUT | `/update/{id}` | 更新零部件 | Path: `id`；Body: `Part` |
| DELETE | `/delete/{id}` | 逻辑删除 | Path: `id` |
| GET | `/get/{id}` | 查单个 | Path: `id` |
| GET | `/page` | 分页查询 | `current=1` `size=10` `name?` `category?` `supplierId?` |
| GET | `/search` | 按名称搜索 | `name`（**必填**） |
| PATCH | `/update-price/{id}` | 改采购单价 | Path: `id`；`purchasePrice`（BigDecimal，必填） |
| GET | `/supplier/{supplierId}` | 查某供应商的零部件 | Path: `supplierId` |

### 2.3 采购订单 `/api/orders`

| 方法 | 路径 | 说明 | 主要参数 |
|------|------|------|----------|
| POST | `/create` | 创建订单（含明细） | Body: `PurchaseOrderWithDetails`；编号重复返回 601 |
| PUT | `/update/{id}` | 更新订单（**整体替换**，见 2.3.1） | Path: `id`；Body: `PurchaseOrderWithDetails` |
| DELETE | `/delete/{id}` | 逻辑删除 | Path: `id` |
| GET | `/get/{id}` | 查订单 + 明细 + 零部件详情 | Path: `id` |
| GET | `/details/{id}` | 查订单 + 纯明细（分离结构） | Path: `id` |
| GET | `/page` | 分页查询（含明细与零部件） | `current=1` `size=10` `orderNumber?` `status?` `startDate?` `endDate?`（后者 `yyyy-MM-dd`） |
| PATCH | `/update-status/{id}` | 改状态 | Path: `id`；`status`（必填）；`status=4` 时自动写 `actualDeliveryDate` |
| GET | `/statistics` | 采购统计 | `startDate?` `endDate?`（`yyyy-MM-dd`） |
| GET | `/search-details` | 按零部件名 + 时间搜明细（含供应商） | `partName?` `startDate?` `endDate?` |

#### 2.3.1 `PUT /orders/update/{id}` 的替换语义

服务实现是**先物理删除订单与其明细，再重新插入**：

```java
orderDetailMapper.physicalDeleteByOrderId(orderId);  // DELETE FROM order_detail WHERE order_id=?
baseMapper.physicalDeleteById(orderId);              // DELETE FROM purchase_order WHERE id=?
baseMapper.insert(order);                            // 重新 INSERT
```

含义：
- 未在请求体中出现的字段会被写成 `null`（`orderTime`、`status` 会被补为 `now()` / `1`）；
- `totalAmount` 一律由明细重算：`Σ(unitPrice × quantity)`，**传入值被忽略**；
- `createTime` / `updateTime` 被刷新为当前时间；
- 外键 `fk_logistics_order ON DELETE CASCADE` 会**连带删除该订单的物流记录**；
- 因此调用方必须"读出完整订单 → 合并变更 → 整体提交"。MCP 的 `order_update` 工具已封装该逻辑。

**`PurchaseOrderWithDetails` 请求体结构：**

```json
{
  "orderNumber": "PO20260523001",
  "totalAmount": 1275.00,
  "status": 1,
  "orderTime": "2026-05-23T14:30:00.000",
  "expectedDeliveryDate": "2026-06-15",
  "actualDeliveryDate": null,
  "createdBy": 2,
  "remark": "加急",
  "orderDetail": [
    { "partId": 100, "quantity": 50, "unitPrice": 25.5, "remark": "刹车片" }
  ]
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `orderNumber` | String | **是** | 唯一，重复返回 601 |
| `orderDetail` | Array | 否 | 明细列表；每项 `partId`/`quantity`/`unitPrice` 必填，`subtotal` 由数据库生成列计算，`remark` 可选 |
| `status` | Integer | 否 | 默认 `1` |
| `orderTime` | LocalDateTime | 否 | 默认当前时间 |
| `expectedDeliveryDate` | LocalDate | 否 | `yyyy-MM-dd` |
| `actualDeliveryDate` | LocalDate | 否 | `yyyy-MM-dd` |
| `createdBy` | Long | 否 | 用户 ID |
| `remark` | String | 否 | 最长 500 |
| `totalAmount` | BigDecimal | — | **写操作中被服务端覆盖**，仅查询响应有意义 |

### 2.4 库存 `/api/inventory`

| 方法 | 路径 | 说明 | 主要参数 |
|------|------|------|----------|
| GET | `/get/{id}` | 查库存（含零部件） | Path: `id` |
| GET | `/page` | 分页查询 | `current=1` `size=10` `partName?` `warehouseLocation?` |
| POST | `/inbound` | 入库 | `partId`（必填） `quantity`（必填） `warehouseLocation?` |
| POST | `/outbound` | 出库 | `partId`（必填） `quantity`（必填）；不足返回 603 |
| GET | `/warning` | 库存预警列表 | 无参；条件 `currentQuantity <= safetyStock` |
| PATCH | `/update-safety-stock/{id}` | 改安全库存 | Path: `id`（**库存记录 ID**）；`safetyStock`（必填） |
| GET | `/check` | 库存盘点汇总 | 无参 |

`GET /inventory/check` 响应 `data`：

```json
{ "totalItems": 60, "warningItems": 7, "normalItems": 53, "inventoryList": [ /* InventoryWithPart[] */ ] }
```

> `update-safety-stock/{id}` 的 `id` 是库存记录 ID，服务内部会先查出 `partId` 再按 `partId` 更新。

### 2.5 客户 `/api/customers`

| 方法 | 路径 | 说明 | 主要参数 |
|------|------|------|----------|
| POST | `/create` | 创建客户 | Body: `Customer` |
| PUT | `/update/{id}` | 更新客户 | Path: `id`；Body: `Customer` |
| DELETE | `/delete/{id}` | 逻辑删除 | Path: `id` |
| GET | `/get/{id}` | 查单个 | Path: `id` |
| GET | `/page` | 分页查询 | `current=1` `size=10` `name?` `customerType?` `discountLevel?` |
| GET | `/search` | 按名称搜索 | `name`（**必填**） |
| PATCH | `/update-type/{id}` | 改客户类型 | Path: `id`；`customerType`（必填） |
| PATCH | `/update-discount/{id}` | 改折扣等级 | Path: `id`；`discountLevel`（必填） |

### 2.6 物流 `/api/logistics`

| 方法 | 路径 | 说明 | 主要参数 |
|------|------|------|----------|
| POST | `/create` | 创建物流记录 | Body: `Logistics` |
| PUT | `/update/{id}` | 更新物流 | Path: `id`；Body: `Logistics` |
| DELETE | `/delete/{id}` | 逻辑删除 | Path: `id` |
| GET | `/get/{id}` | 查单个 | Path: `id` |
| GET | `/page` | 分页查询 | `current=1` `size=10` `orderId?` `trackingNumber?` `status?` |
| GET | `/order/{orderId}` | 按订单查物流 | Path: `orderId` |
| PATCH | `/update-status/{id}` | 改物流状态 | Path: `id`；`status`（必填） |
| PATCH | `/update-shipping/{id}` | 登记发货信息 | Path: `id`；`shipTime`（`yyyy-MM-dd HH:mm:ss`，必填） `trackingNumber`（必填） `logisticsCompany?` |
| PATCH | `/update-receiving/{id}` | 登记收货信息 | Path: `id`；`actualArrivalTime`（`yyyy-MM-dd HH:mm:ss`，必填） `receiver`（必填） |

### 2.7 统计 `/api/statistics`

| 方法 | 路径 | 说明 | 参数 |
|------|------|------|------|
| GET | `/dashboard` | 仪表盘汇总 | 无 |
| GET | `/suppliers` | 供应商分布 | 无 |
| GET | `/parts` | 零部件分类与价格区间分布 | 无 |
| GET | `/inventory` | 库存状态分布 | 无 |
| GET | `/monthly-trend` | 月度采购趋势 | `startDateParam?` `endDateParam?`（`yyyy-MM-dd`，默认最近 6 个月） |

各端点 `data` 结构：

```jsonc
// GET /statistics/dashboard
{
  "supplierCount": 30, "partCount": 60, "customerCount": 40,
  "userCount": 12, "inventoryCount": 60,
  "monthPurchase": { "orderCount": 5, "totalAmount": 123456, "completedCount": 2 }
}

// GET /statistics/suppliers
{ "byStatus": { "1": 20, "2": 6, "3": 4 },
  "byCreditRating": { "A": 8, "B": 14, "C": 6, "D": 2 },
  "total": 30 }

// GET /statistics/parts
{ "byCategory": { "发动机类": 12, "车架类": 10, "电气类": 12, "制动类": 10, "传动类": 10, "外观件": 6 },
  "priceRanges": { "0-100": 25, "100-500": 22, "500-1000": 8, "1000+": 5 },
  "total": 60 }

// GET /statistics/inventory
{ "statusDistribution": { "warning": 7, "normal": 53 }, "zeroStockCount": 3, "total": 60 }

// GET /statistics/monthly-trend   → data 是数组
[ { "month": "2026-01", "orderCount": 12, "totalAmount": 45678 }, ... ]
```

> `monthly-trend` 的时间参数名是 `startDateParam` / `endDateParam`，与其他端点的 `startDate` / `endDate` **不同名**，调用时注意。
> 采购统计（`GET /orders/statistics` 与 `dashboard.monthPurchase`）中 `totalAmount` 经 `.longValue()` 截断为整数元。

### 2.8 辅助端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/swagger-ui/index.html` | Swagger UI（springdoc 2.0.2 路径；旧文档写的 `/swagger-ui.html` 已不适用） |
| GET | `/v3/api-docs` | OpenAPI 3 JSON |

Swagger 元信息：标题「摩托车零部件采购管理系统 API」，版本 `1.0.0`。

---

## 第三部分：AI 助手后端 API（FastAPI）

Base URL：`http://localhost:8090`。对话与历史路由统一挂载在 `/api` 前缀下（`web_main.py` 中 `include_router(..., prefix="/api")`）。

### 3.1 端点总览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 服务信息（名称、版本、docs 路径） |
| GET | `/health` | 健康检查，返回 `{"status":"healthy", ...}` |
| GET | `/docs` | Swagger UI |
| GET | `/redoc` | ReDoc |
| POST | `/api/chat/stream` | **流式对话**（SSE） |
| POST | `/api/chat/{thread_id}/resume` | **中断恢复**（SSE） |
| GET | `/api/chat/{thread_id}` | 会话当前状态（从 checkpoint 读 messages） |
| GET | `/api/chat/{thread_id}/history` | 状态快照列表（`limit` 默认 50，范围 1–100） |
| GET | `/api/history` | 会话列表（`page` 默认 1，`limit` 默认 20，最大 100） |
| GET | `/api/history/{thread_id}/messages` | 会话完整消息历史 |
| DELETE | `/api/history/{thread_id}` | 删除会话（含 checkpoints 与展示消息） |
| PATCH | `/api/history/{thread_id}` | 更新标题 — **占位实现**，返回 `"标题更新功能待实现"` |

CORS：`allow_origins=["*"]`、`allow_credentials=True`、`allow_methods=["*"]`、`allow_headers=["*"]`（`web_main.py`）。生产环境应限定来源。

### 3.2 `POST /api/chat/stream`

**请求**

```json
{ "message": "对比博世和电装的刹车片价格", "thread_id": null }
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `message` | String | 是 | 用户消息 |
| `thread_id` | String | 否 | 省略或为 `null` 时服务端生成 UUID 并随 `done` 事件返回 |

**响应**：`Content-Type: text/event-stream`，逐行 `data: {json}\n\n`。响应头 `Cache-Control: no-cache`、`Connection: keep-alive`、`X-Accel-Buffering: no`。

> 前端必须用 `fetch` + `ReadableStream`（`EventSource` 不支持 POST）。

### 3.3 `POST /api/chat/{thread_id}/resume`

**请求**

```json
{ "resume": { "supplement": "物料ID=100，数量50，单价25.5元" } }
```

或

```json
{ "resume": { "decisions": [ { "type": "approve" } ] } }
```

`resume` 的形态由中断类型决定，见 3.5。

### 3.4 SSE 事件协议

| `type` | 附加字段 | 触发时机 | 前端处理 |
|--------|----------|----------|----------|
| `token` | `content`、`source` | LLM 输出文本增量 | 追加到最后一条 assistant 消息，或新建 |
| `tool_start` | `tool_call_id`、`tool_name`、`source` | 工具开始调用 | 插入一条 `role:"tool"`、`tool_status:"calling"` 的消息 |
| `tool_args` | `args`、`source` | 工具参数分片（可能多次） | 追加到最后一个 `calling` 工具 |
| `tool_result` | `tool_name`、`tool_call_id`、`text`、`images`、`source` | 工具执行完成 | 填充该工具的 `text`/`images`，置 `done` |
| `tool_end` | `tool_name`、`tool_call_id`、`source` | 工具结束标记 | 兜底置 `done` |
| `interrupt` | `interrupt_type` + 类型专属字段 | 检测到 Human-in-the-Loop 中断 | 展示 `InterruptBanner` |
| `done` | `thread_id`、`content`、`interrupted?` | 流结束 | 收尾、清理空消息、必要时刷新会话列表 |
| `error` | `message` | 流内异常 | 在界面展示错误 |

**`source` 字段取值**：`"main"`（主 Agent）或子 Agent 名（`"procurement-analyst"`、`"procurement-order"`）。前端据此标注消息归属。服务端通过解析 LangGraph 的 namespace（形如 `tools:xxxx`）得到子 Agent 名。

**`token` 事件的服务端过滤规则**（重要，避免界面出现"凭空多出的文字"）：以下三类消息**不会**被推送为 token——
- `ToolMessage`（已由 `tool_result` 承担）
- `SystemMessage`（中间件注入的内部上下文）
- `HumanMessage`（用户自己的消息）

### 3.5 中断事件详情

#### 3.5.1 数据补充中断 `order_info_supplement`

来源：`procurement-order` 子 Agent 调用工具 `request_order_info`，内部执行 `langgraph.types.interrupt({...})`。

```json
{
  "type": "interrupt",
  "interrupt_type": "order_info_supplement",
  "missing_fields": "partId（物料ID，必填）、quantity（数量）",
  "collected_data": "供应商=博世，物料=刹车片",
  "thread_id": "b7c1..."
}
```

**恢复请求体**：

```json
{ "resume": { "supplement": "用户输入的自由文本" } }
```

> `supplement` 是**自由文本**，不是 JSON。子 Agent 的提示词负责从中解析键值对（`物料ID=100`、`数量: 50`）、日期（`6月15日交货`）与备注。

#### 3.5.2 审批中断 `hitl_approval`

来源：子 Agent YAML 中的 `interrupt_on` 配置（`order_create` / `order_update`，`allowed_decisions: ["approve","reject"]`）。

```json
{
  "type": "interrupt",
  "interrupt_type": "hitl_approval",
  "action_requests": [ { "name": "order_create", "args": { "...": "..." }, "description": "..." } ],
  "review_configs": [ { "action_name": "order_create", "allowed_decisions": ["approve","reject"] } ],
  "thread_id": "b7c1..."
}
```

**恢复请求体**：

```json
{ "resume": { "decisions": [ { "type": "approve" } ] } }
```

`type` 取值 `approve` 或 `reject`。

#### 3.5.3 未知中断

`interrupt_type: "unknown"`，附 `interrupt_value`（截断至 2000 字符）。前端应展示原始内容供人工判断。

#### 3.5.4 中断后的流行为

检测到中断时服务端会：
1. 兜底把所有 `calling` 状态工具标记为 `done`；
2. 清理空的 assistant 消息；
3. **保存当前部分展示消息到 MongoDB**（`session_display_messages`）；
4. 发 `done` 事件并带 `"interrupted": true`；
5. **结束本次流**。前端需自行发起 `/resume`。

恢复后仍可能再次中断（典型：先数据补充 → 再审批），前端 `onInterrupt` 在恢复路径中同样注册。

### 3.6 `GET /api/history`

```json
{
  "sessions": [
    { "thread_id": "b7c1...", "title": "对比博世和电装的刹车片价格",
      "created_at": "2026-05-23T14:30:00", "updated_at": "2026-05-23T14:35:12",
      "message_count": 6 }
  ],
  "total": 12, "page": 1, "limit": 20
}
```

- `title` 取该会话第一条用户消息的前 50 字符（超出补 `...`），无则 `"新对话"`。
- `message_count` 为 `len(messages) // 2`（估算值）。
- `updated_at` 由 MongoDB `ObjectId.generation_time` 推得（checkpoint 文档的 `_id` 时间戳）。
- 会话来源：`checkpoints` 集合 `distinct("thread_id")`，过滤空值与 `"*"`。

### 3.7 `GET /api/history/{thread_id}/messages`

```json
{
  "thread_id": "b7c1...",
  "messages": [
    { "id": "user-...", "role": "user", "content": "对比博世和电装的刹车片价格", "created_at": "..." },
    { "id": "assistant-...", "role": "assistant", "content": "正在为您分析...", "source": "main" },
    { "id": "...", "role": "tool", "tool_name": "supplier_query", "args": "{\"name\":\"博世\"}",
      "text": "...", "images": [], "source": "procurement-analyst", "tool_status": "done" }
  ]
}
```

**读取优先级**：先读 `session_display_messages` 集合（含子 Agent 消息）；为空则回退到从 checkpoint 反序列化（`serialize_messages_from_checkpoint`，**不含**子 Agent 消息，仅兼容旧数据）。

`Message` 字段完整清单：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | String | 消息唯一标识 |
| `role` | String | `user` / `assistant` / `tool` |
| `content` | String | 文本内容（assistant/user 用） |
| `created_at` | datetime | 创建时间 |
| `tool_calls` | List\<Dict\> | 工具调用信息 |
| `tool_call_id` | String | 工具调用 ID |
| `source` | String | `main` 或子 Agent 名 |
| `tool_name` | String | 工具名（tool 角色） |
| `tool_status` | String | `calling` / `done` |
| `text` | String | 工具结果文本 |
| `images` | List\<String\> | 工具结果图片 URL / base64 |
| `args` | String | 工具调用参数（JSON 字符串） |

### 3.8 `DELETE /api/history/{thread_id}`

删除该 `thread_id` 在 `checkpoints` 与 `session_display_messages` 两个集合中的全部文档。

```json
{ "success": true, "message": "会话已删除" }
```

---

## 第四部分：MCP 工具

MCP 服务由 `src/mcp_server/server_main.py` 启动，transport 为 `streamable-http`，默认 `127.0.0.1:8000/mcp`。底层用 `httpx.AsyncClient`（`base_url = JAVA_API_BASE_URL`，超时 30 s，连接池 100）调用 Java REST。

### 4.1 ERP 业务工具（8 个）

| 工具名 | 底层 REST 调用 | 参数 | 返回 |
|--------|---------------|------|------|
| `supplier_query` | `GET /suppliers/search` | `name`（**必填**） | `List<Supplier>` |
| `part_query` | `GET /parts/page` | `current=1`、`size=10`、`name?`、`category?`、`supplier_id?` | `records` 数组（仅取 `data.records`） |
| `part_search` | `GET /parts/search` | `name`（**必填**） | `List<Part>` |
| `part_by_supplier` | `GET /parts/supplier/{supplier_id}` | `supplier_id`（**必填**） | `List<Part>` |
| `order_search_details` | `GET /orders/search-details` | `part_name?`、`start_date?`、`end_date?` | `List<OrderDetailWithPartAndSupplier>` |
| `order_create` | `POST /orders/create` | 见 4.2 | 新建订单对象 |
| `order_update` | `GET /orders/get/{id}` + `PUT /orders/update/{id}` | `order_id`（**必填**）+ 可选字段 | 更新后订单对象 |
| `inventory_warning` | `GET /inventory/warning` | 无 | `List<InventoryWithPart>` |

**参数命名转换**：MCP 工具参数用 snake_case（Python 风格），工具内部映射为 Java 的 camelCase（`supplier_id → supplierId`、`part_name → partName`、`start_date → startDate`）。

**返回值裁剪**：工具只返回 `result["data"]`，丢弃 `code`/`message`/`timestamp`；`code != 200` 时返回 `{"error": "API error: code=..., message=..."}`（列表型工具返回 `["API error: ..."]`）。全部异常被捕获并转成可读字符串，**不向上抛**。

### 4.2 `order_create` / `order_update` 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `order_detail` | `List[dict]` | `create` 必填 | 每项 `partId`、`quantity`、`unitPrice`，可选 `subtotal`、`remark` |
| `order_id` | `int` | 仅 `update` | 路径参数 |
| `order_number` | `str` | 否 | 不传时**自动生成**：`PO` + `yyyyMMdd` + 3 位随机数（`PO20260523001`） |
| `total_amount` | `float` | 否 | 不传则由 Java 服务端按明细重算 |
| `status` | `int` | 否 | 1–5，默认 1 |
| `order_time` | `str` | 否 | `yyyy-MM-ddTHH:mm:ss.SSS`；不传时工具补当前时间 |
| `expected_delivery_date` | `str` | 否 | `yyyy-MM-dd` |
| `actual_delivery_date` | `str` | 否 | `yyyy-MM-dd` |
| `created_by` | `int` | 否 | 用户 ID |
| `remark` | `str` | 否 | 备注 |

**`order_create` 的默认值注入**（`_prepare_request`）：自动生成 `orderNumber`、自动填 `orderTime`，并递归把 `Decimal → float`、`date/datetime → ISO 字符串`。

**`order_update` 的读-合并-写**：先 `GET /orders/get/{order_id}` 取出完整订单作为基线（含 `orderDetail`，仅保留 `partId`/`quantity`/`unitPrice`/`remark` 四个字段），再用显式传入的参数覆盖，最后 `PUT`。这是为了适配 Java 侧的"整体替换"语义（见 2.3.1）。**未显式传入 `order_number` / `order_time` 时沿用原值，不会被重新生成。**

### 4.3 可视化工具与合并

远程可视化 MCP（`ANALYSIS_MCP_URL`，默认 ModelScope 地址）提供 **27 个** `generate_*` 工具：26 个可视化工具 + 1 个 `generate_spreadsheet`。`agent/tools/chart_generator.py` 把它们中的可视化部分合并为单一入口：

```
generate_visualization(chart_type: str, chart_config: dict) -> str
```

**合并规则**：
- 名称以 `_chart` 结尾 → 去掉后缀作 `chart_type`（`generate_bar_chart` → `"bar"`）；
- 名称以 `_map` / `_diagram` / `_graph` 结尾 → 保留完整后缀作 `chart_type`（`generate_pin_map` → `"pin_map"`）；
- 其余 `generate_*` 工具（如 `generate_spreadsheet`）不合并，作为独立工具保留。

**26 种 `chart_type`**：

| 分组 | 类型 |
|------|------|
| 标准图表（19） | `area` `bar` `boxplot` `column` `dual_axes` `funnel` `histogram` `line` `liquid` `organization` `pie` `radar` `sankey` `scatter` `treemap` `venn` `violin` `waterfall` `word_cloud` |
| 地图（3） | `district_map` `path_map` `pin_map` |
| 图表/关系图（3） | `fishbone_diagram` `flow_diagram` `network_graph` |
| 思维导图（1） | `mind_map` |

**数据模式**：`category-value`（`{category, value}`）、`time-value`（`{time, value, group?}`）、分布统计（`boxplot`/`violin` 用 `{category, value}`，`histogram` 用纯数字数组，`scatter` 用 `{x, y}`）、多维度（`radar` 用 `{name, value}`、`sankey` 用 `{source, target, value}`）、层级树（`organization`/`mind_map`/`fishbone_diagram` 用 `{name, children}`）、节点边图（`flow_diagram`/`network_graph` 用 `{nodes, edges}`）、特殊（`liquid` 用必填 `percent`，不是 `data`）。

**完全参数 schema**：沙箱内 `/skills/procurement/chart_params.md`（由 `build_chart_params_md` 从 MCP 工具的 `args_schema` 自动生成），Agent 在不确定时先 `read_file` 该文件。仓库中的 [chart_params.md](../ERP_OPENCLAW/src/skills/procurement/chart_params.md) 是同一份内容。

### 4.4 非 MCP 的本地工具

| 工具 | 归属 | 说明 |
|------|------|------|
| `web_search` | 主 Agent + 两个子 Agent | 智谱 Web Search API（`search_engine="search_pro"`，`count=3`，`search_recency_filter="noLimit"`）；客户端**惰性创建**，未配 `ZHIPU_API_KEY` 时调用报可读错误 |
| `request_order_info` | `procurement-order` | 调 `interrupt()` 暂停等人工补充数据 |
| `assign_skill` | 主 Agent | 把 `/skills/main/{skill}/` 复制到 `/skills/{scope}/{skill}/` 并持久化到 StoreBackend，清理压缩包 |
| `download_sandbox_file` | 主 Agent | 把沙箱文件下载到本地 `src/download/`，`local_filename` 经 `Path(...).name` 防路径穿越 |
| `generate_visualization` | `procurement-analyst` | 26 图合并入口 |
| `task` | 主 Agent（DeepAgents 内置） | 委派子 Agent |
| `read_file` / `write_file` / `edit_file` / `ls` / `execute` / `compact_conversation` | 全部 Agent（DeepAgents 内置） | 文件系统与代码执行；`compact_conversation` 由摘要中间件提供 |

### 4.5 MCP 健康检查

MCP 无独立健康端点。快速验证：

```powershell
# 确认服务在监听
Test-NetConnection 127.0.0.1 -Port 8000
# 或直接跑仓库自带脚本
cd ERP_OPENCLAW; python src/test/test_mcp.py
```

`src/test/` 下还有 `verify_mcp_bridge.py`、`verify_mcp_write.py`、`test_all_tools.py` 等脚本，详见 [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md)。

---

## 第五部分：错误处理与排错

### 5.1 ERP 侧异常映射

**首要事实：所有异常都返回 HTTP 200。** `GlobalExceptionHandler` 的每个处理器都只返回 `Result<Void>` 响应体，从不设置 HTTP 状态——没有 `@ResponseStatus`、没有 `ResponseEntity`、没有 `setStatus`。**客户端必须读响应体的 `code`，不能依赖 HTTP 状态码判断成败。**

| 异常 | 处理结果 | `code` |
|------|----------|--------|
| `BusinessException` | `Result.error(e.getCode(), e.getMessage())` | 600（**该类从未被抛出，处理器是死代码**） |
| `MethodArgumentNotValidException`（`@Valid` 请求体校验失败） | 字段名 + `: ` + 消息，多条以 `;` 连接 | 400 |
| `BindException` | 同上格式 | 400 |
| `ConstraintViolationException` | 属性路径 + `: ` + 消息 | 400 |
| `MethodArgumentTypeMismatchException` | `参数类型不匹配: {参数名}` | 400 |
| `MissingServletRequestParameterException` | `缺少必填参数: {参数名}` | 400 |
| `HttpMessageNotReadableException`（请求体 JSON 或日期格式错） | `请求体解析失败: {最具体原因}` | 400 |
| 其他所有 `Exception` | `Result.serverError()`（日志记 error 级） | 500 |

**业务失败不抛异常**：服务层用 `boolean` 返回值表达失败，控制器翻译成 `Result.error(...)`。实际会被触发的业务码只有四个：

| code | 触发处 |
|------|--------|
| 601 `DATA_EXISTS` | 供应商创建失败、零部件编码重复、订单编号重复 |
| 602 `DATA_NOT_EXISTS` | 各模块 `get/update/delete/update-status` 查不到记录 |
| 603 `INSUFFICIENT_INVENTORY` | **仅** `POST /inventory/outbound`（且任何失败都归为库存不足，包括参数非法与库存记录不存在） |
| 500 | 服务层返回 false 但控制器未映射具体码时（如 `inventory/inbound`） |

> **`ResultCode` 中声明但永远不会出现的码**：401 `UNAUTHORIZED`、403 `FORBIDDEN`、404 `NOT_FOUND`、600 `BUSINESS_ERROR`、604 `ORDER_STATUS_ERROR`、605 `SUPPLIER_STATUS_ERROR`。文档中提到 604/605 时请注意：订单状态更新**没有任何合法性校验**，任意 1–5（乃至更大整数）都能写入。

**分页失效风险**：项目**没有注册 `MybatisPlusInterceptor` / `PaginationInnerInterceptor`**（`application.yml` 排除了 `MybatisPlusAutoConfiguration`，而手写的 `MyBatisPlusSqlSessionFactoryBean` 也没有添加该插件）。MyBatis-Plus 只在注册该拦截器时才生成 `LIMIT`，因此 6 个 `/page` 端点**很可能忽略 `size`/`current` 而返回全部匹配行**，同时 `PageResult.current`/`size` 仍回显请求值。此项未经实际请求验证，但 `logs/motorparts.log` 中从未出现 `LIMIT` 与计数子查询，与之吻合。集成时请先实测确认。

### 5.2 Agent 启动期错误

| 现象 | 原因 | 处置 |
|------|------|------|
| `无法连接 ERP MCP 桥接服务` | MCP 桥接未启动或 Java 后端未启动 | 先起 Java（8080），再起 MCP（8000） |
| `沙箱配置失败，无法创建 Agent` | WSL 发行版不存在 / OpenSandbox 不可达 | 核对 `WSL_DISTRO` 或 `OPENSANDBOX_DOMAIN` |
| `MongoDB 连接失败` | MongoDB 未启动 | 启动服务，或改 `.env` 的 `MONGODB_URI` |
| 可视化 MCP 告警但仍启动 | 远程 MCP 不可达（**预期行为**） | 图表能力降级，其余功能正常 |

### 5.3 调用侧常见坑

| 现象 | 原因 |
|------|------|
| `PUT /orders/update/{id}` 后字段变空 | 该接口是整体替换（物理删除 + 重新插入），必须带全字段（用 `order_update` 工具或先 GET 再 PUT） |
| `PUT /orders/update/{id}` 后订单 ID 变了、`createTime` 变成当前时间 | 同上实现导致：订单行被重新 INSERT，主键由 `AUTO_INCREMENT` 重新分配 |
| 更新订单后物流记录消失 | `fk_logistics_order ON DELETE CASCADE`（**仅在先执行过 `database_schema.sql` 时存在**）+ 物理删除实现 |
| 更新订单后订单仍存在但明细指向别的订单 | 明细用**请求里的旧 id** 插入，而订单行已拿到新 id；若 MySQL 未复用该 id 则两者错位 |
| `totalAmount` 传了但没生效 | 写操作中总金额一律由明细重算（`Σ unitPrice × quantity`） |
| `monthly-trend` 时间过滤无效 | 参数名是 `startDateParam`/`endDateParam`，不是 `startDate`/`endDate` |
| `update-safety-stock` 返回 602 | 路径参数要传**库存记录 `id`**，不是 `partId` |
| 物流发货时间报 400 | 需要 `yyyy-MM-dd HH:mm:ss`（空格，非 ISO 的 `T`） |
| 请求里传 `2026-05-06` 作为 `orderTime` 报 400 | 纯日期无法解析为 `LocalDateTime`；至少写到分钟（`yyyy-MM-dd HH:mm`） |
| HTTP 状态是 200 但操作没成功 | 业务失败也返回 HTTP 200，必须检查响应体 `code` |
| 分页返回的行数远超 `size` | 未注册分页插件，见 §5.1 末段 |
| 用 `totalAmount` 做金额统计对不上 | `/orders/statistics` 与 `/statistics/dashboard` 的 `totalAmount` 是 `BigDecimal.longValue()`，**已截断为整数元**（元，不是分） |

---

## 相关文档

- [API_DOCUMENTATION.md](../MotorcyclePartsProcurementSystem/docs/API_DOCUMENTATION.md) — 逐端点完整示例与字段说明
- [ARCHITECTURE.md](ARCHITECTURE.md) — 请求全链路与设计决策
- [DATABASE.md](DATABASE.md) — 字段与表结构
- [AI_AGENT.md](AI_AGENT.md) — 工具如何被 Agent 选择与使用
