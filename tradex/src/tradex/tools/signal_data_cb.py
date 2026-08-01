"""
Signal Data — 可转债类子模块 (signal_data_cb)。

原 signal_data.py 拆分自 v3.0.0，本子模块承载可转债品种数据工具：
可转债实时行情、可转债价值分析。

V0.8 品种扩展层。

v3.1.0 起：所有数据获取通过 SmartRouter.route() 路由，
不再直接 import astock_signals 数据源函数。

Tools (共 2 个):
  get_cb_realtime_data        - 可转债实时行情（AKShare bond_zh_cov）
  get_cb_value_analysis_data  - 可转债价值分析/转股溢价率（AKShare bond_zh_cov_value_analysis）
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..data_sources import get_router
from ..utils.cache import TTL_DAILY, TTL_REALTIME, cache
from ..utils.formatter import error_response, dict_to_json

_router = get_router()


def register(mcp: FastMCP):
    """Register signal data convertible bond tools with the MCP server."""

    # ----------------------------------------------------------------
    # V0.8: 品种扩展 — 可转债
    # ----------------------------------------------------------------

    @mcp.tool()
    async def get_cb_realtime_data(
        top_n: int = 50,
        sort_by: str = "成交额",
    ) -> str:
        """
        获取可转债实时行情（全部可转债含转股溢价率）。

        数据源：AKShare bond_zh_cov（东方财富）。
        提供正股价/转股价/转股价值/转股溢价率/信用评级等可转债特有字段。

        Args:
            top_n: 返回前N只可转债，默认50。
            sort_by: 排序字段，默认成交额，可选转股溢价率。

        Returns:
            可转债实时行情 (JSON)，含代码/价格/正股价/转股价/溢价率/评级。
        """
        cache_key = f"cb_realtime:{top_n}:{sort_by}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            # cb_data: symbol="" → get_cb_realtime_json(top_n, sort_by)
            result, _src = _router.route(
                "cb_data", symbol="", top_n=top_n, sort_by=sort_by
            )
            output = dict_to_json(result)
            if result.get("bonds"):
                cache.set(cache_key, output, TTL_REALTIME)
            return output
        except Exception as e:
            return error_response(
                f"获取可转债行情失败: {e}", "get_cb_realtime_data"
            )

    @mcp.tool()
    async def get_cb_value_analysis_data(
        symbol: str,
        days: int = 30,
    ) -> str:
        """
        获取可转债价值分析（历史转股溢价率/纯债价值/纯债溢价率曲线）。

        数据源：AKShare bond_zh_cov_value_analysis（东方财富）。
        用于分析可转债估值区间、溢价率趋势。

        Args:
            symbol: 可转债代码，如 "113527"。
            days: 返回最近N天数据，默认30天。

        Returns:
            可转债价值分析 (JSON)，含日期/收盘价/纯债价值/转股价值/溢价率。
        """
        cache_key = f"cb_value:{symbol}:{days}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            # cb_data: symbol 非空 → get_cb_value_analysis_json(symbol, days)
            result, _src = _router.route(
                "cb_data", symbol=symbol, days=days
            )
            output = dict_to_json(result)
            if result.get("history"):
                cache.set(cache_key, output, TTL_DAILY)
            return output
        except Exception as e:
            return error_response(
                f"获取可转债价值分析失败: {e}", "get_cb_value_analysis_data"
            )
