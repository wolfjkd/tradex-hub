"""
Category 2: Price & Quote Data (V0.1)

Tools:
  5. get_realtime_quote       - Real-time quote (A-share + global codes, v3.3.1)
  6. get_historical_price     - Historical OHLCV (daily/weekly/monthly)
  7. get_intraday_data        - Intraday minute data (today)
  8. get_market_capitalization - Total & free-float market cap
  9. get_stock_list            - Full A-share list with basic data

Data source routing (via SmartRouter):
  实时行情(A股): eltdx(priority=1) → akshare(priority=100) → tencent_http(priority=200)
  实时行情(全球): tencent_http(priority=1)  [global_market_quote]
  历史K线:  eltdx(priority=1) → akshare(priority=100)
  分时数据: eltdx(priority=1) → akshare(priority=100)
  股票列表: akshare(全量行情快照)

v3.4.0 工单 04：get_realtime_quote / get_historical_price / get_intraday_data 三个
核心工具的业务逻辑已抽到 service/price_service.py，本文件这三个工具改为薄包装
（调 service + json.dumps 转 MCP 协议字符串）。
get_market_capitalization / get_stock_list 暂未抽层（不在工单 04 范围），保留原逻辑。
"""

from __future__ import annotations

import json
import logging

from mcp.server.fastmcp import FastMCP

from ..data_sources import get_router
from ..utils.cache import TTL_DAILY, TTL_REALTIME, cache
from ..utils.formatter import df_to_json, dict_to_json, error_response, slim_df
from ..utils.symbol import format_with_exchange, normalize_symbol
from ..service import price_service

logger = logging.getLogger("tradex")

_router = get_router()


def register(mcp: FastMCP):
    """Register price data tools with the MCP server.

    v3.4.0：三个核心工具改为 service 薄包装；市值/列表工具保留原逻辑（工单 04 外）。
    """

    @mcp.tool()
    async def get_realtime_quote(symbol: str) -> str:
        """
        获取实时行情数据。支持A股6位代码和全球行情代码。

        **A股代码**：6位数字，如 "600519"（贵州茅台）、"000001"（平安银行）。

        **全球行情代码**：
        - 美股指数：usDJI（道琼斯）、usIXIC（纳斯达克）、usINX（标普500）
        - 热门美股：usNVDA（英伟达）、usTSLA（特斯拉）、usAAPL（苹果）、usMSFT（微软）、usAMZN（亚马逊）、usGOOGL（谷歌）、usMETA（Meta）、usMU（美光科技）、usAMAT（应用材料）
        - 亚太指数：hkHSI（恒生指数）、hkHSTECH（恒生科技）
        - 韩股：kr005930（三星电子）、kr000660（SK海力士）
        - 外汇：whDINIW（美元指数）

        Args:
            symbol: 股票代码，A股为6位数字，全球行情使用前缀代码

        Returns:
            实时行情数据 (JSON)，包含最新价、涨跌幅、成交量、成交额、
            最高价、最低价、开盘价、昨收价、换手率、市盈率、市净率等。
        """
        try:
            result = price_service.get_realtime_quote(symbol=symbol)
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(
                f"获取实时行情失败 ({symbol}): {e}", "get_realtime_quote"
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
        try:
            result = price_service.get_historical_price(
                symbol=symbol,
                period=period,
                start_date=start_date,
                end_date=end_date,
                adjust=adjust,
            )
            return json.dumps(result, ensure_ascii=False)
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
        try:
            result = price_service.get_intraday_data(symbol=symbol)
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(
                f"获取分时数据失败 ({symbol}): {e}", "get_intraday_data"
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

        # === Tier 1: 个股基本信息（含市值） ===
        try:
            df, _src = _router.route(
                "company_info", endpoint="individual_info", symbol=symbol
            )
            if df is not None and not df.empty:
                info = {}
                for _, row in df.iterrows():
                    info[row.iloc[0]] = row.iloc[1]
                if any("市值" in str(k) for k in info):
                    result = dict_to_json(info)
                    cache.set(cache_key, result, TTL_REALTIME)
                    return result
        except Exception as exc:
            logger.debug("市值 Tier1(实时快照) 失败(%s): %s", symbol, exc)

        # === Tier 2: 全量行情快照 ===
        try:
            df, _src = _router.route("realtime_quote", symbol=symbol)
            if df is not None and not df.empty:
                code_col = _find_code_col(df)
                if len(df) > 1:
                    row = df[df[code_col].astype(str).str.strip() == symbol]
                else:
                    row = df
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
        except Exception as exc:
            logger.debug("市值 Tier2(全量行情) 失败(%s): %s", symbol, exc)

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
            # symbol="" → eltdx 单股源会失败，SmartRouter 自动降级到 akshare 全量快照
            df, _src = _router.route("realtime_quote", symbol="")
            if df is None or df.empty:
                return error_response(
                    "获取股票列表失败: 数据源返回空数据", "get_stock_list"
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


def _is_global_code(symbol: str) -> bool:
    """检测是否为全球行情代码（非A股6位数字代码）。

    v3.4.0：service/price_service.py 有同名函数副本（保持工具与 service 解耦）。
    本函数仍被本文件未抽层的 get_market_capitalization 使用，保留。
    """
    return symbol.startswith(("us", "hk", "kr", "wh", "int_", "hf_"))


def _find_code_col(df) -> str:
    """Find the stock code column in a DataFrame (varies by data source).

    v3.4.0：service/price_service.py 有同名函数副本（保持工具与 service 解耦）。
    本函数仍被本文件未抽层的 get_market_capitalization 使用，保留。
    """
    for c in df.columns:
        if c in ("代码", "code", "symbol"):
            return c
        if "代码" in c or "code" in c.lower() or "symbol" in c.lower():
            return c
    return df.columns[0]
