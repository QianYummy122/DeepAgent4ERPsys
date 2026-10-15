# 摩托车零部件采购管理系统

> 本目录是仓库 [AgentToMotorcycleERP](../README.md) 中两个子工程之一的**业务后端**（system of record）：供应商 / 零部件 / 采购订单 / 库存 / 客户 / 物流 / 统计的 REST 接口与 MySQL 数据都在这里。另一个子工程 [`ERP_OPENCLAW/`](../ERP_OPENCLAW/) 是 AI 采购助手，它**只通过 REST API**（经 MCP 桥接）访问本系统，不直连数据库。本文档与根目录 [README.md](../README.md) 保持一致，陈述均按当前代码核实。

## 一、项目介绍

这是一个基于 Spring Boot 的摩托车零部件采购管理系统，用于管理供应商、产品/零部件、采购订单、库存、客户和物流等业务。

### 主要功能

- **供应商管理**：管理供应商信息，包括信用评级、合作状态等
- **产品管理**：管理摩托车零部件信息，包括分类、采购价格等
- **采购订单**：管理采购订单的全流程，包括创建、审核、入库等
- **库存管理**：管理库存，包括入库、出库、预警等功能
- **客户管理**：管理客户信息，包括客户类型、折扣等级等
- **物流管理**：管理物流信息，跟踪货物运输状态
- **统计分析**：提供采购统计、库存预警等分析报表

## 二、技术栈与运行环境

| 技术 | 版本 | 说明 |
|------|------|------|
| Java | 17 | `pom.xml` 的 `<java.version>` |
| Spring Boot | 3.1.10 | `spring-boot-starter-parent` |
| MyBatis-Plus | 3.5.3.1 | `mybatis-plus-boot-starter` |
| MySQL | 8.0+ | 驱动 `com.mysql:mysql-connector-j` 8.0.33 |
| Lombok | 1.18.30 | 编译期注解处理，已从打包产物中排除 |
| springdoc-openapi | 2.0.2 | 提供 Swagger UI（不是旧版 springfox/Swagger 1.7.0） |
| spring-boot-starter-jdbc | 随 Boot 版本 | `DatabaseInitializer` 依赖 `JdbcTemplate` 建库建表 |

> `pom.xml` 的 `<properties>` 里还留着 `hutool.version`（5.8.25）与 `fastjson.version`（2.0.47），但**没有任何依赖引用它们**——项目既未引入 Hutool，也未引入 Fastjson，不必为它们做任何准备。

### 环境要求

- JDK 17（**不是 JDK 1.8**）
- Maven 3.6+
- MySQL 8.0+

## 三、接口一览

7 个控制器、共 **54 个 REST 端点**，统一前缀 `/api`：

| 控制器 | 基础路径 | 端点数 | 覆盖能力 |
|--------|----------|--------|----------|
| `SupplierController` | `/api/suppliers` | 8 | 档案 CRUD、按名称/状态/信用评级检索、合作状态与信用评级变更 |
| `PartController` | `/api/parts` | 8 | 档案 CRUD、按名称/分类/供应商检索、采购单价调整、按供应商反查零部件 |
| `PurchaseOrderController` | `/api/orders` | 9 | 创建（自动汇总金额）、整体更新、逻辑删除、分页多条件查询、状态流转（1 待审核 → 2 已审核 → 3 采购中 → 4 已入库 / 5 已取消）、明细联表搜索、订单统计 |
| `InventoryController` | `/api/inventory` | 7 | 入库/出库、安全库存维护、库存预警列表（`current_quantity < safety_stock`）、库存检查/盘点（`/check` 统计时改用 `≤`，与 `/warning` 口径不一致） |
| `CustomerController` | `/api/customers` | 8 | 档案 CRUD、客户类型（经销商/零售店/个人）、折扣等级、类型与折扣变更 |
| `LogisticsController` | `/api/logistics` | 9 | 物流单 CRUD、按订单查询、状态更新、发货信息与收货信息登记 |
| `StatisticsController` | `/api/statistics` | 5 | 仪表盘汇总、供应商分布、零部件分类与价格区间分布、库存状态分布、月度采购趋势 |

接口统一返回 `Result<T>`（`code` / `message` / `data` / `timestamp`），分页接口返回 `PageResult<T>`（`current` / `size` / `total` / `pages` / `records`），定义在 `common/Result.java` 与 `common/PageResult.java`。

