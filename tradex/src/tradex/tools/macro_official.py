"""
官方宏观数据工具模块（5 个 MCP 工具）。

Tools:
  - get_social_financing:      社融数据（人行）
  - get_pmi:                   PMI（统计局）
  - get_bond_yield_curve:      国债/信用债收益率曲线（中债）
  - get_repo_fixing_rate:      回购定盘利率（中国货币网）
  - get_lpr_history:           LPR 历史（中国货币网）

数据源全部官方一手，与 akshare 上游独立。
"""

from __future__ import annotations

import json
import logging

from mcp.server.fastmcp import FastMCP

import pandas as pd
from ..data_sources import get_router
from ..utils.cache import TTL_DAILY, cache
from ..utils.formatter import df_to_json, error_response
from ..service import macro_service

logger = logging.getLogger(__name__)

_router = get_router()


def register(mcp: FastMCP):
    """Register macro official tools."""

    @mcp.tool()
    async def get_social_financing(year: int = 0) -> str:
        """
        获取社融数据（人民银行月度数据，12 列）。

        Args:
            year: 年份，默认当前年

        Returns:
            社融增量历史 (JSON)。
        """
        try:
            result = macro_service.get_social_financing(year=year)
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(f"获取社融数据失败: {e}", "get_social_financing")

    @mcp.tool()
    async def get_pmi() -> str:
        """
        获取 PMI 数据（国家统计局，制造业 + 非制造业）。

        Returns:
            PMI 历史数据 (JSON)。
        """
        try:
            result = macro_service.get_pmi()
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(f"获取 PMI 数据失败: {e}", "get_pmi")

    @mcp.tool()
    async def get_bond_yield_curve_official(curve: str = "国债") -> str:
        """
        获取国债/信用债收益率曲线（中债官方一手，3月~30年）。

        与现有 get_bond_yield_curve 不同：本工具走中债官网一手数据，
        支持国债 / 商业银行AAA / 中短票AAA 三种曲线。

        Args:
            curve: 曲线类型，"国债" / "商业银行AAA" / "中短票AAA"

        Returns:
            收益率曲线 (JSON)，含期限、收益率(%)。
        """
        try:
            result = macro_service.get_bond_yield_curve(curve=curve)
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(f"获取收益率曲线失败: {e}", "get_bond_yield_curve_official")

    @mcp.tool()
    async def get_repo_fixing_rate(kind: str = "FR") -> str:
        """
        获取回购定盘利率（中国货币网）。

        Args:
            kind: "FR"（回购定盘）或 "FDR"（银存间定盘）

        Returns:
            定盘利率历史 (JSON)，含 FR001/FR007/FR014。
        """
        try:
            result = macro_service.get_repo_fixing_rate(kind=kind)
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(f"获取回购定盘利率失败: {e}", "get_repo_fixing_rate")

    @mcp.tool()
    async def get_lpr_history(years_back: int = 5) -> str:
        """
        获取 LPR（贷款市场报价利率）历史。

        Args:
            years_back: 最近 N 年，默认 5

        Returns:
            LPR 历史列表 (JSON)，含日期、1年期LPR(%)、5年期LPR(%)。
        """
        try:
            result = macro_service.get_lpr_history(years_back=years_back)
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(f"获取 LPR 历史失败: {e}", "get_lpr_history")
