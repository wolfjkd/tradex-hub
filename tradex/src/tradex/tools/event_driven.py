"""
事件驱动工具模块（6 个 MCP 工具）。

Tools:
  - get_earnings_forecast:   业绩预告（预增/预减/扭亏/续亏）
  - get_institution_survey:  机构调研
  - get_holder_trades:       股东增减持
  - get_share_buyback:       股票回购
  - get_equity_pledge:       股权质押
  - get_ipo_calendar:        新股申购日历

数据源路由（via SmartRouter）:
  全部走 em_datacenter（东财 datacenter，限流防封）
"""

from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP

import pandas as pd
from ..data_sources import get_router
from ..utils.cache import TTL_DAILY, cache
from ..service import event_service
from ._mcp_serve import mcp_serve

logger = logging.getLogger(__name__)

_router = get_router()


# ── 事件驱动六工具（QI-ARCH-02 试点上提，2026-11-18）────────────────
# 工具体模块级化：行为测试可直接 import 打桩（原 register() 闭包内不可
# import）；出口走 mcp_serve 单点（QI-ARCH-01，响应形状契约快照背书
# tests/test_mcp_serve_compat.py）。docstring 原样保留（MCP schema 载体）。


async def get_earnings_forecast(
    symbol: str,
    report_date: str = "",
    limit: int = 50,
) -> str:
    """
    获取个股业绩预告（预增/预减/扭亏/续亏/预亏等）。

    Args:
        symbol: 6 位股票代码，如 "600519"
        report_date: 报告期 YYYY-MM-DD（如 2024-12-31），留空取最近
        limit: 返回条数，默认 50

    Returns:
        业绩预告列表 (JSON)，含预测类型、净利润上下限、同比变化。
    """
    return mcp_serve(
        "get_earnings_forecast",
        lambda: event_service.get_earnings_forecast(
            symbol=symbol, report_date=report_date, limit=limit
        ),
        f"获取业绩预告失败 ({symbol})",
    )


async def get_institution_survey(
    symbol: str,
    start_date: str = "",
    end_date: str = "",
    limit: int = 50,
) -> str:
    """
    获取机构调研记录（哪些机构调研了该股票）。

    Args:
        symbol: 6 位股票代码
        start_date: 起始日期 YYYY-MM-DD
        end_date: 截止日期 YYYY-MM-DD
        limit: 返回条数

    Returns:
        机构调研列表 (JSON)，含调研机构、调研方式、接待人、调研日期。
    """
    return mcp_serve(
        "get_institution_survey",
        lambda: event_service.get_institution_survey(
            symbol=symbol, start_date=start_date, end_date=end_date, limit=limit
        ),
        f"获取机构调研失败 ({symbol})",
    )


async def get_holder_trades(
    symbol: str,
    direction: str = "",
    start_date: str = "",
    end_date: str = "",
    limit: int = 50,
) -> str:
    """
    获取股东增减持记录（重要股东 / 高管的买卖动向）。

    Args:
        symbol: 6 位股票代码
        direction: 方向过滤，"增持" / "减持" / ""（全部）
        start_date: 起始日期
        end_date: 截止日期

    Returns:
        股东增减持列表 (JSON)，含变动股东、变动数量、变动比例、公告日期。
    """
    return mcp_serve(
        "get_holder_trades",
        lambda: event_service.get_holder_trades(
            symbol=symbol, direction=direction,
            start_date=start_date, end_date=end_date, limit=limit,
        ),
        f"获取股东增减持失败 ({symbol})",
    )


async def get_share_buyback(
    symbol: str,
    progress: str = "",
    limit: int = 50,
) -> str:
    """
    获取股票回购方案与进度。

    Args:
        symbol: 6 位股票代码
        progress: 进度过滤，"实施中" / "完成" / "停止" / ""（全部）

    Returns:
        股票回购列表 (JSON)，含进度、已回购金额、已回购数量。
    """
    return mcp_serve(
        "get_share_buyback",
        lambda: event_service.get_share_buyback(
            symbol=symbol, progress=progress, limit=limit
        ),
        f"获取股票回购失败 ({symbol})",
    )


async def get_equity_pledge(
    symbol: str,
    date: str = "",
    limit: int = 50,
) -> str:
    """
    获取股权质押情况（质押机构、质押数量、质押比例）。

    Args:
        symbol: 6 位股票代码
        date: 查询日期 YYYY-MM-DD（默认最新）

    Returns:
        股权质押列表 (JSON)。
    """
    return mcp_serve(
        "get_equity_pledge",
        lambda: event_service.get_equity_pledge(
            symbol=symbol, date=date, limit=limit
        ),
        f"获取股权质押失败 ({symbol})",
    )


