"""
Category 6: Market Overview & Capital Flows (V0.3)

Tools:
  26. get_market_overview  - Major index snapshots (v3.3.1: tencent_http fallback)
  27. get_money_flow       - Individual stock fund flow (v3.3.1: retry+fallback)
  28. get_north_bound_flow - Northbound (HK->A) capital flow
  29. get_limit_up_down    - Daily limit-up/limit-down pool
  30. get_dragon_tiger     - Dragon & Tiger Board (institutional activity)
  31. get_global_market_quote - Global market snapshot (v3.3.1 新增)

Data source routing (via SmartRouter):
  市场概览: akshare(priority=1) → tencent_http(priority=100)
  全局行情: tencent_http(priority=1)  [global_market_quote]
  资金流向: em_push2(priority=1) → akshare(priority=100)  [fund_flow]
  北向资金: ths_hsgt(priority=1) → akshare(priority=100)  [northbound]
  涨跌停池: akshare hot_stocks
  龙虎榜:   em_datacenter(priority=1) → akshare(priority=100)  [dragon_tiger]

v3.4.0 工单 02：业务逻辑已抽到 service/market_service.py，本文件保留薄包装
（MCP 工具层），调用 service 并用 json.dumps 转成 MCP 协议要求的字符串返回。
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from ..service import market_service
from ..utils.formatter import error_response

import logging

logger = logging.getLogger(__name__)


def register(mcp: FastMCP):
    """Register market overview tools with the MCP server.

    v3.4.0 起：业务逻辑在 service/market_service.py，本函数只做 MCP 薄包装。
    """

    @mcp.tool()
    async def get_market_overview() -> str:
        """
        获取A股主要指数实时行情快照。

        包含上证指数、深证成指、创业板指、科创50、沪深300、中证500等。

        Returns:
            主要指数实时行情 (JSON)，包含指数名称、最新点位、涨跌幅、
            成交量、成交额等。
        """
        try:
            result = market_service.get_market_overview()
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(
                f"获取市场概览失败: {e}", "get_market_overview"
            )

    @mcp.tool()
    async def get_index_volume_compare(days: int = 6) -> str:
        """
        获取三大指数（上证/深证/创业板）近 days 个交易日的量能序列，
        用于盘后复盘「量能对比」柱状图。

        返回 JSON：
        {
          "sh000001": {
            "name": "上证指数",
            "series": [{"date": "2026-08-13", "volume_hand": 572793677, "volume_yi_share": 5.73,
                        "amount_yuan": 1164203068530, "amount_yi": 11642.03}, ...]
          },
          ...
        }
        - volume_hand: 成交量(手)
        - volume_yi_share: 成交量(亿手)
        - amount_yuan: 成交额(元)，东财源才有，腾讯源为 null
        - amount_yi: 成交额(亿元)
        单指数取数失败则在对应项中返回 {"series": [], "error": "..."}。
        """
        try:
            result = market_service.get_index_volume_compare(days=days)
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(
                f"获取量能对比失败: {e}", "get_index_volume_compare"
            )

    @mcp.tool()
    async def get_money_flow(symbol: str) -> str:
        """
        获取个股资金流向数据。

        Args:
            symbol: 6位股票代码，如 "600519"

        Returns:
            资金流向数据 (JSON)，包含日期、主力净流入、超大单净流入、
            大单净流入、中单净流入、小单净流入等。
        """
        try:
            result = market_service.get_money_flow(symbol=symbol)
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(
                f"资金流向暂时不可用: {e}", "get_money_flow"
            )

    @mcp.tool()
    async def get_north_bound_flow() -> str:
        """
        获取北向资金（沪股通+深股通）净流入数据。

        北向资金是境外投资者通过港交所买入A股的资金，是市场重要的
        情绪和趋势指标。

        Returns:
            北向资金流入时间序列 (JSON)，包含日期、沪股通净流入、
            深股通净流入、北向资金合计净流入等。
        """
        try:
            result = market_service.get_north_bound_flow()
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(
                f"获取北向资金失败: {e}", "get_north_bound_flow"
            )

    @mcp.tool()
    async def get_limit_up_down(direction: str = "涨停") -> str:
        """
        获取当日涨停板或跌停板股票池。

        Args:
            direction: "涨停" 获取涨停板，"跌停" 获取跌停板

        Returns:
            涨停/跌停股票列表 (JSON)，包含代码、名称、涨跌幅、封单额、
            首次涨停/跌停时间、最后涨停/跌停时间、连板天数等。
        """
        try:
            result = market_service.get_limit_up_down(direction=direction)
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(
                f"获取{direction}板数据失败: {e}", "get_limit_up_down"
            )

    @mcp.tool()
    async def get_dragon_tiger(
        num_days: int = 5,
    ) -> str:
        """
        获取龙虎榜数据（机构和游资活跃买卖记录）。

        龙虎榜是沪深交易所公布的异动股票交易席位信息，反映机构和
        大型游资的交易行为。

        Args:
            num_days: 返回最近几个交易日的数据，默认5天

        Returns:
            龙虎榜数据 (JSON)，包含股票代码、名称、上榜原因、
            买入额、卖出额、净买入额、买方营业部等。
        """
        try:
            result = market_service.get_dragon_tiger(num_days=num_days)
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(
                f"获取龙虎榜失败: {e}", "get_dragon_tiger"
            )

    @mcp.tool()
    async def get_global_market_quote(category: str = "") -> str:
        """
        获取全球市场行情快照。v3.3.1 新增，通过腾讯接口批量获取。

        包含美股三大指数、热门美股（英伟达/特斯拉/苹果/微软/亚马逊/谷歌/Meta/美光/应用材料）、
        亚太指数（恒生/恒生科技）、韩股龙头（三星/SK海力士）、美元指数。

        Args:
            category: 可选分类过滤，如 "美股指数"、"热门美股"、"亚太指数"、"韩股"、"外汇"。
                为空时返回全部。

        Returns:
            全球市场行情 (JSON)，包含代码、名称、类别、最新价、涨跌额、涨跌幅等。
        """
        try:
            result = market_service.get_global_market_quote(category=category)
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(
                f"获取全球行情失败: {e}", "get_global_market_quote"
            )
