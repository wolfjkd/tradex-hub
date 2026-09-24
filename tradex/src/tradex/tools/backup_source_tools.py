"""
备胎源显式调用工具模块（4 个 MCP 工具）。

让用户/AI 能显式调用某个独立上游的备源，用于：
  - 回测时需要稳定的独立源
  - 主源失效时人工切换
  - 多源交叉验证

Tools:
  - get_sina_research_reports:   新浪研报列表（独立于 tdx_mcp 主源）
  - get_sina_fund_flow:          新浪日度资金流（独立于东财）
  - get_baidu_kline:             百度带 MA 的 K 线（第四备源）
  - get_baostock_valuation:      baostock 估值历史（TCP 独立通道）
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
    """Register explicit backup-source tools."""

    @mcp.tool()
    async def get_sina_research_reports(
        symbol: str, page: int = 1, page_size: int = 20
    ) -> str:
        """
        【备源直取】新浪财经研报列表。

        显式调用新浪上游（与主源 tdx_mcp / 东财完全独立）。
        不含评级和目标价，仅有标题、类型、机构、研究员、日期。
        用于：主源失效 / 多源交叉验证 / 回测。

        Args:
            symbol: 6 位股票代码
            page: 页码
            page_size: 每页条数

        Returns:
            研报列表 (JSON)。
        """
        try:
            df, src = _router.route(
                "research_report",
                source_name="sina_research",
                symbol=symbol, page=page, page_size=page_size,
            )
            return df_to_json(df)
        except Exception as e:
            return error_response(
                f"获取新浪研报失败 ({symbol}): {e}", "get_sina_research_reports"
            )

    @mcp.tool()
    async def get_sina_fund_flow(symbol: str, days: int = 10) -> str:
        """
        【备源直取】新浪财经个股资金流向（日度）。

        显式调用新浪上游，与东财 push2his / akshare 完全独立。
        用于：东财资金流被封时的降级方案。

        Args:
            symbol: 6 位股票代码
            days: 最近天数，默认 10

        Returns:
            日度资金流 (JSON)，含日期、主力/游资/散户净流入。
        """
        try:
            df, src = _router.route(
                "fund_flow",
                source_name="sina_fund_flow",
                symbol=symbol, days=days,
            )
            return df_to_json(df)
        except Exception as e:
            return error_response(
                f"获取新浪资金流失败 ({symbol}): {e}", "get_sina_fund_flow"
            )

    @mcp.tool()
    async def get_baidu_kline(
        symbol: str, period: str = "day", count: int = 120
    ) -> str:
        """
        【备源直取】百度股市通带 MA 的 K 线。

        显式调用百度上游（第四备源），返回 OHLCV + MA5/MA10/MA20/MA30。
        与 eltdx(TCP)/akshare(HTTP)/tdx_mcp(官方 MCP) 完全独立。

        Args:
            symbol: 6 位股票代码
            period: K 线周期，day / week / month
            count: K 线数量

        Returns:
            K 线数据 (JSON)，含日期、OHLC、成交量、MA 均线。
        """
        try:
            df, src = _router.route(
                "historical_kline",
                source_name="baidu_http",
                symbol=symbol, period=period, count=count,
            )
            return df_to_json(df)
        except Exception as e:
            return error_response(
                f"获取百度 K 线失败 ({symbol}): {e}", "get_baidu_kline"
            )

    @mcp.tool()
    async def get_baostock_valuation(
        symbol: str, start_date: str = "", end_date: str = ""
    ) -> str:
        """
        【备源直取】baostock 估值历史（TCP 协议，零鉴权）。

        显式调用 baostock 独立 TCP 通道，与东财/akshare 上游完全独立。
        注意：baostock 不支持北交所股票。

        Args:
            symbol: 6 位股票代码
            start_date: 起始日期 YYYY-MM-DD
            end_date: 截止日期 YYYY-MM-DD

        Returns:
            估值历史 (JSON)，含日期、PE(TTM)、PB、PS(TTM)。
        """
        try:
            df, src = _router.route(
                "valuation",
                source_name="baostock_tcp",
                symbol=symbol, start_date=start_date, end_date=end_date,
            )
            return df_to_json(df)
        except Exception as e:
            return error_response(
                f"获取 baostock 估值失败 ({symbol}): {e}", "get_baostock_valuation"
            )
