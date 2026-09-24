"""
ETF 期权工具模块（2 个 MCP 工具）。

Tools:
  - get_etf_option_tquote:   ETF 期权 T 型报价（买卖五档 / 持仓量 / 行权价）
  - get_etf_option_greeks:   ETF 期权希腊字母 + 隐含波动率（Delta/Gamma/Theta/Vega/IV）

数据源路由（via SmartRouter）:
  etf_option_tquote: sina_option(priority=1)
  etf_option_greeks: sina_option(priority=1)
"""

from __future__ import annotations

import json
import logging

from mcp.server.fastmcp import FastMCP

import pandas as pd
from ..data_sources import get_router
from ..utils.cache import TTL_REALTIME, cache
from ..utils.formatter import df_to_json, error_response
from ..service import option_service

logger = logging.getLogger(__name__)

_router = get_router()


def register(mcp: FastMCP):
    """Register ETF option tools."""

    @mcp.tool()
    async def get_etf_option_tquote(underlying: str = "510050") -> str:
        """
        获取 ETF 期权 T 型报价（买卖五档 / 持仓量 / 行权价 / 最新价）。
        数据源：新浪财经期权接口（零鉴权、稳定）。

        Args:
            underlying: 标的代码，默认 "510050"（50ETF），可选 "510300"（300ETF）/ "159919"（嘉实 300）

        Returns:
            期权合约 T 型报价列表 (JSON)，含合约代码、最新价、行权价、持仓量、买卖五档等。
        """
        try:
            result = option_service.get_etf_option_tquote(underlying=underlying)
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(
                f"获取 ETF 期权 T 型报价失败 ({underlying}): {e}",
                "get_etf_option_tquote",
            )

    @mcp.tool()
    async def get_etf_option_greeks(underlying: str = "510050") -> str:
        """
        获取 ETF 期权希腊字母 + 隐含波动率（Delta / Gamma / Theta / Vega / Rho / IV）。

        Args:
            underlying: 标的代码，默认 "510050"

        Returns:
            期权合约希腊字母列表 (JSON)，用于期权定价、对冲、波动率分析。
        """
        try:
            result = option_service.get_etf_option_greeks(underlying=underlying)
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(
                f"获取 ETF 期权希腊字母失败 ({underlying}): {e}",
                "get_etf_option_greeks",
            )
