# 安装与部署

本文覆盖从零把 AgentToMotorcycleERP 跑起来所需的全部步骤：环境依赖、四个服务的启动顺序、每个配置项的含义、两种沙箱模式的选择与部署、以及故障排查。

架构与设计理由见 [ARCHITECTURE.md](ARCHITECTURE.md)。接口契约见 [API_REFERENCE.md](API_REFERENCE.md)。

---

## 1. 需要启动的东西

系统由 **4 个进程 + 2 个外部服务**组成，存在严格的依赖方向：

```
① MySQL            :3306    ERP 后端的数据库          （外部服务）
② Java ERP 后端     :8080    首次启动自建库表 + 种子数据
③ MCP 桥接          :8000    把 ② 的 REST 封装为 MCP 工具
④ MongoDB          :27017   AI 后端的对话持久化        （外部服务）
⑤ AI 助手后端       :8090    依赖 ③ 与 ④，并创建沙箱
⑥ Vue 前端          :3000    代理 /api 到 ⑤
                          （可选）WSL2 发行版或 OpenSandbox 服务 = 沙箱执行环境
```

**必须按 ①②③④⑤⑥ 的顺序启动。** ⑤ 启动时会连接 ③ 与 ④，③ 在工具被调用时才真正访问 ②，但为了快速定位问题建议全部先起好。

> ⑤ 的 Agent 初始化需要 **30–60 秒**（创建沙箱、播种技能、建 Python venv 并预装 5 个包）。首次运行更慢（venv 安装 + pip 下载）。这不是卡死。

---

## 2. 环境要求

### 2.1 版本要求

| 组件 | 版本 | 出处 |
|------|------|------|
| JDK | **17**（必须） | `pom.xml`：`<java.version>17</java.version>`；代码使用 `jakarta.*` 导入，**JDK 8 无法编译** |
| Maven | 3.6+ | 构建 |
| MySQL | **8.0+** | `mysql-connector-j 8.0.33`；DDL 使用 `utf8mb4_0900_ai_ci` 排序规则（MySQL 8 专属） |
| MongoDB | 5.0+ | `langgraph-checkpoint-mongodb` |
| Python | **3.10+** | `pyproject.toml`：`requires-python = ">=3.10"`；代码使用 `X \| None` 注解（PEP 604，3.10 起可用），实际开发环境为 3.14 |
| Node.js | **18+** | Vite 5 要求 |
| WSL2 + 一个发行版 | 默认 `Ubuntu-20.04` | 仅 `SANDBOX_MODE=local` 时需要 |

> ✅ 子项目的 [MotorcyclePartsProcurementSystem/README.md](../MotorcyclePartsProcurementSystem/README.md) 已按 `pom.xml` 核实：**JDK 17 + Spring Boot 3.1.10**（该 README 早期版本曾写 "JDK 1.8+ / Spring Boot 2.7.18"，现已更正，以 `pom.xml` 为准）。

### 2.2 检查清单

```powershell
java -version          # 期望 17.x
mvn -v
node -v                # 期望 v18+
python --version       # 期望 3.10+
mysql --version        # 期望 8.0+
mongod --version
wsl -l -v              # 仅 local 沙箱模式需要
```

---

## 3. 外部服务准备

### 3.1 MySQL

无需手动建库——`DatabaseInitializer` 启动时会执行 `CREATE DATABASE IF NOT EXISTS motorparts_db`。但账号需要有 **CREATE 权限**。

```sql
-- 验证（启动后执行）
USE motorparts_db;
SHOW TABLES;            -- 期望 8 张表
SELECT COUNT(*) FROM part;      -- 期望 64
SELECT COUNT(*) FROM supplier;  -- 期望 30
```

**关于建表方式的取舍**（重要，详见 [DATABASE.md](DATABASE.md) §1.6）：

