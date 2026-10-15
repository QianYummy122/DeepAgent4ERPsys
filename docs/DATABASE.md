# 数据库设计

本系统涉及两个数据库：

| 数据库 | 用途 | 归属 |
|--------|------|------|
| **MySQL 8** `motorparts_db` | ERP 业务数据（供应商、零部件、订单、库存、客户、物流、用户） | Java 后端 |
| **MongoDB** `langchain_db` | AI 对话状态（checkpoint）与展示消息 | Python AI 助手 |

权威建表 SQL： [`MotorcyclePartsProcurementSystem/docs/database_schema.sql`](../MotorcyclePartsProcurementSystem/docs/database_schema.sql)

---

## 第一部分：MySQL 业务库

### 1.1 库级设置

```sql
CREATE DATABASE IF NOT EXISTS `motorparts_db`
DEFAULT CHARACTER SET utf8mb4
DEFAULT COLLATE utf8mb4_0900_ai_ci;
```

引擎统一 `InnoDB`；排序规则 `utf8mb4_0900_ai_ci`（支持中文与 emoji）。

### 1.2 表关系总览

```
                        ┌──────────┐
                        │  user    │  用户/员工
                        └────┬─────┘
                             │ created_by
                             ▼
┌──────────┐  supplier_id  ┌────────────────┐  order_id   ┌───────────┐
│ supplier │◀──────────────│ purchase_order │◀────────────│ logistics │
└──────────┘               └───────┬────────┘             └───────────┘
                                   │ order_id
                                   ▼
                            ┌──────────────┐  part_id  ┌──────────┐
                            │ order_detail │◀──────────│  part  │
                            └──────────────┘           └────┬─────┘
                                                            │ part_id
                                                     ┌──────▼──────┐
                                                     │  inventory  │
                                                     └─────────────┘

  customer   独立表，无关联
```

> **关键前提**：上图的连线是**逻辑关系**，不是数据库外键约束。**Java 应用自动建的表完全没有 FOREIGN KEY**（见 §1.7）。外键、唯一约束与级联行为只存在于手动执行的 `database_schema.sql` 中。

逻辑关系与"若执行了 `database_schema.sql`"时的约束：

| 关系 | 基数 | `database_schema.sql` 中的外键行为 | 影响 |
|------|------|-----------------------------------|------|
| `supplier` → `part` | 1:N | `fk_part_supplier` … `ON DELETE SET NULL` | 删供应商后零部件 `supplier_id` 置空，零部件保留 |
| `user` → `purchase_order` | 1:N | `fk_order_created_by` … `ON DELETE SET NULL` | 删用户后订单 `created_by` 置空 |
| `purchase_order` → `order_detail` | 1:N | `fk_detail_order` … `ON DELETE CASCADE` | **物理删订单会连带删明细** |
| `purchase_order` → `logistics` | 1:N | `fk_logistics_order` … `ON DELETE CASCADE` | **物理删订单会连带删物流记录** |
| `part` → `order_detail` | 1:N | `fk_detail_part` … `ON DELETE RESTRICT` | 有明细的零部件无法物理删除（逻辑删除不受限） |
| `part` → `inventory` | 1:1 | `fk_inventory_part` … `ON DELETE CASCADE` | 删零部件连带删库存记录（同样仅物理删除受限） |

> **注意**：业务代码的 `DELETE` 接口都是 MyBatis-Plus **逻辑删除**（`UPDATE ... SET deleted = 1`），不触发外键级联。唯一会触发级联的是 `PurchaseOrderServiceImpl.updateById` 里的物理删除路径（见 [ARCHITECTURE.md](ARCHITECTURE.md) §3.3）。
>
> 若应用建表时**没有**外键（默认情况），物理删除订单不会连带删除物流记录——会留下孤儿行。这是"是否先跑过 `database_schema.sql`"导致的行为差异之一。

### 1.3 公共字段

所有 8 张表都包含以下 4 个字段：

| 列名 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `deleted` | `tinyint` | `0` | 逻辑删除标志（0 未删除 / 1 已删除），由 `@TableLogic` 管理 |
| `create_time` | `datetime` | `CURRENT_TIMESTAMP` | 创建时间 |
| `update_time` | `datetime` | `CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP` | 更新时间 |

Java 侧对应 `com.motorparts.entity.BaseEntity`，被所有实体继承。

### 1.4 表结构明细

#### 1.4.1 `user` — 用户/员工表

> `user` 是 MySQL 关键字，SQL 中必须用反引号。

