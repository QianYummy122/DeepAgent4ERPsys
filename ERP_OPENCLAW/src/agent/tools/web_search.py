"""
自定义网络搜索工具。

基于智谱 AI 的 Web Search API，供主 Agent 和所有子 Agent 使用。

注意：智谱客户端改为**惰性创建**。
早期版本在模块导入时就执行 `ZhipuAiClient(api_key=ZHIPU_API_KEY)`，
一旦未配置 ZHIPU_API_KEY，整个 `agent.tools` 包都会导入失败，
连带导致智能体无法启动——而联网搜索只是可选能力，不应成为启动前提。
"""

from langchain_core.tools import tool

from agent.env_utils import ZHIPU_API_KEY

_client = None


def _get_client():
    """惰性创建智谱客户端；未配置密钥时抛出可读异常。"""
    global _client
    if _client is None:
        if not ZHIPU_API_KEY:
            raise RuntimeError(
                "未配置 ZHIPU_API_KEY，联网搜索不可用。"
                "如需使用 web_search，请在 .env 中设置 ZHIPU_API_KEY。"
            )
        from zai import ZhipuAiClient

        _client = ZhipuAiClient(api_key=ZHIPU_API_KEY)
    return _client


@tool('web_search', parse_docstring=True)
def web_search(query: str) -> str:
    """
    使用智谱的API进行Web搜索。

    适用于：市场行情调研、供应商背景调查、物料价格趋势查询、行业资讯获取等。

    Args:
        query: 需要搜索的内容或者关键字。

    Returns:
        返回搜索之后的结果。
    """
    try:
        client = _get_client()
        response = client.web_search.web_search(
            search_engine="search_pro",
            search_query=query,
            count=3,  # 返回结果的条数，范围1-50，默认10
            search_recency_filter="noLimit",  # 搜索指定日期范围内的内容
        )
        if response.search_result:
            return "\n\n".join([d.content for d in response.search_result])
        return '没有搜索到任何内容！'
    except Exception as e:
        print(e)
        return f"搜索失败: {e}"
