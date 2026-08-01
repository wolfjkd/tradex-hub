"""
Category 1: Company Information & Search (V0.1)

Tools:
  1. search_stock       - Search A-share stocks by name or code
  2. get_company_info   - Get company basic info (industry, market cap, shares)
  3. get_company_profile - Get company business description & revenue breakdown
  4. get_competitors    - Get peer companies in the same industry

Data source fallback:
  Primary: 东方财富 (eastmoney)
  Fallback: 新浪 (sina) — for list-based lookups
"""

from __future__ import annotations

import akshare as ak
from mcp.server.fastmcp import FastMCP

from ..utils.cache import TTL_COMPANY, cache
from ..utils.fallback import call_with_fallback
from ..utils.formatter import df_to_json, dict_to_json, error_response, slim_df
from ..utils.symbol import normalize_symbol


def register(mcp: FastMCP):
    """Register company information tools with the MCP server."""

    @mcp.tool()
    async def search_stock(keyword: str) -> str:
        """
        搜索A股股票，支持名称或代码模糊匹配。

        Args:
            keyword: 搜索关键词，可以是股票名称（如"贵州茅台"）或代码（如"600519"）

        Returns:
            匹配的股票列表 (JSON)，包含代码(code)和名称(name)字段，最多返回20条。
        """
        cache_key = f"search_stock:{keyword}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            df = ak.stock_info_a_code_name()
            # Search in both code and name columns
            mask = df["code"].str.contains(keyword, case=False, na=False) | df[
                "name"
            ].str.contains(keyword, case=False, na=False)
            matched = df[mask].head(20)
            result = df_to_json(matched)
            cache.set(cache_key, result, TTL_COMPANY)
            return result
        except Exception as e:
            return error_response(f"搜索股票失败: {e}", "search_stock")

    @mcp.tool()
    async def get_company_info(symbol: str) -> str:
        """
        获取A股公司基本信息，包括行业、市值、股本等。

        Args:
            symbol: 6位股票代码，如 "000001"（平安银行）、"600519"（贵州茅台）

        Returns:
            公司基本信息 (JSON)，包含总市值、流通市值、行业、上市日期等。
        """
        symbol = normalize_symbol(symbol)
        cache_key = f"company_info:{symbol}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            # Primary: 东方财富个股信息
            try:
                df = ak.stock_individual_info_em(symbol=symbol)
                if df is not None and not df.empty:
                    info = {}
                    for _, row in df.iterrows():
                        info[row.iloc[0]] = row.iloc[1]
                    if info:
                        result = dict_to_json(info)
                        cache.set(cache_key, result, TTL_COMPANY)
                        return result
            except Exception:
                pass

            # Fallback: 从 A 股列表中提取基本信息
            df = await call_with_fallback(
                ("东方财富(列表)", ak.stock_zh_a_spot_em, {}),
                ("新浪财经", ak.stock_zh_a_spot, {}),
            )
            code_col = _find_code_col(df)
            row = df[df[code_col].astype(str).str.strip() == symbol]
            if row.empty:
                return error_response(
                    f"未找到股票 {symbol} 的公司信息", "get_company_info"
                )
            result = df_to_json(row)
            cache.set(cache_key, result, TTL_COMPANY)
            return result
        except Exception as e:
            return error_response(
                f"获取公司信息失败 ({symbol}): {e}", "get_company_info"
            )

    @mcp.tool()
    async def get_company_profile(symbol: str) -> str:
        """
        获取公司主营业务构成和业务描述。

        Args:
            symbol: 6位股票代码，如 "000001"（平安银行）

        Returns:
            公司主营业务构成 (JSON)，包含各业务的营收占比、毛利率等。
        """
        symbol = normalize_symbol(symbol)
        cache_key = f"company_profile:{symbol}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            df = ak.stock_zyjs_ths(symbol=symbol)
            result = df_to_json(df)
            cache.set(cache_key, result, TTL_COMPANY)
            return result
        except Exception as e:
            return error_response(
                f"获取公司主营构成失败 ({symbol}): {e}", "get_company_profile"
            )

    @mcp.tool()
    async def get_competitors(
        symbol: str, industry: str = ""
    ) -> str:
        """
        获取同行业公司列表（竞争对手/可比公司）。

        先根据股票代码查找所属行业板块，然后返回该板块的所有成分股。
        也可以直接传入行业名称来查询。

        Args:
            symbol: 6位股票代码，如 "600519"。如果同时提供了 industry 参数则忽略此参数。
            industry: 行业板块名称，如 "白酒"、"银行"。如果为空则自动从 symbol 推断。

        Returns:
            同行业公司列表 (JSON)，包含代码、名称、最新价、涨跌幅等。
        """
        symbol = normalize_symbol(symbol)
        cache_key = f"competitors:{symbol}:{industry}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            # If no industry provided, look it up from company info
            if not industry:
                try:
                    info_df = ak.stock_individual_info_em(symbol=symbol)
                    if info_df is not None and not info_df.empty:
                        for _, row in info_df.iterrows():
                            key = str(row.iloc[0])
                            if "行业" in key:
                                industry = str(row.iloc[1])
                                break
                except Exception:
                    pass

            # Fallback: try to find industry from board industry list
            if not industry:
                try:
                    board_df = ak.stock_board_industry_name_em()
                    if board_df is not None and not board_df.empty:
                        # Try each industry to see if the stock is in it
                        # This is expensive, so we use a heuristic:
                        # look up stock in A-share spot to find the industry name
                        spot_df = ak.stock_zh_a_spot_em()
                        if spot_df is not None and not spot_df.empty:
                            code_col = _find_code_col(spot_df)
                            row = spot_df[spot_df[code_col].astype(str).str.strip() == symbol]
                            if not row.empty:
                                # Check if there's an industry column
                                for c in row.columns:
                                    if "行业" in c or "板块" in c:
                                        industry = str(row.iloc[0][c])
                                        break
                except Exception:
                    pass

            if not industry:
                return error_response(
                    f"无法确定 {symbol} 所属行业，请手动传入 industry 参数",
                    "get_competitors",
                )

            # 东方财富行业成分股 (unique source, no THS alternative)
            df = ak.stock_board_industry_cons_em(symbol=industry)
            df = slim_df(df)
            result = df_to_json(df, max_rows=30)
            cache.set(cache_key, result, TTL_COMPANY)
            return result
        except Exception as e:
            return error_response(
                f"获取竞争对手列表失败 ({symbol}, {industry}): {e}",
                "get_competitors",
            )


def _find_code_col(df) -> str:
    """Find the stock code column in a DataFrame (varies by data source)."""
    for c in df.columns:
        if c in ("代码", "code", "symbol"):
            return c
        if "代码" in c or "code" in c.lower() or "symbol" in c.lower():
            return c
    return df.columns[0]
