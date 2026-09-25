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

import json
import logging

from mcp.server.fastmcp import FastMCP

import pandas as pd
from ..data_sources import get_router
from ..utils.cache import TTL_DAILY, cache
from ..utils.formatter import df_to_json, error_response
from ..service import event_service

logger = logging.getLogger(__name__)

_router = get_router()


def register(mcp: FastMCP):
    """Register event-driven tools."""

    @mcp.tool()
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
        try:
            result = event_service.get_earnings_forecast(
                symbol=symbol, report_date=report_date, limit=limit
            )
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(
                f"获取业绩预告失败 ({symbol}): {e}", "get_earnings_forecast"
            )

    @mcp.tool()
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
        try:
            result = event_service.get_institution_survey(
                symbol=symbol, start_date=start_date, end_date=end_date, limit=limit
            )
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(
                f"获取机构调研失败 ({symbol}): {e}", "get_institution_survey"
            )

    @mcp.tool()
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
        try:
            result = event_service.get_holder_trades(
                symbol=symbol, direction=direction,
                start_date=start_date, end_date=end_date, limit=limit,
            )
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(
                f"获取股东增减持失败 ({symbol}): {e}", "get_holder_trades"
            )

    @mcp.tool()
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
        try:
            result = event_service.get_share_buyback(
                symbol=symbol, progress=progress, limit=limit
            )
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(
                f"获取股票回购失败 ({symbol}): {e}", "get_share_buyback"
            )

    @mcp.tool()
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
        try:
            result = event_service.get_equity_pledge(
                symbol=symbol, date=date, limit=limit
            )
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(
                f"获取股权质押失败 ({symbol}): {e}", "get_equity_pledge"
            )

    @mcp.tool()
    async def get_ipo_calendar(days_ahead: int = 30, limit: int = 50) -> str:
        """
        获取新股申购日历（未来 N 天可申购新股清单）。

        Args:
            days_ahead: 未来天数，默认 30

        Returns:
            新股申购日历 (JSON)，含代码、名称、申购日期、上市板块、发行价、申购上限。
        """
        try:
            result = event_service.get_ipo_calendar(days_ahead=days_ahead, limit=limit)
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(f"获取新股日历失败: {e}", "get_ipo_calendar")

    # ── 监管异动（交易所股票交易异常波动预警） ──
    # 借鉴 chengzuopeng/stock-sdk 的 getUnusualFluctuation 实现（ISC license）
    # 直接调用 em_client.fetch_unusual_fluctuation，不经过 SmartRouter（P999 单源，
    # 健康分降级机制对其无意义）。返回 list[dict]，不是 DataFrame。

    @mcp.tool()
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
        try:
            from ..data_sources.em_client import fetch_unusual_fluctuation
            result = fetch_unusual_fluctuation(
                trade_date=trade_date or None,
                start_date=start_date or None,
                end_date=end_date or None,
                triggered=triggered if triggered else None,
                max_pages=max(1, (limit + 499) // 500),
            )
            if limit > 0:
                result = result[:limit]
            return json.dumps({
                "count": len(result),
                "filter": {
                    "trade_date": trade_date or None,
                    "start_date": start_date or None,
                    "end_date": end_date or None,
                    "triggered": triggered if triggered else None,
                },
                "records": result,
            }, ensure_ascii=False)
        except ValueError as e:
            return error_response(f"参数错误: {e}", "get_unusual_fluctuation")
        except Exception as e:
            return error_response(
                f"获取监管异动失败: {e}", "get_unusual_fluctuation"
            )