> **本模块没有认证与授权层**：没有登录接口、没有 Spring Security、没有拦截器，包括创建订单、修改库存在内的所有端点都匿名可访问。定位是内部演示/教学系统，**不可直接暴露公网**。

逐端点的请求/响应示例见 [docs/API_DOCUMENTATION.md](docs/API_DOCUMENTATION.md)；跨子工程的接口总览见根文档集的 [API 参考](../docs/API_REFERENCE.md)。

## 四、快速开始

### 4.1 数据库

系统启动时会**自动创建数据库 `motorparts_db`（如果不存在）并建表**，一般不需要手工执行 SQL。若要提前手工建库：

```sql
CREATE DATABASE motorparts_db CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
```

### 4.2 配置连接信息

编辑 `src/main/resources/application.yml`：

```yaml
spring:
  datasource:
    url: jdbc:mysql://localhost:3306/motorparts_db?useUnicode=true&characterEncoding=utf8&serverTimezone=Asia/Shanghai&useSSL=false&allowPublicKeyRetrieval=true
    username: root
    password: <你的数据库口令>
```

> 该文件中目前保存的是**明文口令**，而且**它已随仓库提交进入版本控制**（`git ls-files` 可见、`git show HEAD:` 能直接读出明文）。部署或分享前建议按顺序处理：改为环境变量注入（例如 `password: ${DB_PASSWORD}`）→ 轮换该口令 → `git rm --cached` 移出版本控制；完整安全须知见根 README 的「安全与合规须知」。

### 4.3 构建与运行

```bash
# 编译
mvn clean compile

# 运行（前台）
mvn spring-boot:run

# 或者打包后运行
mvn clean package
java -jar target/MotorcyclePartsProcurementSystem-1.0.0.jar
```

### 4.4 访问地址

| 用途 | 地址 |
|------|------|
| Swagger UI | <http://localhost:8080/swagger-ui/index.html> |
| OpenAPI JSON | <http://localhost:8080/v3/api-docs> |
| 接口基础路径 | <http://localhost:8080/api> |

> 后端**没有首页路由**：`src/main/resources` 下既没有 `static/` 也没有 `templates/`，访问 <http://localhost:8080/> 会返回 404。注意 `/swagger-ui.html` 是 springdoc 1.x 的写法，本项目用的 2.0.2 对应 `/swagger-ui/index.html`（旧路径会重定向）。

## 五、API 接口测试

### 使用 Swagger UI

1. 启动项目后访问 <http://localhost:8080/swagger-ui/index.html>
2. 页面上按「供应商管理」「采购订单管理」等分组列出全部 54 个接口
3. 展开任意接口即可查看参数与响应并直接调试

### 使用 Postman / curl

基础 URL：`http://localhost:8080/api`。写操作带 `/create`、`/update/{id}`、`/delete/{id}` 等后缀。

**创建供应商**

```http
POST http://localhost:8080/api/suppliers/create
Content-Type: application/json

{
  "supplierCode": "SUP00031",
  "name": "测试供应商",
  "contactPerson": "张三",
  "phone": "13800138000",
  "email": "test@example.com",
  "address": "上海市某区某路1号",
  "creditRating": "A",
  "status": 1
}
```

**分页查询供应商**

```http
GET http://localhost:8080/api/suppliers/page?current=1&size=10
```

**订单明细联表搜索**

```http
GET http://localhost:8080/api/orders/search-details?partName=火花塞&startTime=2024-01-01&endTime=2025-12-31
```

> 分页参数的**实际生效情况存疑**：`MyBatisPlusConfig` 只注册了 `SqlSessionFactory`、事务管理器与字段自动填充，没有注册 `MybatisPlusInterceptor`（分页插件），而 `application.yml` 又排除了 `MybatisPlusAutoConfiguration`。因此 6 个 `/page` 端点很可能忽略 `current`/`size` 直接返回全表，接入前端前请先实测确认。

## 六、数据初始化

启动时由 [init/DatabaseInitializer.java](src/main/java/com/motorparts/init/DatabaseInitializer.java)（`ApplicationRunner`）自动执行：建库 → 建表（`CREATE TABLE IF NOT EXISTS`）→ 插入模拟数据。

