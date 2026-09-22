"""
tdx_mcp 决策支持工具（L3 决策支持层）— v0.1.0-DEV，SP-2026-09-21-001。

本模块是通达信官方 MCP 的「决策支持」暴露层。纯增量能力（eltdx 无）经 registry
统一暴露，不重复包装与 eltdx 互备的那两个数据类型（realtime_quote / historical_kline
的对外入口仍是 price_data / signal_data，本模块只管官方 MCP 的独有能力）：

  - natural_lang_screener : 自然语言条件选股（L3 独立工具，拍板 #6）
  - research_report       : 券商研报查询（wenda_report_query，拍板 #5 走 registry）
  - query_macro_indicator : 宏观数据增强（wenda_macro_query，与 akshare 版互为交叉验证）

实现约定（对齐 tools/registry.py v3.3.9 勘误）：
  - 一律用 register(mcp) 函数轨 + @mcp.tool() 注册，勿用 @register_tool 装饰器。
  - 数据一律通过 get_router().route() 获取，不直连官方 MCP（铁律）。
  - token 缺失时 fetch_fn 抛 TDXSourceUnavailable → route 自动降级，
    本层在 route 内部消化，不外泄（返回 error_response 兜底）。
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..data_sources import get_router
from ..utils.cache import TTL_DAILY, cache
from ..utils.formatter import df_to_json, dict_to_json, error_response

_router = get_router()


def _router_route_cached(data_type: str, cache_key: str, tool_name: str, **kwargs) -> str:
    """统一「route → JSON → 缓存 → 失败兜底」骨架。

    - 数据源失败（含 token 缺失）时在 route 内部消化，返回 error_response，不外泄异常。
    - 成功结果写入 TTL_DAILY 缓存，降低对官方 MCP 的请求频率。
    """
    try:
        data, _src = _router.route(data_type, **kwargs)
        if hasattr(data, "to_dict") or hasattr(data, "iloc"):  # DataFrame/Series
            out = df_to_json(data)
        else:
            out = dict_to_json(data)
        cache.set(cache_key, out, TTL_DAILY)
        return out
    except Exception as e:  # noqa: BLE001 —— 数据源失败统一兜底，不外泄
        return error_response(f"获取 {data_type} 数据失败: {e}", tool_name)


def register(mcp: FastMCP):
    """注册通达信官方 MCP 决策支持工具。"""

    @mcp.tool()
    async def natural_lang_screener(query: str, limit: int = 20) -> str:
        """
        自然语言条件选股（通达信官方 MCP）。
        L3 决策支持 · 直达官方 tdx_screener，无需写复杂筛选代码。

        用日常中文描述选股条件即可，例如：
        "市盈率低于20且ROE高于15%的A股"、"连续3天放量上涨的央企"、"市值大于100亿的分红股"。

        Args:
            query: 自然语言选股条件，如 "市盈率低于20且ROE高于15%"。
            limit: 返回结果条数上限（默认20，最大50）。

        Returns:
            JSON：符合条件的股票列表（代码/名称/匹配度等，字段取决于官方返回）。
        """
        limit = max(1, min(int(limit), 50))
        cache_key = f"tdx_screener:{query}:{limit}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        return _router_route_cached("screener", cache_key, "natural_lang_screener",
                                    query=query, limit=limit)

    @mcp.tool()
    async def research_report(
        symbol: str = "",
        keyword: str = "",
        limit: int = 20,
    ) -> str:
        """
        券商研报查询（通达信问财 wenda_report_query）。
        按股票代码或关键词检索券商研究报告摘要。

        Args:
            symbol: 6位股票代码，如 "600519"；可留空仅按 keyword 检索。
            keyword: 检索关键词（如行业/主题/公司名），可留空仅按 symbol 检索。
            limit: 返回条数上限（默认20）。

        Returns:
            研报列表 (JSON)，含研报标题/券商/评级/日期/要点等。
        """
        limit = max(1, min(int(limit), 50))
        cache_key = f"tdx_research:{symbol}:{keyword}:{limit}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        return _router_route_cached("research_report", cache_key, "research_report",
                                    symbol=symbol, keyword=keyword, limit=limit)

    @mcp.tool()
    async def query_macro_indicator(indicator: str = "CPI") -> str:
        """
        宏观数据查询（通达信问财 wenda_macro_query）。
        按指标名获取宏观口径；与 akshare 版宏观数据互为交叉验证。

        Args:
            indicator: 宏观指标名，如 "CPI"/"PMI"/"GDP"/"M2"/"社融"。默认 "CPI"。

        Returns:
            宏观数据 (JSON)，含指标值/同比/历史序列等（字段取决于官方返回）。
        """
        indicator = (indicator or "CPI").strip() or "CPI"
        cache_key = f"tdx_macro:{indicator}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        return _router_route_cached("macro_data", cache_key, "query_macro_indicator",
                                    indicator=indicator)