| 做法 | 结果 |
|------|------|
| **A. 只启动应用**（省事） | 表能工作，但**没有外键、没有 `uk_order_part`、没有视图、只有 11 个二级索引/唯一键** |
| **B. 先手动执行 `docs/database_schema.sql`** | 得到完整约束与视图，**但它会插入 4 个种子用户，导致应用启动时 `insertSampleData()` 因 `COUNT(*) FROM user > 0` 而整体跳过** → 你会得到"空表 + 4 用户"的库 |
| **C. 推荐** | 先让应用建表并播种（做法 A）→ 再手动补执行 `database_schema.sql` 中**除末尾 `INSERT INTO user` 之外**的部分。注意其中 `CREATE INDEX IF NOT EXISTS` 在 MySQL 8 上是**非法语法**，需改写为 `CREATE INDEX` 或 `ALTER TABLE ... ADD INDEX` |

### 3.2 MongoDB

```powershell
# Windows 服务方式
Get-Service MongoDB | Start-Service

# 或手动启动
mongod --dbpath "C:\data\db"
```

验证：`mongosh --eval "db.runCommand({ping:1})"`

AI 后端会用两个集合：
- `langchain_db.checkpoints` — LangGraph 检查点（HITL 中断状态、跨重启续聊）
- `langchain_db.session_display_messages` — 展示消息（含子 Agent 消息）

`agent/config.py` 的 `MongoClient` 设置了 5 秒超时，MongoDB 未启动时**5 秒内即报错**，便于定位。可用 `agent.config.check_mongodb()` 主动探测（`src/test/verify_agent_build.py` 第一步就会调用它）。

### 3.3 WSL2（仅 `SANDBOX_MODE=local`）

```powershell
wsl --install -d Ubuntu-20.04     # 若尚未安装
wsl -l -v                         # 确认发行版名称与 .env 中的 WSL_DISTRO 一致
wsl -d Ubuntu-20.04 -- python3 --version
```

沙箱内会在**首次启动时**创建 `/opt/skills-venv` 并 `pip install` numpy、pandas、matplotlib、requests、beautifulsoup4。这一步可能需要几分钟，取决于网络。若使用代理或内网，可通过 `SANDBOX_PYPI_INDEX` 换镜像源。

> **安全提示**：`LocalWslSandboxBackend` 默认以 `WSL_USER=root` 在**本机**执行任意命令（`wsl -d <distro> -u root -- bash -lc "<cmd>"`）。这是为了免部署而做的取舍，**仅适合个人开发环境**。生产请用 OpenSandbox。

---

## 4. 启动步骤

### 4.1 步骤 ①：MySQL（见 §3.1）

### 4.2 步骤 ②：Java ERP 后端

```powershell
cd MotorcyclePartsProcurementSystem
mvn clean compile
mvn spring-boot:run
```

首次启动会依次输出：

```
HikariPool-1 - Start completed.
数据库 motorparts_db 创建成功或已存在
已切换到数据库 motorparts_db
所有数据表创建成功
开始插入模拟数据...
用户数据插入完成 / 供应商数据插入完成 / 产品数据插入完成 / ...
========== 数据库初始化完成 ==========
Tomcat started on port(s): 8080 (http) with context path ''
```

验证：

```powershell
curl.exe "http://localhost:8080/api/parts/page?current=1&size=3"
curl.exe "http://localhost:8080/api/statistics/dashboard"
# Swagger UI：http://localhost:8080/swagger-ui/index.html
# OpenAPI JSON：http://localhost:8080/v3/api-docs
```

> ⚠️ **Swagger 地址**：`pom.xml` 用的是 springdoc-openapi **2.0.2**，UI 在 `/swagger-ui/index.html`（`/swagger-ui.html` 是 springdoc 1.x 的路径，2.x 会重定向，但直接访问新路径更可靠）。

### 4.3 步骤 ③：MCP 桥接

