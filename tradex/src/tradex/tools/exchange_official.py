"""
交易所官方一手数据工具模块（4 个 MCP 工具）。

显式调用交易所官方接口（独立于东财聚合数据）。

Tools:
  - get_sse_dragon_tiger:         上交所官方龙虎榜（含营业部席位）
  - get_szse_dragon_tiger:        深交所官方龙虎榜
  - get_cninfo_announcement_backup: 深交所官方公告（深市备源）
  - get_trading_calendar:         深交所官方交易日历（整月）
"""

from __future__ import annotations

import json
import logging

from mcp.server.fastmcp import FastMCP

import pandas as pd
from ..data_sources import get_router
from ..utils.cache import TTL_DAILY, cache
from ..utils.formatter import df_to_json, error_response

logger = logging.getLogger(__name__)

_router = get_router()


def register(mcp: FastMCP):
    """Register exchange official tools."""

    @mcp.tool()
    async def get_sse_dragon_tiger(date: str = "") -> str:
        """
        【官方一手】上交所龙虎榜（含营业部席位明细）。

        上交所官方接口，比东财聚合数据更详细（含买卖席位明细）。

        Args:
            date: 交易日 YYYY-MM-DD，默认今天

        Returns:
            龙虎榜列表 (JSON)。
        """
        try:
            df, src = _router.route(
                "dragon_tiger",
                source_name="sse_official",
                date=date,
            )
            return df_to_json(df)
        except Exception as e:
            return error_response(
                f"获取上交所龙虎榜失败: {e}", "get_sse_dragon_tiger"
            )

    @mcp.tool()
    async def get_szse_dragon_tiger(date: str = "") -> str:
        """
        【官方一手】深交所龙虎榜。

        Args:
            date: 交易日 YYYY-MM-DD

        Returns:
            龙虎榜列表 (JSON)。
        """
        try:
            df, src = _router.route(
                "dragon_tiger",
                source_name="szse_official",
                date=date,
            )
            return df_to_json(df)
        except Exception as e:
            return error_response(
                f"获取深交所龙虎榜失败: {e}", "get_szse_dragon_tiger"
            )

    @mcp.tool()
    async def get_cninfo_announcement_backup(
        symbol: str, page: int = 1, page_size: int = 20
    ) -> str:
        """
        【官方备源】深交所官方公告（与巨潮信息网独立）。

        Args:
            symbol: 6 位股票代码（深市）
            page: 页码

        Returns:
            公告列表 (JSON)。
        """
        try:
            df, src = _router.route(
                "cninfo_announcement",
                source_name="szse_official",
                symbol=symbol, page=page, page_size=page_size,
            )
            return df_to_json(df)
        except Exception as e:
            return error_response(
                f"获取深交所公告失败 ({symbol}): {e}",
                "get_cninfo_announcement_backup",
            )

    @mcp.tool()
    async def get_trading_calendar(year: int = 0, month: int = 0) -> str:
        """
        【官方一手】深交所交易日历（整月）。

        Args:
            year: 年份，默认当前年
            month: 月份，默认当前月

        Returns:
            交易日历 (JSON)，含日期、是否交易日、节假日说明。
        """
        try:
            df, src = _router.route(
                "trading_calendar",
                source_name="szse_official",
                year=year, month=month,
            )
            return df_to_json(df)
        except Exception as e:
            return error_response(
                f"获取交易日历失败: {e}", "get_trading_calendar"
            )