| 列名 | 类型 | 约束/默认 | 说明 |
|------|------|-----------|------|
| `id` | `bigint` | PK, AUTO_INCREMENT | 用户 ID |
| `username` | `varchar(50)` | NOT NULL, UNIQUE `uk_username` | 用户名 |
| `password` | `varchar(100)` | NOT NULL | 密码（加密存储） |
| `real_name` | `varchar(50)` | NULL | 真实姓名 |
| `role` | `varchar(50)` | DEFAULT `'purchase'` | `admin` / `purchase` / `warehouse` / `sales` |
| `department` | `varchar(50)` | DEFAULT `'采购部'` | 采购部 / 仓储部 / 销售部 / 财务部 |
| `phone` | `varchar(20)` | NULL | 电话 |
| `email` | `varchar(100)` | NULL | 邮箱 |
| `status` | `tinyint` | DEFAULT `1` | 1 正常 / 2 禁用 |

索引：`uk_username(username)`、`idx_role(role)`、`idx_department(department)`、`idx_status(status)`

#### 1.4.2 `supplier` — 供应商表

| 列名 | 类型 | 约束/默认 | 说明 |
|------|------|-----------|------|
| `id` | `bigint` | PK, AUTO_INCREMENT | 供应商 ID |
| `supplier_code` | `varchar(50)` | NOT NULL, UNIQUE `uk_supplier_code` | 供应商编码 |
| `name` | `varchar(100)` | NOT NULL | 供应商名称 |
| `contact_person` | `varchar(50)` | NULL | 联系人 |
| `phone` | `varchar(20)` | NULL | 联系电话 |
| `email` | `varchar(100)` | NULL | 邮箱 |
| `address` | `varchar(200)` | NULL | 地址 |
| `credit_rating` | `char(1)` | DEFAULT `'B'` | A 优秀 / B 良好 / C 一般 / D 较差 |
| `status` | `tinyint` | DEFAULT `1` | 1 合作中 / 2 已终止 / 3 审核中 |

索引：`uk_supplier_code`、`idx_status`、`idx_credit_rating`、`idx_create_time`

#### 1.4.3 `part` — 产品/零部件表

| 列名 | 类型 | 约束/默认 | 说明 |
|------|------|-----------|------|
| `id` | `bigint` | PK, AUTO_INCREMENT | 零部件 ID |
| `part_code` | `varchar(50)` | NOT NULL, UNIQUE `uk_part_code` | 零件编码 |
| `name` | `varchar(100)` | NOT NULL | 零件名称 |
| `model` | `varchar(100)` | NULL | 型号 |
| `specification` | `varchar(200)` | NULL | 规格 |
| `unit` | `varchar(20)` | DEFAULT `'个'` | 单位（个/套/件/台/对/根） |
| `purchase_price` | `decimal(10,2)` | NOT NULL DEFAULT `0.00` | 采购单价 |
| `suggested_retail_price` | `decimal(10,2)` | DEFAULT `0.00` | 建议零售价 |
| `stock_warning_value` | `int` | DEFAULT `10` | 库存预警值 |
| `supplier_id` | `bigint` | NULL, FK `fk_part_supplier` | → `supplier(id)` SET NULL |
| `category` | `varchar(50)` | NULL | 发动机类/车架类/电气类/制动类/传动类/外观件 |
| `description` | `text` | NULL | 零件描述 |

索引：`uk_part_code`、`idx_supplier_id`、`idx_category`、`idx_create_time`，另有复合索引 `idx_part_category_price(category, purchase_price)`

#### 1.4.4 `purchase_order` — 采购订单表

| 列名 | 类型 | 约束/默认 | 说明 |
|------|------|-----------|------|
| `id` | `bigint` | PK, AUTO_INCREMENT | 订单 ID |
| `order_number` | `varchar(50)` | NOT NULL, UNIQUE `uk_order_number` | 订单编号（`PO` + 日期 + 序号） |
| `total_amount` | `decimal(12,2)` | DEFAULT `0.00` | 订单总金额（服务端按明细重算） |
| `status` | `tinyint` | DEFAULT `1` | 1 待审核 / 2 已审核 / 3 采购中 / 4 已入库 / 5 已取消 |
| `order_time` | `datetime` | DEFAULT `CURRENT_TIMESTAMP` | 下单时间 |
| `expected_delivery_date` | `date` | NULL | 预计交货日期 |
| `actual_delivery_date` | `date` | NULL | 实际交货日期（`status=4` 时自动写当天） |
| `created_by` | `bigint` | NULL, FK `fk_order_created_by` | → `user(id)` SET NULL |
| `remark` | `varchar(500)` | NULL | 备注 |

索引：`uk_order_number`、`idx_status`、`idx_order_time`、`idx_created_by`，另有复合索引 `idx_order_status_time(status, order_time)`

#### 1.4.5 `order_detail` — 订单明细表

