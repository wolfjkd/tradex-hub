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
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

import pandas as pd
from ..data_sources import get_router
from ..utils.cache import TTL_DAILY, TTL_REALTIME, cache
from ..utils.formatter import df_to_json, error_response, slim_df
from ..utils.symbol import normalize_symbol

_router = get_router()


def register(mcp: FastMCP):
    """Register market overview tools with the MCP server."""

    @mcp.tool()
    async def get_market_overview() -> str:
        """
        获取A股主要指数实时行情快照。

        包含上证指数、深证成指、创业板指、科创50、沪深300、中证500等。

        Returns:
            主要指数实时行情 (JSON)，包含指数名称、最新点位、涨跌幅、
            成交量、成交额等。
        """
        cache_key = "market_overview"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            df, _src = _router.route("market_overview")
            df = slim_df(df)
            result = df_to_json(df, max_rows=30)
            cache.set(cache_key, result, TTL_REALTIME)
            return result
        except Exception as e:
            return error_response(
                f"获取市场概览失败: {e}", "get_market_overview"
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
        symbol = normalize_symbol(symbol)
        cache_key = f"money_flow:{symbol}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            # SmartRouter 自动处理 fallback：em_push2(priority=1) → akshare(priority=100)
            result, _src = _router.route(
                "fund_flow", code=symbol, include_history=True
            )
            # fund_flow fetch_fn 返回 dict（含 realtime/history 列表）
            rows = []
            if isinstance(result, dict):
                realtime = result.get("realtime") or []
                history = result.get("history") or []
                for item in realtime:
                    rows.append({
                        "时间": item.get("time", item.get("date", "")),
                        "主力净流入": float(item.get("main_net", 0) or 0),
                        "小单净流入": float(item.get("small", 0) or 0),
                        "中单净流入": float(item.get("mid", 0) or 0),
                        "大单净流入": float(item.get("large", 0) or 0),
                        "超大单净流入": float(item.get("super_large", 0) or 0),
                    })
                if not rows:
                    for item in history:
                        rows.append({
                            "日期": item.get("date", item.get("time", "")),
                            "主力净流入": float(item.get("main_net", 0) or 0),
                            "小单净流入": float(item.get("small", 0) or 0),
                            "中单净流入": float(item.get("mid", 0) or 0),
                            "大单净流入": float(item.get("large", 0) or 0),
                            "超大单净流入": float(item.get("super_large", 0) or 0),
                        })
            if not rows:
                return df_to_json(pd.DataFrame([{
                    "代码": symbol,
                    "提示": "该股票暂无资金流向数据",
                }]))
            df = pd.DataFrame(rows)
            result_json = df_to_json(df, max_rows=30)
            cache.set(cache_key, result_json, TTL_DAILY)
            return result_json
        except Exception as e:
            return df_to_json(pd.DataFrame([{
                "代码": symbol,
                "提示": f"资金流向暂时不可用: {e}",
            }]))

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
        cache_key = "north_bound_flow"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            result, _src = _router.route("northbound", include_history=True)
            # ths_hsgt 源返回 dict；akshare 源返回 DataFrame
            if isinstance(result, pd.DataFrame):
                df = result
            elif isinstance(result, dict):
                # 同花顺返回的 dict 含 history 列表
                history = result.get("history") or []
                if not history:
                    return error_response(
                        "北向资金数据为空", "get_north_bound_flow"
                    )
                df = pd.DataFrame(history)
            else:
                return error_response(
                    "北向资金数据为空", "get_north_bound_flow"
                )

            if df is None or df.empty:
                return error_response(
                    "北向资金数据为空", "get_north_bound_flow"
                )
            for col in ["日期", "date", "时间", "time"]:
                if col in df.columns:
                    df = df.sort_values(col, ascending=False)
                    break
            df = slim_df(df)
            result_json = df_to_json(df, max_rows=30)
            cache.set(cache_key, result_json, TTL_DAILY)
            return result_json
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
        cache_key = f"limit_pool:{direction}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            df, _src = _router.route("hot_stocks", direction=direction)
            result = df_to_json(df)
            cache.set(cache_key, result, TTL_DAILY)
            return result
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
        cache_key = f"dragon_tiger:{num_days}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            # code="" → 返回全市场龙虎榜明细 DataFrame（akshare 源）
            result, _src = _router.route(
                "dragon_tiger", code="", look_back_days=num_days * 2
            )
            # dragon_tiger with code="" 返回原始 DataFrame
            if isinstance(result, pd.DataFrame):
                df = result
            else:
                return error_response(
                    "龙虎榜数据格式异常", "get_dragon_tiger"
                )
            df = slim_df(df)
            result_json = df_to_json(df, max_rows=30)
            cache.set(cache_key, result_json, TTL_DAILY)
            return result_json
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
        cache_key = f"global_market_quote:{category}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            df, _src = _router.route("global_market_quote")
            if df is None or df.empty:
                return df_to_json(pd.DataFrame())

            if category:
                df = df[df["类别"] == category]

            result = df_to_json(df, max_rows=50)
            cache.set(cache_key, result, TTL_REALTIME)
            return result
        except Exception as e:
            return error_response(
                f"获取全球行情失败: {e}", "get_global_market_quote"
            )
