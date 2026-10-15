"""
后端配置文件

包含 MongoDB 连接配置、项目路径等
"""

from pathlib import Path

# ============================================================
# MongoDB 配置 - 用于存储 Agent 的短期记忆（checkpoint）
# ============================================================
# 统一从 agent.env_utils 读取，确保与 config.py 使用完全相同的连接串，
# 避免「checkpointer 写一个库、历史接口读另一个库」的不一致。
from agent.env_utils import (
    MONGODB_CHECKPOINT_COLLECTION,
    MONGODB_DB_NAME,
    MONGODB_URI,
)

# ============================================================
# 项目路径配置
# ============================================================
# 项目根目录（ERP_OPENCLAW/）
PROJECT_DIR = Path(__file__).parent.parent.parent

# src 目录
SRC_DIR = PROJECT_DIR / "src"

# Agent 相关代码路径
AGENT_DIR = SRC_DIR / "agent"
# 技能目录（沙箱中的路径，与 sandbox_setup.py 保持一致）
SKILLS_PATH = "/skills"
# 内存文件（AGENTS.md，沙箱内路径）
MEMORY_PATH = "/AGENTS.md"
# 子代理配置文件
SUBAGENTS_CONFIG = AGENT_DIR / "subagents" / "configs"
# AGENTS.md 文件路径
AGENTS_MD_PATH = AGENT_DIR / "memory" / "AGENTS.md"

# ============================================================
# 服务配置
# ============================================================
# API 服务标题
API_TITLE = "DeepAgent Chat API"
# API 版本
API_VERSION = "1.0.0"
# API 描述
API_DESCRIPTION = "基于 DeepAgent 的 AI 对话系统 API"