```powershell
cd ERP_OPENCLAW
copy .env.example .env      # 首次
$env:PYTHONPATH = "$PWD\src"
python -m mcp_server.server_main
```

启动后监听 `http://127.0.0.1:8000/mcp`（streamable-http）。

> **`PYTHONPATH` 是必须的**：代码用 `from mcp_server.server_config import ...` 这类顶层包名导入，而源码在 `src/` 下。`start_web.py` 会自动注入，手动启动时必须自己设。

验证：

```powershell
python src/test/verify_mcp_bridge.py     # 逐个调用只读工具并打印回传摘要
```

### 4.4 步骤 ④：MongoDB（见 §3.2）

### 4.5 步骤 ⑤ + ⑥：AI 助手 + 前端

**方式一：一键启动（推荐首次）**

```powershell
cd ERP_OPENCLAW
python start_web.py
```

它会：
1. 用 `uvicorn --reload` 在 **8090** 启动后端（自动注入 `PYTHONPATH=src`）；
2. 轮询 `http://localhost:8090/health` 直到返回 `healthy`（**最长等 180 秒**，覆盖 Agent 初始化时间）；
3. 后端就绪后以 `npm run dev` 启动前端（缺少 `node_modules` 时自动 `npm install`）；
4. 打印访问地址，按 Ctrl+C 一起停止。

**方式二：分开启动（推荐调试）**

```powershell
# 终端 A — 后端（热重载）
cd ERP_OPENCLAW
$env:PYTHONPATH = "$PWD\src"
uvicorn api_view.web_main:app --reload --host 0.0.0.0 --port 8090

# 终端 B — 前端（热重载）
cd ERP_OPENCLAW\frontend
npm install        # 首次
npm run dev
```

验证：

```powershell
curl.exe http://localhost:8090/health
curl.exe http://localhost:8090/api/history
```

浏览器打开 **http://localhost:3000** 开始对话。

---

## 5. 配置项全量说明

### 5.1 AI 助手后端（`ERP_OPENCLAW/.env`）

配置由 `src/agent/env_utils.py` 统一读取。`.env` 路径**显式指定**为项目根目录（不依赖启动目录），且 `override=True`（`.env` 优先于系统环境变量）。所有项都有可用默认值，最小配置下也能启动。

#### 5.1.1 大模型

| 变量 | 默认值 | 必填 | 说明 |
|------|--------|------|------|
| `DEEPSEEK_API_KEY` | 无 | **是**（否则模型不可用） | 主模型与摘要模型的密钥；代码兜底为 `"not-configured"` 字符串以避免启动即崩 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com/v1` | 否 | OpenAI 兼容接口地址，可指向任何兼容服务（智谱/通义/本地 vLLM 等） |
| `MAIN_MODEL_NAME` | `deepseek-chat` | 否 | 主 Agent 与子 Agent 默认模型 |
| `SUMMARY_MODEL_NAME` | `deepseek-chat` | 否 | 摘要与实体抽取用模型（建议用更便宜的） |
| `ZHIPU_API_KEY` | 无 | 否 | `web_search` 工具所需；**未配置时不影响启动**，仅调用该工具时报可读错误 |
| `ZHIPU_BASE_URL` | `https://open.bigmodel.cn/api/paas/v4` | 否 | 智谱接口地址；`FALLBACK_MODEL`（`glm-4-plus`）仅在此 Key 存在时才构造 |

模型参数（不可通过环境变量调整，需改 `src/agent/config.py`）：主模型 `temperature=1.1`、摘要模型 `0.3`、均 `max_tokens=8192`、均带 `extra_body={"thinking":{"type":"disabled"}}`。

#### 5.1.2 MongoDB

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MONGODB_URI` | `mongodb://127.0.0.1:27017/` | 连接串 |
| `MONGODB_DB_NAME` | `langchain_db` | 库名 |
| `MONGODB_CHECKPOINT_COLLECTION` | `checkpoints` | 检查点集合名 |

