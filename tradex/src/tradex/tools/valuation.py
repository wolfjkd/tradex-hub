"""
Category 4: Valuation & Analysis (V0.2)

Tools:
  17. get_valuation_metrics      - Historical PE/PB/PS ratios
  18. get_dividend_data          - Dividend history
  19. get_institutional_holdings - Institutional shareholder data
  20. get_analyst_rating         - Analyst forecasts and ratings
"""

from __future__ import annotations

import akshare as ak
from mcp.server.fastmcp import FastMCP

import pandas as pd
from ..utils.cache import TTL_DAILY, TTL_FINANCIAL, cache
from ..utils.formatter import df_to_json, error_response, slim_df
from ..utils.symbol import normalize_symbol


def register(mcp: FastMCP):
    """Register valuation tools with the MCP server."""

    @mcp.tool()
    async def get_valuation_metrics(
        symbol: str,
        num_periods: int = 100,
    ) -> str:
        """
        获取股票历史估值指标（PE、PB、PS等市盈率/市净率/市销率时间序列）。

        可用于估值分析、历史百分位计算、可比公司估值对比等。

        Args:
            symbol: 6位股票代码，如 "600519"
            num_periods: 返回最近几个交易日的数据，默认100

        Returns:
            估值指标时间序列 (JSON)，包含日期、PE、PB、PS、总市值、
            流通市值等。
        """
        symbol = normalize_symbol(symbol)
        cache_key = f"valuation:{symbol}:{num_periods}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            # stock_a_lg_indicator has been removed from akshare;
            # use stock_zh_valuation_baidu which provides PE/PB/总市值 etc.
            indicators = ["总市值", "市盈率(TTM)", "市净率", "市销率(TTM)"]
            frames = []
            for ind in indicators:
                try:
                    df = ak.stock_zh_valuation_baidu(
                        symbol=symbol, indicator=ind, period="近一年"
                    )
                    if df is not None and not df.empty:
                        # Rename value column to indicator name
                        if "value" in df.columns:
                            df = df.rename(columns={"value": ind})
                        elif len(df.columns) == 2:
                            df.columns = ["date", ind]
                        frames.append(df)
                except Exception:
                    continue

            if not frames:
                return error_response(
                    f"估值指标数据为空 ({symbol})", "get_valuation_metrics"
                )

            # Merge all indicators on date
            result_df = frames[0]
            for f in frames[1:]:
                date_col = result_df.columns[0]
                f_date_col = f.columns[0]
                if date_col != f_date_col:
                    f = f.rename(columns={f_date_col: date_col})
                result_df = pd.merge(result_df, f, on=date_col, how="outer")

            result_df = result_df.sort_values(result_df.columns[0], ascending=False)
            if num_periods > 0:
                result_df = result_df.head(num_periods)
            result = df_to_json(result_df)
            cache.set(cache_key, result, TTL_DAILY)
            return result
        except Exception as e:
            return error_response(
                f"获取估值指标失败 ({symbol}): {e}", "get_valuation_metrics"
            )

    @mcp.tool()
    async def get_dividend_data(symbol: str) -> str:
        """
        获取股票历史分红派息详情。

        Args:
            symbol: 6位股票代码，如 "600519"

        Returns:
            分红历史 (JSON)，包含分红年度、每股派息、除权日、股权登记日等。
        """
        symbol = normalize_symbol(symbol)
        cache_key = f"dividend:{symbol}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        # Primary: stock_history_dividend_detail
        try:
            df = ak.stock_history_dividend_detail(
                symbol=symbol, indicator="分红"
            )
            if df is not None and not df.empty:
                result = df_to_json(df)
                cache.set(cache_key, result, TTL_FINANCIAL)
                return result
        except Exception:
            pass

        # Fallback: stock_dividend_cninfo (巨潮信息网)
        try:
            df = ak.stock_dividend_cninfo(symbol=symbol)
            if df is not None and not df.empty:
                result = df_to_json(df)
                cache.set(cache_key, result, TTL_FINANCIAL)
                return result
        except Exception:
            pass

        return error_response(
            f"获取分红数据失败 ({symbol}): 所有数据源均不可用",
            "get_dividend_data",
        )

    @mcp.tool()
    async def get_institutional_holdings(symbol: str) -> str:
        """
        获取机构持股/十大流通股东数据。

        Args:
            symbol: 6位股票代码，如 "600519"

        Returns:
            流通股东数据 (JSON)，包含股东名称、持股数量、持股比例、
            变动情况等。
        """
        symbol = normalize_symbol(symbol)
        cache_key = f"institutions:{symbol}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            df = ak.stock_circulate_stock_holder(symbol=symbol)
            if df is None or df.empty:
                return error_response(
                    f"机构持股数据为空 ({symbol})", "get_institutional_holdings"
                )
            df = slim_df(df)
            result = df_to_json(df)
            cache.set(cache_key, result, TTL_FINANCIAL)
            return result
        except Exception as e:
            return error_response(
                f"获取机构持股失败 ({symbol}): {e}", "get_institutional_holdings"
            )

    @mcp.tool()
    async def get_analyst_rating(
        symbol: str = "",
        num_results: int = 20,
    ) -> str:
        """
        获取分析师评级和盈利预测数据。

        可查询特定股票的分析师评级，或获取全市场最新评级列表。

        Args:
            symbol: 6位股票代码，如 "600519"。为空则返回全市场最新评级。
            num_results: 最大返回条数，默认20

        Returns:
            分析师评级数据 (JSON)，包含评级机构、目标价、评级、
            预测EPS等。
        """
        cache_key = f"analyst:{symbol}:{num_results}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            df = ak.stock_rank_forecast_cninfo()
            if symbol:
                symbol = normalize_symbol(symbol)
                # Filter for the specific stock
                code_cols = [c for c in df.columns if "代码" in c or "code" in c.lower()]
                if code_cols:
                    df = df[df[code_cols[0]].astype(str).str.contains(symbol)]

            df = df.head(num_results)
            df = slim_df(df)
            result = df_to_json(df)
            cache.set(cache_key, result, TTL_DAILY)
            return result
        except Exception as e:
            return error_response(
                f"获取分析师评级失败 ({symbol}): {e}", "get_analyst_rating"
            )