### 6.1 初始化配置

`application.yml`：

```yaml
motorparts:
  init:
    enabled: true             # 是否启用数据库初始化（false 时连建库建表一起跳过）
    insert-sample-data: true  # 是否插入模拟数据
```

> 配置文件里还写着 `motorparts.init.recreate-tables: false`，但**代码从未读取这个键**（`DatabaseInitializer` 只注入 `enabled` 与 `insert-sample-data`）。插入前只做一次判断：`SELECT COUNT(*) FROM user`，非 0 就整体跳过。因此**想重新灌数据，唯一有效的做法是清空 `user` 表**（或连同其他表一起清空）。

### 6.2 模拟数据规模（以代码为准）

| 数据 | 条数 | 说明 |
|------|------|------|
| 供应商 | 30 | 编码 `SUP00001`…，名称参考 Bosch、DENSO、Brembo、KYB 等真实品牌 |
| 零部件 | 64 | 6 个分类：发动机类 12、车架类 10、电气类 12、制动类 10、传动类 10、外观件 10 |
| 库存 | 64 | 与零部件一一对应；约 30% 概率低于安全库存，同类别落在同一库区 |
| 采购订单 | 120 | 订单号形如 `PO{当前年份}000001`；每单 2–7 条明细（同单内零部件不重复） |
| 客户 | 40 | 经销商 / 零售店 / 个人用户，折扣等级 1–4 |
| 用户 | 12 | `user1`…`user12`，角色与部门循环分配 |
| 物流 | 约 78 | 状态为 3（采购中）或 4（已入库）的订单各一条，数量随随机状态分布浮动 |

> 时间字段（下单时间、入库时间、客户注册时间等）随机落在 **2024–2025 年**，不是"2024 年至今"。

### 6.3 模拟用户

| 用户名 | 角色 | 部门 | 真实姓名 |
|--------|------|------|----------|
| user1 | admin（管理员） | 财务部 | 系统管理员 |
| user2 | purchase（采购员） | 采购部 | 张三 |
| user3 | warehouse（仓管员） | 仓储部 | 李四 |
| user4 | sales（销售员） | 销售部 | 王五 |
| user5–user12 | 按上表顺序循环 | 同上循环 | 赵六、钱七、孙八、周九，再循环（如"系统管理员2"） |

> 12 个用户的 `password` 字段是**同一段固定 BCrypt 哈希**，没有任何地方保存其明文；系统也没有登录接口，因此"默认密码是 `admin123`"之类的说法无法验证，请勿依赖。用户表目前只用于 `purchase_order.created_by` 的关联展示。

> 如果你改用手工脚本 [docs/database_schema.sql](docs/database_schema.sql) 建库，`user` 表里会是另一套 4 条记录（`admin` / `purchase1` / `warehouse1` / `sales1`，部门为财务部 / 采购部 / 仓储部 / 销售部），其 `password` 是占位字符串 `$2a$10$YourEncryptedPasswordHere`——脚本注释里写的 `admin123` 并不是有效哈希。而且此时应用启动会因 `user` 表非空而跳过模拟数据插入。

### 6.4 SparkPlugDataInitializer（独立补数脚本）

[init/SparkPlugDataInitializer.java](src/main/java/com/motorparts/init/SparkPlugDataInitializer.java) 带 `main()` 方法，**不是 Spring 组件**，启动流程不会调用它。它是一个通过 HTTP 调用本系统 REST 接口的补数脚本：

1. 先在 `localhost:8080` 启动后端；
2. 在 IDE 中运行它的 `main()`；
3. 它会创建/更新 3 个供应商（`SUP-SPARK-001` 电装配件专营店 / `SUP-SPARK-002` 博世配件旗舰店 / `SUP-SPARK-003` 电气配件专营店）、3 个火花塞零件（DENSO U27ETR、BOSCH FR7DC+、NGK CR9EIX）、对应入库记录（C区-3号库，100–199 件）以及 2024–2025 年的历史订单。

脚本按"存在则更新、不存在则创建"处理，可重复运行。

## 七、数据库设计

### 7.1 表结构（8 张业务表）

