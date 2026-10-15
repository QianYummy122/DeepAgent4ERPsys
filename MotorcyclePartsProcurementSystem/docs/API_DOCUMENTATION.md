# 摩托车零部件采购管理系统 API 接口文档

## 基本信息

| 项目 | 说明 |
|------|------|
| **API文档地址** | http://localhost:8080/swagger-ui/index.html （springdoc-openapi 2.0.2；旧的 `/swagger-ui.html` 已不适用） |
| **OpenAPI JSON** | http://localhost:8080/v3/api-docs |
| **基础路径** | http://localhost:8080/api |
| **响应格式** | JSON |
| **认证方式** | 当前系统未配置认证，所有接口可直接访问（也因此**不可暴露到公网**） |
| **字符编码** | UTF-8 |

> 后端没有首页路由：访问 http://localhost:8080/ 返回 404。

---

## 目录

1. [通用说明](#通用说明)
2. [采购订单管理](#1-采购订单管理)
3. [供应商管理](#2-供应商管理)
4. [产品零部件管理](#3-产品零部件管理)
5. [客户管理](#4-客户管理)
6. [物流管理](#5-物流管理)
7. [库存管理](#6-库存管理)
8. [统计分析](#7-统计分析)

---

## 通用说明

### 统一响应格式

所有API接口均遵循以下统一响应格式：

```json
{
  "code": 200,
  "message": "操作成功",
  "data": { ... },
  "timestamp": 1746508800000
}
```

**响应字段说明：**

| 字段 | 类型 | 说明 |
|------|------|------|
| code | Integer | 状态码，200表示成功 |
| message | String | 操作结果描述信息 |
| data | Object/Array | 返回的数据对象，失败时为null |
| timestamp | Long | 响应时间戳（毫秒） |

### 分页响应格式

```json
{
  "code": 200,
  "message": "操作成功",
  "data": {
    "records": [ ... ],
    "total": 100,
    "size": 10,
    "current": 1,
    "pages": 10
  },
  "timestamp": 1746508800000
}
```

**分页字段说明：**

| 字段 | 类型 | 说明 |
|------|------|------|
| records | Array | 当前页的数据列表 |
| total | Long | 总记录数 |
| size | Long | 每页记录数 |
| current | Long | 当前页码（从1开始） |
| pages | Long | 总页数 |

> ⚠️ **分页参数目前不生效**：`MyBatisPlusConfig` 只注册了 `SqlSessionFactory`、事务管理器与字段自动填充，**没有注册 MyBatis-Plus 的分页插件**（`MybatisPlusInterceptor` + `PaginationInnerInterceptor`），而 `application.yml` 又排除了 `MybatisPlusAutoConfiguration`。实际行为是：`records` **返回整张表**（没有 LIMIT/OFFSET，也不发 COUNT 查询），`size`/`current` 仅回显请求参数，`total` 与 `pages` **恒为 0**。上表中的"总记录数/总页数"与示例里的 `100`/`10` 都不是真实返回值，接入前端前请先实测确认。

### 写接口的响应回显

多个写接口**不把数据库中的最新记录读回来**，而是把反序列化后的请求对象（补上 `id` 和 `updateTime`）直接作为 `data` 返回：

| 接口 | 回显行为 |
|------|----------|
| `POST /api/orders/create` | 回显请求体；订单级字段（`totalAmount`、`status`、`orderTime`、`deleted`、`createTime`、`updateTime`）由服务层补齐后可见，但**明细数组不回填**：`orderDetail[i]` 的 `id`/`orderId`/`subtotal`/`deleted`/`createTime`/`updateTime` 均为 `null` |
| `PUT /api/orders/update/{id}` | 回显请求体；`deleted`/`createTime`/`updateTime` 会被重新赋值，因此可见 |
| `PUT /api/suppliers/update/{id}`、`PUT /api/parts/update/{id}`、`PUT /api/customers/update/{id}`、`PUT /api/logistics/update/{id}` | 回显请求体，只额外填充 `updateTime`；**请求里没有出现的字段在响应中为 `null`**（例如 `deleted`、`createTime`、`registeredTime`、`stockWarningValue`）——这些 `null` 只说明"没回读"，**不代表数据库里的值被清空** |

> 需要确认真实落库结果时，请在写操作之后调用对应的 `GET /get/{id}`（订单用 `GET /orders/get/{id}` 或 `GET /orders/details/{id}`）。

### 状态码说明

| 状态码 | 枚举 | 说明 | 是否会出现 |
|--------|------|------|------------|
| 200 | `SUCCESS` | 操作成功 | 会 |
| 400 | `PARAM_ERROR` | 参数错误（含请求体解析失败、缺少必填参数、字段校验不通过） | 会 |
| 500 | `ERROR` / `SERVER_ERROR` | 操作失败 / 服务器内部错误（两个枚举共用 500） | 会 |
| 600 | `BUSINESS_ERROR` | 业务异常（`BusinessException` 的默认码） | 会 |
| 601 | `DATA_EXISTS` | 数据已存在（如订单编号、零件编码重复） | 会 |
| 602 | `DATA_NOT_EXISTS` | 数据不存在 | 会 |
| 603 | `INSUFFICIENT_INVENTORY` | 库存不足（出库量 > 当前库存） | 会 |
| 401 / 403 / 404 | `UNAUTHORIZED` / `FORBIDDEN` / `NOT_FOUND` | 未授权 / 禁止访问 / 资源不存在 | **不会**：`Result` 里有对应方法，但没有任何代码路径调用 |
| 604 | `ORDER_STATUS_ERROR` | 订单状态异常 | **不会**：订单状态更新没有任何合法性校验 |
| 605 | `SUPPLIER_STATUS_ERROR` | 供应商状态异常 | **不会**：供应商状态变更同样无校验 |

### 枚举值说明

**订单状态 (status)**

| 值 | 说明 |
|----|------|
| 1 | 待审核 |
| 2 | 已审核 |
| 3 | 采购中 |
| 4 | 已入库 |
| 5 | 已取消 |

**供应商状态 (status)**

| 值 | 说明 |
|----|------|
| 1 | 合作中 |
| 2 | 已终止 |
| 3 | 审核中 |

**客户类型 (customerType)**

| 值 | 说明 |
|----|------|
| 1 | 经销商 |
| 2 | 零售店 |
| 3 | 个人用户 |

**客户折扣等级 (discountLevel)**

| 值 | 说明 |
|----|------|
| 1 | 无折扣 |
| 2 | 银牌 |
| 3 | 金牌 |
| 4 | 钻石 |

**物流状态 (status)**

| 值 | 说明 |
|----|------|
| 1 | 待发货 |
| 2 | 运输中 |
| 3 | 已签收 |
| 4 | 异常 |

**零部件分类 (category)**

| 值 | 说明 |
|----|------|
| 发动机类 | 发动机类配件 |
| 车架类 | 车架类配件 |
| 电气类 | 电气类配件 |
| 制动类 | 制动类配件 |
| 传动类 | 传动类配件 |
| 外观件 | 外观类配件 |

**用户角色 (role)**

| 值 | 说明 |
|----|------|
| admin | 管理员 |
| purchase | 采购员 |
| warehouse | 仓管员 |
| sales | 销售员 |

**用户状态 (status)**

| 值 | 说明 |
|----|------|
| 1 | 正常 |
| 2 | 禁用 |

**供应商信用评级 (creditRating)**

| 值 | 说明 |
|----|------|
| A | 优秀 |
| B | 良好 |
| C | 一般 |
| D | 较差 |

---

## 1. 采购订单管理

**基础路径**: `/api/orders`

### 1.1 创建采购订单

创建新的采购订单，包含订单基本信息和订单明细。订单编号需唯一，如不提供则需在请求体中指定。

**请求**

```
POST /api/orders/create
Content-Type: application/json
```

**请求参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| orderNumber | String | **是** | 订单编号（唯一标识，不可重复） |
| totalAmount | BigDecimal | 否 | 订单总金额。**传入值会被忽略**：服务端始终按明细重算（Σ quantity × unitPrice）并覆盖 |
| status | Integer | 否 | 订单状态，默认1（待审核） |
| orderTime | LocalDateTime | 否 | 下单时间，默认当前时间，格式：yyyy-MM-dd HH:mm:ss |
| expectedDeliveryDate | LocalDate | 否 | 预计交货日期，格式：yyyy-MM-dd |
| actualDeliveryDate | LocalDate | 否 | 实际交货日期，格式：yyyy-MM-dd |
| createdBy | Long | 否 | 创建人ID |
| remark | String | 否 | 备注 |
| orderDetail | Array | 否 | 订单明细列表。**嵌套校验未生效**：`orderDetail` 字段上没有 `@Valid`，因此不传或传空数组也会创建成功（`totalAmount` 为 0）；明细项里的 `@NotNull`/`@Min` 也不会被校验 |

**orderDetail 数组中的对象参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| partId | Long | **是** | 零部件ID |
| quantity | Integer | **是** | 采购数量，最小值为1 |
| unitPrice | BigDecimal | **是** | 采购单价 |
| subtotal | BigDecimal | 否（只读） | 小计金额，由数据库**生成列**计算（= quantity × unitPrice）：服务层从不赋值，请求中带上该字段会被忽略，只有响应里才有值 |
| remark | String | 否 | 明细备注 |

**请求示例：**

```json
{
  "orderNumber": "PO202605060001",
  "status": 1,
  "orderTime": "2026-05-06 10:00:00",
  "expectedDeliveryDate": "2026-05-15",
  "createdBy": 1,
  "remark": "紧急采购",
  "orderDetail": [
    {
      "partId": 1,
      "quantity": 10,
      "unitPrice": 500.00,
      "remark": "发动机配件"
    },
    {
      "partId": 2,
      "quantity": 20,
      "unitPrice": 150.00
    }
  ]
}
```

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": {
    "id": 1,
    "orderNumber": "PO202605060001",
    "totalAmount": 8000.00,
    "status": 1,
    "orderTime": "2026-05-06 10:00:00",
    "expectedDeliveryDate": "2026-05-15",
    "actualDeliveryDate": null,
    "createdBy": 1,
    "remark": "紧急采购",
    "deleted": 0,
    "createTime": "2026-05-06 10:00:00",
    "updateTime": "2026-05-06 10:00:00",
    "orderDetail": [
      {
        "id": null,
        "orderId": null,
        "partId": 1,
        "quantity": 10,
        "unitPrice": 500.00,
        "subtotal": null,
        "remark": "发动机配件",
        "deleted": null,
        "createTime": null,
        "updateTime": null,
        "partDetail": null
      },
      {
        "id": null,
        "orderId": null,
        "partId": 2,
        "quantity": 20,
        "unitPrice": 150.00,
        "subtotal": null,
        "remark": null,
        "deleted": null,
        "createTime": null,
        "updateTime": null,
        "partDetail": null
      }
    ]
  },
  "timestamp": 1746508800000
}
```

> 本接口**直接回显请求体**（不重新查询数据库）：明细数组里的 `id`/`orderId`/`subtotal`/`deleted`/`createTime`/`updateTime` 都是 `null`，`partDetail` 也为 `null`——这不是"订单没有明细"，实际明细已写入数据库且 `subtotal` 由生成列算出。回显规则的完整说明见「写接口的响应回显」。

---

### 1.2 更新采购订单

根据ID更新采购订单信息，包括订单明细。

> **实现方式注意**：这不是原地 UPDATE。服务层依次执行：物理删除该订单的全部明细（绕过 `@TableLogic` 的 DELETE）→ 物理删除订单主表记录 → 插入新的订单行 → 插入新的明细行。带来几个后果：
> 1. `PurchaseOrder.id` 是 `IdType.AUTO`，新订单行由数据库分配**新的自增 id**（MyBatis 会把它回填进响应对象，所以响应的 `id` 往往与请求路径里的 `{id}` 不同）；
> 2. 明细行的 `order_id` 仍写成**旧 id**，于是明细与订单失去关联，成为孤儿行（详见 [DEVELOPMENT_GUIDE.md](../../docs/DEVELOPMENT_GUIDE.md) 的技术债表）；
> 3. `createTime`/`updateTime` 被重置为当前时间，明细的 `id` 全部重新生成；
> 4. 若 `orderDetail` 传空数组或不传，更新后该订单**没有明细**，`totalAmount` 归零。

**请求**

```
PUT /api/orders/update/{id}
Content-Type: application/json
```

**路径参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| id | Long | **是** | 订单ID |

**请求参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| orderNumber | String | **是** | 订单编号 |
| totalAmount | BigDecimal | 否 | 订单总金额。**传入值会被忽略**：服务端始终按明细重算并覆盖 |
| status | Integer | 否 | 订单状态 |
| orderTime | LocalDateTime | 否 | 下单时间 |
| expectedDeliveryDate | LocalDate | 否 | 预计交货日期 |
| actualDeliveryDate | LocalDate | 否 | 实际交货日期 |
| createdBy | Long | 否 | 创建人ID |
| remark | String | 否 | 备注 |
| orderDetail | Array | 否 | 订单明细列表。**注意：它是"整体替换"而非"合并"**——服务层先物理删除该订单原有明细，只重新插入本次传入的内容；不传或传空数组时该订单更新后将没有明细，且 `totalAmount` 被重算为 0 |

**请求示例：**

```json
{
  "orderNumber": "PO202605060001",
  "totalAmount": 8500.00,
  "status": 2,
  "expectedDeliveryDate": "2026-05-16",
  "remark": "已审核，等待发货",
  "orderDetail": [
    {
      "partId": 1,
      "quantity": 10,
      "unitPrice": 500.00,
      "remark": "发动机配件"
    },
    {
      "partId": 2,
      "quantity": 20,
      "unitPrice": 150.00
    }
  ]
}
```

> 示例里 `totalAmount` 传了 8500.00，但服务端会按明细重算为 `10 × 500 + 20 × 150 = 8000.00` 并覆盖；若本例**不传** `orderDetail`，该订单的原有明细会被删除，`totalAmount` 变成 0。

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": {
    "id": 1,
    "orderNumber": "PO202605060001",
    "totalAmount": 8000.00,
    "status": 2,
    "orderTime": "2026-05-06 10:00:00",
    "expectedDeliveryDate": "2026-05-16",
    "actualDeliveryDate": null,
    "createdBy": 1,
    "remark": "已审核，等待发货",
    "deleted": 0,
    "createTime": "2026-05-06 10:00:00",
    "updateTime": "2026-05-06 10:00:00"
  },
  "timestamp": 1746508800000
}
```

> 响应同样是**请求体回显**（见「写接口的响应回显」）：`deleted`/`createTime`/`updateTime` 由服务层重新赋值、`id` 被回填为**新的自增 id**，其余字段是请求里的值；数据库的实际内容请用新 `id` 调 `GET /orders/get/{id}` 复查（注意此时明细已与订单失联，见上）。

---

### 1.3 删除采购订单

逻辑删除采购订单（将deleted字段置为1）。

**请求**

```
DELETE /api/orders/delete/{id}
```

**路径参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| id | Long | **是** | 订单ID |

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": null,
  "timestamp": 1746508800000
}
```

---

### 1.4 获取单个订单

根据ID获取采购订单详情。

**请求**

```
GET /api/orders/get/{id}
```

**路径参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| id | Long | **是** | 订单ID |

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": {
    "id": 1,
    "orderNumber": "PO202605060001",
    "totalAmount": 8000.00,
    "status": 1,
    "orderTime": "2026-05-06 10:00:00",
    "expectedDeliveryDate": "2026-05-15",
    "actualDeliveryDate": null,
    "createdBy": 1,
    "remark": "紧急采购",
    "deleted": 0,
    "createTime": "2026-05-06 10:00:00",
    "updateTime": "2026-05-06 10:00:00",
    "orderDetail": [
      {
        "id": 1,
        "orderId": 1,
        "partId": 1,
        "quantity": 10,
        "unitPrice": 500.00,
        "subtotal": 5000.00,
        "remark": "发动机配件",
        "deleted": 0,
        "createTime": "2026-05-06 10:00:00",
        "updateTime": "2026-05-06 10:00:00",
        "partDetail": {
          "id": 1,
          "partCode": "ENG-001",
          "name": "发动机总成",
          "model": "CG125",
          "specification": "四冲程",
          "unit": "台",
          "purchasePrice": 500.00,
          "suggestedRetailPrice": 800.00,
          "stockWarningValue": 10,
          "supplierId": 1,
          "category": "发动机类",
          "description": "CG125发动机总成",
          "deleted": 0,
          "createTime": "2026-05-06 10:00:00",
          "updateTime": "2026-05-06 10:00:00"
        }
      }
    ]
  },
  "timestamp": 1746508800000
}
```

---

### 1.5 获取订单详情（分离结构）

根据ID获取订单详情，返回订单和明细分离的结构。

**请求**

```
GET /api/orders/details/{id}
```

**路径参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| id | Long | **是** | 订单ID |

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": {
    "order": {
      "id": 1,
      "orderNumber": "PO202605060001",
      "totalAmount": 8000.00,
      "status": 1,
      "orderTime": "2026-05-06 10:00:00",
      "expectedDeliveryDate": "2026-05-15",
      "actualDeliveryDate": null,
      "createdBy": 1,
      "remark": "紧急采购",
      "deleted": 0,
      "createTime": "2026-05-06 10:00:00",
      "updateTime": "2026-05-06 10:00:00"
    },
    "details": [
      {
        "id": 1,
        "orderId": 1,
        "partId": 1,
        "quantity": 10,
        "unitPrice": 500.00,
        "subtotal": 5000.00,
        "remark": "发动机配件",
        "deleted": 0,
        "createTime": "2026-05-06 10:00:00",
        "updateTime": "2026-05-06 10:00:00"
      }
    ]
  },
  "timestamp": 1746508800000
}
```

---

### 1.6 分页查询订单

分页查询采购订单列表，支持多条件筛选。返回的订单包含订单明细和零部件详情。

> ⚠️ 分页目前不生效：`records` 为全表，`total`/`pages` 为 0，见「分页响应格式」的说明；下方示例中的 `total`/`pages` 数值不可得。

**请求**

```
GET /api/orders/page?current=1&size=10&orderNumber=&status=&startDate=&endDate=
```

**查询参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| current | Long | 否 | 当前页码，默认1 |
| size | Long | 否 | 每页大小，默认10 |
| orderNumber | String | 否 | 订单编号（模糊匹配） |
| status | Integer | 否 | 订单状态 |
| startDate | String | 否 | 开始日期，格式：yyyy-MM-dd |
| endDate | String | 否 | 结束日期，格式：yyyy-MM-dd |

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": {
    "records": [
      {
        "id": 1,
        "orderNumber": "PO202605060001",
        "totalAmount": 8000.00,
        "status": 1,
        "orderTime": "2026-05-06 10:00:00",
        "expectedDeliveryDate": "2026-05-15",
        "actualDeliveryDate": null,
        "createdBy": 1,
        "remark": "紧急采购",
        "deleted": 0,
        "createTime": "2026-05-06 10:00:00",
        "updateTime": "2026-05-06 10:00:00",
        "orderDetail": [...]
      }
    ],
    "total": 50,
    "size": 10,
    "current": 1,
    "pages": 5
  },
  "timestamp": 1746508800000
}
```

---

### 1.7 更新订单状态

更新采购订单的状态。当状态变更为4（已入库）时，会自动设置actualDeliveryDate为当前日期。

> **没有任何状态合法性校验**：1–5 之外的值同样能写入，也不校验状态流转顺序（例如可从 4 直接跳回 1）。错误码 604 `ORDER_STATUS_ERROR` 因此永远不会返回。

**请求**

```
PATCH /api/orders/update-status/{id}?status=2
```

**路径参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| id | Long | **是** | 订单ID |

**查询参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| status | Integer | **是** | 新状态（1-待审核，2-已审核，3-采购中，4-已入库，5-已取消） |

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": null,
  "timestamp": 1746508800000
}
```

---

### 1.8 获取采购统计

获取指定时间范围内的采购订单统计数据。

**请求**

```
GET /api/orders/statistics?startDate=2026-01-01&endDate=2026-05-06
```

**查询参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| startDate | String | 否 | 开始日期，格式：yyyy-MM-dd |
| endDate | String | 否 | 结束日期，格式：yyyy-MM-dd |

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": {
    "totalOrders": 100,
    "totalAmount": 500000,
    "completedOrders": 80,
    "pendingOrders": 20
  },
  "timestamp": 1746508800000
}
```

**响应字段说明：**

| 字段 | 类型 | 说明 |
|------|------|------|
| totalOrders | Long | 订单总数 |
| totalAmount | Long | 订单总金额（单位：**元**；服务端把区间内各订单的 totalAmount 求和后经 `.longValue()` **截断为整数元**） |
| completedOrders | Long | 已完成订单数（status=4） |
| pendingOrders | Long | 待处理订单数（status=1,2,3） |

---

### 1.9 搜索订单明细

根据零部件名称和时间范围搜索订单明细。返回的结果包含订单明细、零部件详情和供应商信息。

**请求**

```
GET /api/orders/search-details?partName=发动机&startDate=2026-01-01&endDate=2026-05-06
```

**查询参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| partName | String | 否 | 零部件名称（模糊匹配） |
| startDate | String | 否 | 开始时间，支持 yyyy-MM-dd（自动补全00:00:00）或 yyyy-MM-dd HH:mm:ss |
| endDate | String | 否 | 结束时间，支持 yyyy-MM-dd（自动补全23:59:59）或 yyyy-MM-dd HH:mm:ss |

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": [
    {
      "id": 1,
      "orderId": 1,
      "partId": 1,
      "quantity": 10,
      "unitPrice": 500.00,
      "subtotal": 5000.00,
      "remark": "发动机配件",
      "createTime": "2026-05-06T10:00:00",
      "updateTime": "2026-05-06T10:00:00",
      "partDetail": {
        "id": 1,
        "partCode": "ENG-001",
        "name": "发动机总成",
        "model": "CG125",
        "specification": "四冲程",
        "unit": "台",
        "purchasePrice": 500.00,
        "suggestedRetailPrice": 800.00,
        "stockWarningValue": 10,
        "supplierId": 1,
        "category": "发动机类",
        "description": "CG125发动机总成",
        "createTime": "2026-05-01T10:00:00",
        "updateTime": "2026-05-01T10:00:00",
        "supplier": {
          "id": 1,
          "supplierCode": "SUP001",
          "name": "摩托车配件供应商A",
          "contactPerson": "张三",
          "phone": "13800138000",
          "email": "supplier@example.com",
          "address": "广东省广州市白云区",
          "creditRating": "A",
          "status": 1
        }
      }
    }
  ],
  "timestamp": 1746508800000
}
```

---

## 2. 供应商管理

**基础路径**: `/api/suppliers`

### 2.1 创建供应商

添加新的供应商信息。

**请求**

```
POST /api/suppliers/create
Content-Type: application/json
```

**请求参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| supplierCode | String | **是** | 供应商编码（唯一标识） |
| name | String | **是** | 供应商名称 |
| contactPerson | String | 否 | 联系人 |
| phone | String | 否 | 联系电话 |
| email | String | 否 | 邮箱地址（需符合邮箱格式） |
| address | String | 否 | 地址 |
| creditRating | String | 否 | 信用评级（A/B/C/D） |
| status | Integer | 否 | 合作状态，默认1（合作中） |

**请求示例：**

```json
{
  "supplierCode": "SUP001",
  "name": "摩托车配件供应商A",
  "contactPerson": "张三",
  "phone": "13800138000",
  "email": "supplier@example.com",
  "address": "广东省广州市白云区某某路123号",
  "creditRating": "A",
  "status": 1
}
```

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": {
    "id": 1,
    "supplierCode": "SUP001",
    "name": "摩托车配件供应商A",
    "contactPerson": "张三",
    "phone": "13800138000",
    "email": "supplier@example.com",
    "address": "广东省广州市白云区某某路123号",
    "creditRating": "A",
    "status": 1,
    "deleted": 0,
    "createTime": "2026-05-06 10:00:00",
    "updateTime": "2026-05-06 10:00:00"
  },
  "timestamp": 1746508800000
}
```