> `agent/config.py` 与 `api_view/web_config.py` **共用同一份配置**（后者从前者导入），避免了"checkpointer 写一个库、历史接口读另一个库"的不一致。

#### 5.1.3 沙箱

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SANDBOX_MODE` | `local` | `local`（本机 WSL）/ `opensandbox`（独立服务）。**其他值会抛 `ValueError`** |
| `WSL_DISTRO` | `Ubuntu-20.04` | `local` 模式的发行版名，须与 `wsl -l -v` 一致 |
| `WSL_USER` | `root` | `local` 模式执行用户 |
| `SANDBOX_SETUP_VENV` | `1` | 是否创建 `/opt/skills-venv` 并预装包；`0` 跳过（离线环境/不需要 Python 分析时） |
| `SANDBOX_PYPI_INDEX` | `https://pypi.tuna.tsinghua.edu.cn/simple` | venv 预装用的 PyPI 镜像 |
| `OPENSANDBOX_DOMAIN` | `http://127.0.0.1:8080` | 仅 `opensandbox` 模式 |
| `OPENSANDBOX_IMAGE` | `sandbox-registry.cn-zhangjiakou.cr.aliyuncs.com/opensandbox/code-interpreter:v1.0.2` | 仅 `opensandbox` 模式 |

> ⚠️ **注意端口冲突**：`OPENSANDBOX_DOMAIN` 默认是 `:8080`，与 Java ERP 后端**同端口**。若在同一台机器上同时跑 Java 后端和 OpenSandbox 服务，必须改其中一个（建议改 OpenSandbox 的监听端口，或把 `OPENSANDBOX_DOMAIN` 指向另一台机器）。

#### 5.1.4 MCP 服务地址

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ERP_MCP_URL` | `http://127.0.0.1:8000/mcp` | 本地 ERP 桥接；**必须可达**，否则 Agent 启动失败 |
| `ANALYSIS_MCP_URL` | `https://mcp.api-inference.modelscope.net/af3893df5be041/mcp` | 远程可视化 MCP（26 种图表 + 1 个电子表格工具，共 27 个 `generate_*`）；**不可达时仅告警降级**，不阻塞启动。置空则该键被跳过 |

#### 5.1.5 Java 后端地址与其它

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `JAVA_API_BASE_URL` | `http://localhost:8080/api` | MCP 桥接转发目标；`mcp_server/server_config.py` 读取 |
| `APP_ENV` | `development` | `production` 时日志写入 `erp_agent.log` 文件，否则输出到 stdout（且级别为 ERROR） |

#### 5.1.6 MCP 桥接自身的监听配置

由 `mcp_server/server_config.py` 读取（同样有默认值）：

| 变量 | 默认值 |
|------|--------|
| `MCP_HOST` | `127.0.0.1` |
| `MCP_PORT` | `8000` |
| `MCP_PATH` | `/mcp` |

#### 5.1.7 未被使用但已声明的变量

`env_utils.py` 还声明了 `OPENAI_API_KEY`、`MINIMAX_API_KEY`、`ALIBABA_API_KEY`、`K2_API_KEY`、`K2_BASE_URL`、`ALIBABA_BASE_URL`、`MINIMAX_BASE_URL`、`OPENAI_BASE_URL`、`LOCAL_BASE_URL`、`DAYTONA_API_KEY`、`DAYTONA_BASE_URL`。这些在当前代码路径中**没有被任何模块引用**——属于多模型/多云切换留下的扩展位。可以留空。

### 5.2 Java 后端（`application.yml`）