| 列名 | 类型 | 约束/默认 | 说明 |
|------|------|-----------|------|
| `id` | `bigint` | PK, AUTO_INCREMENT | 明细 ID |
| `order_id` | `bigint` | NOT NULL；`database_schema.sql` 中另有 FK `fk_detail_order` | → `purchase_order(id)` CASCADE |
| `part_id` | `bigint` | NOT NULL；`database_schema.sql` 中另有 FK `fk_detail_part` | → `part(id)` RESTRICT |
| `quantity` | `int` | NOT NULL DEFAULT `1` | 采购数量 |
| `unit_price` | `decimal(10,2)` | NOT NULL DEFAULT `0.00` | 采购单价（下单时的快照价） |
| `subtotal` | `decimal(12,2)` | **GENERATED ALWAYS AS (quantity * unit_price) STORED** | 小计，数据库生成列 |
| `remark` | `varchar(200)` | NULL | 备注 |

索引：`idx_order_id`、`idx_part_id`；**`database_schema.sql` 另有唯一约束 `uk_order_part(order_id, part_id)`，但应用自动建表不含它**——在默认（应用建表）环境下同一订单中同一零部件可以出现多行。

> `subtotal` 是**存储型生成列**，INSERT/UPDATE 时不可写入。因此 Java 的 `OrderDetail` 实体有 `subtotal` 字段但插入语句不包含它，只在查询时读回。

#### 1.4.6 `inventory` — 库存表

| 列名 | 类型 | 约束/默认 | 说明 |
|------|------|-----------|------|
| `id` | `bigint` | PK, AUTO_INCREMENT | 库存 ID |
| `part_id` | `bigint` | NOT NULL, FK `fk_inventory_part` | → `part(id)` CASCADE，**UNIQUE `uk_part_id`**（一件一库存记录） |
| `current_quantity` | `int` | NOT NULL DEFAULT `0` | 当前库存数量 |
| `safety_stock` | `int` | DEFAULT `10` | 安全库存量 |
| `last_inbound_time` | `datetime` | NULL | 最近入库时间 |
| `last_outbound_time` | `datetime` | NULL | 最近出库时间 |
| `warehouse_location` | `varchar(100)` | DEFAULT `'A区-1号库'` | 仓库位置 |

索引：`uk_part_id`、`idx_current_quantity`、`idx_warehouse_location`，另有复合索引 `idx_inventory_quantity_location(current_quantity, warehouse_location)`

#### 1.4.7 `customer` — 客户表

| 列名 | 类型 | 约束/默认 | 说明 |
|------|------|-----------|------|
| `id` | `bigint` | PK, AUTO_INCREMENT | 客户 ID |
| `customer_code` | `varchar(50)` | NOT NULL, UNIQUE `uk_customer_code` | 客户编码 |
| `name` | `varchar(100)` | NOT NULL | 客户名称 |
| `contact_person` | `varchar(50)` | NULL | 联系人 |
| `phone` | `varchar(20)` | NULL | 联系电话 |
| `email` | `varchar(100)` | NULL | 邮箱 |
| `address` | `varchar(200)` | NULL | 地址 |
| `customer_type` | `tinyint` | DEFAULT `1` | 1 经销商 / 2 零售店 / 3 个人用户 |
| `discount_level` | `tinyint` | DEFAULT `1` | 1 无折扣 / 2 银牌 / 3 金牌 / 4 钻石 |
| `registered_time` | `datetime` | DEFAULT `CURRENT_TIMESTAMP` | 注册时间 |

索引：`uk_customer_code`、`idx_customer_type`、`idx_discount_level`、`idx_registered_time`，另有 `idx_customer_type_discount(customer_type, discount_level)`

#### 1.4.8 `logistics` — 物流信息表

| 列名 | 类型 | 约束/默认 | 说明 |
|------|------|-----------|------|
| `id` | `bigint` | PK, AUTO_INCREMENT | 物流 ID |
| `order_id` | `bigint` | NOT NULL, FK `fk_logistics_order` | → `purchase_order(id)` CASCADE |
| `logistics_company` | `varchar(100)` | NULL | 物流公司 |
| `tracking_number` | `varchar(100)` | NULL | 运单号 |
| `ship_time` | `datetime` | NULL | 发货时间 |
| `estimated_arrival_time` | `datetime` | NULL | 预计到达时间 |
| `actual_arrival_time` | `datetime` | NULL | 实际到达时间 |
| `status` | `tinyint` | DEFAULT `1` | 1 待发货 / 2 运输中 / 3 已签收 / 4 异常 |
| `receiver` | `varchar(100)` | NULL | 收货人 |
| `remark` | `varchar(500)` | NULL | 备注 |

索引：`idx_order_id`、`idx_tracking_number`、`idx_status`、`idx_ship_time`，另有 `idx_logistics_order_status(order_id, status)`

### 1.5 视图

`database_schema.sql` 定义了 3 个视图。**Java 代码未使用它们**（全部查询走 MyBatis-Plus），它们仅供人工查询与报表工具使用。

#### `inventory_warning_view` — 三档库存状态