---

### 2.2 更新供应商

根据ID更新供应商信息。

> 响应是**请求体回显**（见「写接口的响应回显」）：请求中未出现的字段（如 `deleted`、`createTime`）在响应里为 `null`，示例中的非 null 值并不可得；数据库内容请用 `GET /api/suppliers/get/{id}` 复查。

**请求**

```
PUT /api/suppliers/update/{id}
Content-Type: application/json
```

**路径参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| id | Long | **是** | 供应商ID |

**请求参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| supplierCode | String | **是** | 供应商编码 |
| name | String | **是** | 供应商名称 |
| contactPerson | String | 否 | 联系人 |
| phone | String | 否 | 联系电话 |
| email | String | 否 | 邮箱地址 |
| address | String | 否 | 地址 |
| creditRating | String | 否 | 信用评级 |
| status | Integer | 否 | 合作状态 |

**请求示例：**

```json
{
  "supplierCode": "SUP001",
  "name": "摩托车配件供应商A（更新）",
  "contactPerson": "李四",
  "phone": "13900139000",
  "email": "supplier_new@example.com",
  "address": "广东省深圳市南山区某某路456号",
  "creditRating": "B",
  "status": 1
}
```

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": {
    "id": 1,
    "supplierCode": "SUP001",
    "name": "摩托车配件供应商A（更新）",
    "contactPerson": "李四",
    "phone": "13900139000",
    "email": "supplier_new@example.com",
    "address": "广东省深圳市南山区某某路456号",
    "creditRating": "B",
    "status": 1,
    "deleted": 0,
    "createTime": "2026-05-06 10:00:00",
    "updateTime": "2026-05-06 11:00:00"
  },
  "timestamp": 1746508800000
}
```

---

### 2.3 删除供应商

逻辑删除供应商信息。

**请求**

```
DELETE /api/suppliers/delete/{id}
```

**路径参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| id | Long | **是** | 供应商ID |

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": null,
  "timestamp": 1746508800000
}
```