| 配置 | 当前值 | 说明 |
|------|--------|------|
| `server.port` | `8080` | 实际 context path 为空（`server.servlet.context-path: /`） |
| `spring.datasource.url` | `jdbc:mysql://localhost:3306/motorparts_db?...&serverTimezone=Asia/Shanghai&useSSL=false&allowPublicKeyRetrieval=true` | 库名 `motorparts_db` |
| `spring.datasource.username` / `password` | `root` / **明文口令已提交到仓库** | ⚠️ 部署前改为环境变量注入并轮换该口令 |
| `spring.datasource.hikari.*` | `maximum-pool-size: 20`、`minimum-idle: 5`、`connection-timeout: 30000`、`idle-timeout: 600000`、`max-lifetime: 1800000`、`connection-test-query: SELECT 1` | 连接池 |
| `spring.autoconfigure.exclude` | `...MybatisPlusAutoConfiguration` | ⚠️ 与手写的 `MybatisSqlSessionFactoryBean` 配合；副作用是**分页插件不会自动注册**、`mybatis-plus.*` 配置全部失效（见 [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) §7.1 #5） |
| `spring.jackson.*` | `date-format: yyyy-MM-dd HH:mm:ss`、`time-zone: UTC`、`write-dates-as-timestamps: false`、`fail-on-unknown-properties: false` | 对 `LocalDateTime` 无实际影响（它们由自定义序列化器处理）；`time-zone` 只影响 zoned 类型 |
| `logging.level.com.motorparts` | `debug` | 日志里的 SQL 来自这个 logger，**不是** `log-impl: StdOutImpl` |
| `logging.file.name` | `logs/motorparts.log` | 滚动策略 10 MB / 保留 30 个 |
| `motorparts.init.enabled` | `true` | `false` 则完全跳过建库建表插数据 |
| `motorparts.init.insert-sample-data` | `true` | `false` 则只建表不插数据 |
| `motorparts.init.recreate-tables` | `false` | ⚠️ **代码从未读取该配置项，设置无效** |
| `motorparts.upload.*` | `./uploads/`、`10MB` | ⚠️ 无人读取（无上传接口） |
| `motorparts.system.*` | name/version/copyright | ⚠️ 无人读取 |
| `spring.jpa.*` | `ddl-auto: none`、`show-sql: false` | ⚠️ 项目没有 JPA 依赖，完全惰性 |
| `spring.messages.basename` | `i18n/messages` | ⚠️ `src/main/resources/i18n/` 目录不存在 |

**改用环境变量覆盖数据库凭据**（推荐）：

```yaml
spring:
  datasource:
    url: ${DB_URL:jdbc:mysql://localhost:3306/motorparts_db?useUnicode=true&characterEncoding=utf8&serverTimezone=Asia/Shanghai&useSSL=false&allowPublicKeyRetrieval=true}
    username: ${DB_USERNAME:root}
    password: ${DB_PASSWORD}
```

### 5.3 前端（`frontend/vite.config.js`）

| 配置 | 值 | 说明 |
|------|-----|------|
| `server.host` | `127.0.0.1` | 显式绑定 IPv4 回环。Vite 默认只监听 `localhost`，Windows 上常解析为 `::1`，导致 `http://127.0.0.1:3000` 无法访问（脚本探测会误判为"未启动"）。改 `0.0.0.0` 可让局域网访问，但会暴露服务 |
| `server.port` | `3000` | |
| `server.strictPort` | `true` | 端口被占用时直接报错，不静默切到 3001（否则文档里的地址失效） |
| `server.proxy['/api'].target` | `http://localhost:8090` | 前端代码统一用相对路径 `/api`，无 rewrite（后端路由已带 `/api` 前缀） |
| `build.outDir` | `dist` | |

---

## 6. 沙箱部署详解

### 6.1 模式选择

| | `SANDBOX_MODE=local` | `SANDBOX_MODE=opensandbox` |
|---|---|---|
| 前置条件 | Windows + WSL2 + 一个发行版 | 自行部署 OpenSandbox 服务 |
| 部署成本 | 零 | 需要额外服务与容器运行时 |
| 隔离性 | 弱（root 在宿主机 WSL 内执行任意命令） | 强（容器隔离） |
| 资源限制 | 无 | `cpu=2`、`memory=4Gi`、`timeout=2h` |
| 网络策略 | 无 | 可通过 `network_policy` 限制出网 |
| 适用 | 个人开发、演示、离线环境 | 生产、多租户 |

