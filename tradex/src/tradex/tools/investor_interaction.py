"""
投资者互动工具模块（2 个 MCP 工具）。

Tools:
  - get_cninfo_irm:          互动易（深市投资者问答，巨潮）
  - get_sse_e_interaction:   上证 e 互动（沪市投资者问答，上交所独立平台）
"""

from __future__ import annotations

import json
import logging

from mcp.server.fastmcp import FastMCP

from ..data_sources import get_router
from ..utils.cache import TTL_DAILY, cache
from ..utils.formatter import error_response
from ..service import interaction_service
from ..utils.symbol import normalize_symbol

logger = logging.getLogger(__name__)

_router = get_router()


def register(mcp: FastMCP):
    """Register investor interaction tools."""

    @mcp.tool()
    async def get_cninfo_irm(symbol: str, page: int = 1, page_size: int = 20) -> str:
        """
        获取互动易（深市投资者互动问答）。

        巨潮信息网运营，深市股票专用。含投资者提问与上市公司答复。

        Args:
            symbol: 6 位股票代码（深市，如 "000001"）
            page: 页码
            page_size: 每页条数

        Returns:
            互动问答列表 (JSON)，含提问、答复、提问时间、答复时间。
        """
        try:
            result = interaction_service.get_cninfo_irm(
                symbol=symbol, page=page, page_size=page_size
            )
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(
                f"获取互动易失败 ({symbol}): {e}", "get_cninfo_irm"
            )

    @mcp.tool()
    async def get_sse_e_interaction(
        symbol: str, page: int = 1, page_size: int = 20, kind: str = ""
    ) -> str:
        """
        获取上证 e 互动（沪市投资者问答）。

        上交所运营的独立平台，与互动易完全独立。沪市股票专用。

        Args:
            symbol: 6 位股票代码（沪市，如 "600519"）
            page: 页码
            kind: 类型过滤，"问答" / "建议" / ""（全部）

        Returns:
            互动问答列表 (JSON)。
        """
        try:
            result = interaction_service.get_sse_e_interaction(
                symbol=symbol, page=page, page_size=page_size, kind=kind
            )
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(
                f"获取上证 e 互动失败 ({symbol}): {e}", "get_sse_e_interaction"
            )
