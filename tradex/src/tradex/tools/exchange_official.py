"""
交易所官方一手数据工具模块（4 个 MCP 工具）。

显式调用交易所官方接口（独立于东财聚合数据）。

Tools:
  - get_sse_dragon_tiger:         上交所官方龙虎榜（含营业部席位）
  - get_szse_dragon_tiger:        深交所官方龙虎榜
  - get_cninfo_announcement_backup: 深交所官方公告（深市备源）
  - get_trading_calendar:         交易日历（深交所官方 + sina 备源，整月）
"""

from __future__ import annotations

import json
import logging

from mcp.server.fastmcp import FastMCP

import pandas as pd
from ..data_sources import get_router
from ..utils.cache import TTL_DAILY, TTL_MACRO, cache
from ._mcp_serve import mcp_serve
from ..utils.formatter import df_to_json, error_response

logger = logging.getLogger(__name__)

_router = get_router()


# （QI-ARCH-02 全量上提，2026-11-19：4 个工具体模块级化 + mcp_serve 出口
# 收拢（dump=False——df_to_json 自带格式化）；按月缓存保留。）


async def get_sse_dragon_tiger(date: str = "") -> str:
    """
    【官方一手】上交所龙虎榜（含营业部席位明细）。

    上交所官方接口，比东财聚合数据更详细（含买卖席位明细）。

    Args:
        date: 交易日 YYYY-MM-DD，默认今天

    Returns:
        龙虎榜列表 (JSON)。
    """
    def _build() -> str:
        df, src = _router.route(
            "dragon_tiger",
            source_name="sse_official",
            date=date,
        )
        return df_to_json(df)

    return mcp_serve("get_sse_dragon_tiger", _build, "获取上交所龙虎榜失败", dump=False)


async def get_szse_dragon_tiger(date: str = "") -> str:
    """
    【官方一手】深交所龙虎榜。

    Args:
        date: 交易日 YYYY-MM-DD

    Returns:
        龙虎榜列表 (JSON)。
    """
    def _build() -> str:
        df, src = _router.route(
            "dragon_tiger",
            source_name="szse_official",
            date=date,
        )
        return df_to_json(df)

    return mcp_serve("get_szse_dragon_tiger", _build, "获取深交所龙虎榜失败", dump=False)


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
    def _build() -> str:
        df, src = _router.route(
            "cninfo_announcement",
            source_name="szse_official",
            symbol=symbol, page=page, page_size=page_size,
        )
        return df_to_json(df)

    return mcp_serve(
        "get_cninfo_announcement_backup",
        _build,
        f"获取深交所公告失败 ({symbol})",
        dump=False,
    )


async def get_trading_calendar(year: int = 0, month: int = 0) -> str:
    """
    交易日历（整月）。主源深交所官方，失效时自动走 sina 交易日清单备源。

    Args:
        year: 年份，默认当前年
        month: 月份，默认当前月

    Returns:
        交易日历 (JSON)，含日期、是否交易日、节假日说明。
    """
    # 按月缓存：日历一个月内不会变，没必要每次打外部接口（保留在工具体层）
    from datetime import datetime as _dt

    cache_key = f"trading_calendar:{year or _dt.now().year}:{month or _dt.now().month}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    def _build() -> str:
        df, src = _router.route(
            "trading_calendar", year=year, month=month
        )
        output = df_to_json(df)
        cache.set(cache_key, output, TTL_MACRO)
        return output

    return mcp_serve("get_trading_calendar", _build, "获取交易日历失败", dump=False)


def register(mcp: FastMCP):
    """Register exchange official tools.

    QI-ARCH-02 全量上提（2026-11-19）：4 工具体模块级，引用注册。"""
    for _fn in (
        get_sse_dragon_tiger,
        get_szse_dragon_tiger,
        get_cninfo_announcement_backup,
        get_trading_calendar,
    ):
        mcp.tool()(_fn)