---

### 2.4 获取单个供应商

根据ID获取供应商详情。

**请求**

```
GET /api/suppliers/get/{id}
```

**路径参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| id | Long | **是** | 供应商ID |

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": {
    "id": 1,
    "supplierCode": "SUP001",
    "name": "摩托车配件供应商A",
    "contactPerson": "张三",
    "phone": "13800138000",
    "email": "supplier@example.com",
    "address": "广东省广州市白云区某某路123号",
    "creditRating": "A",
    "status": 1,
    "deleted": 0,
    "createTime": "2026-05-06 10:00:00",
    "updateTime": "2026-05-06 10:00:00"
  },
  "timestamp": 1746508800000
}
```

---

### 2.5 分页查询供应商

分页查询供应商列表，支持多条件筛选。

> ⚠️ 分页目前不生效：`records` 为全表，`total`/`pages` 为 0，见「分页响应格式」的说明；下方示例中的 `total`/`pages` 数值不可得。

**请求**

```
GET /api/suppliers/page?current=1&size=10&name=&status=&creditRating=
```

**查询参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| current | Long | 否 | 当前页码，默认1 |
| size | Long | 否 | 每页大小，默认10 |
| name | String | 否 | 供应商名称（模糊匹配） |
| status | Integer | 否 | 合作状态（1-合作中，2-已终止，3-审核中） |
| creditRating | String | 否 | 信用评级（精确匹配） |

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": {
    "records": [
      {
        "id": 1,
        "supplierCode": "SUP001",
        "name": "摩托车配件供应商A",
        "contactPerson": "张三",
        "phone": "13800138000",
        "email": "supplier@example.com",
        "address": "广东省广州市白云区某某路123号",
        "creditRating": "A",
        "status": 1,
        "deleted": 0,
        "createTime": "2026-05-06 10:00:00",
        "updateTime": "2026-05-06 10:00:00"
      }
    ],
    "total": 20,
    "size": 10,
    "current": 1,
    "pages": 2
  },
  "timestamp": 1746508800000
}
```