| 表名 | 说明 | 声明的关系 |
|------|------|------------|
| `supplier` | 供应商表 | — |
| `part` | 产品/零部件表 | `supplier_id` → `supplier` |
| `purchase_order` | 采购订单表 | `created_by` → `user` |
| `order_detail` | 订单明细表 | `order_id` → `purchase_order`，`part_id` → `part` |
| `inventory` | 库存表 | `part_id` → `part` |
| `customer` | 客户表 | — |
| `user` | 用户/员工表 | — |
| `logistics` | 物流表 | `order_id` → `purchase_order` |

### 7.2 两种建表方式（重要）

| 方式 | 何时生效 | 实际内容 |
|------|----------|----------|
| 应用内 DDL（`DatabaseInitializer.createTables()`） | **每次启动真实执行**，是运行时唯一权威结构 | 8 张表；**无外键、无视图**；`order_detail.subtotal` 是 `GENERATED ALWAYS AS (quantity * unit_price) STORED` 生成列 |
| [docs/database_schema.sql](docs/database_schema.sql) | 只在你手工导入时执行，**应用从不读取它** | 定义了 6 个外键、`uk_order_part`、3 个视图与额外索引；末尾的 `CREATE INDEX IF NOT EXISTS` 是 MySQL 8 的**非法语法** |

> 因此"数据正确"目前主要靠应用层校验，而不是数据库约束；`order_detail.subtotal` 由数据库生成，插入时也不能传。两种方式的完整差异见根 README 第一节的说明与第六节的「已知不一致」。

### 7.3 字段约定

- 所有表都含 `deleted`（逻辑删除）、`create_time`、`update_time`
- 金额字段用 `DECIMAL`：订单 `total_amount` 为 `DECIMAL(12,2)`，单价为 `DECIMAL(10,2)`
- 时间字段用 `DATETIME`；**接口输出的时间格式因类而异**：实体字段（`createTime`/`updateTime`/`orderTime`/`shipTime` 等）固定为 `yyyy-MM-dd HH:mm:ss`（由 `CustomLocalDateTimeSerializer` 覆盖 `@JsonFormat`），而 DTO 字段走 ISO——`InventoryWithPart` 带毫秒（`2026-05-23T14:30:00.000`），`PartWithSupplier`、`OrderDetailWithPartAndSupplier` 不带毫秒（`2026-05-23T14:30:00`）。输入侧由 `CustomLocalDateTimeDeserializer` 宽容解析多种写法（带 `T`、带毫秒、只有分钟等均可）

### 7.4 枚举取值

| 枚举 | 取值 |
|------|------|
| 订单状态 `OrderStatusEnum` | 1 待审核 · 2 已审核 · 3 采购中 · 4 已入库 · 5 已取消 |
| 供应商状态 `SupplierStatusEnum` | 1 合作中 · 2 已终止 · 3 审核中 |
| 客户类型 `CustomerTypeEnum` | 1 经销商 · 2 零售店 · 3 个人用户 |
| 零部件分类 `PartCategoryEnum` | 发动机类 · 车架类 · 电气类 · 制动类 · 传动类 · 外观件 |
| 用户角色 `UserRoleEnum` | admin · purchase · warehouse · sales |
| 结果码 `ResultCode` | 200 成功；400 参数错误、401 未授权、403 禁止访问、404 资源不存在；500 失败/服务器错误；600 业务异常、601 数据已存在、602 数据不存在、603 库存不足、604 订单状态异常、605 供应商状态异常 |

> `ResultCode` 里的 **401 / 403 / 404 / 600 / 604 / 605 没有任何代码路径会产生**：`Result` 有对应方法但无人调用、`BusinessException` 从未实例化；`PATCH /api/orders/update-status/{id}` 不做状态合法性校验，供应商状态变更同理。调用方不要针对这些码写分支。

## 八、项目结构