两种模式实现同一套 `BaseSandbox` 协议（`execute` / `upload_files` / `download_files` / `id`），因此上层的中间件与工具完全无感，可随时切换。

### 6.2 `local` 模式的沙箱内布局

首次启动 `setup_sandbox()` 会执行：

```
mkdir -p /analysis/temp /data /skills           # 预建目录
上传 src/skills/** → /skills/**                  # 内容比对，未变则跳过
python3 -m venv /opt/skills-venv                 # 幂等：已存在则跳过
/opt/skills-venv/bin/pip install --upgrade pip   # 清华镜像
预装 numpy pandas matplotlib requests beautifulsoup4
```

**venv 的 sentinel 机制**：每个包在 `/opt/skills-venv/.installed/{pkg}` 放哨兵文件。哨兵存在 → 跳过；哨兵缺失但 `pip show {pkg}` 成功 → 直接补哨兵、跳过联网。哨兵刻意放在 venv 内部而**不是** `/tmp`——WSL 重启会清空 `/tmp`，放那里会导致每次冷启动都重跑一遍 pip 解析。

PATH 被注入 `/opt/skills-venv/bin`（在最前），因此沙箱内 `python` / `pip` 命令自动路由到 venv，脚本无需写绝对路径。

**沙箱内路径约定**：

| 路径 | 用途 |
|------|------|
| `/AGENTS.md` | 全局行为准则（每次启动重传，Agent 只读） |
| `/skills/{scope}/` | 技能包（`main` / `procurement` / `order`） |
| `/analysis/` | 分析产物，报告写 `/analysis/report_{timestamp}.md` |
| `/analysis/temp/` | 网页抓取的中间 Markdown |
| `/data/` | 分析数据文件与图表 |
| `/opt/skills-venv/` | Python 虚拟环境 |
| `/memories/{user_id}/` | 用户偏好 —— **经 CompositeBackend 路由到 Store，不在沙箱磁盘上** |
| `/persisted-skills/` | 持久化技能 —— **同样路由到 Store** |

### 6.3 `opensandbox` 模式