---

### 2.6 搜索供应商

根据名称关键字搜索供应商列表。

**请求**

```
GET /api/suppliers/search?name=配件
```

**查询参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| name | String | **是** | 供应商名称关键字（模糊匹配） |

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": [
    {
      "id": 1,
      "supplierCode": "SUP001",
      "name": "摩托车配件供应商A",
      "contactPerson": "张三",
      "phone": "13800138000",
      "email": "supplier@example.com",
      "address": "广东省广州市白云区某某路123号",
      "creditRating": "A",
      "status": 1,
      "deleted": 0,
      "createTime": "2026-05-06 10:00:00",
      "updateTime": "2026-05-06 10:00:00"
    }
  ],
  "timestamp": 1746508800000
}
```

---

### 2.7 更新供应商状态

更新供应商的合作状态。

**请求**

```
PATCH /api/suppliers/update-status/{id}?status=2
```

**路径参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| id | Long | **是** | 供应商ID |

**查询参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| status | Integer | **是** | 新状态（1-合作中，2-已终止，3-审核中） |

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": null,
  "timestamp": 1746508800000
}
```

---

### 2.8 更新供应商信用评级

更新供应商的信用评级。

**请求**

```
PATCH /api/suppliers/update-credit-rating/{id}?creditRating=B
```

**路径参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| id | Long | **是** | 供应商ID |

**查询参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| creditRating | String | **是** | 新信用评级（A/B/C/D） |

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": null,
  "timestamp": 1746508800000
}
```

---

## 3. 产品零部件管理

**基础路径**: `/api/parts`

### 3.1 创建零部件

添加新的产品零部件信息。零件编码需唯一。

**请求**

```
POST /api/parts/create
Content-Type: application/json
```

**请求参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| partCode | String | **是** | 零件编码（唯一标识） |
| name | String | **是** | 零件名称 |
| model | String | 否 | 型号 |
| specification | String | 否 | 规格 |
| unit | String | 否 | 单位（个/套/件/台等） |
| purchasePrice | BigDecimal | **是** | 采购单价（不能小于0） |
| suggestedRetailPrice | BigDecimal | 否 | 建议零售价 |
| stockWarningValue | Integer | 否 | 库存预警值 |
| supplierId | Long | 否 | 供应商ID |
| category | String | 否 | 分类（发动机类/车架类/电气类/制动类/传动类/外观件） |
| description | String | 否 | 零件描述 |

**请求示例：**

```json
{
  "partCode": "ENG-001",
  "name": "发动机总成",
  "model": "CG125",
  "specification": "四冲程风冷",
  "unit": "台",
  "purchasePrice": 500.00,
  "suggestedRetailPrice": 800.00,
  "stockWarningValue": 10,
  "supplierId": 1,
  "category": "发动机类",
  "description": "CG125发动机总成，原装品质"
}
```

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": {
    "id": 1,
    "partCode": "ENG-001",
    "name": "发动机总成",
    "model": "CG125",
    "specification": "四冲程风冷",
    "unit": "台",
    "purchasePrice": 500.00,
    "suggestedRetailPrice": 800.00,
    "stockWarningValue": 10,
    "supplierId": 1,
    "category": "发动机类",
    "description": "CG125发动机总成，原装品质",
    "deleted": 0,
    "createTime": "2026-05-06 10:00:00",
    "updateTime": "2026-05-06 10:00:00"
  },
  "timestamp": 1746508800000
}
```

---

### 3.2 更新零部件

根据ID更新零部件信息。

> 响应是**请求体回显**（见「写接口的响应回显」）：请求中未出现的字段（如 `stockWarningValue`、`supplierId`、`deleted`、`createTime`）在响应里为 `null`，示例中的非 null 值并不可得；数据库内容请用 `GET /api/parts/get/{id}` 复查。

**请求**

```
PUT /api/parts/update/{id}
Content-Type: application/json
```

**路径参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| id | Long | **是** | 零部件ID |

**请求参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| partCode | String | **是** | 零件编码 |
| name | String | **是** | 零件名称 |
| model | String | 否 | 型号 |
| specification | String | 否 | 规格 |
| unit | String | 否 | 单位 |
| purchasePrice | BigDecimal | **是** | 采购单价 |
| suggestedRetailPrice | BigDecimal | 否 | 建议零售价 |
| stockWarningValue | Integer | 否 | 库存预警值 |
| supplierId | Long | 否 | 供应商ID |
| category | String | 否 | 分类 |
| description | String | 否 | 零件描述 |

**请求示例：**

```json
{
  "partCode": "ENG-001",
  "name": "发动机总成（升级版）",
  "model": "CG150",
  "specification": "四冲程水冷",
  "unit": "台",
  "purchasePrice": 600.00,
  "suggestedRetailPrice": 950.00,
  "category": "发动机类"
}
```

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": {
    "id": 1,
    "partCode": "ENG-001",
    "name": "发动机总成（升级版）",
    "model": "CG150",
    "specification": "四冲程水冷",
    "unit": "台",
    "purchasePrice": 600.00,
    "suggestedRetailPrice": 950.00,
    "stockWarningValue": 10,
    "supplierId": 1,
    "category": "发动机类",
    "description": null,
    "deleted": 0,
    "createTime": "2026-05-06 10:00:00",
    "updateTime": "2026-05-06 11:00:00"
  },
  "timestamp": 1746508800000
}
```

---

### 3.3 删除零部件

逻辑删除零部件信息。

**请求**

```
DELETE /api/parts/delete/{id}
```

**路径参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| id | Long | **是** | 零部件ID |

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": null,
  "timestamp": 1746508800000
}
```

---

### 3.4 获取单个零部件

根据ID获取零部件详情。

**请求**

```
GET /api/parts/get/{id}
```

**路径参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| id | Long | **是** | 零部件ID |

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": {
    "id": 1,
    "partCode": "ENG-001",
    "name": "发动机总成",
    "model": "CG125",
    "specification": "四冲程风冷",
    "unit": "台",
    "purchasePrice": 500.00,
    "suggestedRetailPrice": 800.00,
    "stockWarningValue": 10,
    "supplierId": 1,
    "category": "发动机类",
    "description": "CG125发动机总成，原装品质",
    "deleted": 0,
    "createTime": "2026-05-06 10:00:00",
    "updateTime": "2026-05-06 10:00:00"
  },
  "timestamp": 1746508800000
}
```

---

### 3.5 分页查询零部件

分页查询零部件列表，支持多条件筛选。

> ⚠️ 分页目前不生效：`records` 为全表，`total`/`pages` 为 0，见「分页响应格式」的说明；下方示例中的 `total`/`pages` 数值不可得。

**请求**

```
GET /api/parts/page?current=1&size=10&name=&category=&supplierId=
```

**查询参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| current | Long | 否 | 当前页码，默认1 |
| size | Long | 否 | 每页大小，默认10 |
| name | String | 否 | 零件名称（模糊匹配） |
| category | String | 否 | 分类（精确匹配） |
| supplierId | Long | 否 | 供应商ID（精确匹配） |

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": {
    "records": [
      {
        "id": 1,
        "partCode": "ENG-001",
        "name": "发动机总成",
        "model": "CG125",
        "specification": "四冲程风冷",
        "unit": "台",
        "purchasePrice": 500.00,
        "suggestedRetailPrice": 800.00,
        "stockWarningValue": 10,
        "supplierId": 1,
        "category": "发动机类",
        "description": "CG125发动机总成，原装品质",
        "deleted": 0,
        "createTime": "2026-05-06 10:00:00",
        "updateTime": "2026-05-06 10:00:00"
      }
    ],
    "total": 50,
    "size": 10,
    "current": 1,
    "pages": 5
  },
  "timestamp": 1746508800000
}
```

---

### 3.6 搜索零部件