```
src/main/java/com/motorparts/
├── MotorpartsApplication.java            # 启动类
├── common/                               # 通用返回与序列化
│   ├── Result.java / PageResult.java
│   ├── CustomLocalDateTimeSerializer.java / CustomLocalDateTimeDeserializer.java
│   ├── enums/                            # 6 个枚举：状态、分类、角色、结果码
│   └── exception/                        # BusinessException、GlobalExceptionHandler
├── config/                               # 配置类
│   ├── MyBatisPlusConfig.java            # SqlSessionFactory、事务管理器、字段自动填充
│   ├── WebMvcConfig.java                 # 全局 CORS（allowedOriginPatterns "*" 且允许携带凭据）
│   ├── SwaggerConfig.java                # OpenAPI 元信息
│   └── DdlApplicationRunnerConfig.java   # 占位 ApplicationRunner（名为 ddlApplicationRunner）
├── controller/                           # 7 个控制器，共 54 个端点
├── service/ + service/impl/              # 7 个业务接口与实现
├── mapper/                               # 8 个 MyBatis-Plus Mapper（注解方式，无 XML）
├── entity/                               # 8 张表实体 + BaseEntity + 2 个联表实体
├── dto/                                  # PartWithSupplier、InventoryWithPart、订单明细查询与结果对象
└── init/                                 # 数据初始化
    ├── DatabaseInitializer.java          # 启动时建库建表 + 插入模拟数据
    └── SparkPlugDataInitializer.java     # 独立 main()，经 REST 接口补火花塞数据

src/main/resources/application.yml        # 唯一配置文件（无 static/、无 templates/、无 i18n/）
src/test/java/                            # 空目录，没有测试用例
docs/                                     # 本模块既有文档
ecommerce-demo/                           # 纯静态前端演示页
```

## 九、已知问题与注意事项

1. **无认证授权**：所有接口匿名可写（含创建订单、改库存），不要暴露到公网。
2. **分页可能不生效**：未注册 MyBatis-Plus 分页插件，6 个 `/page` 端点很可能忽略 `size`，见第五节说明。
3. **状态流转无校验**：订单状态、供应商状态可任意跳转，`ResultCode` 604 / 605 形同虚设。
4. **重新初始化不靠 `recreate-tables`**：只有清空 `user` 表才会触发重新插入。
5. **配置含明文口令且已入库**：见 4.2——需改为环境变量注入、轮换口令，并把 `application.yml` 移出版本控制。
6. **`application.yml` 中未被代码读取的配置**：`motorparts.upload.*`、`motorparts.system.*`、`spring.jpa.*`（无 JPA 依赖）、`spring.messages.basename: i18n/messages`（`i18n/` 目录不存在）。
7. **`PUT /orders/update/{id}` 会更换订单主键且明细失联**：它是"物理删除 + 重新插入"，`PurchaseOrder.id` 为 `IdType.AUTO` 因而拿到新的自增 id，而明细仍按**旧 id** 写入 → 明细成为孤儿行；同时多个写接口只回显请求体（未传字段返回 `null`，不代表被清空）。细节见 [docs/API_DOCUMENTATION.md](docs/API_DOCUMENTATION.md) §1.2 与「写接口的响应回显」。

## 十、文档与许可

本模块文档：

- [docs/API_DOCUMENTATION.md](docs/API_DOCUMENTATION.md) — 逐端点的请求/响应示例（已按代码核实并对齐）
- [docs/database_schema.sql](docs/database_schema.sql) — 手工建表脚本（注意 7.2 的差异说明）
- [docs/数据来源说明.txt](docs/数据来源说明.txt) — 模拟数据来源与免责声明

仓库级文档（位于根目录 `docs/`）：

- [ARCHITECTURE.md](../docs/ARCHITECTURE.md) · [SETUP_AND_DEPLOYMENT.md](../docs/SETUP_AND_DEPLOYMENT.md) · [API_REFERENCE.md](../docs/API_REFERENCE.md) · [DATABASE.md](../docs/DATABASE.md) · [AI_AGENT.md](../docs/AI_AGENT.md) · [FRONTEND.md](../docs/FRONTEND.md) · [DEVELOPMENT_GUIDE.md](../docs/DEVELOPMENT_GUIDE.md)
- 仓库总览、安全须知与已知不一致清单：[根 README](../README.md)

**许可**：本项目仅供学习和参考使用。模拟数据中的企业名称仅作示例，不代表真实商业关系（见 [数据来源说明](docs/数据来源说明.txt)）。

## 关于 ecommerce-demo

仅用于展示大致前端（用于为后续前端开发提供参考），**不对接任何后端业务与数据库**。页脚中的 `d:\idea_space\MotorcyclePartsProcurementSystem\ecommerce-demo\` 是来自另一台机器的陈旧路径，不是本仓库的位置。