```sql
SELECT i.id, i.part_id, p.part_code, p.name AS part_name,
       i.current_quantity, i.safety_stock, p.stock_warning_value,
       i.warehouse_location,
       CASE
         WHEN i.current_quantity <= p.stock_warning_value THEN '严重不足'
         WHEN i.current_quantity <= i.safety_stock THEN '不足'
         ELSE '充足'
       END AS stock_status,
       i.last_inbound_time, i.last_outbound_time
FROM inventory i JOIN part p ON i.part_id = p.id
WHERE i.deleted = 0 AND p.deleted = 0;
```

> **口径差异提醒**：`sys` 侧的"预警"判定在 Java 代码里只用 `current_quantity <= safety_stock`（两档），而本视图引入了 `part.stock_warning_value` 作为"严重不足"档。MCP 工具 `inventory_warning` 返回的是前者。

#### `order_statistics_view` — 按日订单汇总

```sql
SELECT DATE(o.order_time) AS order_date, COUNT(*) AS order_count,
       SUM(o.total_amount) AS total_amount, AVG(o.total_amount) AS avg_amount
FROM purchase_order o WHERE o.deleted = 0
GROUP BY DATE(o.order_time);
```

#### `order_detail_full_view` — 明细 + 零部件 + 供应商宽表

```sql
SELECT od.id AS detail_id, od.order_id, o.order_number, od.part_id,
       p.part_code, p.name AS part_name, p.model, p.specification,
       od.quantity, od.unit_price, od.subtotal,
       p.supplier_id, s.name AS supplier_name, s.supplier_code,
       od.create_time AS detail_create_time
FROM order_detail od
JOIN purchase_order o ON od.order_id = o.id
JOIN part p ON od.part_id = p.id
LEFT JOIN supplier s ON p.supplier_id = s.id
WHERE od.deleted = 0 AND o.deleted = 0 AND p.deleted = 0;
```

### 1.6 建表的两个来源（**必读**）

8 张表在两个地方被定义，且**差异很大**。应用启动时**只执行 `DatabaseInitializer` 的 DDL**，`docs/database_schema.sql` 是纯手工执行的文档脚本（项目中没有 `spring.sql.init`、`schema.sql`、Flyway 或 Liquibase）。

| 来源 | 执行时机 | 覆盖内容 |
|------|----------|----------|
| `DatabaseInitializer.createTables()` | 应用启动时**自动**执行（`ApplicationRunner`） | 8 张表（`CREATE TABLE IF NOT EXISTS`）+ **11 个二级索引/唯一键**（6 个 `uk_` 唯一键 + 5 个 `idx_` 普通索引，另有 8 个主键），**无外键、无视图、无复合索引、无 `uk_order_part`** |
| `docs/database_schema.sql` | **必须手动**执行 | 8 张表 + **6 个外键** + 全部索引 + 5 个复合索引 + 3 个视图 + 4 条种子用户 |
| `SparkPlugDataInitializer` | **手动**运行 main（见 1.9） | 仅通过 REST 接口追加火花塞相关的供应商/零部件/库存/订单数据 |

**逐项差异对照**：

| 维度 | `database_schema.sql` | `DatabaseInitializer`（**实际生效**） |
|------|----------------------|--------------------------------------|
| 外键 | 6 个（part/purchase_order/order_detail/inventory/logistics） | **完全没有**（无任何 `CONSTRAINT`） |
| `order_detail` 唯一约束 | `uk_order_part (order_id, part_id)` | **无**（只有 `idx_order_id`、`idx_part_id`）→ 同一订单可重复同一零部件 |
| `user` 索引 | `uk_username` + `idx_role` + `idx_department` + `idx_status` | 仅 `uk_username` |
| `supplier` 索引 | `uk_supplier_code` + `idx_status` + `idx_credit_rating` + `idx_create_time` | 仅 `uk_supplier_code` |
| `part` 索引 | `uk_part_code` + `idx_supplier_id` + `idx_category` + `idx_create_time` | `uk_part_code` + `idx_supplier_id` |
| `purchase_order` 索引 | `uk_order_number` + `idx_status` + `idx_order_time` + `idx_created_by` | `uk_order_number` + `idx_order_time` |
| `inventory` 索引 | `uk_part_id` + `idx_current_quantity` + `idx_warehouse_location` | 仅 `uk_part_id` |
| `customer` 索引 | `uk_customer_code` + `idx_customer_type` + `idx_discount_level` + `idx_registered_time` | 仅 `uk_customer_code` |
| `logistics` 索引 | `idx_order_id` + `idx_tracking_number` + `idx_status` + `idx_ship_time` | 仅 `idx_order_id` |
| 复合索引（5 个） | 有 | 无 |
| 视图（3 个） | 有 | 无 |
| 列注释 | 完整枚举，如 `'状态(1-正常, 2-禁用)'` | 简略，如 `'状态'`（枚举值只在 Java 实体注释里） |
| 种子用户 | `admin`、`purchase1`、`warehouse1`、`sales1` | `user1`…`user12`（**不创建名为 admin 的行**） |
| 种子口令哈希 | 占位符 `$2a$10$YourEncryptedPasswordHere` | 全部 12 行使用同一个固定字面量哈希 |
| 批量种子数据 | 无（设计如此） | 30 供应商 / 64 零部件 / 40 客户 / 12 用户 / 120 订单 / 每零部件一条库存 / 每已发货订单一条物流 |
| 可直接执行性 | **`CREATE INDEX IF NOT EXISTS` 块在 MySQL 8 上是非法语法**（该子句属 MariaDB 扩展），整块会报错 | Java DDL 是合法 MySQL 8 语法 |