根据名称关键字搜索零部件列表。

**请求**

```
GET /api/parts/search?name=发动机
```

**查询参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| name | String | **是** | 零件名称关键字（模糊匹配） |

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": [
    {
      "id": 1,
      "partCode": "ENG-001",
      "name": "发动机总成",
      "model": "CG125",
      "specification": "四冲程风冷",
      "unit": "台",
      "purchasePrice": 500.00,
      "suggestedRetailPrice": 800.00,
      "stockWarningValue": 10,
      "supplierId": 1,
      "category": "发动机类",
      "description": "CG125发动机总成，原装品质",
      "deleted": 0,
      "createTime": "2026-05-06 10:00:00",
      "updateTime": "2026-05-06 10:00:00"
    },
    {
      "id": 2,
      "partCode": "ENG-002",
      "name": "发动机活塞",
      "model": "CG125",
      "specification": "标准尺寸",
      "unit": "个",
      "purchasePrice": 80.00,
      "suggestedRetailPrice": 120.00,
      "stockWarningValue": 20,
      "supplierId": 1,
      "category": "发动机类",
      "description": "CG125发动机活塞",
      "deleted": 0,
      "createTime": "2026-05-06 10:00:00",
      "updateTime": "2026-05-06 10:00:00"
    }
  ],
  "timestamp": 1746508800000
}
```

---

### 3.7 更新采购单价

快速更新零部件的采购单价。

**请求**

```
PATCH /api/parts/update-price/{id}?purchasePrice=550.00
```

**路径参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| id | Long | **是** | 零部件ID |

**查询参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| purchasePrice | BigDecimal | **是** | 新采购单价（必须 >= 0） |

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": null,
  "timestamp": 1746508800000
}
```

---

### 3.8 获取供应商的产品列表

获取指定供应商供应的所有产品。

**请求**

```
GET /api/parts/supplier/{supplierId}
```

**路径参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| supplierId | Long | **是** | 供应商ID |

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": [
    {
      "id": 1,
      "partCode": "ENG-001",
      "name": "发动机总成",
      "model": "CG125",
      "specification": "四冲程风冷",
      "unit": "台",
      "purchasePrice": 500.00,
      "suggestedRetailPrice": 800.00,
      "stockWarningValue": 10,
      "supplierId": 1,
      "category": "发动机类",
      "description": "CG125发动机总成，原装品质",
      "deleted": 0,
      "createTime": "2026-05-06T10:00:00",
      "updateTime": "2026-05-06T10:00:00"
    },
    {
      "id": 3,
      "partCode": "ENG-003",
      "name": "发动机缸体",
      "model": "CG125",
      "specification": "铝合金",
      "unit": "个",
      "purchasePrice": 200.00,
      "suggestedRetailPrice": 350.00,
      "stockWarningValue": 15,
      "supplierId": 1,
      "category": "发动机类",
      "description": "CG125发动机缸体",
      "deleted": 0,
      "createTime": "2026-05-06T10:00:00",
      "updateTime": "2026-05-06T10:00:00"
    }
  ],
  "timestamp": 1746508800000
}
```

---

## 4. 客户管理

**基础路径**: `/api/customers`

### 4.1 创建客户

添加新的客户信息。

**请求**

```
POST /api/customers/create
Content-Type: application/json
```

**请求参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| customerCode | String | **是** | 客户编码（唯一标识） |
| name | String | **是** | 客户名称 |
| contactPerson | String | 否 | 联系人 |
| phone | String | 否 | 联系电话 |
| email | String | 否 | 邮箱地址（需符合邮箱格式） |
| address | String | 否 | 地址 |
| customerType | Integer | 否 | 客户类型（1-经销商，2-零售店，3-个人用户） |
| discountLevel | Integer | 否 | 折扣等级（1-无折扣，2-银牌，3-金牌，4-钻石） |
| registeredTime | LocalDateTime | 否 | 注册时间，格式：yyyy-MM-dd HH:mm:ss |

**请求示例：**

```json
{
  "customerCode": "CUST001",
  "name": "摩托车维修店A",
  "contactPerson": "王五",
  "phone": "13700137000",
  "email": "customer@example.com",
  "address": "广东省佛山市禅城区某某路78号",
  "customerType": 2,
  "discountLevel": 2,
  "registeredTime": "2026-05-06 10:00:00"
}
```

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": {
    "id": 1,
    "customerCode": "CUST001",
    "name": "摩托车维修店A",
    "contactPerson": "王五",
    "phone": "13700137000",
    "email": "customer@example.com",
    "address": "广东省佛山市禅城区某某路78号",
    "customerType": 2,
    "discountLevel": 2,
    "registeredTime": "2026-05-06 10:00:00",
    "deleted": 0,
    "createTime": "2026-05-06 10:00:00",
    "updateTime": "2026-05-06 10:00:00"
  },
  "timestamp": 1746508800000
}
```

---

### 4.2 更新客户

根据ID更新客户信息。

> 响应是**请求体回显**（见「写接口的响应回显」）：请求中未出现的字段（如 `email`、`registeredTime`、`deleted`、`createTime`）在响应里为 `null`，示例中的非 null 值并不可得；数据库内容请用 `GET /api/customers/get/{id}` 复查。

**请求**

```
PUT /api/customers/update/{id}
Content-Type: application/json
```

**路径参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| id | Long | **是** | 客户ID |

**请求参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| customerCode | String | **是** | 客户编码 |
| name | String | **是** | 客户名称 |
| contactPerson | String | 否 | 联系人 |
| phone | String | 否 | 联系电话 |
| email | String | 否 | 邮箱地址 |
| address | String | 否 | 地址 |
| customerType | Integer | 否 | 客户类型 |
| discountLevel | Integer | 否 | 折扣等级 |
| registeredTime | LocalDateTime | 否 | 注册时间 |

**请求示例：**

```json
{
  "customerCode": "CUST001",
  "name": "摩托车维修店A（更新）",
  "contactPerson": "赵六",
  "phone": "13600136000",
  "address": "广东省广州市天河区某某路90号",
  "customerType": 1,
  "discountLevel": 3
}
```

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": {
    "id": 1,
    "customerCode": "CUST001",
    "name": "摩托车维修店A（更新）",
    "contactPerson": "赵六",
    "phone": "13600136000",
    "email": "customer@example.com",
    "address": "广东省广州市天河区某某路90号",
    "customerType": 1,
    "discountLevel": 3,
    "registeredTime": "2026-05-06 10:00:00",
    "deleted": 0,
    "createTime": "2026-05-06 10:00:00",
    "updateTime": "2026-05-06 11:00:00"
  },
  "timestamp": 1746508800000
}
```

---

### 4.3 删除客户

逻辑删除客户信息。

**请求**

```
DELETE /api/customers/delete/{id}
```

**路径参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| id | Long | **是** | 客户ID |

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": null,
  "timestamp": 1746508800000
}
```

---

### 4.4 获取单个客户

根据ID获取客户详情。

**请求**

```
GET /api/customers/get/{id}
```

**路径参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| id | Long | **是** | 客户ID |

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": {
    "id": 1,
    "customerCode": "CUST001",
    "name": "摩托车维修店A",
    "contactPerson": "王五",
    "phone": "13700137000",
    "email": "customer@example.com",
    "address": "广东省佛山市禅城区某某路78号",
    "customerType": 2,
    "discountLevel": 2,
    "registeredTime": "2026-05-06 10:00:00",
    "deleted": 0,
    "createTime": "2026-05-06 10:00:00",
    "updateTime": "2026-05-06 10:00:00"
  },
  "timestamp": 1746508800000
}
```

---

### 4.5 分页查询客户

分页查询客户列表，支持多条件筛选。

> ⚠️ 分页目前不生效：`records` 为全表，`total`/`pages` 为 0，见「分页响应格式」的说明；下方示例中的 `total`/`pages` 数值不可得。

**请求**

```
GET /api/customers/page?current=1&size=10&name=&customerType=&discountLevel=
```

**查询参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| current | Long | 否 | 当前页码，默认1 |
| size | Long | 否 | 每页大小，默认10 |
| name | String | 否 | 客户名称（模糊匹配） |
| customerType | Integer | 否 | 客户类型（精确匹配） |
| discountLevel | Integer | 否 | 折扣等级（精确匹配） |

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": {
    "records": [
      {
        "id": 1,
        "customerCode": "CUST001",
        "name": "摩托车维修店A",
        "contactPerson": "王五",
        "phone": "13700137000",
        "email": "customer@example.com",
        "address": "广东省佛山市禅城区某某路78号",
        "customerType": 2,
        "discountLevel": 2,
        "registeredTime": "2026-05-06 10:00:00",
        "deleted": 0,
        "createTime": "2026-05-06 10:00:00",
        "updateTime": "2026-05-06 10:00:00"
      }
    ],
    "total": 30,
    "size": 10,
    "current": 1,
    "pages": 3
  },
  "timestamp": 1746508800000
}
```

---

### 4.6 搜索客户

根据名称关键字搜索客户列表。

**请求**

