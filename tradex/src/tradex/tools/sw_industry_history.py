"""
申万行业历史变迁工具模块（2 个 MCP 工具）。

Tools:
  - get_sw_industry_history:   申万行业分类变迁史（一次性下载缓存）
  - get_sw_industry_as_of:     按 (code, date) 查询股票在指定日期的申万行业

用途：历史回测时还原当时的行业归属，避免用今日行业造成未来函数。
"""

from __future__ import annotations

import json
import logging

from mcp.server.fastmcp import FastMCP

from ..data_sources import get_router
from ..utils.cache import TTL_DAILY, cache
from ..utils.formatter import error_response
from ..service import sw_industry_service

logger = logging.getLogger(__name__)

_router = get_router()


def register(mcp: FastMCP):
    """Register SW industry history tools."""

    @mcp.tool()
    async def get_sw_industry_history(force_refresh: bool = False) -> str:
        """
        获取申万行业分类变迁史（含所有股票在不同时期的行业归属）。

        首次调用会下载 .xls 文件并内存缓存，后续调用直接返回缓存。

        Args:
            force_refresh: 强制重新下载（绕过缓存）

        Returns:
            行业变迁史 DataFrame (JSON)。
        """
        try:
            result = sw_industry_service.get_sw_industry_history(
                force_refresh=force_refresh
            )
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(
                f"获取申万行业变迁史失败: {e}", "get_sw_industry_history"
            )

    @mcp.tool()
    async def get_sw_industry_as_of(symbol: str, date: str = "") -> str:
        """
        查询股票在指定日期所属的申万行业（历史回测用，避免未来函数）。

        Args:
            symbol: 6 位股票代码
            date: 查询日期 YYYY-MM-DD（默认今天）

        Returns:
            行业归属 (JSON)，含股票代码、行业代码、行业名称、生效日期。
        """
        try:
            result = sw_industry_service.get_sw_industry_as_of(
                symbol=symbol, date=date
            )
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(
                f"获取申万行业归属失败 ({symbol}): {e}", "get_sw_industry_as_of"
            )
