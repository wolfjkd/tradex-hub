"""
Signal Data — 资金流类子模块 (signal_data_flow)。

原 signal_data.py 拆分自 v3.0.0，本子模块承载资金流类信号工具：
北向资金、个股资金流、龙虎榜、行业横向对比。

TradingAgents-astock 移植层（V0.7 4 个工具）。
函数名带 _signal 后缀以避免与 market/industry 模块同名冲突。

v3.1.0 起：所有数据源注册已集中到 data_sources/registry.py，
本模块仅通过 SmartRouter.route() 获取数据，不再直接 import astock_signals/akshare。

Tools (共 4 个):
  get_northbound_flow_signal     - 北向资金流向（同花顺 hsgtApi → akshare 备源）
  get_fund_flow_signal           - 个股资金流向（东财 push2 → akshare 备源）
  get_dragon_tiger_signal        - 龙虎榜席位明细（东财 datacenter → akshare 备源）
  get_industry_comparison_signal - 行业横向对比排名（东财 push2 → akshare 备源）
"""

from __future__ import annotations

import logging

import pandas as pd
from mcp.server.fastmcp import FastMCP

from ..data_sources import get_router
from ..utils.cache import TTL_DAILY, TTL_REALTIME, cache
from ..utils.formatter import df_to_json, dict_to_json, error_response
from ..utils.symbol import normalize_symbol

logger = logging.getLogger(__name__)

# 全局 SmartRouter 单例（数据源注册在 server.py 启动时由 register_all_sources() 完成）
_router = get_router()


def register(mcp: FastMCP):
    """Register signal data flow tools with the MCP server."""

    # ----------------------------------------------------------------
    # V0.7: 4 tools from astock_signals (northbound/fund_flow/
    #       dragon_tiger/industry) — TradingAgents-astock 移植
    # 函数名带 _signal 后缀以避免与 market/industry 模块同名冲突
    # ----------------------------------------------------------------

    @mcp.tool()
    async def get_northbound_flow_signal(
        curr_date: str = "",
        include_history: bool = False,
    ) -> str:
        """
        获取北向资金流向（沪深股通）。

        数据源：同花顺 hsgtApi（主源），提供实时分钟级沪股通+深股通累计净买入。
        备用源：AKShare stock_hsgt_hist_em。
        附带本地缓存的历史每日收盘数据（最多20个交易日）。

        Args:
            curr_date: 日期 YYYY-MM-DD，空字符串默认今天。
            include_history: 是否包含历史每日数据（最近20个交易日）。

        Returns:
            北向资金数据 (JSON)，含实时数据点、收盘净流入、多空信号、历史数据。
        """
        cache_key = f"northbound:{curr_date or 'today'}:{include_history}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            result, _src = _router.route(
                "northbound", curr_date=curr_date, include_history=include_history
            )
            # ths_hsgt 源返回 dict；akshare 源返回 DataFrame
            if isinstance(result, dict):
                output = dict_to_json(result)
                if result.get("realtime"):
                    cache.set(cache_key, output, TTL_REALTIME)
                return output
            elif isinstance(result, pd.DataFrame):
                output = df_to_json(result, max_rows=30)
                cache.set(cache_key, output, TTL_REALTIME)
                return output
            else:
                return error_response(
                    "北向资金数据为空", "get_northbound_flow_signal"
                )
        except Exception as e:
            return error_response(
                f"获取北向资金数据失败: {e}", "get_northbound_flow_signal"
            )

    @mcp.tool()
    async def get_fund_flow_signal(
        symbol: str,
        curr_date: str = "",
        include_history: bool = True,
    ) -> str:
        """
        获取个股资金流向（主力/大单/中单/小单/超大单净流入）。

        数据源：东财 push2（实时分钟级）+ push2his（历史日线20天）。
        备用源：AKShare stock_individual_fund_flow。

        Args:
            symbol: 6位股票代码，如 "600519"。
            curr_date: 日期 YYYY-MM-DD，空字符串默认今天。
            include_history: 是否包含历史每日资金流（最近20个交易日）。

        Returns:
            资金流向数据 (JSON)，含实时分钟级数据、历史日线、多空信号。
        """
        symbol = normalize_symbol(symbol)
        cache_key = f"fund_flow_signal:{symbol}:{curr_date or 'today'}:{include_history}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            # SmartRouter 智能路由：东财 em_push2 优先，失败降级 AKShare
            result, _source = _router.route(
                "fund_flow",
                code=symbol,
                curr_date=curr_date,
                include_history=include_history,
            )
            output = dict_to_json(result)
            if result.get("realtime"):
                cache.set(cache_key, output, TTL_REALTIME)
            return output
        except Exception as e:
            return error_response(
                f"获取个股资金流向失败: {e}", "get_fund_flow_signal"
            )

    @mcp.tool()
    async def get_dragon_tiger_signal(
        symbol: str,
        trade_date: str = "",
        look_back_days: int = 30,
    ) -> str:
        """
        获取个股龙虎榜数据（上榜记录 + 买卖席位 + 机构动向）。

        数据源：东财 datacenter-web（主源，直连）。
        备用源：AKShare stock_lhb_detail_em。

        Args:
            symbol: 6位股票代码，如 "000858"。
            trade_date: 参考日期 YYYY-MM-DD，空字符串默认今天。
            look_back_days: 向前查询天数，默认30天。

        Returns:
            龙虎榜数据 (JSON)，含上榜记录、买卖席位TOP5、机构动向。
        """
        symbol = normalize_symbol(symbol)
        cache_key = f"dragon_tiger_signal:{symbol}:{trade_date or 'today'}:{look_back_days}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            # SmartRouter 智能路由：东财 em_datacenter 优先，失败降级 AKShare
            result, _source = _router.route(
                "dragon_tiger",
                code=symbol,
                trade_date=trade_date,
                look_back_days=look_back_days,
            )
            output = dict_to_json(result)
            cache.set(cache_key, output, TTL_DAILY)
            return output
        except Exception as e:
            return error_response(
                f"获取龙虎榜数据失败: {e}", "get_dragon_tiger_signal"
            )

    @mcp.tool()
    async def get_industry_comparison_signal(
        symbol: str = "",
        trade_date: str = "",
        top_n: int = 20,
    ) -> str:
        """
        获取行业横向对比排名（全行业涨跌幅/上涨下跌家数/领涨股）。

        数据源：东财 push2 行业板块排名（主源，直连）。
        备用源：AKShare stock_sector_fund_flow_rank。

        Args:
            symbol: 6位股票代码（可选，用于定位所属行业）。
            trade_date: 日期 YYYY-MM-DD，空字符串默认今天。
            top_n: 显示前/后N个行业，默认20。

        Returns:
            行业排名数据 (JSON)，含行业名称/涨跌幅/上涨下跌家数/领涨股。
        """
        if symbol:
            symbol = normalize_symbol(symbol)
        cache_key = f"industry_cmp:{symbol or 'all'}:{trade_date or 'today'}:{top_n}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            # SmartRouter 智能路由：东财 em_push2 优先，失败降级 AKShare
            result, _source = _router.route(
                "industry_comparison",
                code=symbol,
                trade_date=trade_date,
                top_n=top_n,
            )
            output = dict_to_json(result)
            if result.get("industries"):
                cache.set(cache_key, output, TTL_DAILY)
            return output
        except Exception as e:
            return error_response(
                f"获取行业对比数据失败: {e}", "get_industry_comparison_signal"
            )