```
GET /api/customers/search?name=摩托车
```

**查询参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| name | String | **是** | 客户名称关键字（模糊匹配） |

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": [
    {
      "id": 1,
      "customerCode": "CUST001",
      "name": "摩托车维修店A",
      "contactPerson": "王五",
      "phone": "13700137000",
      "email": "customer@example.com",
      "address": "广东省佛山市禅城区某某路78号",
      "customerType": 2,
      "discountLevel": 2,
      "registeredTime": "2026-05-06 10:00:00",
      "deleted": 0,
      "createTime": "2026-05-06 10:00:00",
      "updateTime": "2026-05-06 10:00:00"
    }
  ],
  "timestamp": 1746508800000
}
```

---

### 4.7 更新客户类型

快速更新客户类型。

**请求**

```
PATCH /api/customers/update-type/{id}?customerType=1
```

**路径参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| id | Long | **是** | 客户ID |

**查询参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| customerType | Integer | **是** | 新客户类型（1-经销商，2-零售店，3-个人用户） |

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": null,
  "timestamp": 1746508800000
}
```

---

### 4.8 更新折扣等级

快速更新客户折扣等级。

**请求**

```
PATCH /api/customers/update-discount/{id}?discountLevel=3
```

**路径参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| id | Long | **是** | 客户ID |

**查询参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| discountLevel | Integer | **是** | 新折扣等级（1-无折扣，2-银牌，3-金牌，4-钻石） |

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": null,
  "timestamp": 1746508800000
}
```

---

## 5. 物流管理

**基础路径**: `/api/logistics`

### 5.1 创建物流记录

添加新的物流信息记录。

**请求**

```
POST /api/logistics/create
Content-Type: application/json
```

**请求参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| orderId | Long | **是** | 关联的订单ID |
| logisticsCompany | String | 否 | 物流公司 |
| trackingNumber | String | 否 | 运单号 |
| shipTime | LocalDateTime | 否 | 发货时间，格式：yyyy-MM-dd HH:mm:ss |
| estimatedArrivalTime | LocalDateTime | 否 | 预计到达时间，格式：yyyy-MM-dd HH:mm:ss |
| actualArrivalTime | LocalDateTime | 否 | 实际到达时间，格式：yyyy-MM-dd HH:mm:ss |
| status | Integer | 否 | 物流状态（1-待发货，2-运输中，3-已签收，4-异常） |
| receiver | String | 否 | 收货人 |
| remark | String | 否 | 备注 |

**请求示例：**

```json
{
  "orderId": 1,
  "logisticsCompany": "顺丰速运",
  "trackingNumber": "SF1234567890",
  "shipTime": "2026-05-08 10:00:00",
  "estimatedArrivalTime": "2026-05-10 18:00:00",
  "status": 1,
  "receiver": "李四",
  "remark": "请当面验货"
}
```

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": {
    "id": 1,
    "orderId": 1,
    "logisticsCompany": "顺丰速运",
    "trackingNumber": "SF1234567890",
    "shipTime": "2026-05-08 10:00:00",
    "estimatedArrivalTime": "2026-05-10 18:00:00",
    "actualArrivalTime": null,
    "status": 1,
    "receiver": "李四",
    "remark": "请当面验货",
    "deleted": 0,
    "createTime": "2026-05-08 10:00:00",
    "updateTime": "2026-05-08 10:00:00"
  },
  "timestamp": 1746508800000
}
```

---

### 5.2 更新物流信息

根据ID更新物流信息。

> 响应是**请求体回显**（见「写接口的响应回显」）：`deleted` 与 `createTime` 不会被回填（只有 `updateTime` 会），示例中的非 null 值并不可得；数据库内容请用 `GET /api/logistics/get/{id}` 复查。

**请求**

```
PUT /api/logistics/update/{id}
Content-Type: application/json
```

**路径参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| id | Long | **是** | 物流ID |

**请求参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| orderId | Long | **是** | 关联的订单ID |
| logisticsCompany | String | 否 | 物流公司 |
| trackingNumber | String | 否 | 运单号 |
| shipTime | LocalDateTime | 否 | 发货时间 |
| estimatedArrivalTime | LocalDateTime | 否 | 预计到达时间 |
| actualArrivalTime | LocalDateTime | 否 | 实际到达时间 |
| status | Integer | 否 | 物流状态 |
| receiver | String | 否 | 收货人 |
| remark | String | 否 | 备注 |

**请求示例：**

```json
{
  "orderId": 1,
  "logisticsCompany": "顺丰速运",
  "trackingNumber": "SF1234567890",
  "shipTime": "2026-05-08 10:00:00",
  "estimatedArrivalTime": "2026-05-10 18:00:00",
  "status": 2,
  "receiver": "李四",
  "remark": "货物已发出"
}
```

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": {
    "id": 1,
    "orderId": 1,
    "logisticsCompany": "顺丰速运",
    "trackingNumber": "SF1234567890",
    "shipTime": "2026-05-08 10:00:00",
    "estimatedArrivalTime": "2026-05-10 18:00:00",
    "actualArrivalTime": null,
    "status": 2,
    "receiver": "李四",
    "remark": "货物已发出",
    "deleted": 0,
    "createTime": "2026-05-08 10:00:00",
    "updateTime": "2026-05-08 12:00:00"
  },
  "timestamp": 1746508800000
}
```

---

### 5.3 删除物流记录

逻辑删除物流记录。

**请求**

```
DELETE /api/logistics/delete/{id}
```

**路径参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| id | Long | **是** | 物流ID |

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": null,
  "timestamp": 1746508800000
}
```

---

### 5.4 获取物流记录

根据ID获取物流详情。

**请求**

```
GET /api/logistics/get/{id}
```

**路径参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| id | Long | **是** | 物流ID |

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": {
    "id": 1,
    "orderId": 1,
    "logisticsCompany": "顺丰速运",
    "trackingNumber": "SF1234567890",
    "shipTime": "2026-05-08 10:00:00",
    "estimatedArrivalTime": "2026-05-10 18:00:00",
    "actualArrivalTime": null,
    "status": 2,
    "receiver": "李四",
    "remark": "货物已发出",
    "deleted": 0,
    "createTime": "2026-05-08 10:00:00",
    "updateTime": "2026-05-08 12:00:00"
  },
  "timestamp": 1746508800000
}
```

---

### 5.5 分页查询物流信息

分页查询物流列表，支持多条件筛选。

> ⚠️ 分页目前不生效：`records` 为全表，`total`/`pages` 为 0，见「分页响应格式」的说明；下方示例中的 `total`/`pages` 数值不可得。

**请求**

```
GET /api/logistics/page?current=1&size=10&orderId=&trackingNumber=&status=
```

**查询参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| current | Long | 否 | 当前页码，默认1 |
| size | Long | 否 | 每页大小，默认10 |
| orderId | Long | 否 | 订单ID（精确匹配） |
| trackingNumber | String | 否 | 运单号（模糊匹配） |
| status | Integer | 否 | 物流状态（精确匹配） |

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": {
    "records": [
      {
        "id": 1,
        "orderId": 1,
        "logisticsCompany": "顺丰速运",
        "trackingNumber": "SF1234567890",
        "shipTime": "2026-05-08 10:00:00",
        "estimatedArrivalTime": "2026-05-10 18:00:00",
        "actualArrivalTime": null,
        "status": 2,
        "receiver": "李四",
        "remark": "货物已发出",
        "deleted": 0,
        "createTime": "2026-05-08 10:00:00",
        "updateTime": "2026-05-08 12:00:00"
      }
    ],
    "total": 20,
    "size": 10,
    "current": 1,
    "pages": 2
  },
  "timestamp": 1746508800000
}
```

---

### 5.6 根据订单获取物流信息

根据订单ID获取该订单的所有物流信息。

**请求**

```
GET /api/logistics/order/{orderId}
```

**路径参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| orderId | Long | **是** | 订单ID |

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": [
    {
      "id": 1,
      "orderId": 1,
      "logisticsCompany": "顺丰速运",
      "trackingNumber": "SF1234567890",
      "shipTime": "2026-05-08 10:00:00",
      "estimatedArrivalTime": "2026-05-10 18:00:00",
      "actualArrivalTime": null,
      "status": 2,
      "receiver": "李四",
      "remark": "货物已发出",
      "deleted": 0,
      "createTime": "2026-05-08 10:00:00",
      "updateTime": "2026-05-08 12:00:00"
    }
  ],
  "timestamp": 1746508800000
}
```

---

### 5.7 更新物流状态

快速更新物流状态。

**请求**

```
PATCH /api/logistics/update-status/{id}?status=3
```

**路径参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| id | Long | **是** | 物流ID |

**查询参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| status | Integer | **是** | 新物流状态（1-待发货，2-运输中，3-已签收，4-异常） |

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": null,
  "timestamp": 1746508800000
}
```

---

### 5.8 更新发货信息

更新物流的发货信息。调用此接口会自动将状态设置为2（运输中）。

