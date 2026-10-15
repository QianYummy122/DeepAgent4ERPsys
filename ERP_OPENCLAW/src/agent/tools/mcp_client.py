"""
MCP 工具客户端。

在 Agent 启动时连接所有 MCP Server，获取全部 MCP 工具，
并按分组筛选后分配给不同的子 Agent。

使用方式:
    from agent.tools.mcp_client import load_mcp_tools

    all_tools, analyst_tools, order_tools, chart_tools = await load_mcp_tools()
"""

from typing import List, Tuple

from langchain_mcp_adapters.client import MultiServerMCPClient

from agent.env_utils import ANALYSIS_MCP_URL, ERP_MCP_URL

# MCP Server 连接配置（地址可通过 .env 覆盖）
MCP_SERVER_CONFIG = {
    "erp-api": {
        "url": ERP_MCP_URL,
        "transport": "streamable_http",
    },
    "analysis": {
        "url": ANALYSIS_MCP_URL,
        "transport": "streamable_http",
    },
}

# 工具分组规则（前缀匹配）
ANALYST_TOOL_PREFIXES = ("supplier_", "part_", "inventory_")
ORDER_TOOL_PREFIXES = ("order_",)
CHART_TOOL_PREFIXES = ("generate_",)  # 魔塔社区 MCP 可视化+工具（26 图表/地图/图表 + 1 spreadsheet）


async def load_mcp_tools(
    server_config: dict | None = None,
) -> Tuple[List, List, List, List]:
    """
    连接到所有 MCP Server，加载全部工具并分组。

    **容错策略**：
    * ``erp-api`` 失败 → 抛出异常（ERP 业务工具是系统的核心，缺失即无意义）。
    * ``analysis`` 失败 → 打印警告并继续（图表只是增强能力，
      远程可视化 MCP 属于外部服务，不可用不应阻塞整个智能体启动）。

    Args:
        server_config: MCP Server 连接配置，默认使用 MCP_SERVER_CONFIG。

    Returns:
        (all_tools, analyst_tools, order_tools, chart_tools) 四元组
        - all_tools: 全部 MCP 工具列表（ERP + 图表）
        - analyst_tools: 供应商查询 + 零部件查询 + 库存预警工具
        - order_tools: 订单创建 + 订单更新 + 订单搜索工具
        - chart_tools: 图表/地图/可视化生成工具（来自可视化 MCP Server，27 种）
    """
    if server_config is None:
        server_config = MCP_SERVER_CONFIG

    print("[INFO] 正在连接 MCP Server...")
    mcp_client = MultiServerMCPClient(server_config)

    # ---------- ERP 业务工具（必需） ----------
    try:
        erp_tools = await mcp_client.get_tools(server_name="erp-api")
    except Exception as exc:
        raise RuntimeError(
            f"无法连接 ERP MCP 桥接服务（{server_config['erp-api']['url']}）：{exc}\n"
            f"请先确认：\n"
            f"  1) Java ERP 后端已启动（默认 http://localhost:8080）；\n"
            f"  2) ERP MCP 桥接已启动：python -m mcp_server.server_main（默认 127.0.0.1:8000/mcp）。"
        ) from exc

    print(f"[INFO] 已从 ERP MCP Server 加载 {len(erp_tools)} 个工具")

    # ---------- 可视化工具（可选） ----------
    analysis_tools: List = []
    if "analysis" in server_config:
        try:
            analysis_tools = await mcp_client.get_tools(server_name="analysis")
            print(f"[INFO] 已从可视化 MCP Server 加载 {len(analysis_tools)} 个工具（可视化+其他）")
        except Exception as exc:
            print(
                f"[WARNING] 可视化 MCP Server 不可用（{server_config['analysis']['url']}）："
                f"{type(exc).__name__}: {str(exc)[:200]}"
            )
            print(
                "[WARNING] 将跳过图表工具，分析报告仍可正常生成（只是无法输出图表）。\n"
                "[WARNING] 如需图表能力，请在 .env 中把 ANALYSIS_MCP_URL 换成可用的 MCP 服务地址。"
            )
            analysis_tools = []

    # 合并全部工具
    all_tools = list(erp_tools) + list(analysis_tools)

    # 按前缀分组：业务工具
    analyst_tools = [
        t for t in erp_tools
        if t.name.startswith(ANALYST_TOOL_PREFIXES)
    ]
    order_tools = [
        t for t in erp_tools
        if t.name.startswith(ORDER_TOOL_PREFIXES)
    ]

    # 图表工具（来自可视化 MCP 社区服务）
    chart_tools = [
        t for t in analysis_tools
        if t.name.startswith(CHART_TOOL_PREFIXES)
    ]

    print(
        f"[INFO] 工具分组完成: "
        f"分析类 {len(analyst_tools)} 个, "
        f"订单类 {len(order_tools)} 个, "
        f"图表类 {len(chart_tools)} 个"
    )

    return all_tools, analyst_tools, order_tools, chart_tools