需要：
1. 部署 OpenSandbox 服务（见 [OpenSandbox 官方文档](https://github.com/alibaba/OpenSandbox)）；
2. 把 `OPENSANDBOX_DOMAIN` 指向该服务（**注意默认 8080 与 Java 后端冲突**）；
3. 按需更换 `OPENSANDBOX_IMAGE`。

创建沙箱时的参数（`sandbox_setup._create_opensandbox`）：

```python
SandboxSync.create(
    image, entrypoint=["/opt/opensandbox/code-interpreter.sh"],
    env={"PYTHON_VERSION": "3.11"},
    resource={"cpu": "2", "memory": "4Gi"},
    timeout=timedelta(hours=2),
    connection_config=config,
    # network_policy=NetworkPolicy(defaultAction="deny", egress=[...])   ← 已注释，默认放行
)
```

> **网络策略代码处于注释状态**（默认允许全部出网）。生产部署建议启用 `defaultAction="deny"` 并只放行必要域名（`pypi.org`、`*.github.com` 等）。

`ConnectionConfigSync` 设置：`request_timeout=60s`、`max_connections=20`、`use_server_proxy=True`。

失败回退：若传入的 `sandbox_id` 连接失败，会打印 warning 并**自动创建新沙箱**。

---

## 7. 启动后验证

按层次从底向上验证（顺序与 [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) §4 一致）：

```powershell
cd ERP_OPENCLAW
$env:PYTHONPATH = "$PWD\src"

# 1) 沙箱（最底层）
python src/test/verify_local_sandbox.py

# 2) 沙箱初始化全流程（首次 venv 安装慢，建议单独跑观察进度）
python src/test/setup_sandbox_only.py

# 3) MCP 桥接（只读工具）
python src/test/verify_mcp_bridge.py

# 4) Agent 构建（不调用大模型）
python src/test/verify_agent_build.py

# 5) 端到端（会调用大模型，最慢）
python src/test/agent_test.py
```

另有两个专门脚本：`verify_mcp_write.py`（`order_create`/`order_update` 完整链路，**会写数据**）与 `test_all_tools.py`（全量工具测试，`python -m test.test_all_tools`）。

浏览器端验证：
1. 打开 http://localhost:3000；
2. 发"你好"确认基础对话通；
3. 发"对比一下博世和电装的刹车片价格"确认委派、工具调用、图表与报告链路通；
4. 发"帮我下一单"确认数据补充中断与审批中断的 UI 正常。

---

## 8. 生产部署注意事项

| 项 | 建议 |
|----|------|
| 沙箱模式 | 必须用 `SANDBOX_MODE=opensandbox`，并启用容器网络策略 |
| 认证 | ERP 后端**当前无任何认证/授权**。生产必须在网关层加鉴权，勿直接暴露 8080 |
| 数据库凭据 | 从 `application.yml` 移出，改环境变量或密钥管理服务；**轮换已泄漏的口令** |
| 长期记忆 | `STORE = InMemoryStore()` 导致用户偏好与持久化技能重启即丢。改为 `PostgresStore` / `RedisStore` |
| 多用户 | `api/chat.py` 硬编码 `user_id="yummyQian"`，需从请求体透传（见 [AI_AGENT.md](AI_AGENT.md) §10.3） |
| 前端构建 | `npm run build` 产出 `dist/`，用 Nginx 等托管；同时把 `/api` 反向代理到 8090 |
| CORS | FastAPI 侧 `allow_origins=["*"]` 且 `allow_credentials=True`；Java 侧 `allowedOriginPatterns("*")` + `allowCredentials(true)`。生产都要收窄到具体域名 |
| 日志 | AI 侧大量 `print` 而非 `logging`；`chat.py` 的调试日志写入 `%TEMP%/deepagent_debug/` 且无清理机制 |
| 数据库建表 | 明确选择做法 A/B/C（见 §3.1），不要混用 |
| 密钥 | `ERP_OPENCLAW/.env` 含真实模型 Key；确认它不在版本控制中 |

---

## 9. 故障排查

### 9.1 按启动阶段

| 阶段 | 现象 | 原因与处置 |
|------|------|-----------|
| ② Java | `Communications link failure` | MySQL 未启动或端口不对 |
| ② Java | `Access denied for user` | 账号口令不符（注意 `application.yml` 里的口令是仓库中的值） |
| ② Java | `Unknown collation: utf8mb4_0900_ai_ci` | MySQL 版本低于 8.0 |
| ② Java | 表建好了但没有数据 | `user` 表已有行（可能来自 `database_schema.sql`）→ `insertSampleData()` 短路。清空或 drop 库后重启 |
| ③ MCP | `ModuleNotFoundError: No module named 'mcp_server'` | 未设置 `PYTHONPATH=src` |
| ③ MCP | 端口占用 | 改 `.env` 的 `MCP_PORT`，同时改 `ERP_MCP_URL` |
| ⑤ AI | `无法连接 ERP MCP 桥接服务（...）` | ③ 未启动，或 ② 未启动。错误消息里已列出两步检查清单 |
| ⑤ AI | `沙箱配置失败，无法创建 Agent` | `wsl -l -v` 确认发行版名与 `WSL_DISTRO` 一致；或 OpenSandbox 不可达 |
| ⑤ AI | `MongoDB 连接失败` | 启动 MongoDB，或改 `MONGODB_URI` |
| ⑤ AI | 启动很久没反应 | **正常**——Agent 初始化 30–60 秒，首次 venv 安装更久 |
| ⑤ AI | 可视化 MCP 告警但服务起来了 | **预期行为**——图表能力降级，其余正常 |
| ⑥ 前端 | `http://127.0.0.1:3000` 打不开但 `localhost:3000` 可以 | `vite.config.js` 已绑 `127.0.0.1`，若仍异常检查是否有其他进程占用 3000（`strictPort` 会直接报错） |
| ⑥ 前端 | 接口 404 / CORS 报错 | Vite 代理指向 8090，确认后端在该端口；或直接用 `start_web.py` 启动 |

### 9.2 按功能现象

| 现象 | 排查 |
|------|------|
| 对话无响应、界面一直转圈 | 看 `%TEMP%\deepagent_debug\stream_*.log` 的 `STREAM_START` 与 `RAW_CHUNK` |
| 工具返回 `API error: code=...` | 绕过 MCP 直接用 `curl` 打同一个 Java 接口，确认是接口问题还是桥接问题 |
| 界面出现用户没问过的文字 | `chat.py` 的 `SystemMessage` 过滤失效（中间件注入的上下文泄漏了） |
| 刷新后看不到子 Agent 的过程 | 检查 `SAVE_DISPLAY` 日志与 `session_display_messages` 集合 |
| 分页返回的行数远超 `size` | 未注册分页插件（见 [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) §7.1 #5） |
| 订单更新后字段变空 / ID 变了 | `PUT /orders/update/{id}` 是物理删除 + 重新插入，必须走 `order_update` 工具（读-合并-写） |
| 出图失败但文字正常 | `ANALYSIS_MCP_URL` 不可达，属预期降级 |

### 9.3 常用诊断命令

```powershell
# 端口占用
Get-NetTCPConnection -LocalPort 8080,8000,8090,3000 -ErrorAction SilentlyContinue |
    Select-Object LocalPort, State, OwningProcess

# 健康检查
curl.exe http://localhost:8080/api/statistics/dashboard
curl.exe http://localhost:8090/health

# 数据库
mysql -uroot -p -e "USE motorparts_db; SELECT COUNT(*) FROM part; SELECT COUNT(*) FROM purchase_order;"

# MongoDB
mongosh --eval "db.getSiblingDB('langchain_db').checkpoints.countDocuments()"
mongosh --eval "db.getSiblingDB('langchain_db').session_display_messages.countDocuments()"

# WSL
wsl -l -v
wsl -d Ubuntu-20.04 -- ls -la /skills/
wsl -d Ubuntu-20.04 -- /opt/skills-venv/bin/pip list
```

---

## 10. 停止与清理

```powershell
# 一键启动的直接 Ctrl+C 即可（start_web.py 注册了信号处理，会 terminate 两个子进程）

# 单独启动的各自 Ctrl+C

# 强制清理端口占用
Get-NetTCPConnection -LocalPort 8090 -State Listen |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

清理沙箱内的分析产物：

```powershell
wsl -d Ubuntu-20.04 -- rm -rf /analysis /data
```

清理对话数据（**不可恢复**）：

```javascript
use langchain_db
db.checkpoints.deleteMany({})
db.session_display_messages.deleteMany({})
```

清理 Java 调试日志与临时目录：

```powershell
Remove-Item "MotorcyclePartsProcurementSystem\logs\*.gz"
Remove-Item "$env:TEMP\deepagent_debug\*" -Recurse -Force
```

---

## 相关文档

- [ARCHITECTURE.md](ARCHITECTURE.md) — 架构与设计决策
- [API_REFERENCE.md](API_REFERENCE.md) — 接口契约与 MCP 工具清单
- [DATABASE.md](DATABASE.md) — 表结构、建表方式取舍、运维 SQL
- [AI_AGENT.md](AI_AGENT.md) — Agent 机制、环境变量如何被使用
- [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) — 验证脚本清单、调试技巧、技术债