> ⚠️ `logisticsCompany` **虽然标为可选，但省略它会清空原有物流公司**：服务层无条件执行 `SET logistics_company = ?`，MyBatis-Plus 对 `null` 也会拼进 SET 子句，结果是写入 NULL 而不是"保持原值"。要保留原值请显式传回原公司名。

**请求**

```
PATCH /api/logistics/update-shipping/{id}?shipTime=2026-05-08 10:00:00&trackingNumber=SF1234567890&logisticsCompany=顺丰速运
```

**路径参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| id | Long | **是** | 物流ID |

**查询参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| shipTime | LocalDateTime | **是** | 发货时间，格式：yyyy-MM-dd HH:mm:ss |
| trackingNumber | String | **是** | 运单号 |
| logisticsCompany | String | 否 | 物流公司 |

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": null,
  "timestamp": 1746508800000
}
```

---

### 5.9 更新收货信息

更新物流的收货信息。调用此接口会自动将状态设置为3（已签收）。

**请求**

```
PATCH /api/logistics/update-receiving/{id}?actualArrivalTime=2026-05-10 18:00:00&receiver=李四
```

**路径参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| id | Long | **是** | 物流ID |

**查询参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| actualArrivalTime | LocalDateTime | **是** | 实际到达时间，格式：yyyy-MM-dd HH:mm:ss |
| receiver | String | **是** | 收货人 |

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": null,
  "timestamp": 1746508800000
}
```

---

## 6. 库存管理

**基础路径**: `/api/inventory`

### 6.1 获取库存记录

根据ID获取库存详情（包含零部件信息）。

**请求**

```
GET /api/inventory/get/{id}
```

**路径参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| id | Long | **是** | 库存ID |

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": {
    "id": 1,
    "partId": 1,
    "currentQuantity": 50,
    "safetyStock": 10,
    "lastInboundTime": "2026-05-01 10:00:00",
    "lastOutboundTime": "2026-05-05 14:30:00",
    "warehouseLocation": "A区-01-01",
    "deleted": 0,
    "createTime": "2026-05-01T09:00:00.000",
    "updateTime": "2026-05-05T14:30:00.000",
    "partDetail": {
      "id": 1,
      "partCode": "ENG-001",
      "name": "发动机总成",
      "model": "CG125",
      "specification": "四冲程风冷",
      "unit": "台",
      "purchasePrice": 500.00,
      "suggestedRetailPrice": 800.00,
      "stockWarningValue": 10,
      "supplierId": 1,
      "category": "发动机类",
      "description": "CG125发动机总成，原装品质"
    }
  },
  "timestamp": 1746508800000
}
```

---

### 6.2 分页查询库存

分页查询库存列表，支持多条件筛选。返回的库存记录包含零部件信息。

> ⚠️ 分页目前不生效：`records` 为全表，`total`/`pages` 为 0，见「分页响应格式」的说明；下方示例中的 `total`/`pages` 数值不可得。
>
> 另外 `partName` **不是在 SQL 里过滤**，而是在取回数据后于 Java 侧过滤：命中的记录若落在"后面几页"就永远不会返回，`total` 也仍是未过滤的计数。

**请求**

```
GET /api/inventory/page?current=1&size=10&partName=&warehouseLocation=
```

**查询参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| current | Long | 否 | 当前页码，默认1 |
| size | Long | 否 | 每页大小，默认10 |
| partName | String | 否 | 零件名称（模糊匹配，会过滤不匹配的记录） |
| warehouseLocation | String | 否 | 仓库位置（模糊匹配） |

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": {
    "records": [
      {
        "id": 1,
        "partId": 1,
        "currentQuantity": 50,
        "safetyStock": 10,
        "lastInboundTime": "2026-05-01 10:00:00",
        "lastOutboundTime": "2026-05-05 14:30:00",
        "warehouseLocation": "A区-01-01",
        "deleted": 0,
        "createTime": "2026-05-01T09:00:00.000",
        "updateTime": "2026-05-05T14:30:00.000",
        "partDetail": {
          "id": 1,
          "partCode": "ENG-001",
          "name": "发动机总成",
          "purchasePrice": 500.00,
          "category": "发动机类"
        }
      }
    ],
    "total": 100,
    "size": 10,
    "current": 1,
    "pages": 10
  },
  "timestamp": 1746508800000
}
```

---

### 6.3 入库操作

执行库存入库操作。如果该零件没有库存记录，则创建新记录；如果已有记录，则累加库存数量。

**请求**

```
POST /api/inventory/inbound?partId=1&quantity=20&warehouseLocation=A区-01-01
```

**查询参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| partId | Long | **是** | 零件ID |
| quantity | Integer | **是** | 入库数量（必须 > 0） |
| warehouseLocation | String | 否 | 仓库位置（新建记录时默认为"A区-1号库"） |

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": null,
  "timestamp": 1746508800000
}
```

---

### 6.4 出库操作

执行库存出库操作。库存不足时返回错误。

**请求**

```
POST /api/inventory/outbound?partId=1&quantity=5
```

**查询参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| partId | Long | **是** | 零件ID |
| quantity | Integer | **是** | 出库数量（必须 > 0，且不能超过当前库存） |

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": null,
  "timestamp": 1746508800000
}
```

**错误响应示例（库存不足）：**

```json
{
  "code": 603,
  "message": "库存不足",
  "data": null,
  "timestamp": 1746508800000
}
```

---

### 6.5 获取库存预警列表

获取当前库存数量**低于**安全库存的记录列表（currentQuantity < safetyStock）。

> 注意两点：(1) 与 6.7 的口径不同——这里用严格 `<`，6.7 用 `<=`；(2) 关联零部件**已被逻辑删除**的库存记录会被静默丢弃（取不到 `part` 就不加入结果），因此列表可能少于实际预警数。

**请求**

```
GET /api/inventory/warning
```

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": [
    {
      "id": 2,
      "partId": 3,
      "currentQuantity": 5,
      "safetyStock": 10,
      "lastInboundTime": "2026-04-15 10:00:00",
      "lastOutboundTime": "2026-05-05 14:30:00",
      "warehouseLocation": "B区-02-05",
      "deleted": 0,
      "createTime": "2026-04-01T09:00:00.000",
      "updateTime": "2026-05-05T14:30:00.000",
      "partDetail": {
        "id": 3,
        "partCode": "BRAKE-001",
        "name": "前刹车片",
        "purchasePrice": 45.00,
        "category": "制动类"
      }
    }
  ],
  "timestamp": 1746508800000
}
```

---

### 6.6 更新安全库存

更新指定库存记录的安全库存量。

**请求**

```
PATCH /api/inventory/update-safety-stock/{id}?safetyStock=20
```

**路径参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| id | Long | **是** | 库存ID |

**查询参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| safetyStock | Integer | **是** | 新的安全库存量（必须 >= 0） |

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": null,
  "timestamp": 1746508800000
}
```

---

### 6.7 库存盘点

获取库存盘点统计数据和所有库存明细。注意本接口的预警口径与 6.5 **不一致**：这里用 `当前数量 <= 安全库存`，而 `/inventory/warning` 用 `<`（严格小于）。

**请求**

```
GET /api/inventory/check
```

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": {
    "totalItems": 100,
    "warningItems": 15,
    "normalItems": 85,
    "inventoryList": [
      {
        "id": 1,
        "partId": 1,
        "currentQuantity": 50,
        "safetyStock": 10,
        "lastInboundTime": "2026-05-01 10:00:00",
        "lastOutboundTime": "2026-05-05 14:30:00",
        "warehouseLocation": "A区-01-01",
        "deleted": 0,
        "createTime": "2026-05-01T09:00:00.000",
        "updateTime": "2026-05-05T14:30:00.000",
        "partDetail": {
          "id": 1,
          "partCode": "ENG-001",
          "name": "发动机总成",
          "purchasePrice": 500.00,
          "category": "发动机类"
        }
      }
    ]
  },
  "timestamp": 1746508800000
}
```

**响应字段说明：**

| 字段 | 类型 | 说明 |
|------|------|------|
| totalItems | Long | 库存记录总数 |
| warningItems | Long | 预警库存数（当前数量 **<=** 安全库存） |
| normalItems | Long | 其余库存数（= totalItems − warningItems，即当前数量 > 安全库存） |
| inventoryList | Array | 所有库存明细列表 |

---

## 7. 统计分析

**基础路径**: `/api/statistics`

### 7.1 获取仪表盘统计数据

获取系统总览的统计数据，包括供应商、产品、客户、用户、库存数量以及本月采购统计。

**请求**

```
GET /api/statistics/dashboard
```

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": {
    "supplierCount": 25,
    "partCount": 500,
    "customerCount": 150,
    "userCount": 10,
    "inventoryCount": 480,
    "monthPurchase": {
      "orderCount": 35,
      "totalAmount": 180000,
      "completedCount": 30
    }
  },
  "timestamp": 1746508800000
}
```

**响应字段说明：**

