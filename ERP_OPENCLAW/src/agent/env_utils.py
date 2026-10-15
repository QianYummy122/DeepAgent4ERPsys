"""
统一环境配置模块。

所有可外部化的配置（模型密钥、MongoDB、沙箱、MCP 地址）都从这里读取，
.env 文件位于项目根目录（ERP_OPENCLAW/.env），不存在时回退到系统环境变量。

设计原则：
1. 任何硬编码的地址/凭据都可以被环境变量覆盖；
2. 每一项都有可用的默认值，保证在最小配置下也能启动；
3. 不打印任何密钥明文。
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------
# 项目根目录（ERP_OPENCLAW/）
# ---------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

# 显式指定 .env 路径，避免因启动目录不同而加载失败
load_dotenv(dotenv_path=ENV_FILE, override=True)


def _get(name: str, default: str | None = None) -> str | None:
    """读取环境变量，空字符串视作未设置。"""
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def _get_bool(name: str, default: bool = False) -> bool:
    """读取布尔型环境变量，接受 1/true/yes/on（大小写不敏感）。"""
    value = _get(name)
    if value is None:
        return default
    return value.lower() in ("1", "true", "yes", "on", "y")


# ===============================================================
# 大模型（LLM）
# ===============================================================
OPENAI_API_KEY = _get("OPENAI_API_KEY")
DEEPSEEK_API_KEY = _get("DEEPSEEK_API_KEY")
ZHIPU_API_KEY = _get("ZHIPU_API_KEY")
MINIMAX_API_KEY = _get("MINIMAX_API_KEY")
ALIBABA_API_KEY = _get("ALIBABA_API_KEY")
K2_API_KEY = _get("K2_API_KEY")

K2_BASE_URL = _get("K2_BASE_URL")
ALIBABA_BASE_URL = _get("ALIBABA_BASE_URL")
MINIMAX_BASE_URL = _get("MINIMAX_BASE_URL")
OPENAI_BASE_URL = _get("OPENAI_BASE_URL")
DEEPSEEK_BASE_URL = _get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
ZHIPU_BASE_URL = _get("ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")

LOCAL_BASE_URL = _get("LOCAL_BASE_URL")
DAYTONA_API_KEY = _get("DAYTONA_API_KEY")
DAYTONA_BASE_URL = _get("DAYTONA_BASE_URL")

# 模型名称（可替换为任何 OpenAI 兼容模型）
MAIN_MODEL_NAME = _get("MAIN_MODEL_NAME", "deepseek-chat")
SUMMARY_MODEL_NAME = _get("SUMMARY_MODEL_NAME", "deepseek-chat")

# ===============================================================
# MongoDB（会话检查点 + 会话历史展示）
# ===============================================================
MONGODB_URI = _get("MONGODB_URI", "mongodb://127.0.0.1:27017/")
MONGODB_DB_NAME = _get("MONGODB_DB_NAME", "langchain_db")
MONGODB_CHECKPOINT_COLLECTION = _get("MONGODB_CHECKPOINT_COLLECTION", "checkpoints")

# ===============================================================
# 沙箱（代码执行环境）
# ===============================================================
# SANDBOX_MODE:
#   opensandbox —— 连接独立部署的 OpenSandbox 服务（需要自行部署，见文档）
#   local       —— 使用本机 WSL 发行版作为 Linux 沙箱（Windows 免部署方案）
#   none        —— 不使用代码执行沙箱，仅保留文件/记忆能力
SANDBOX_MODE = (_get("SANDBOX_MODE", "local") or "local").lower()

# OpenSandbox 服务地址（SANDBOX_MODE=opensandbox 时生效）
OPENSANDBOX_DOMAIN = _get("OPENSANDBOX_DOMAIN", "http://127.0.0.1:8080")
OPENSANDBOX_IMAGE = _get(
    "OPENSANDBOX_IMAGE",
    "sandbox-registry.cn-zhangjiakou.cr.aliyuncs.com/opensandbox/code-interpreter:v1.0.2",
)

# 本地 WSL 沙箱配置（SANDBOX_MODE=local 时生效）
WSL_DISTRO = _get("WSL_DISTRO", "Ubuntu-20.04")
WSL_USER = _get("WSL_USER", "root")
# 是否在沙箱内创建 /opt/skills-venv 并预装分析用 Python 包（首次启动较慢）
SANDBOX_SETUP_VENV = _get_bool("SANDBOX_SETUP_VENV", True)
# 沙箱内预装包使用的 PyPI 镜像
SANDBOX_PYPI_INDEX = _get("SANDBOX_PYPI_INDEX", "https://pypi.tuna.tsinghua.edu.cn/simple")

# ===============================================================
# MCP 服务地址
# ===============================================================
# 本地 ERP MCP 桥接服务（把 Java REST 封装成 MCP 工具）
ERP_MCP_URL = _get("ERP_MCP_URL", "http://127.0.0.1:8000/mcp")
# 远程可视化 MCP 服务（26 个图表工具，来自 ModelScope）
ANALYSIS_MCP_URL = _get(
    "ANALYSIS_MCP_URL",
    "https://mcp.api-inference.modelscope.net/af3893df5be041/mcp",
)

# ===============================================================
# Java ERP 后端
# ===============================================================
JAVA_API_BASE_URL = _get("JAVA_API_BASE_URL", "http://localhost:8080/api")

# ===============================================================
# 其它
# ===============================================================
APP_ENV = _get("APP_ENV", "development")