**两者一致的部分**：8 张表名、`ENGINE=InnoDB`、`CHARSET=utf8mb4`、`COLLATE=utf8mb4_0900_ai_ci`、`bigint AUTO_INCREMENT` 主键、`decimal(10,2)` 价格、`decimal(12,2)` 的 `total_amount`/`subtotal`、`subtotal` 生成列定义、`tinyint` 状态列、以及每张表都有 `deleted`/`create_time`/`update_time`。

**实践建议**：

- **推荐**：新环境先手动执行一次 `database_schema.sql`（得到外键、完整索引与视图），**但注意它会插入 4 个种子用户**，导致随后启动应用时 `insertSampleData()` 因 `SELECT COUNT(*) FROM user > 0` 而整体跳过——你将得到"空表 + 4 个用户"的库。若想要完整演示数据，应先让应用建表播种，再手动补执行索引/视图部分（跳过末尾的 `INSERT INTO user` 语句）。
- **若只跑应用不管 SQL**：表能正常工作，但**没有外键**——物理删除订单不会级联删除明细与物流，可能留下孤儿行；也没有 `uk_order_part`，同一订单可重复同一零部件。
- 因为用 `IF NOT EXISTS`，**先执行哪一个决定了表的最终形态**，后执行者不会补齐缺失的约束。

### 1.7 索引与优化

除各表的内联索引外，`database_schema.sql` 末尾还追加 5 个复合索引（**仅在该脚本实际执行成功时存在**）：

| 索引 | 表 | 列 | 服务的查询 |
|------|----|----|-----------|
| `idx_order_status_time` | `purchase_order` | `(status, order_time)` | 订单分页按状态 + 时间过滤 |
| `idx_part_category_price` | `part` | `(category, purchase_price)` | 零部件按分类筛选 + 价格区间统计 |
| `idx_inventory_quantity_location` | `inventory` | `(current_quantity, warehouse_location)` | 库存预警 + 按仓库位置查询 |
| `idx_logistics_order_status` | `logistics` | `(order_id, status)` | 按订单查物流 |
| `idx_customer_type_discount` | `customer` | `(customer_type, discount_level)` | 客户按类型/折扣筛选 |

> 这 5 条语句写作 `CREATE INDEX IF NOT EXISTS ...`，**在 MySQL 8 上会直接报语法错误**（`IF NOT EXISTS` 是 MariaDB 的扩展）。要真正建立这些索引，需改写为普通 `CREATE INDEX`（或 `ALTER TABLE ... ADD INDEX`）。

### 1.8 模拟数据生成规则

`DatabaseInitializer.insertSampleData()` 的顺序与规模（首次启动且 `user` 表为空时执行）：

| 顺序 | 方法 | 数据量 | 说明 |
|------|------|--------|------|
| 1 | `insertUsers()` | 12 条 | `user1`…`user12`；角色按 `i % 4` 轮转 admin/purchase/warehouse/sales；部门按 `i % 4` 轮转 财务部/采购部/仓储部/销售部 |
| 2 | `insertSuppliers()` | 30 条 | 取自 `SUPPLIER_NAMES`（博世、电装、布雷博、昭和、KYB、日清纺、米其林、倍耐力…… 含少量非中文混排字符）；`supplier_code` = `SUP00001`…`SUP00030`；信用评级随机 A/B/C/D；状态从 `{1,1,1,2,3}` 随机 |
| 3 | `insertParts()` | **64 条** | 取自 `PARTS_DATA`，六类：发动机类 12（`PC2001`–`PC2012`）、车架类 10（`FC3001`–`FC3010`）、电气类 12（`EC4001`–`EC4012`）、制动类 10（`BC5001`–`BC5010`）、传动类 10（`TC6001`–`TC6010`）、外观件 10（`AC7001`–`AC7010`） |
| 4 | `insertCustomers()` | 40 条 | 取自 `CUSTOMER_NAMES`（各地摩托车配件城/骑士装备店）；`customer_code` = `CUS00001`…`CUS00040` |
| 5 | `insertInventories()` | 64 条 | 与零部件一一对应（`uk_part_id`）；`safety_stock` 直接取自该零部件的 `stock_warning_value` |
| 6 | `insertPurchaseOrders()` | 120 条订单 + 每单 2–7 条明细 | 状态按权重 `{1:10, 2:20, 3:30, 4:35, 5:5}` 随机 |
| 7 | `insertLogistics()` | 仅 `status IN (3,4)` 的订单各一条（约 78 条） | 状态取 `3 已签收` / `2 运输中` 各 50% |

