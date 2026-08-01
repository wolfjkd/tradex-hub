"""
Signal Data — 信号数据基础子模块 (signal_data_base)。

原 signal_data.py 拆分自 v3.0.0，本子模块承载信号数据基础工具：
涨停归因、解禁日历、概念归属、一致预期、技术指标。

TradingAgents-astock 移植层基础工具集。

v3.1.0 起：所有数据获取通过 SmartRouter.route() 路由，
不再直接 import astock_signals 数据源函数。

Tools (共 6 个):
  get_hot_stocks                - 涨停股票+主题归因（同花顺 editorial）
  get_lockup_expiry             - 限售解禁日历（东财 datacenter）
  get_concept_attribution       - 个股概念板块归属（东财 push2delay）
  get_profit_forecast           - 一致预期EPS/Forward PE/PEG（同花顺）
  get_technical_indicator       - 技术指标计算 MACD/RSI/Boll（stockstats）
  list_technical_indicators     - 列出所有支持的技术指标及说明
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
from mcp.server.fastmcp import FastMCP

from ..data_sources import get_router
from ..utils.cache import TTL_DAILY, cache
from ..utils.formatter import error_response, dict_to_json
from ..utils.symbol import normalize_symbol

_router = get_router()


def register(mcp: FastMCP):
    """Register signal data base tools with the MCP server."""

    @mcp.tool()
    async def get_hot_stocks(date: str = "") -> str:
        """
        获取涨停股票及主题归因（同花顺 editorial 人工标注）。

        返回当日涨停股票列表，含人工标注的上涨原因标签（如"算力租赁+AI政务"），
        以及主题频次统计。

        Args:
            date: 日期 YYYY-MM-DD，空字符串默认今天。

        Returns:
            涨停股票列表及主题归因 (JSON)，含股票代码/名称/涨幅/换手率/
            成交额/DDE净量/原因标签，以及主题频次 top20。
        """
        cache_key = f"hot_stocks:{date or 'today'}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            # hot_money 数据源: code="" → get_hot_stocks_json(date)
            result, _src = _router.route("hot_money", code="", date=date)
            output = dict_to_json(result)

            if len(result.get("stocks", [])) > 0:
                cache.set(cache_key, output, TTL_DAILY)

            return output
        except Exception as e:
            return error_response(
                f"获取涨停归因数据失败: {e}", "get_hot_stocks"
            )

    @mcp.tool()
    async def get_lockup_expiry(
        symbol: str,
        trade_date: str = "",
        forward_days: int = 90,
    ) -> str:
        """
        获取个股限售解禁日历。

        包含历史解禁记录和未来待解禁安排，自动计算累计解禁占比并提示风险。

        Args:
            symbol: 6位股票代码，如 "000858"。
            trade_date: 参考日期 YYYY-MM-DD，空字符串默认今天。
            forward_days: 向前查询天数，默认90天。

        Returns:
            解禁日历 (JSON)，含历史记录和待解禁列表，以及风险提示。
        """
        symbol = normalize_symbol(symbol)
        if not trade_date or trade_date.strip() == "":
            trade_date = datetime.now().strftime("%Y-%m-%d")

        cache_key = f"lockup:{symbol}:{trade_date}:{forward_days}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            data, _src = _router.route(
                "lockup_expiry",
                symbol=symbol,
                trade_date=trade_date,
                forward_days=forward_days,
            )
            output = dict_to_json(data)
            cache.set(cache_key, output, TTL_DAILY)
            return output
        except Exception as e:
            return error_response(
                f"获取解禁日历失败: {e}", "get_lockup_expiry"
            )

    @mcp.tool()
    async def get_concept_attribution(symbol: str) -> str:
        """
        获取个股所属概念/行业/地域板块。

        显示股票归属于哪些概念板块、行业分类和地域板块，
        每个板块含当日涨跌幅。主力源：东方财富，备用源：百度股市通。

        Args:
            symbol: 6位股票代码，如 "688017"。

        Returns:
            概念归属数据 (JSON)，含概念/行业/地域三个维度的板块列表。
        """
        symbol = normalize_symbol(symbol)
        cache_key = f"concept_attribution:{symbol}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            data, _src = _router.route("concept_attribution", symbol=symbol)
            output = dict_to_json(data)
            if data.get("source"):
                cache.set(cache_key, output, TTL_DAILY)
            return output
        except Exception as e:
            return error_response(
                f"获取概念归属失败: {e}", "get_concept_attribution"
            )

    @mcp.tool()
    async def get_profit_forecast(symbol: str) -> str:
        """
        获取分析师一致预期EPS及Forward PE/PEG估值。

        基于同花顺分析师一致预期数据，计算Forward PE、PEG、
        以及PE消化年限（PEG估值框架）。

        主源：同花顺 basic.10jqka 抓取；备源：腾讯实时价格/PE。

        Args:
            symbol: 6位股票代码，如 "600519"。

        Returns:
            一致预期数据 (JSON)，含FY年份/EPS均值/预测机构数/
            Forward PE/PEG/PE消化年限。
        """
        symbol = normalize_symbol(symbol)
        cache_key = f"profit_forecast:{symbol}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            result, _src = _router.route("profit_forecast", symbol=symbol)
            output = dict_to_json(result)
            cache.set(cache_key, output, TTL_DAILY)
            return output
        except Exception as e:
            return error_response(
                f"获取一致预期失败: {e}", "get_profit_forecast"
            )

    @mcp.tool()
    async def get_technical_indicator(
        symbol: str,
        indicator: str,
        curr_date: str = "",
        look_back_days: int = 30,
    ) -> str:
        """
        计算个股技术指标。

        支持 MACD、RSI、布林带、ATR、SMA、EMA、VWMA、MFI 等 13 种常用指标。
        底层使用 stockstats 标准库计算，OHLCV 数据通过 SmartRouter 获取。

        Args:
            symbol: 6位股票代码，如 "600519"。
            indicator: 指标名称，可选: macd, macds, macdh, rsi,
                       boll, boll_ub, boll_lb, atr, vwma, mfi,
                       close_50_sma, close_200_sma, close_10_ema。
            curr_date: 参考日期 YYYY-MM-DD，空字符串默认今天。
            look_back_days: 回溯天数，默认30天。

        Returns:
            技术指标值 (JSON)，含日期和指标值列表。
        """
        import json as _json

        symbol = normalize_symbol(symbol)
        if not curr_date or curr_date.strip() == "":
            curr_date = datetime.now().strftime("%Y-%m-%d")

        # L2 计算模块延迟导入（非数据源，是纯计算/元数据函数）
        from astock_signals.indicators import (
            calculate_indicators,
            get_supported_indicators,
            get_indicator_description,
        )

        if indicator not in get_supported_indicators():
            return error_response(
                f"不支持的指标 '{indicator}'。可选: {get_supported_indicators()}",
                "get_technical_indicator",
            )

        cache_key = f"indicator:{symbol}:{indicator}:{curr_date}:{look_back_days}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            # 通过 SmartRouter 获取 OHLCV 数据
            fetch_trading_days = look_back_days + 60
            fetch_calendar_days = int(fetch_trading_days * 1.5) + 30
            start_date = (
                datetime.now() - timedelta(days=fetch_calendar_days)
            ).strftime("%Y%m%d")
            end_date = datetime.now().strftime("%Y%m%d")

            df, _src = _router.route(
                "historical_kline",
                symbol=symbol,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="qfq",
            )

            if df is None or df.empty:
                return error_response(
                    f"无 {indicator} 数据 ({symbol})", "get_technical_indicator"
                )

            # 列名标准化（中文 → 英文，兼容多数据源）
            col_map = {
                "日期": "Date", "开盘": "Open", "最高": "High",
                "最低": "Low", "收盘": "Close", "成交量": "Volume",
                "date": "Date", "open": "Open", "high": "High",
                "low": "Low", "close": "Close", "volume": "Volume",
            }
            df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
            needed = ["Date", "Open", "High", "Low", "Close", "Volume"]
            df = df[[c for c in needed if c in df.columns]]

            if "Date" in df.columns:
                df["Date"] = pd.to_datetime(df["Date"])
            for col in ["Open", "High", "Low", "Close", "Volume"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            if "Date" in df.columns:
                df = df.sort_values("Date").reset_index(drop=True)
            if len(df) > look_back_days:
                df = df.iloc[-look_back_days:]

            result_df = calculate_indicators(df, indicator, look_back_days)

            if result_df.empty:
                return error_response(
                    f"无 {indicator} 数据 ({symbol})", "get_technical_indicator"
                )

            data = {
                "symbol": symbol,
                "indicator": indicator,
                "indicator_desc": get_indicator_description(indicator),
                "curr_date": curr_date,
                "look_back_days": look_back_days,
                "values": [],
            }
            for _, row in result_df.iterrows():
                data["values"].append({
                    "date": str(row["Date"])[:10],
                    "value": row[indicator],
                })

            output = _json.dumps(data, ensure_ascii=False)
            cache.set(cache_key, output, TTL_DAILY)
            return output

        except Exception as e:
            return error_response(
                f"计算技术指标失败: {e}", "get_technical_indicator"
            )

    @mcp.tool()
    async def list_technical_indicators() -> str:
        """
        列出所有支持的技术指标及其说明。

        Returns:
            指标列表 (JSON)，含指标名称和中文说明。
        """
        # L2 元数据延迟导入（非数据源）
        from astock_signals.indicators import (
            get_supported_indicators,
            get_indicator_description,
        )

        result = []
        for name in get_supported_indicators():
            result.append({
                "name": name,
                "description": get_indicator_description(name),
            })
        return dict_to_json(result)
