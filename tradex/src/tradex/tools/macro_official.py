"""
官方宏观数据工具模块（2 个 MCP 工具）。

Tools:
  - get_pmi:                   PMI（统计局）
  - get_bond_yield_curve:      国债/信用债收益率曲线（中债）

数据源全部官方一手，与 akshare 上游独立。

2026-09-28 死源剥离（老板拍板）：get_social_financing（人行 404）/
get_repo_fixing_rate + get_lpr_history（货币网静态 json 404）已随死源移除。
"""

from __future__ import annotations

import json
import logging

from mcp.server.fastmcp import FastMCP

from ..utils.formatter import error_response
from ..service import macro_service

logger = logging.getLogger(__name__)


def register(mcp: FastMCP):
    """Register macro official tools."""

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