| 字段 | 类型 | 说明 |
|------|------|------|
| supplierCount | Long | 供应商总数 |
| partCount | Long | 产品总数 |
| customerCount | Long | 客户总数 |
| userCount | Long | 用户总数 |
| inventoryCount | Long | 库存记录数 |
| monthPurchase | Object | 本月采购统计 |
| monthPurchase.orderCount | Long | 本月订单数 |
| monthPurchase.totalAmount | Long | 本月采购总金额（单位：**元**，截断为整数元） |
| monthPurchase.completedCount | Long | 本月已完成订单数 |

---

### 7.2 获取供应商统计

获取供应商的分类统计数据。

**请求**

```
GET /api/statistics/suppliers
```

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": {
    "byStatus": {
      "1": 20,
      "2": 3,
      "3": 2
    },
    "byCreditRating": {
      "A": 10,
      "B": 12,
      "C": 2,
      "D": 1
    },
    "total": 25
  },
  "timestamp": 1746508800000
}
```

**响应字段说明：**

| 字段 | 类型 | 说明 |
|------|------|------|
| byStatus | Object | 按状态分组的供应商数量 |
| byStatus.1 | Long | 合作中的供应商数 |
| byStatus.2 | Long | 已终止的供应商数 |
| byStatus.3 | Long | 审核中的供应商数 |
| byCreditRating | Object | 按信用评级分组的供应商数量 |
| total | Integer | 供应商总数 |

---

### 7.3 获取产品分类统计

获取产品的分类统计数据。

**请求**

```
GET /api/statistics/parts
```

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": {
    "byCategory": {
      "发动机类": 100,
      "车架类": 80,
      "电气类": 90,
      "制动类": 70,
      "传动类": 60,
      "外观件": 100
    },
    "priceRanges": {
      "0-100": 150,
      "100-500": 200,
      "500-1000": 100,
      "1000+": 50
    },
    "total": 500
  },
  "timestamp": 1746508800000
}
```

**响应字段说明：**

| 字段 | 类型 | 说明 |
|------|------|------|
| byCategory | Object | 按分类分组的零件数量 |
| priceRanges | Object | 按价格区间分布的零件数量 |
| priceRanges.0-100 | Long | 价格 < 100的零件数 |
| priceRanges.100-500 | Long | 价格 >= 100 且 < 500的零件数 |
| priceRanges.500-1000 | Long | 价格 >= 500 且 < 1000的零件数 |
| priceRanges.1000+ | Long | 价格 >= 1000的零件数 |
| total | Integer | 零件总数 |

---

### 7.4 获取库存预警统计

获取库存预警相关的统计数据。

**请求**

```
GET /api/statistics/inventory
```

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": {
    "statusDistribution": {
      "warning": 15,
      "normal": 465
    },
    "zeroStockCount": 5,
    "total": 480
  },
  "timestamp": 1746508800000
}
```

**响应字段说明：**

| 字段 | 类型 | 说明 |
|------|------|------|
| statusDistribution | Object | 库存状态分布 |
| statusDistribution.warning | Long | 预警库存数（currentQuantity <= safetyStock） |
| statusDistribution.normal | Long | 正常库存数 |
| zeroStockCount | Long | 库存为0的产品数 |
| total | Integer | 库存记录总数 |

---

### 7.5 获取月度采购趋势

获取指定时间范围内的月度采购趋势数据。默认查询最近6个月。

**请求**

```
GET /api/statistics/monthly-trend?startDateParam=2026-01-01&endDateParam=2026-05-06
```

**查询参数：**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| startDateParam | String | 否 | 开始日期，格式：yyyy-MM-dd，默认：6个月前的1号 |
| endDateParam | String | 否 | 结束日期，格式：yyyy-MM-dd，默认：当前日期 |

**响应示例：**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": [
    {
      "month": "2026-01",
      "orderCount": 25,
      "totalAmount": 125000
    },
    {
      "month": "2026-02",
      "orderCount": 30,
      "totalAmount": 150000
    },
    {
      "month": "2026-03",
      "orderCount": 28,
      "totalAmount": 140000
    },
    {
      "month": "2026-04",
      "orderCount": 35,
      "totalAmount": 175000
    },
    {
      "month": "2026-05",
      "orderCount": 20,
      "totalAmount": 100000
    }
  ],
  "timestamp": 1746508800000
}
```

**响应字段说明：**

| 字段 | 类型 | 说明 |
|------|------|------|
| month | String | 月份，格式：yyyy-MM |
| orderCount | Integer | 该月订单数量 |
| totalAmount | BigDecimal | 该月采购总金额（单位：**元**，保留小数；本接口**不**做整数截断，与 7.1 的同名字段语义不同） |

---

## 错误码详细说明

| 状态码 | 说明 | 可能原因 |
|--------|------|----------|
| 200 | 操作成功 | - |
| 400 | 参数错误 | 请求体 JSON 解析失败、时间格式不合法、缺少必填查询参数、字段校验（`@NotNull`、`@Min` 等）不通过 |
| 500 | 操作失败 / 服务器内部错误 | 未捕获异常（`ERROR` 与 `SERVER_ERROR` 共用 500） |
| 600 | 业务异常 | `BusinessException` 抛出（未指定具体码时的默认值） |
| 601 | 数据已存在 | 重复插入相同编码的记录（订单编号、零件编码等） |
| 602 | 数据不存在 | 尝试操作不存在的记录 |
| 603 | 库存不足 | 出库数量超过当前库存 |
| 604 | 订单状态异常 | **预留，不会出现**：订单状态更新无任何校验，1–5 之外的值也能写入 |
| 605 | 供应商状态异常 | **预留，不会出现**：供应商状态变更同样无校验 |
| 401 / 403 / 404 | 未授权 / 禁止访问 / 资源不存在 | **预留，不会出现**（`Result` 方法存在但无人调用；无鉴权层） |

---

## 数据类型说明

| 类型 | 说明 | 示例 |
|------|------|------|
| Long | 64位整数 | 1, 100, 123456789 |
| Integer | 32位整数 | 1, 100, 1000 |
| BigDecimal | 高精度小数（金额） | 500.00, 1234.56 |
| String | 字符串 | "发动机", "SF123456" |
| Boolean | 布尔值 | true, false |
| LocalDate | 日期 | 2026-05-06 |
| LocalDateTime | 日期时间 | 2026-05-06 10:00:00 |
| Array | 数组 | [1, 2, 3] |
| Object | 对象 | {"key": "value"} |

---

## 时间格式说明

**输出（服务端 → 客户端）**——注意**同一个响应里可能同时出现两种写法**，取决于字段所在的类：

| 字段来源 | 序列化方式 | 输出格式 | 示例 |
|----------|------------|----------|------|
| 实体类字段（`BaseEntity.createTime`/`updateTime`，以及 `orderTime`、`shipTime`、`lastInboundTime`、`registeredTime` 等） | `CustomLocalDateTimeSerializer`（`@JsonSerialize` 覆盖 `@JsonFormat`） | `yyyy-MM-dd HH:mm:ss` | `2026-05-06 10:00:00` |
| `InventoryWithPart.createTime`/`updateTime`（含其 `partDetail`） | `@JsonFormat("yyyy-MM-dd'T'HH:mm:ss.SSS")` | ISO，**带毫秒** | `2026-05-06T10:00:00.000` |
| `PartWithSupplier.createTime`/`updateTime`、`OrderDetailWithPartAndSupplier.createTime`/`updateTime`（**未加任何注解**） | Jackson 默认 ISO | ISO，无毫秒 | `2026-05-06T10:00:00` |
| 所有 `LocalDate` 字段（`expectedDeliveryDate`、`actualDeliveryDate`） | `@JsonFormat("yyyy-MM-dd")` | `yyyy-MM-dd` | `2026-05-06` |

> 哪些接口会返回后两种 ISO 写法：`/inventory/get/{id}`、`/inventory/page`、`/inventory/warning`、`/inventory/check`（`InventoryWithPart`），`/parts/supplier/{supplierId}`（`PartWithSupplier`），`/orders/search-details`（`OrderDetailWithPartAndSupplier`）。其余接口返回的是实体，用空格写法。
>
> 上述三种写法已用 Jackson 2.15（与 Spring Boot 3.1.10 同版本）实测确认；注意 `spring.jackson.date-format` **不影响** `LocalDateTime`（它只作用于 `java.util.Date`），不要以为配置里写了空格格式就全局统一。

**输入（客户端 → 服务端）**

- JSON 请求体中的 `LocalDateTime` 经 `CustomLocalDateTimeDeserializer` 宽容解析，以下写法都能接受：`2026-05-06 10:00:00`、`2026-05-06 10:00:00.000`、`2026-05-06T10:00:00`、`2026-05-06T10:00:00.000`、`2026-05-06 10:00`、`2026-05-06T10:00:00Z`、`2026-05-06T10:00:00+08:00`。
- 解析失败（如 `2026/05/06 10:00:00`、纯日期 `2026-05-06`）会返回 `code=400`，不是 500。
- 查询参数中的时间（`logistics/update-shipping`、`logistics/update-receiving`）**只接受** `yyyy-MM-dd HH:mm:ss`（空格，不是 `T`）。

---

*文档生成时间：2026-05-06*