> `logistics` 的行数不是固定值——它取决于第 6 步随机出的订单状态分布（约 78 条）。

关键随机规则：

- **订单时间**：`getRandomDateTime2024()` 生成 2024–2025 年内的随机时刻（月 1–12，日 1–28）。
- **订单状态**：`getWeightedRandom(orderStatuses, statusWeights)` 加权随机，使"待审核/已审核/采购中/已入库"分布接近真实业务。
- **明细数量**：`2 + random.nextInt(6)` → 2–7 条，且通过 `usedPartIds` 去重。
- **明细数量值**：`5 + random.nextInt(20)` → 5–24；`unit_price` 取该零部件的 `purchase_price`（为空时兜底 `100`）。
- **库存量**：`insertInventories` 依据零部件的 `stock_warning_value` 决定区间——**30% 概率生成低于安全库存的数量**（`currentQuantity = rand(safetyStock)`），其余为 `safetyStock + rand(100)`，以便库存预警功能有数据可展示。
- **价格区间**：发动机类与传动类的采购单价为 `500 + rand(4500)`，其余四类为 `10 + rand(490)`；建议零售价 = 采购价 × (1.2 + rand(0.3))。

**幂等性**：`insertSampleData()` 开头检查 `SELECT COUNT(*) FROM user`，非 0 则整体跳过。因此**只要表里有一个用户就不会重复插入**——注意这也意味着**先执行 `database_schema.sql`（它会插入 4 个种子用户）会让 Java 的整套种子数据完全不被插入**。想重新生成需清空数据（或 drop 库）。

**随机不可复现**：所有随机值来自同一个共享的 `new Random()`，两次运行得到的数据不同。种子数据的行数固定，内容不固定。

**零部件分类与示例编码**：

| 分类 | 编码前缀 | 示例 |
|------|----------|------|
| 发动机类 | `PC2xxx` | PC2001 活塞环组件、PC2003 曲轴总成、PC2009 化油器总成 |
| 车架类 | `FC3xxx` | FC3001 前减震器、FC3003 方向把、FC3007 链轮 |
| 电气类 | `EC4xxx` | EC4001 磁电机总成、EC4003 火花塞、EC4005 大灯总成 |
| 制动类 | `BC5xxx` | BC5001 前刹车片、BC5004 刹车泵、BC5009 刹车总泵 |
| 传动类 | `TC6xxx` | TC6001 传动皮带、TC6002 普利珠、TC6007 链条 |
| 外观件 | `AC7xxx` | AC7001 前挡泥板、AC7004 后视镜、AC7008 脚蹬 |

### 1.9 火花塞专项数据集（独立工具，非自动执行）

`SparkPlugDataInitializer` 虽然放在 `init/` 包下，但**不是 Spring 组件**——它没有 `@Component`、不实现 `ApplicationRunner`，只有一个 `public static void main`。启动应用时它**不会执行**。`mvn spring-boot:run` 对它完全无感。

它是一个**通过 HTTP 调用后端 API** 的独立数据补种程序（`BASE_URL = http://localhost:8080/api`，用 `java.net.http.HttpClient` 发请求），围绕**火花塞**这一个品类构建更贴近真实电商场景的数据，用于支撑 AI 助手的比价与选型分析演示。

```powershell
# 前置条件：Spring Boot 后端已在 localhost:8080 运行
cd MotorcyclePartsProcurementSystem
mvn -q compile
mvn -q exec:java -Dexec.mainClass=com.motorparts.init.SparkPlugDataInitializer
# 或在 IDE 中直接运行该类的 main 方法
```

四个执行步骤：

| 步骤 | 动作 | 内容 |
|------|------|------|
| 1 | `createOrUpdateSuppliers()` | 3 个火花塞供应商：`SUP-SPARK-001` 电装配件专营店、`SUP-SPARK-002` 博世配件旗舰店、`SUP-SPARK-003` 电气配件专营店（信用评级 A、状态 1） |
| 2 | `createOrUpdateParts(supplierIds)` | 3 个火花塞零部件：`SPARK-DENSO-U27ETR` 电装DENSO火花塞 U27ETR（32.00/38.00）、`SPARK-BOSCH-FR7DC` 博世BOSCH火花塞 FR7DC+（40.00/48.00）、`SPARK-NGK-CR9EIX` NGK铱金火花塞 Iridium IX CR9EIX（58.00/68.00），均为 `unit=个`、`category=电气类`、`stockWarningValue=20` |
| 3 | `createInboundRecords(partIds)` | 对每个零部件先 `GET /api/inventory/page?partName=…` 查是否已有记录，无则 `POST /api/inventory/inbound?partId=…&quantity=100+rand(100)&warehouseLocation=C区-3号库` |
| 4 | `createHistoricalOrders(partIds, supplierIds)` | `POST /api/orders/create` 生成历史订单：2024 年 1–12 月每月 2–4 单（约 36 单），2025 年 1–5 月每月 3–5 单（约 15–25 单）；每单 1–3 条火花塞明细；`createdBy=1`；备注形如 `2024年3月火花塞常规采购订单` |