async def get_ipo_calendar(days_ahead: int = 30, limit: int = 50) -> str:
    """
    获取新股申购日历（未来 N 天可申购新股清单）。

    Args:
        days_ahead: 未来天数，默认 30

    Returns:
        新股申购日历 (JSON)，含代码、名称、申购日期、上市板块、发行价、申购上限。
    """
    return mcp_serve(
        "get_ipo_calendar",
        lambda: event_service.get_ipo_calendar(days_ahead=days_ahead, limit=limit),
        "获取新股日历失败",
    )


def register(mcp: FastMCP):
    """Register event-driven tools.

    QI-ARCH-02（2026-11-18 试点）：前 6 个 event_service 工具体已上提模块级
    （本模块可直接 import 打桩做行为测试），此处引用注册；后续非同构工具
    （监管异动/龙虎榜族等）仍为闭包注册，全量收拢续批。"""
    for _fn in (
        get_earnings_forecast,
        get_institution_survey,
        get_holder_trades,
        get_share_buyback,
        get_equity_pledge,
        get_ipo_calendar,
    ):
        mcp.tool()(_fn)


# ── 监管异动（交易所股票交易异常波动预警） ──
# 借鉴 chengzuopeng/stock-sdk 的 getUnusualFluctuation 实现（ISC license）
# 直接调用 em_client.fetch_unusual_fluctuation，不经过 SmartRouter（P999 单源，
# 健康分降级机制对其无意义）。返回 list[dict]，不是 DataFrame。
# （QI-ARCH-02 全量上提，2026-11-19：以下 11 工具体全部模块级化 + mcp_serve
# 出口收拢；双 except 分支工具走 value_error_detail 参数承载「参数错误」文案。）


