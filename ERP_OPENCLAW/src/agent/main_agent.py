"""
主 Agent 入口模块。

使用 DeepAgents `create_deep_agent` 将所有组件串联为一个可运行的
ERP 采购智能助手。采用 async graph factory 模式，每次调用创建新沙箱。

使用方式:
    from agent.main_agent import agent

    # 本地调用
    agent_graph = await agent()
    result = await agent_graph.ainvoke(
        {"messages": [HumanMessage(content="...")]},
        {"context": ProcurementContext(user_id="zhangsan", username="张三")},
    )
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Optional

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StoreBackend
from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ToolCallLimitMiddleware,
)
from langchain_core.runnables import RunnableConfig

from agent.backends.sandbox_setup import setup_sandbox

from agent.config import (
    AGENTS_MD_FILENAME,
    CHECKPOINTER,
    DOWNLOAD_DIR,
    LOCAL_AGENTS_MD,
    MAIN_MODEL,
    SANDBOX_CONFIG,
    SKILLS_STORE_NAMESPACE,
    STORE,
    SUMMARY_MODEL,
)
from agent.memory.prompts import system_prompt
from agent.middleware_config import (
    create_analyst_middleware,
    create_order_middleware,
)
from agent.middlewares.context_injection import ContextInjectionMiddleware
from agent.middlewares.memory_update import MemoryUpdateMiddleware
from agent.middlewares.skills_sync import SkillsSyncMiddleware
from agent.middlewares.tools_summarization import build_summarization_middleware
from agent.middlewares.user_skills_restore import UserSkillsRestoreMiddleware
from agent.schema import ProcurementContext
from agent.subagents.loader import load_subagent_configs, resolve_subagent_tools
from agent.tools.chart_generator import create_generate_chart_tool
from agent.tools.hitl_tools import request_order_info
from agent.tools.assign_skill import create_assign_skill_tool
from agent.tools.download_sandbox_file import create_download_tool
from agent.tools.mcp_client import load_mcp_tools
from agent.tools.web_search import web_search

def _setup_logging() -> None:
    """配置日志：开发环境输出到控制台，生产环境输出到文件。"""
    env = os.environ.get("APP_ENV", "development")
    if env == "production":
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            filename="erp_agent.log",
            filemode="a",
        )
    else:
        logging.basicConfig(
            level=logging.ERROR,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            stream=sys.stdout,
        )

_setup_logging()
logger = logging.getLogger(__name__)


async def create_main_agent(
    config: Optional[RunnableConfig] = None,
    *,
    sandbox_id: Optional[str] = None,
):
    """
    创建 ERP 采购智能助手的 async graph factory。

    每次调用执行完整的 11 阶段初始化流水线：
      1. 沙箱配置 → 1.4 AGENTS.md 写入 Store → 1.5 CompositeBackend 分流 → 2. MCP 工具加载
      → 3. 可视化工具合并 → 4. 工具池构建 → 5. 子 Agent YAML 加载
      → 6. 子 Agent 中间件 → 7. 工具名称解析
      → 8. 主 Agent 中间件栈 → 9. create_deep_agent()

    Args:
        config: LangGraph RunnableConfig，由 langgraph 平台注入。
        sandbox_id: 可选，复用已有沙箱 ID。为 None 时创建新沙箱。

    Returns:
        编译后的 LangGraph StateGraph，可调用 .ainvoke() / .astream()。
    """
    logger.info("=== 开始创建 ERP 采购智能助手 ===")

    # ---- Phase 1: 沙箱配置 ----
    logger.info("Phase 1/10: 配置沙箱...")
    try:
        sandbox_backend = setup_sandbox(SANDBOX_CONFIG, sandbox_id=sandbox_id)
    except Exception:
        logger.exception("沙箱配置失败")
        raise RuntimeError("沙箱配置失败，无法创建 Agent")

    # ---- Phase 1.4: 上传 AGENTS.md 到沙箱 ----
    # AGENTS.md 存储到 OpenSandbox 后端 /AGENTS.md，不走 StoreBackend。
    # 沙箱内的 /AGENTS.md 由 CompositeBackend 的 default 路由命中。
    logger.info("Phase 1.4/10: 上传 AGENTS.md 到沙箱...")
    ag_md_content = LOCAL_AGENTS_MD.read_text(encoding="utf-8")
    sandbox_backend.upload_files([("/AGENTS.md", ag_md_content.encode("utf-8"))])
    logger.info("  AGENTS.md 已上传到沙箱")

    # ---- Phase 1.5: CompositeBackend 分流 ----
    # /AGENTS.md          → 沙箱 default 路由（OpenSandbox，Phase 1.4 已上传）
    # /memories/          → StoreBackend（按 user_id 隔离用户偏好）
    # /persisted-skills/  → StoreBackend（按 Agent scope 组织技能）
    # 其余路径（临时文件、代码执行）保留在沙箱。
    #
    # 注意：deepagents 0.7 起 `backend` 参数只接受**已实例化的后端对象**，
    # 不再接受 backend 工厂函数（factory 已在 0.7 移除）。
    # 用户隔离改由 StoreBackend 的 namespace 回调在运行时解析。
    logger.info("Phase 1.5/10: 配置 CompositeBackend (memories + persisted-skills → Store)...")

    def _user_memories_namespace(rt) -> tuple:
        """按 user_id 隔离用户偏好；context 缺失时回退到默认用户。"""
        context = getattr(rt, "context", None)
        user_id = getattr(context, "user_id", None) or "laoxiao"
        return (str(user_id),)

    backend = CompositeBackend(
        default=sandbox_backend,
        routes={
            "/memories/": StoreBackend(
                namespace=_user_memories_namespace,
                store=STORE,
            ),
            "/persisted-skills/": StoreBackend(
                namespace=lambda rt: SKILLS_STORE_NAMESPACE,
                store=STORE,
            ),
        },
    )

    # ---- Phase 2: MCP 工具加载 ----
    logger.info("Phase 2/10: 加载 MCP 工具...")
    try:
        all_mcp_tools, analyst_mcp_tools, order_mcp_tools, chart_mcp_tools = (
            await load_mcp_tools()
        )
    except Exception:
        logger.exception("MCP 工具加载失败")
        raise RuntimeError("MCP 工具加载失败，无法创建 Agent")

    # ---- Phase 3: 可视化工具合并 ----
    logger.info("Phase 3/10: 合并可视化工具 (26→1)...")
    generate_visualization, extra_mcp_tools = create_generate_chart_tool(chart_mcp_tools)
    if extra_mcp_tools:
        logger.info(f"  保留独立工具: {[t.name for t in extra_mcp_tools]}")

    # ---- Phase 3.6: 创建技能管理工具 ----
    assign_skill = create_assign_skill_tool(
        sandbox_backend,
        store=STORE,
        skills_namespace=SKILLS_STORE_NAMESPACE,
    )
    download_sandbox_file = create_download_tool(sandbox_backend, DOWNLOAD_DIR)

    # ---- Phase 4: 构建工具解析池 ----
    logger.info("Phase 4/10: 构建工具解析池...")
    available_tools = (
        list(analyst_mcp_tools)
        + list(order_mcp_tools)
        + list(extra_mcp_tools)
        + [generate_visualization]
        + [web_search]
        + [request_order_info]
        + [assign_skill]
        + [download_sandbox_file]
    )
    logger.info(f"  工具池: {len(available_tools)} 个工具")

    # ---- Phase 5: 子 Agent YAML 加载 ----
    logger.info("Phase 5/10: 加载子 Agent YAML 配置...")
    raw_configs = load_subagent_configs()
    if not raw_configs:
        logger.warning("  未找到任何子 Agent 配置，Agent 将在无子 Agent 模式下运行")
    else:
        logger.info(f"  已加载 {len(raw_configs)} 个子 Agent 配置")

    # ---- Phase 6: 子 Agent 中间件 ----
    logger.info("Phase 6/10: 创建子 Agent 中间件...")
    extra_middleware = {
        "procurement-analyst": create_analyst_middleware(SUMMARY_MODEL, backend),
        "procurement-order": create_order_middleware(),
    }

    # ---- Phase 7: 子 Agent 工具解析 ----
    logger.info("Phase 7/10: 解析子 Agent 工具名称...")
    subagents = resolve_subagent_tools(
        raw_configs,
        available_tools,
        extra_middleware=extra_middleware,
    )
    logger.info(f"  已解析 {len(subagents)} 个子 Agent")

    # ---- Phase 8: 主 Agent 中间件栈 ----
    logger.info("Phase 8/10: 构建主 Agent 中间件栈...")
    main_middleware = [
        ContextInjectionMiddleware(),
        SkillsSyncMiddleware(sandbox_backend),
        UserSkillsRestoreMiddleware(sandbox_backend, SKILLS_STORE_NAMESPACE),
        build_summarization_middleware(backend, SUMMARY_MODEL),
        MemoryUpdateMiddleware(model=SUMMARY_MODEL),
        ModelCallLimitMiddleware(run_limit=50),
        ToolCallLimitMiddleware(run_limit=200),
    ]

    # ---- Phase 9: create_deep_agent ----
    logger.info("Phase 9/10: 创建 Deep Agent...")
    agent_graph = create_deep_agent(
        model=MAIN_MODEL,
        system_prompt=system_prompt,
        skills=["/skills/main/"],
        memory=[AGENTS_MD_FILENAME],
        tools=[web_search, assign_skill, download_sandbox_file],
        subagents=subagents,
        middleware=main_middleware,
        backend=backend,
        store=STORE,
        checkpointer=CHECKPOINTER,
        context_schema=ProcurementContext,
    )

    logger.info("=== ERP 采购智能助手创建完成 ===")
    return agent_graph


# agent = asyncio.run(create_main_agent(sandbox_id='8b5d68e6-b6f4-4bde-823d-1fb510881581'))
# agent = asyncio.run(create_main_agent())


# ============================================================
# Agent 懒加载代理（兼容同步/异步两种初始化场景）
# ============================================================

async def _create_agent():
    """创建 Agent 实例（供 _AgentProxy 调用）"""
    return await create_main_agent()


class _AgentProxy:
    """
    懒加载 Agent 代理类

    兼容以下两种使用场景：
    1. 同步环境（如 agent_test.py 控制台）：在模块导入后、事件循环启动前初始化
    2. 异步环境（如 FastAPI 后端）：通过 get_agent_async() 在事件循环中初始化

    当直接访问 agent 对象的属性/方法时，代理会自动触发初始化并委托调用。
    """

    def __init__(self):
        self._agent = None

    @property
    def _is_initialized(self):
        """检查底层 agent 是否已初始化"""
        return self._agent is not None

    def _ensure_initialized(self):
        """
        确保 agent 已初始化（同步方式）

        如果没有运行中的事件循环，使用 asyncio.run() 创建 agent。
        如果事件循环正在运行，抛出 RuntimeError 提示使用 get_agent_async()。
        """
        if self._agent is not None:
            return self._agent

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                raise RuntimeError(
                    "Agent 尚未初始化且当前在事件循环中，"
                    "请使用 await get_agent_async() 获取 agent"
                )
        except RuntimeError as e:
            if "Agent 尚未初始化" in str(e):
                raise
            # 没有事件循环，继续初始化

        self._agent = asyncio.run(_create_agent())
        return self._agent

    def __getattr__(self, name):
        return getattr(self._ensure_initialized(), name)

    def __repr__(self):
        if self._agent is None:
            return "<AgentProxy (not initialized)>"
        return repr(self._agent)


# agent 实例，初始化为懒加载代理，由 get_agent() / get_agent_async() 函数触发初始化
agent = _AgentProxy()


def get_agent():
    """
    获取 agent 实例，懒加载方式（同步）

    如果 agent 尚未初始化，则同步创建它。
    注意：不能在运行中的事件循环内调用此函数。

    Returns:
        CompiledStateGraph: Agent 实例
    """
    global agent
    if isinstance(agent, _AgentProxy):
        if agent._is_initialized:
            return agent._agent
        return agent._ensure_initialized()
    return agent


async def get_agent_async():
    """
    异步获取 agent 实例，懒加载方式

    适用于在事件循环中运行时调用（如 FastAPI 的 lifespan）。
    如果 agent 已通过 get_agent() 同步初始化，则直接返回。

    Returns:
        CompiledStateGraph: Agent 实例
    """
    global agent
    if isinstance(agent, _AgentProxy):
        if agent._is_initialized:
            return agent._agent
        agent._agent = await _create_agent()
        return agent._agent
    return agent