**幂等性**：设计为可重复运行——先 `GET` 查询（供应商按硬编码中文名 `/api/suppliers/search`，零部件按 `/api/parts/search`，库存按 `/api/inventory/page`），存在则 `PUT` 更新或跳过，不存在则 `POST` 创建，因此不会产生重复数据。

**订单编号规则**：`PO{year}{month:02d}{序号:04d}-{毫秒数%10000}`，例如 `PO2024010001-2345`。这与 `DatabaseInitializer` 的 `PO{year}{6位序号}` 以及文档示例里出现的 `PO202605060001` 都**不是同一个规则**——项目中共存多套编号约定（详见 [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) 的技术债表）。

**实现细节**：JSON 由手写的 `toJson`/`toJsonArray`/`escapeJson` 拼装，响应中的 id 用 `indexOf("\"id\":")` 字符串截取（因为项目未引入 Fastjson/Jackson 之外的 JSON 库）。这意味着**后端响应字段顺序或空白一变，该脚本就会失效**。

**时间格式**：代码中显式使用 `yyyy-MM-dd'T'HH:mm:ss.SSS`（注释说明这是为了匹配后端 `CustomLocalDateTimeDeserializer`）。该格式确实可被接受，详见 [API_REFERENCE.md](API_REFERENCE.md) §1.4。

> 具体插入的字段与订单明细请直接阅读 [`SparkPlugDataInitializer.java`](../MotorcyclePartsProcurementSystem/src/main/java/com/motorparts/init/SparkPlugDataInitializer.java)。

### 1.10 初始化开关

`application.yml` 的 `motorparts.init` 段：

```yaml
motorparts:
  init:
    enabled: true              # 总开关：false 则 DatabaseInitializer.run 直接返回
    recreate-tables: false     # ⚠️ 代码未读取此配置项，设置无效
    insert-sample-data: true   # false 则只建表不插数据
```

| 开关 | 效果 |
|------|------|
| `enabled=false` | 完全不执行建库/建表/插数据 |
| `insert-sample-data=false` | 建库建表，但不插入模拟数据 |
| `recreate-tables` | **无效果**（`DatabaseInitializer` 未注入该属性）；要重建需手动 `DROP DATABASE` |

---

## 第二部分：MongoDB（AI 助手）

连接配置来自 `.env`（`agent/env_utils.py` 读取）：

| 环境变量 | 默认值 |
|----------|--------|
| `MONGODB_URI` | `mongodb://127.0.0.1:27017/` |
| `MONGODB_DB_NAME` | `langchain_db` |
| `MONGODB_CHECKPOINT_COLLECTION` | `checkpoints` |

`config.py` 中的 `MongoClient` 设置 `serverSelectionTimeoutMS=5000`、`connectTimeoutMS=5000`——MongoDB 未启动时**5 秒内即报错**，便于快速定位问题。可通过 `check_mongodb()` 主动探测。

### 2.1 集合 `checkpoints`

由 `langgraph.checkpoint.mongodb.MongoDBSaver` 管理，**不要手工修改**。

| 字段 | 说明 |
|------|------|
| `thread_id` | 会话 ID（顶层字段，便于 `distinct` 查询） |
| `checkpoint_id` / `checkpoint_ns` | LangGraph 检查点标识 |
| `checkpoint` / `metadata` / `writes` | 序列化的图状态（含 `messages`） |
| `_id` | ObjectId；`agent_loader.get_session_updated_at()` 借其 `generation_time` 推断会话更新时间 |

用途：
- **Human-in-the-Loop 中断持久化** —— 中断状态必须落库，否则跨请求无法恢复；
- **跨重启续聊** —— 服务重启后仍能读取历史会话状态。

### 2.2 集合 `session_display_messages`

由 `api_view/agent_loader.py` 直接读写，**每条消息一个文档**。

| 字段 | 类型 | 说明 |
|------|------|------|
| `thread_id` | String | 会话 ID |
| `index` | Integer | 消息在会话内的顺序 |
| `message` | Object | 消息本体（`id`/`role`/`content`/`source`/`tool_name`/`args`/`text`/`images`/`tool_status`） |
| `updated_at` | datetime | 写入时间 |

索引：`{ thread_id: 1, index: 1 }`（`save_display_messages` 中幂等创建）

**为什么需要这个集合**：LangGraph 的 checkpoint 只保存图的内部 `messages`，而子 Agent 经由 `task` 工具折叠后的中间消息**不会完整保留**。为了让前端刷新页面后仍能看到子 Agent 的完整过程（含工具调用与图表），SSE 流在推送的同时累积一份展示消息并独立落库。

