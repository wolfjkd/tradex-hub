"""
Category 3: Financial Statements (V0.2)

Tools:
  9.  get_income_statement      - Quarterly income statement
  10. get_balance_sheet         - Quarterly balance sheet
  11. get_cash_flow_statement   - Quarterly cash flow statement
  12. get_financial_line_item   - Extract specific line items
  13. get_financial_indicators  - Key financial ratios (ROE, margins, etc.)
  14. get_growth_rates          - Revenue/profit growth rates
  15. get_per_share_data        - EPS, BPS, CFPS, etc.
  16. get_segments_revenue      - Revenue breakdown by business segment
"""

from __future__ import annotations

import akshare as ak
from mcp.server.fastmcp import FastMCP

from ..utils.cache import TTL_FINANCIAL, cache
from ..utils.formatter import (
    BALANCE_SHEET_COLS,
    CASHFLOW_STATEMENT_COLS,
    INCOME_STATEMENT_COLS,
    df_to_json,
    error_response,
    slim_df,
    slim_financial_df,
)
from ..utils.symbol import format_em_symbol, normalize_symbol


def register(mcp: FastMCP):
    """Register financial statement tools with the MCP server."""

    @mcp.tool()
    async def get_income_statement(
        symbol: str,
        num_quarters: int = 8,
    ) -> str:
        """
        获取利润表（按季度）。

        Args:
            symbol: 6位股票代码，如 "600519"
            num_quarters: 返回最近几个季度的数据，默认8个季度（2年）

        Returns:
            利润表数据 (JSON)，包含营业收入、营业成本、毛利润、净利润、
            研发费用、销售费用、管理费用等字段。
        """
        symbol = normalize_symbol(symbol)
        em_symbol = format_em_symbol(symbol)
        cache_key = f"income_stmt:{symbol}:{num_quarters}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            df = ak.stock_profit_sheet_by_quarterly_em(symbol=em_symbol)
            if df is None or df.empty:
                return error_response(
                    f"利润表数据为空 ({symbol})", "get_income_statement"
                )
            if num_quarters > 0:
                df = df.head(num_quarters)
            df = slim_financial_df(df, INCOME_STATEMENT_COLS)
            result = df_to_json(df)
            cache.set(cache_key, result, TTL_FINANCIAL)
            return result
        except Exception as e:
            return error_response(
                f"获取利润表失败 ({symbol}): {e}", "get_income_statement"
            )

    @mcp.tool()
    async def get_balance_sheet(
        symbol: str,
        num_quarters: int = 8,
    ) -> str:
        """
        获取资产负债表（按季度）。

        Args:
            symbol: 6位股票代码，如 "600519"
            num_quarters: 返回最近几个季度的数据，默认8个季度

        Returns:
            资产负债表数据 (JSON)，包含总资产、总负债、股东权益、
            流动资产、非流动资产、存货、应收账款等。
        """
        symbol = normalize_symbol(symbol)
        em_symbol = format_em_symbol(symbol)
        cache_key = f"balance_sheet:{symbol}:{num_quarters}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            # stock_balance_sheet_by_quarterly_em has been removed;
            # use stock_balance_sheet_by_report_em instead (按报告期).
            df = ak.stock_balance_sheet_by_report_em(symbol=em_symbol)
            if df is None or df.empty:
                return error_response(
                    f"资产负债表数据为空 ({symbol})", "get_balance_sheet"
                )
            if num_quarters > 0:
                df = df.head(num_quarters)
            df = slim_financial_df(df, BALANCE_SHEET_COLS)
            result = df_to_json(df)
            cache.set(cache_key, result, TTL_FINANCIAL)
            return result
        except Exception as e:
            return error_response(
                f"获取资产负债表失败 ({symbol}): {e}", "get_balance_sheet"
            )

    @mcp.tool()
    async def get_cash_flow_statement(
        symbol: str,
        num_quarters: int = 8,
    ) -> str:
        """
        获取现金流量表（按季度）。

        Args:
            symbol: 6位股票代码，如 "600519"
            num_quarters: 返回最近几个季度的数据，默认8个季度

        Returns:
            现金流量表数据 (JSON)，包含经营活动现金流、投资活动现金流、
            筹资活动现金流、自由现金流等。
        """
        symbol = normalize_symbol(symbol)
        em_symbol = format_em_symbol(symbol)
        cache_key = f"cash_flow:{symbol}:{num_quarters}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            df = ak.stock_cash_flow_sheet_by_quarterly_em(symbol=em_symbol)
            if df is None or df.empty:
                return error_response(
                    f"现金流量表数据为空 ({symbol})", "get_cash_flow_statement"
                )
            if num_quarters > 0:
                df = df.head(num_quarters)
            df = slim_financial_df(df, CASHFLOW_STATEMENT_COLS)
            result = df_to_json(df)
            cache.set(cache_key, result, TTL_FINANCIAL)
            return result
        except Exception as e:
            return error_response(
                f"获取现金流量表失败 ({symbol}): {e}", "get_cash_flow_statement"
            )

    @mcp.tool()
    async def get_financial_line_item(
        symbol: str,
        item: str,
        num_quarters: int = 8,
    ) -> str:
        """
        从三大财务报表中提取特定财务科目的时间序列数据。

        Args:
            symbol: 6位股票代码，如 "600519"
            item: 要提取的科目名称，如 "营业总收入"、"净利润"、"基本每股收益"、
                  "经营活动产生的现金流量净额"、"总资产" 等。支持模糊匹配。
            num_quarters: 返回最近几个季度的数据，默认8个季度

        Returns:
            该科目的时间序列数据 (JSON)，包含报告期和对应值。
        """
        symbol = normalize_symbol(symbol)
        em_symbol = format_em_symbol(symbol)
        cache_key = f"line_item:{symbol}:{item}:{num_quarters}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            # Try each financial statement to find the item
            # Note: all EM financial APIs require exchange-prefixed symbol
            # We slim each statement first so the user can search by Chinese
            # name (e.g. "营业总收入") or English name (e.g. "NETPROFIT").
            statements = [
                ("利润表", ak.stock_profit_sheet_by_quarterly_em, INCOME_STATEMENT_COLS),
                ("资产负债表", ak.stock_balance_sheet_by_report_em, BALANCE_SHEET_COLS),
                ("现金流量表", ak.stock_cash_flow_sheet_by_quarterly_em, CASHFLOW_STATEMENT_COLS),
            ]

            for stmt_name, func, whitelist in statements:
                try:
                    df = func(symbol=em_symbol)
                except Exception:
                    continue
                if df is None or df.empty:
                    continue

                # Slim the DataFrame so columns are in clean Chinese
                slim = slim_financial_df(df, whitelist)

                # Search for matching columns (fuzzy match)
                matching_cols = [c for c in slim.columns if item in c]
                if not matching_cols:
                    # Also try case-insensitive match on original columns
                    raw_match = [c for c in df.columns if item.upper() in c.upper()]
                    if raw_match:
                        # Found in raw columns — extract with date
                        date_cols = [
                            c for c in df.columns
                            if "REPORT_DATE_NAME" in c.upper()
                        ]
                        keep = date_cols + raw_match
                        avail = [c for c in keep if c in df.columns]
                        sub = df[avail] if avail else df[raw_match]
                        if num_quarters > 0:
                            sub = sub.head(num_quarters)
                        result = df_to_json(slim_df(sub))
                        cache.set(cache_key, result, TTL_FINANCIAL)
                        return result
                    continue

                # Found in slimmed Chinese columns
                date_cols = [c for c in slim.columns if "报告期" in c]
                keep = date_cols + matching_cols
                avail = [c for c in keep if c in slim.columns]
                sub = slim[avail] if avail else slim[matching_cols]
                if num_quarters > 0:
                    sub = sub.head(num_quarters)
                result = df_to_json(sub)
                cache.set(cache_key, result, TTL_FINANCIAL)
                return result

            return error_response(
                f"在三大财务报表中未找到科目 '{item}'", "get_financial_line_item"
            )
        except Exception as e:
            return error_response(
                f"获取财务科目失败 ({symbol}, {item}): {e}",
                "get_financial_line_item",
            )

    @mcp.tool()
    async def get_financial_indicators(
        symbol: str,
        num_periods: int = 8,
    ) -> str:
        """
        获取财务分析指标（ROE、毛利率、净利率、资产负债率等）。

        Args:
            symbol: 6位股票代码，如 "600519"
            num_periods: 返回最近几期数据，默认8期

        Returns:
            财务指标数据 (JSON)，包含盈利能力、偿债能力、运营能力、
            成长能力等多维度指标。
        """
        symbol = normalize_symbol(symbol)
        cache_key = f"fin_indicators:{symbol}:{num_periods}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            df = ak.stock_financial_analysis_indicator(symbol=symbol)
            if df is None or df.empty:
                return error_response(
                    f"财务指标数据为空 ({symbol})", "get_financial_indicators"
                )
            if num_periods > 0:
                df = df.head(num_periods)
            df = slim_df(df)
            result = df_to_json(df)
            cache.set(cache_key, result, TTL_FINANCIAL)
            return result
        except Exception as e:
            return error_response(
                f"获取财务指标失败 ({symbol}): {e}", "get_financial_indicators"
            )

    @mcp.tool()
    async def get_growth_rates(
        symbol: str,
        num_periods: int = 8,
    ) -> str:
        """
        获取成长性指标（营收增长率、净利润增长率等）。

        Args:
            symbol: 6位股票代码，如 "600519"
            num_periods: 返回最近几期数据，默认8期

        Returns:
            成长性指标数据 (JSON)，包含各项增长率。
        """
        symbol = normalize_symbol(symbol)
        cache_key = f"growth_rates:{symbol}:{num_periods}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            df = ak.stock_financial_analysis_indicator(symbol=symbol)
            if df is None or df.empty:
                return error_response(
                    f"增长指标数据为空 ({symbol})", "get_growth_rates"
                )
            # Filter growth-related columns
            growth_cols = [
                c for c in df.columns
                if "增长" in c or "同比" in c or "环比" in c or "日期" in c or "报告" in c
            ]
            if growth_cols:
                df = df[growth_cols]
            if num_periods > 0:
                df = df.head(num_periods)
            df = slim_df(df)
            result = df_to_json(df)
            cache.set(cache_key, result, TTL_FINANCIAL)
            return result
        except Exception as e:
            return error_response(
                f"获取增长指标失败 ({symbol}): {e}", "get_growth_rates"
            )

    @mcp.tool()
    async def get_per_share_data(
        symbol: str,
        num_periods: int = 8,
    ) -> str:
        """
        获取每股指标（每股收益EPS、每股净资产BPS、每股现金流CFPS等）。

        Args:
            symbol: 6位股票代码，如 "600519"
            num_periods: 返回最近几期数据，默认8期

        Returns:
            每股指标数据 (JSON)，包含EPS、BPS、每股经营现金流等。
        """
        symbol = normalize_symbol(symbol)
        cache_key = f"per_share:{symbol}:{num_periods}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            df = ak.stock_financial_analysis_indicator(symbol=symbol)
            if df is None or df.empty:
                return error_response(
                    f"每股指标数据为空 ({symbol})", "get_per_share_data"
                )
            # Filter per-share columns
            share_cols = [
                c for c in df.columns
                if "每股" in c or "日期" in c or "报告" in c
            ]
            if share_cols:
                df = df[share_cols]
            if num_periods > 0:
                df = df.head(num_periods)
            df = slim_df(df)
            result = df_to_json(df)
            cache.set(cache_key, result, TTL_FINANCIAL)
            return result
        except Exception as e:
            return error_response(
                f"获取每股指标失败 ({symbol}): {e}", "get_per_share_data"
            )

    @mcp.tool()
    async def get_segments_revenue(symbol: str) -> str:
        """
        获取公司主营业务构成（按产品/地区分拆营收）。

        Args:
            symbol: 6位股票代码，如 "600519"

        Returns:
            主营构成数据 (JSON)，包含各业务板块的营收、占比、毛利率等。
        """
        symbol = normalize_symbol(symbol)
        cache_key = f"segments:{symbol}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            df = ak.stock_zygc_em(symbol=symbol)
            df = slim_df(df)
            result = df_to_json(df)
            cache.set(cache_key, result, TTL_FINANCIAL)
            return result
        except Exception as e:
            return error_response(
                f"获取主营构成失败 ({symbol}): {e}", "get_segments_revenue"
            )
