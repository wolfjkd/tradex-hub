"""
Category 2: Price & Quote Data (V0.1)

Tools:
  5. get_realtime_quote       - Real-time A-share quote
  6. get_historical_price     - Historical OHLCV (daily/weekly/monthly)
  7. get_intraday_data        - Intraday minute data (today)
  8. get_market_capitalization - Total & free-float market cap
  9. get_stock_list            - Full A-share list with basic data

Data source fallback chain:
  实时行情: 东方财富(push2) → 新浪全量 → 新浪单股(stock_zh_a_daily)
  历史K线:  东方财富 → 腾讯(stock_zh_a_hist_tx)
  分时数据:  东方财富(stock_intraday_em) → eltdx(minutes.today)
  股票列表: 东方财富 → 新浪全量
"""

from __future__ import annotations

import logging

import akshare as ak
from mcp.server.fastmcp import FastMCP

from ..utils.cache import TTL_DAILY, TTL_REALTIME, cache
from ..utils.fallback import call_with_fallback
from ..utils.formatter import df_to_json, error_response, slim_df
from ..utils.symbol import format_with_exchange, normalize_symbol

logger = logging.getLogger("tradex")


def register(mcp: FastMCP):
    """Register price data tools with the MCP server."""

    @mcp.tool()
    async def get_realtime_quote(symbol: str) -> str:
        """
        获取A股股票实时行情数据。

        Args:
            symbol: 6位股票代码，如 "000001"（平安银行）、"600519"（贵州茅台）

        Returns:
            实时行情数据 (JSON)，包含最新价、涨跌幅、成交量、成交额、
            最高价、最低价、开盘价、昨收价、换手率、市盈率、市净率等。
        """
        symbol = normalize_symbol(symbol)
        cache_key = f"realtime_quote:{symbol}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        # === Tier 1 & 2: 全量行情接口 ===
        try:
            df = await call_with_fallback(
                ("东方财富", ak.stock_zh_a_spot_em, {}),
                ("新浪财经", ak.stock_zh_a_spot, {}),
            )
            code_col = _find_code_col(df)
            row = df[df[code_col].astype(str).str.strip() == symbol]
            if not row.empty:
                result = df_to_json(row)
                cache.set(cache_key, result, TTL_REALTIME)
                return result
        except Exception:
            pass

        # === Tier 3: 新浪单股日线 (当天数据) ===
        try:
            ex_symbol = format_with_exchange(symbol)  # e.g. "sh600519"
            df = ak.stock_zh_a_daily(symbol=ex_symbol)
            if df is not None and not df.empty:
                row = df.tail(1)
                logger.debug(f"[新浪单股] 成功, 返回最新日数据 ({symbol})")
                result = df_to_json(row)
                cache.set(cache_key, result, TTL_REALTIME)
                return result
        except Exception:
            pass

        return error_response(
            f"获取实时行情失败 ({symbol}): 所有数据源均不可用", "get_realtime_quote"
        )

    @mcp.tool()
    async def get_historical_price(
        symbol: str,
        period: str = "daily",
        start_date: str = "",
        end_date: str = "",
        adjust: str = "qfq",
    ) -> str:
        """
        获取A股股票历史K线数据 (OHLCV)。

        Args:
            symbol: 6位股票代码，如 "600519"
            period: K线周期，可选 "daily"（日线）, "weekly"（周线）, "monthly"（月线）
            start_date: 开始日期，格式 "YYYYMMDD"，如 "20240101"。默认为空返回所有数据。
            end_date: 结束日期，格式 "YYYYMMDD"，如 "20241231"。默认为空返回至今。
            adjust: 复权类型，"qfq"（前复权）, "hfq"（后复权）, ""（不复权）

        Returns:
            K线数据 (JSON)，包含日期、开盘价、收盘价、最高价、最低价、
            成交量、成交额、振幅、涨跌幅、涨跌额、换手率。
        """
        symbol = normalize_symbol(symbol)
        cache_key = f"hist_price:{symbol}:{period}:{start_date}:{end_date}:{adjust}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            # Primary: 东方财富
            em_kwargs: dict = {
                "symbol": symbol,
                "period": period,
                "adjust": adjust,
            }
            if start_date:
                em_kwargs["start_date"] = start_date
            if end_date:
                em_kwargs["end_date"] = end_date

            # Fallback: 腾讯 (needs sh/sz prefix)
            tx_symbol = format_with_exchange(symbol)
            tx_kwargs: dict = {
                "symbol": tx_symbol,
                "adjust": adjust,
            }
            if start_date:
                tx_kwargs["start_date"] = start_date
            if end_date:
                tx_kwargs["end_date"] = end_date

            df = await call_with_fallback(
                ("东方财富", ak.stock_zh_a_hist, em_kwargs),
                ("腾讯", ak.stock_zh_a_hist_tx, tx_kwargs),
            )
            result = df_to_json(df, max_rows=500)
            cache.set(cache_key, result, TTL_DAILY)
            return result
        except Exception as e:
            return error_response(
                f"获取历史K线失败 ({symbol}): {e}", "get_historical_price"
            )

    @mcp.tool()
    async def get_intraday_data(symbol: str) -> str:
        """
        获取A股股票当日分时数据（1分钟K线）。

        返回当天从开盘到当前的每分钟价格、均价、成交量数据，
        可用于绘制分时图。

        Args:
            symbol: 6位股票代码，如 "600519"

        Returns:
            分时数据 (JSON)，包含时间、价格、均价、成交量。
        """
        symbol = normalize_symbol(symbol)
        cache_key = f"intraday:{symbol}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            df = ak.stock_intraday_em(symbol=symbol)
            if df is not None and not df.empty:
                col_map = {
                    "时间": "time", "time": "time",
                    "开盘": "open", "open": "open",
                    "收盘": "close", "close": "close", "价格": "close", "price": "close",
                    "最高": "high", "high": "high",
                    "最低": "low", "low": "low",
                    "均价": "avg_price", "avg_price": "avg_price",
                    "成交量": "volume", "volume": "volume",
                    "成交额": "amount", "amount": "amount",
                }
                
                df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
                
                points = []
                for _, row in df.iterrows():
                    time_val = str(row.get("time", ""))
                    price_val = float(row.get("close", row.get("price", 0)))
                    avg_val = float(row.get("avg_price", 0))
                    vol_val = int(row.get("volume", 0))
                    
                    if time_val and price_val > 0:
                        points.append({
                            "time": time_val,
                            "price": price_val,
                            "avg_price": avg_val,
                            "volume": vol_val,
                        })
                
                if points:
                    data = {
                        "code": symbol,
                        "point_count": len(points),
                        "points": points,
                    }
                    from ..utils.formatter import dict_to_json
                    result_json = dict_to_json(data)
                    cache.set(cache_key, result_json, TTL_REALTIME)
                    return result_json
        except Exception as e:
            logger.debug(f"东方财富分时数据失败: {e}")

        try:
            from .eltdx_data import _get_client, _normalize_code

            client = _get_client()
            if client is not None:
                norm_code = _normalize_code(symbol)
                result = client.minutes.today(norm_code)
                points = getattr(result, "points", None) or []
                if points:
                    data = {
                        "code": norm_code,
                        "point_count": len(points),
                        "points": [
                            {
                                "time": getattr(p, "time_label", None) or getattr(p, "time", None),
                                "price": getattr(p, "price", None),
                                "avg_price": getattr(p, "avg_price", None),
                                "volume": getattr(p, "volume", None),
                            }
                            for p in points
                        ],
                    }
                    from ..utils.formatter import dict_to_json
                    result_json = dict_to_json(data)
                    cache.set(cache_key, result_json, TTL_REALTIME)
                    return result_json
        except Exception as e:
            logger.debug(f"eltdx分时数据失败: {e}")

        return error_response(
            f"获取分时数据失败 ({symbol}): 所有数据源均不可用", "get_intraday_data"
        )

    @mcp.tool()
    async def get_market_capitalization(symbol: str) -> str:
        """
        获取A股股票的总市值和流通市值。

        Args:
            symbol: 6位股票代码，如 "600519"

        Returns:
            市值数据 (JSON)，包含总市值、流通市值、最新价、成交量等关键字段。
        """
        symbol = normalize_symbol(symbol)
        cache_key = f"market_cap:{symbol}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        # === Tier 1: 东方财富个股信息 (emweb, not push2, reliable) ===
        try:
            df = ak.stock_individual_info_em(symbol=symbol)
            info = {}
            for _, row in df.iterrows():
                info[row.iloc[0]] = row.iloc[1]
            # Check if it has market cap data
            if any("市值" in str(k) for k in info):
                from ..utils.formatter import dict_to_json
                result = dict_to_json(info)
                cache.set(cache_key, result, TTL_REALTIME)
                return result
        except Exception:
            pass

        # === Tier 2 & 3: 全量行情 ===
        try:
            df = await call_with_fallback(
                ("东方财富", ak.stock_zh_a_spot_em, {}),
                ("新浪财经", ak.stock_zh_a_spot, {}),
            )
            code_col = _find_code_col(df)
            row = df[df[code_col].astype(str).str.strip() == symbol]
            if not row.empty:
                cap_keywords = ["代码", "名称", "最新价", "总市值", "流通市值",
                                "涨跌幅", "成交量", "成交额", "市盈率", "市净率",
                                "code", "name", "trade", "volume", "amount",
                                "changepercent", "settlement", "mktcap"]
                available_cols = [
                    c for c in row.columns
                    if any(k in c for k in cap_keywords)
                ]
                if not available_cols:
                    available_cols = list(row.columns)
                result = df_to_json(row[available_cols])
                cache.set(cache_key, result, TTL_REALTIME)
                return result
        except Exception:
            pass

        return error_response(
            f"获取市值数据失败 ({symbol}): 所有数据源均不可用",
            "get_market_capitalization",
        )

    @mcp.tool()
    async def get_stock_list(
        min_market_cap: float = 0,
        max_results: int = 50,
    ) -> str:
        """
        获取A股完整股票列表，附带行情摘要信息。可按市值筛选。

        Args:
            min_market_cap: 最低总市值过滤（单位：亿元），默认0不过滤。如传入100则只返回市值>=100亿的股票。
            max_results: 最大返回条数，默认50。

        Returns:
            股票列表 (JSON)，包含代码、名称、最新价、涨跌幅、总市值、流通市值、
            成交量、成交额、市盈率、市净率等。
        """
        cache_key = f"stock_list:{min_market_cap}:{max_results}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            # Primary: 东方财富, Fallback: 新浪
            df = await call_with_fallback(
                ("东方财富", ak.stock_zh_a_spot_em, {}),
                ("新浪财经", ak.stock_zh_a_spot, {}),
            )

            cap_col = None
            for c in df.columns:
                if "总市值" in c or "mktcap" in c.lower() or "market_cap" in c.lower():
                    cap_col = c
                    break

            if min_market_cap > 0 and cap_col:
                threshold = min_market_cap * 1e8
                df = df[df[cap_col] >= threshold]

            if cap_col:
                df = df.sort_values(cap_col, ascending=False)

            df = slim_df(df)
            result = df_to_json(df, max_rows=max_results)
            cache.set(cache_key, result, TTL_DAILY)
            return result
        except Exception as e:
            return error_response(f"获取股票列表失败: {e}", "get_stock_list")


def _find_code_col(df) -> str:
    """Find the stock code column in a DataFrame (varies by data source)."""
    for c in df.columns:
        if c in ("代码", "code", "symbol"):
            return c
        if "代码" in c or "code" in c.lower() or "symbol" in c.lower():
            return c
    return df.columns[0]
