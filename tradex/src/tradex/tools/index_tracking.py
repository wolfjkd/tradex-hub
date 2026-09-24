"""
指数追踪工具模块（3 个 MCP 工具）。

Tools:
  - get_index_constituents:   指数成分股（中证 / 国证）
  - get_index_weights:        指数权重
  - get_index_valuation:      指数 PE / 股息率（仅中证）

数据源路由（via SmartRouter）:
  index_constituents: csi_official(1) + cnindex_official(100)
  index_weights:      csi_official(1) + cnindex_official(100)
  index_valuation:    csi_official(1)
"""

from __future__ import annotations

import json
import logging

from mcp.server.fastmcp import FastMCP

import pandas as pd
from ..data_sources import get_router
from ..utils.cache import TTL_DAILY, cache
from ..utils.formatter import df_to_json, error_response
from ..service import index_service

logger = logging.getLogger(__name__)

_router = get_router()


def register(mcp: FastMCP):
    """Register index tracking tools."""

    @mcp.tool()
    async def get_index_constituents(index_code: str = "000300") -> str:
        """
        获取指数成分股清单（中证指数官网一手数据）。

        Args:
            index_code: 指数代码，如 "000300"（沪深300）/ "000905"（中证500）/ "000852"（中证1000）/
                        "399001"（深证成指，走国证备源）

        Returns:
            成分股列表 (JSON)，含代码、名称、上市交易所。
        """
        try:
            result = index_service.get_index_constituents(index_code=index_code)
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(
                f"获取指数成分股失败 ({index_code}): {e}",
                "get_index_constituents",
            )

    @mcp.tool()
    async def get_index_weights(index_code: str = "000300") -> str:
        """
        获取指数权重（最近公布的指数权重，月末快照）。

        Args:
            index_code: 指数代码

        Returns:
            权重列表 (JSON)，含代码、名称、权重(%)。
        """
        try:
            result = index_service.get_index_weights(index_code=index_code)
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(
                f"获取指数权重失败 ({index_code}): {e}", "get_index_weights"
            )

    @mcp.tool()
    async def get_index_valuation(index_code: str = "000300") -> str:
        """
        获取指数估值（PE 与股息率，不含 PB）。

        Args:
            index_code: 指数代码（仅中证指数支持）

        Returns:
            估值历史列表 (JSON)，含日期、PE、股息率(%)。
        """
        try:
            result = index_service.get_index_valuation(index_code=index_code)
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(
                f"获取指数估值失败 ({index_code}): {e}", "get_index_valuation"
            )
