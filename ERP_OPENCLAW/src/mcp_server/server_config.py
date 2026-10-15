import os
from pathlib import Path

from dotenv import load_dotenv

# 显式加载项目根目录下的 .env，避免因启动目录不同而读取失败
_ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=_ENV_FILE, override=True)


def _get(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


# Java 后端 API 地址（可通过 .env 的 JAVA_API_BASE_URL 覆盖）
JAVA_API_BASE_URL = _get("JAVA_API_BASE_URL", "http://localhost:8080/api")

# MCP 服务监听配置
MCP_HOST = _get("MCP_HOST", "127.0.0.1")
MCP_PORT = int(_get("MCP_PORT", "8000"))
MCP_PATH = _get("MCP_PATH", "/mcp")