async def get_unusual_fluctuation(
    trade_date: str = "",
    start_date: str = "",
    end_date: str = "",
    triggered: bool = False,
    limit: int = 200,
) -> str:
    """
    获取交易所「股票交易异常波动」监管预警列表（监管异动）。

    哪些个股已触发异常波动公告、哪些正在逼近阈值。数据来自东财 datacenter
    的 RPT_WATCH_UNUSUAL_FLUCTUATE 报表，自带约两个月历史滚动窗口。

    Args:
        trade_date: 单日过滤 YYYY-MM-DD（如 2026-09-25），与 start_date/end_date 互斥
        start_date: 区间起始（含），与 trade_date 互斥
        end_date: 区间结束（含），与 trade_date 互斥
        triggered: True 仅返回已触发公告（IS_HAPPEN=1）；False 不过滤（默认）
        limit: 返回条数上限，默认 200

    Returns:
        监管异动列表 (JSON)，每条含：
        - code/name: 证券代码/简称
        - date: 触发日期
        - rule: 触发规则（中文原文）
        - triggered: 是否已正式公告
        - deviation_value: 偏离值（规则阈值通常 100）
        - change_pct: 区间累计涨跌幅
        - direction: up 上涨偏离 / down 下跌偏离
    """
    from ..data_sources.em_client import fetch_unusual_fluctuation

    def _build() -> dict:
        result = fetch_unusual_fluctuation(
            trade_date=trade_date or None,
            start_date=start_date or None,
            end_date=end_date or None,
            triggered=triggered if triggered else None,
            max_pages=max(1, (limit + 499) // 500),
        )
        if limit > 0:
            result = result[:limit]
        return {
            "count": len(result),
            "filter": {
                "trade_date": trade_date or None,
                "start_date": start_date or None,
                "end_date": end_date or None,
                "triggered": triggered if triggered else None,
            },
            "records": result,
        }

    return mcp_serve(
        "get_unusual_fluctuation",
        _build,
        "获取监管异动失败",
        value_error_detail="参数错误",
    )


# ════════════════════════════════════════════════════════════════════
# SP-2026-09-25-002 龙虎榜扩展族（5 工具）
# 借鉴 chengzuopeng/stock-sdk (ISC) 的 dragonTiger.ts 实现
# ════════════════════════════════════════════════════════════════════


async def get_dragon_tiger_detail(
    start_date: str, end_date: str, limit: int = 200,
) -> str:
    """
    龙虎榜上榜个股详情（含 D1/D2/D5/D10 上榜后股价表现跟踪）。

    Args:
        start_date: 起始日期 YYYY-MM-DD（必填）
        end_date: 结束日期 YYYY-MM-DD（必填）
        limit: 返回条数，默认 200

    Returns:
        龙虎榜详情列表（含上榜后 1/2/5/10 日涨跌幅跟踪字段）
    """
    from ..data_sources.em_client import fetch_dragon_tiger_detail

    def _build() -> dict:
        result = fetch_dragon_tiger_detail(
            start_date=start_date, end_date=end_date,
            max_pages=max(1, (limit + 4999) // 5000),
        )
        if limit > 0:
            result = result[:limit]
        return {
            "count": len(result),
            "filter": {"start_date": start_date, "end_date": end_date},
            "records": result,
        }

    return mcp_serve("get_dragon_tiger_detail", _build, "获取龙虎榜详情失败")


async def get_dragon_tiger_stock_stats(
    period: str = "1month", limit: int = 200,
) -> str:
    """
    个股龙虎榜上榜次数统计（按周期聚合：1月/3月/6月/1年）。

    Args:
        period: 1month / 3month / 6month / 1year，默认 1month
        limit: 返回条数，默认 200

    Returns:
        上榜次数排行（代码、名称、上榜次数、累计买卖额等）
    """
    from ..data_sources.em_client import fetch_dragon_tiger_stock_stats

    def _build() -> dict:
        result = fetch_dragon_tiger_stock_stats(period=period)
        if limit > 0:
            result = result[:limit]
        return {
            "count": len(result),
            "period": period,
            "records": result,
        }

    return mcp_serve(
        "get_dragon_tiger_stock_stats",
        _build,
        "获取龙虎榜统计失败",
        value_error_detail="参数错误",
    )


async def get_dragon_tiger_institution(
    start_date: str, end_date: str, limit: int = 200,
) -> str:
    """
    龙虎榜机构买卖统计（机构席位层面，按日期范围）。

    Args:
        start_date: 起始日期 YYYY-MM-DD（必填）
        end_date: 结束日期 YYYY-MM-DD（必填）
        limit: 返回条数，默认 200

    Returns:
        机构买卖明细（每行是个股某日的机构席位明细）
    """
    from ..data_sources.em_client import fetch_dragon_tiger_institution

    def _build() -> dict:
        result = fetch_dragon_tiger_institution(
            start_date=start_date, end_date=end_date,
        )
        if limit > 0:
            result = result[:limit]
        return {
            "count": len(result),
            "filter": {"start_date": start_date, "end_date": end_date},
            "records": result,
        }

    return mcp_serve("get_dragon_tiger_institution", _build, "获取机构统计失败")


async def get_dragon_tiger_seat_detail(
    symbol: str, date: str, limit: int = 100,
) -> str:
    """
    个股某日龙虎榜席位明细（买入榜 + 卖出榜合并）。

    Args:
        symbol: 6 位股票代码
        date: 上榜日期 YYYY-MM-DD / YYYYMMDD
        limit: 返回条数，默认 100

    Returns:
        席位明细（营业部、买卖额、净额、买卖方向）
    """
    from ..data_sources.em_client import fetch_dragon_tiger_seat_detail

    def _build() -> dict:
        result = fetch_dragon_tiger_seat_detail(symbol=symbol, date=date)
        if limit > 0:
            result = result[:limit]
        return {
            "count": len(result),
            "symbol": symbol,
            "date": date,
            "records": result,
        }

    return mcp_serve(
        "get_dragon_tiger_seat_detail",
        _build,
        "获取席位明细失败",
        value_error_detail="参数错误",
    )


async def get_dragon_tiger_branch_rank(
    period: str = "1month", limit: int = 100,
) -> str:
    """
    龙虎榜营业部排行（按周期统计：近1月/3月/6月/1年）。

    每条含：营业部名称、上榜后 1/2/3/5/10 天买入次数、平均涨幅、上涨概率。
    用于跟踪哪些营业部对股价短期走势的影响力最强。

    Args:
        period: 1month / 3month / 6month / 1year，默认 1month
        limit: 返回条数，默认 100

    Returns:
        营业部排行列表

    数据源说明：
        akshare 独占源（上游 datacenter-web 无对应 report，
        走 akshare stock_lhb_yybph_em 包装函数）
    """
    from ..data_sources.akshare_fetchers import fetch_dt_branch_rank_em

    def _build() -> dict:
        result = fetch_dt_branch_rank_em(period=period)
        if limit > 0:
            result = result[:limit]
        return {
            "count": len(result),
            "period": period,
            "records": result,
        }

    return mcp_serve(
        "get_dragon_tiger_branch_rank",
        _build,
        "获取营业部排行失败",
        value_error_detail="参数错误",
    )


# ════════════════════════════════════════════════════════════════════
# SP-2026-09-25-003 融资融券扩展族（2 工具）
# ════════════════════════════════════════════════════════════════════


async def get_margin_account_info(limit: int = 100) -> str:
    """
    获取全市场融资融券账户统计（按日）。

    含：融资余额、融券余额、参与账户数、总担保物等。
    用于跟踪两融杠杆资金整体动向，是市场情绪温度计。

    Args:
        limit: 返回最近 N 天，默认 100

    Returns:
        按日倒序的两融账户统计列表
    """
    from ..data_sources.em_client import fetch_margin_account_info

    def _build() -> dict:
        result = fetch_margin_account_info()
        if limit > 0:
            result = result[:limit]
        return {
            "count": len(result),
            "records": result,
        }

    return mcp_serve("get_margin_account_info", _build, "获取两融账户统计失败")


async def get_margin_target_list(date: str = "", limit: int = 200) -> str:
    """
    获取融资融券标的明细（当日可融资/可融券清单）。

    Args:
        date: 交易日 YYYY-MM-DD；不传则取最新
        limit: 返回条数，默认 200（全市场约 2000+ 只标的）

    Returns:
        两融标的清单（代码、名称、融资余额、融券余额等）
    """
    from ..data_sources.em_client import fetch_margin_target_list

    def _build() -> dict:
        result = fetch_margin_target_list(trade_date=date or None)
        if limit > 0:
            result = result[:limit]
        return {
            "count": len(result),
            "date": date or "latest",
            "records": result,
        }

    return mcp_serve("get_margin_target_list", _build, "获取两融标的清单失败")


# ════════════════════════════════════════════════════════════════════
# SP-2026-09-25-004 大宗交易族（3 工具）
# ════════════════════════════════════════════════════════════════════


async def get_block_trade_market_stat(limit: int = 100) -> str:
    """
    获取大宗交易市场每日总览（全市场汇总）。

    含：当日总成交额、溢价/折价成交额及占比、上证收盘价等。
    用于跟踪全市场大宗交易整体活跃度。

    Args:
        limit: 返回最近 N 天，默认 100

    Returns:
        按日倒序的大宗交易市场统计
    """
    from ..data_sources.em_client import fetch_block_trade_market_stat

    def _build() -> dict:
        result = fetch_block_trade_market_stat()
        if limit > 0:
            result = result[:limit]
        return {
            "count": len(result),
            "records": result,
        }

    return mcp_serve("get_block_trade_market_stat", _build, "获取大宗交易市场统计失败")


async def get_block_trade_detail(
    start_date: str = "", end_date: str = "", limit: int = 200,
) -> str:
    """
    获取大宗交易明细（按日期范围筛选个股大宗交易记录）。

    每条含：成交价、成交量、买卖营业部、溢价率等。
    省略日期则默认拉取最近一段时间。

    Args:
        start_date: 起始日期 YYYY-MM-DD
        end_date: 结束日期 YYYY-MM-DD
        limit: 返回条数，默认 200

    Returns:
        大宗交易明细列表
    """
    from ..data_sources.em_client import fetch_block_trade_detail

    def _build() -> dict:
        result = fetch_block_trade_detail(
            start_date=start_date or None, end_date=end_date or None,
        )
        if limit > 0:
            result = result[:limit]
        return {
            "count": len(result),
            "filter": {"start_date": start_date or None, "end_date": end_date or None},
            "records": result,
        }

    return mcp_serve("get_block_trade_detail", _build, "获取大宗交易明细失败")


async def get_block_trade_daily_stat(
    start_date: str = "", end_date: str = "", limit: int = 200,
) -> str:
    """
    获取大宗交易每日统计（按股票汇总成交笔数、总额等）。

    与 detail 的区别：这里是按股票汇总后的统计视图，detail 是逐笔明细。

    Args:
        start_date: 起始日期
        end_date: 结束日期
        limit: 返回条数，默认 200

    Returns:
        大宗交易按股票汇总的每日统计
    """
    from ..data_sources.em_client import fetch_block_trade_daily_stat

    def _build() -> dict:
        result = fetch_block_trade_daily_stat(
            start_date=start_date or None, end_date=end_date or None,
        )
        if limit > 0:
            result = result[:limit]
        return {
            "count": len(result),
            "filter": {"start_date": start_date or None, "end_date": end_date or None},
            "records": result,
        }

    return mcp_serve("get_block_trade_daily_stat", _build, "获取大宗交易每日统计失败")


def register(mcp: FastMCP):
    """Register event-driven tools.

    QI-ARCH-02 全量上提完成（2026-11-19）：本模块 17 个工具体全部模块级
    （行为测试可直接 import 打桩），此处统一引用注册。"""
    for _fn in (
        get_earnings_forecast,
        get_institution_survey,
        get_holder_trades,
        get_share_buyback,
        get_equity_pledge,
        get_ipo_calendar,
        get_unusual_fluctuation,
        get_dragon_tiger_detail,
        get_dragon_tiger_stock_stats,
        get_dragon_tiger_institution,
        get_dragon_tiger_seat_detail,
        get_dragon_tiger_branch_rank,
        get_margin_account_info,
        get_margin_target_list,
        get_block_trade_market_stat,
        get_block_trade_detail,
        get_block_trade_daily_stat,
    ):
        mcp.tool()(_fn)
