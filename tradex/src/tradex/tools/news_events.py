"""
Category 7: News & Events (V0.3)

Tools:
  31. get_stock_news           - Stock-specific news
  32. get_financial_calendar   - Earnings/report disclosure schedule
  33. get_company_announcements - Company announcements
  34. search_news              - Keyword-based news search
"""

from __future__ import annotations

import akshare as ak
from mcp.server.fastmcp import FastMCP

from ..utils.cache import TTL_DAILY, TTL_REALTIME, cache
from ..utils.formatter import df_to_json, error_response, slim_df
from ..utils.symbol import normalize_symbol


def register(mcp: FastMCP):
    """Register news and event tools with the MCP server."""

    @mcp.tool()
    async def get_stock_news(symbol: str) -> str:
        """
        获取个股相关新闻资讯。

        Args:
            symbol: 6位股票代码，如 "600519"

        Returns:
            新闻列表 (JSON)，包含新闻标题、发布时间、来源、摘要、链接等。
        """
        symbol = normalize_symbol(symbol)
        cache_key = f"stock_news:{symbol}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            df = ak.stock_news_em(symbol=symbol)
            result = df_to_json(df, max_rows=30)
            cache.set(cache_key, result, TTL_REALTIME)
            return result
        except Exception as e:
            return error_response(
                f"获取股票新闻失败 ({symbol}): {e}", "get_stock_news"
            )

    @mcp.tool()
    async def get_financial_calendar(date: str = "") -> str:
        """
        获取上市公司财报披露时间表。

        Args:
            date: 查询日期，格式 "YYYYMMDD"。默认为空获取最新一期。

        Returns:
            财报披露时间表 (JSON)，包含股票代码、名称、预计披露日期、
            实际披露日期、报告类型等。
        """
        cache_key = f"fin_calendar:{date}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            kwargs = {}
            if date:
                kwargs["date"] = date
            df = ak.stock_report_disclosure(**kwargs)
            df = slim_df(df)
            result = df_to_json(df, max_rows=50)
            cache.set(cache_key, result, TTL_DAILY)
            return result
        except Exception as e:
            return error_response(
                f"获取财报披露日历失败: {e}", "get_financial_calendar"
            )

    @mcp.tool()
    async def get_company_announcements(
        symbol: str = "",
        num_results: int = 30,
    ) -> str:
        """
        获取上市公司公告。

        Args:
            symbol: 6位股票代码，如 "600519"。为空则获取全市场最新公告。
            num_results: 最大返回条数，默认30

        Returns:
            公告列表 (JSON)，包含公告标题、发布日期、公告类型等。
        """
        cache_key = f"announcements:{symbol}:{num_results}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            kwargs = {}
            if symbol:
                symbol = normalize_symbol(symbol)
                kwargs["symbol"] = symbol
            df = ak.stock_notice_report(**kwargs)
            df = df.head(num_results)
            result = df_to_json(df)
            cache.set(cache_key, result, TTL_DAILY)
            return result
        except Exception as e:
            return error_response(
                f"获取公司公告失败 ({symbol}): {e}", "get_company_announcements"
            )

    @mcp.tool()
    async def search_news(
        keyword: str,
        symbol: str = "",
        num_results: int = 20,
    ) -> str:
        """
        按关键词搜索股票新闻资讯。

        如果提供了股票代码，则在该股票的新闻中搜索关键词；
        否则在全市场新闻中搜索。

        Args:
            keyword: 搜索关键词，如 "业绩预增"、"回购"、"增持"
            symbol: 可选的6位股票代码，用于限定搜索范围
            num_results: 最大返回条数，默认20

        Returns:
            匹配的新闻列表 (JSON)，包含标题、时间、来源、摘要等。
        """
        cache_key = f"search_news:{keyword}:{symbol}:{num_results}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            import pandas as pd

            all_dfs = []

            if symbol:
                symbol = normalize_symbol(symbol)
                try:
                    df = ak.stock_news_em(symbol=symbol)
                    if df is not None and not df.empty:
                        all_dfs.append(df)
                except Exception:
                    pass
            else:
                # Try multiple general news sources instead of relying on one stock
                # Source 1: 财新网 general financial news
                try:
                    df = ak.stock_news_main_cx()
                    if df is not None and not df.empty:
                        all_dfs.append(df)
                except Exception:
                    pass

                # Source 2: CCTV financial news
                try:
                    df = ak.news_cctv(date="")
                    if df is not None and not df.empty:
                        all_dfs.append(df)
                except Exception:
                    pass

            if not all_dfs:
                return df_to_json(pd.DataFrame())

            combined = pd.concat(all_dfs, ignore_index=True)

            # Filter by keyword in title or content columns
            text_cols = [
                c for c in combined.columns
                if any(k in c for k in ["标题", "内容", "title", "content", "摘要"])
            ]
            if text_cols:
                mask = combined[text_cols[0]].str.contains(keyword, case=False, na=False)
                for col in text_cols[1:]:
                    mask = mask | combined[col].str.contains(keyword, case=False, na=False)
                combined = combined[mask]

            combined = combined.head(num_results)
            result = df_to_json(combined)
            cache.set(cache_key, result, TTL_REALTIME)
            return result
        except Exception as e:
            return error_response(
                f"搜索新闻失败 ({keyword}): {e}", "search_news"
            )