**写入策略**：`save_display_messages` 是 **delete-then-insert**（先 `delete_many({thread_id})` 再批量 `insert_many`），因此每轮对话保存的是**累积后的完整列表**，而非增量。

**容量保护**：
- `_MAX_FIELD_LENGTH = 500_000` —— `text` / `content` / `args` 三个字段超长时截断并追加 `"...(内容过长已截断)"`，避免单文档超过 16 MB；
- 改为逐条存储本身就是为了绕开单文档 16 MB 上限（早期整会话一个文档时，长对话含大量工具结果会静默保存失败）。

### 2.3 会话删除的连带影响

`DELETE /api/history/{thread_id}` 会同时清理两个集合：

```python
collection.delete_many({"thread_id": thread_id})          # checkpoints
display_collection.delete_many({"thread_id": thread_id})  # session_display_messages
```

因此删除后该会话**不可恢复**。

### 2.4 长期记忆不在 MongoDB 中

用户偏好文件（`/memories/{user_id}/preferences.md`）与持久化技能（`/persisted-skills/`）存放在 **LangGraph Store**，而 `agent/config.py` 当前用的是 `STORE = InMemoryStore()`：

```python
# InMemoryStore: 开发阶段使用。生产环境替换为持久 Store。
STORE = InMemoryStore()
```

**后果**：这两个路径下的内容**只存活于当前 Python 进程**，重启即丢失。MongoDB 只保存对话状态与展示消息。要让偏好与技能真正跨重启保留，需把 `STORE` 替换为持久化实现（如 `PostgresStore` / `RedisStore`）。

---

## 第三部分：日常运维 SQL

```sql
-- 各表行数一览
SELECT 'user' t, COUNT(*) n FROM `user` WHERE deleted = 0
UNION ALL SELECT 'supplier', COUNT(*) FROM supplier WHERE deleted = 0
UNION ALL SELECT 'part', COUNT(*) FROM part WHERE deleted = 0
UNION ALL SELECT 'purchase_order', COUNT(*) FROM purchase_order WHERE deleted = 0
UNION ALL SELECT 'order_detail', COUNT(*) FROM order_detail WHERE deleted = 0
UNION ALL SELECT 'inventory', COUNT(*) FROM inventory WHERE deleted = 0
UNION ALL SELECT 'customer', COUNT(*) FROM customer WHERE deleted = 0
UNION ALL SELECT 'logistics', COUNT(*) FROM logistics WHERE deleted = 0;

-- 订单状态分布
SELECT status, COUNT(*) cnt, SUM(total_amount) amount
FROM purchase_order WHERE deleted = 0 GROUP BY status ORDER BY status;

-- 库存预警（与 GET /api/inventory/warning 同口径）
SELECT p.part_code, p.name, i.current_quantity, i.safety_stock, i.warehouse_location
FROM inventory i JOIN part p ON i.part_id = p.id
WHERE i.deleted = 0 AND p.deleted = 0 AND i.current_quantity <= i.safety_stock
ORDER BY i.current_quantity;

-- 最近 7 天创建的订单
SELECT id, order_number, status, total_amount, order_time
FROM purchase_order WHERE deleted = 0
  AND order_time >= DATE_SUB(NOW(), INTERVAL 7 DAY)
ORDER BY order_time DESC;

-- 某订单的完整明细（含供应商）
SELECT * FROM order_detail_full_view WHERE order_number = 'PO20260523001';

-- 检查重复的订单编号（应为空）
SELECT order_number, COUNT(*) FROM purchase_order
GROUP BY order_number HAVING COUNT(*) > 1;

-- 检查孤儿明细（应为空）
SELECT od.* FROM order_detail od
LEFT JOIN purchase_order o ON od.order_id = o.id WHERE o.id IS NULL;
```

**重建数据库**（谨慎，会丢全部数据）：

```sql
DROP DATABASE motorparts_db;
```

随后重启 Java 应用，`DatabaseInitializer` 会重新建库建表；若希望同时得到视图与完整索引，再手动执行一次 `database_schema.sql`。

**MongoDB 清理**：

```javascript
use langchain_db
db.checkpoints.countDocuments()
db.session_display_messages.countDocuments()
// 删除全部对话数据（不可恢复）
db.checkpoints.deleteMany({})
db.session_display_messages.deleteMany({})
```

---

## 相关文档

- [database_schema.sql](../MotorcyclePartsProcurementSystem/docs/database_schema.sql) — 权威建表 SQL
- [数据来源说明.txt](../MotorcyclePartsProcurementSystem/docs/数据来源说明.txt) — 模拟数据的参考资料与免责声明
- [ARCHITECTURE.md](ARCHITECTURE.md) — 订单更新的物理删除语义及其后果
- [API_REFERENCE.md](API_REFERENCE.md) — 各字段在接口中的呈现
