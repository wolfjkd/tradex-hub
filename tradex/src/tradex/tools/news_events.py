"""
Category 7: News & Events (V0.3)

Tools:
  31. get_stock_news           - Stock-specific news (v3.2.0: em_news_direct直连主源)
  32. get_financial_calendar   - Earnings/report disclosure schedule + 百度经济数据日历 (v3.3.0)
  33. get_company_announcements - Company announcements (v3.2.0: cninfo_direct直连主源)
  34. search_news              - Keyword-based news search (v3.3.0: 百度交易提醒/期货/新浪/热搜)
  35. get_telegraph_news       - Real-time market telegraph (v3.2.0 新增)
  36. get_market_sentiment     - Index news sentiment (v3.3.0 新增)
  37. get_futures_news         - Futures/commodities news (v3.3.0 新增)
  38. get_hot_rank             - East Money hot rank (v3.3.0 新增)
  39. get_hot_keywords         - Stock hot keywords (v3.3.0 新增)
  40. get_xueqiu_hot           - Xueqiu hot ranking (v3.3.0 新增)
  41. get_fund_hold            - Institutional holdings (v3.3.0 新增)
  42. get_hot_search           - Baidu hot search stocks (v3.3.0 新增)
  43. get_wencai_query         - THS Wencai natural language stock query (v3.3.0 新增)
  44. get_wencai_news          - THS Wencai news/announcement/report search (v3.3.0 新增)

Data source routing (via SmartRouter, v3.3.0):
  个股新闻: em_news_direct(priority=1) → akshare(priority=100)
  实时电报: cls_telegraph(priority=1)
  全量公告: cninfo_direct(priority=1)
  财报日历: stock_report_disclosure(priority=1) → baidu_economic_calendar(priority=100)
  指数情绪: index_news_sentiment(priority=1)
  期货新闻: futures_news(priority=1)
  人气榜: hot_rank(priority=1)
  雪球热度: xueqiu_hot(priority=1)
  机构持仓: fund_hold(priority=1)
  百度热搜: hot_search(priority=1)
  问财查询: wencai_query(priority=1, pywencai 可选依赖)
  问财搜索: wencai_news(priority=1, iwencai OpenAPI 需 API Key)
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
    """Register news and event tools with the MCP server."""

    @mcp.tool()
    async def get_stock_news(symbol: str) -> str:
        """
        获取个股相关新闻资讯。v3.2.0 起直连东财 search-api-web，更稳定。

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
            # 走 news_data 类型：em_news_direct(priority=1) → akshare(priority=100)
            df, _src = _router.route("news_data", symbol=symbol)
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
        获取上市公司财报披露时间表和经济数据日历。v3.3.0 新增百度经济数据日历补充源。

        Args:
            date: 查询日期，格式 "YYYYMMDD"。默认为空获取最新一期。

        Returns:
            财报披露时间表和经济数据日历 (JSON)，包含股票代码、名称、预计披露日期、
            实际披露日期、报告类型、经济数据等。
        """
        cache_key = f"fin_calendar:{date}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            all_dfs = []
            # Source 1: 财报披露时间
            try:
                df1, _src1 = _router.route("news_data", endpoint="stock_report_disclosure", date=date)
                if df1 is not None and not df1.empty:
                    all_dfs.append(df1)
            except Exception:
                pass
            # Source 2: 百度经济数据日历（v3.3.0 新增）
            try:
                df2, _src2 = _router.route("baidu_economic_calendar", date=date)
                if df2 is not None and not df2.empty:
                    all_dfs.append(df2)
            except Exception:
                pass

            if not all_dfs:
                return df_to_json(pd.DataFrame())

            combined = pd.concat(all_dfs, ignore_index=True)
            combined = slim_df(combined)
            result = df_to_json(combined, max_rows=50)
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
        获取上市公司公告。v3.2.0 起直连巨潮 cninfo.com.cn，信息更全更及时。

        Args:
            symbol: 6位股票代码，如 "600519"。为空则获取全市场最新公告。
            num_results: 最大返回条数，默认30

        Returns:
            公告列表 (JSON)，包含公告标题、发布日期、公告类型、PDF链接等。
        """
        cache_key = f"announcements:{symbol}:{num_results}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            if symbol:
                symbol = normalize_symbol(symbol)
            # 走 cninfo_announcement 类型：cninfo_direct(priority=1)
            df, _src = _router.route("cninfo_announcement", symbol=symbol)
            df = df.head(num_results)
            result = df_to_json(df)
            cache.set(cache_key, result, TTL_DAILY)
            return result
        except Exception as e:
            return error_response(
                f"获取公司公告失败 ({symbol}): {e}", "get_company_announcements"
            )

    @mcp.tool()
    async def get_telegraph_news(num_results: int = 20) -> str:
        """
        获取全市场实时财经快讯（财联社7×24小时电报）。v3.2.0 新增。

        Args:
            num_results: 最大返回条数，默认20，最大50

        Returns:
            快讯列表 (JSON)，包含时间戳、内容、类别、链接等。
        """
        cache_key = f"telegraph:{num_results}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            df, _src = _router.route("telegraph_news", num_results=num_results)
            if df is None or df.empty:
                return df_to_json(pd.DataFrame())
            result = df_to_json(df)
            cache.set(cache_key, result, TTL_REALTIME)
            return result
        except Exception as e:
            return error_response(
                f"获取实时快讯失败: {e}", "get_telegraph_news"
            )

    @mcp.tool()
    async def search_news(
        keyword: str,
        symbol: str = "",
        num_results: int = 20,
    ) -> str:
        """
        按关键词搜索股票新闻资讯。v3.2.0 多源增强：财联社快讯 + 巨潮公告 + 财新网 + CCTV。

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
            all_dfs = []

            if symbol:
                symbol = normalize_symbol(symbol)
                # Source 1: 东财个股新闻（em_news_direct 直连）
                try:
                    df, _src = _router.route("news_data", symbol=symbol)
                    if df is not None and not df.empty:
                        all_dfs.append(df)
                except Exception:
                    pass
            else:
                # Source 1: 财联社实时快讯（v3.2.0 新增）
                try:
                    df, _src = _router.route("telegraph_news", num_results=num_results)
                    if df is not None and not df.empty:
                        all_dfs.append(df)
                except Exception:
                    pass

                # Source 2: 巨潮公告（v3.2.0 新增）
                try:
                    df, _src = _router.route("cninfo_announcement", keyword=keyword)
                    if df is not None and not df.empty:
                        all_dfs.append(df)
                except Exception:
                    pass

                # Source 3: 财新网 general financial news
                try:
                    df, _src = _router.route("news_data", endpoint="stock_news_main_cx")
                    if df is not None and not df.empty:
                        all_dfs.append(df)
                except Exception:
                    pass

                # Source 4: CCTV financial news
                try:
                    df, _src = _router.route("news_data", endpoint="news_cctv", date="")
                    if df is not None and not df.empty:
                        all_dfs.append(df)
                except Exception:
                    pass

                # Source 5: 百度交易提醒（v3.3.0 新增）
                try:
                    for ep in ["suspend", "dividend", "report_time"]:
                        df, _src = _router.route("baidu_trade_notify", endpoint=ep, date="")
                        if df is not None and not df.empty:
                            all_dfs.append(df)
                except Exception:
                    pass

                # Source 6: 期货新闻（v3.3.0 新增）
                try:
                    df, _src = _router.route("futures_news", symbol="全部")
                    if df is not None and not df.empty:
                        all_dfs.append(df)
                except Exception:
                    pass

                # Source 7: 新浪财经新闻（v3.3.0 新增）
                try:
                    df, _src = _router.route("sina_finance_news", num_results=20)
                    if df is not None and not df.empty:
                        all_dfs.append(df)
                except Exception:
                    pass

                # Source 8: 百度热搜（v3.3.0 新增）
                try:
                    df, _src = _router.route("hot_search", symbol="A股")
                    if df is not None and not df.empty:
                        all_dfs.append(df)
                except Exception:
                    pass

            if not all_dfs:
                return df_to_json(pd.DataFrame())

            combined = pd.concat(all_dfs, ignore_index=True)

            # Filter by keyword (分词搜索，任一关键词匹配即可)
            keywords = [kw.strip() for kw in keyword.replace(",", " ").replace("，", " ").split() if kw.strip()]
            text_cols = [
                c for c in combined.columns
                if any(k in c for k in ["标题", "内容", "title", "content", "摘要"])
            ]
            if text_cols and keywords:
                mask = pd.Series(False, index=combined.index)
                for kw in keywords:
                    for col in text_cols:
                        mask = mask | combined[col].str.contains(kw, case=False, na=False)
                combined = combined[mask]

            combined = combined.head(num_results)
            result = df_to_json(combined)
            cache.set(cache_key, result, TTL_REALTIME)
            return result
        except Exception as e:
            return error_response(
                f"搜索新闻失败 ({keyword}): {e}", "search_news"
            )

    @mcp.tool()
    async def get_market_sentiment() -> str:
        """
        获取指数新闻情绪数据，反映市场整体情绪倾向。v3.3.0 新增。

        Returns:
            指数新闻情绪数据 (JSON)，包含指数代码、情感得分、相关新闻数量等。
        """
        cache_key = "market_sentiment"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            df, _src = _router.route("index_news_sentiment")
            if df is None or df.empty:
                return df_to_json(pd.DataFrame())
            result = df_to_json(df)
            cache.set(cache_key, result, TTL_REALTIME)
            return result
        except Exception as e:
            return error_response(
                f"获取市场情绪数据失败: {e}", "get_market_sentiment"
            )

    @mcp.tool()
    async def get_futures_news(symbol: str = "全部") -> str:
        """
        获取期货/大宗商品相关新闻。v3.3.0 新增。

        Args:
            symbol: 品种，默认 "全部" 获取所有品种新闻

        Returns:
            期货新闻列表 (JSON)，包含标题、发布时间、内容等。
        """
        cache_key = f"futures_news:{symbol}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            df, _src = _router.route("futures_news", symbol=symbol)
            if df is None or df.empty:
                return df_to_json(pd.DataFrame())
            result = df_to_json(df)
            cache.set(cache_key, result, TTL_REALTIME)
            return result
        except Exception as e:
            return error_response(
                f"获取期货新闻失败: {e}", "get_futures_news"
            )

    @mcp.tool()
    async def get_hot_rank(endpoint: str = "rank", symbol: str = "") -> str:
        """
        获取东方财富个股人气榜数据。v3.3.0 新增。

        Args:
            endpoint: 榜单类型。可选值：
                - "rank": 全市场人气榜（默认）
                - "up": 飙升榜
                - "detail": 个股历史趋势及粉丝特征（需 symbol）
                - "realtime": 个股实时变动（需 symbol）
                - "latest": 个股最新排名（需 symbol）
                - "relate": 相关股票（需 symbol）
            symbol: 带市场表示的证券代码，如 "SZ000665"。部分 endpoint 必填

        Returns:
            人气榜数据 (JSON)。
        """
        cache_key = f"hot_rank:{endpoint}:{symbol}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            kw = {"endpoint": endpoint}
            if symbol:
                kw["symbol"] = symbol
            df, _src = _router.route("hot_rank", **kw)
            if df is None or df.empty:
                return df_to_json(pd.DataFrame())
            result = df_to_json(df)
            cache.set(cache_key, result, TTL_REALTIME)
            return result
        except Exception as e:
            return error_response(
                f"获取人气榜数据失败: {e}", "get_hot_rank"
            )

    @mcp.tool()
    async def get_hot_keywords(symbol: str = "SZ000665") -> str:
        """
        获取指定股票的东方财富热门关联关键词。v3.3.0 新增。

        Args:
            symbol: 带市场表示的证券代码，如 "SZ000665"

        Returns:
            热门关键词列表 (JSON)。
        """
        cache_key = f"hot_keywords:{symbol}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            df, _src = _router.route("hot_rank", endpoint="keyword", symbol=symbol)
            if df is None or df.empty:
                return df_to_json(pd.DataFrame())
            result = df_to_json(df)
            cache.set(cache_key, result, TTL_REALTIME)
            return result
        except Exception as e:
            return error_response(
                f"获取热门关键词失败: {e}", "get_hot_keywords"
            )

    @mcp.tool()
    async def get_xueqiu_hot(endpoint: str = "follow", symbol: str = "最热门") -> str:
        """
        获取雪球沪深股市热度排行榜数据。v3.3.0 新增。

        Args:
            endpoint: 排行榜类型。可选值：
                - "follow": 关注排行榜（默认）
                - "tweet": 讨论排行榜
                - "deal": 交易排行榜
            symbol: {"最热门", "沪深股市", "创业板", "科创板"}

        Returns:
            雪球热度数据 (JSON)。
        """
        cache_key = f"xueqiu_hot:{endpoint}:{symbol}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            df, _src = _router.route("xueqiu_hot", endpoint=endpoint, symbol=symbol)
            if df is None or df.empty:
                return df_to_json(pd.DataFrame())
            result = df_to_json(df)
            cache.set(cache_key, result, TTL_REALTIME)
            return result
        except Exception as e:
            return error_response(
                f"获取雪球热度数据失败: {e}", "get_xueqiu_hot"
            )

    @mcp.tool()
    async def get_fund_hold(endpoint: str = "hold", symbol: str = "基金持仓", date: str = "") -> str:
        """
        获取机构持仓数据（基金/QFII/社保/券商/保险/信托）。v3.3.0 新增。

        Args:
            endpoint: 数据类型。可选值：
                - "hold": 机构持仓汇总（默认），symbol 可选 {"基金持仓", "QFII持仓", "社保持仓", "券商持仓", "保险持仓", "信托持仓"}
                - "detail": 单只基金持仓明细，symbol 为基金代码
            symbol: 机构类型或基金代码
            date: 财报日期，格式 "YYYYMMDD"。默认上一季度末

        Returns:
            机构持仓数据 (JSON)。
        """
        cache_key = f"fund_hold:{endpoint}:{symbol}:{date}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            kw = {"endpoint": endpoint, "symbol": symbol}
            if date:
                kw["date"] = date
            df, _src = _router.route("fund_hold", **kw)
            if df is None or df.empty:
                return df_to_json(pd.DataFrame())
            result = df_to_json(df)
            cache.set(cache_key, result, TTL_DAILY)
            return result
        except Exception as e:
            return error_response(
                f"获取基金持仓数据失败: {e}", "get_fund_hold"
            )

    @mcp.tool()
    async def get_hot_search(symbol: str = "A股", date: str = "", time: str = "今日") -> str:
        """
        获取百度股市通热搜股票排行。v3.3.0 新增。

        Args:
            symbol: 市场范围。可选值：{"全部", "A股", "港股", "美股"}
            date: 日期，格式 "YYYYMMDD"。默认为当日
            time: 时间范围。可选值：{"今日", "1小时"}

        Returns:
            百度热搜股票排行 (JSON)。
        """
        cache_key = f"hot_search:{symbol}:{date}:{time}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            kw = {"symbol": symbol, "time": time}
            if date:
                kw["date"] = date
            df, _src = _router.route("hot_search", **kw)
            if df is None or df.empty:
                return df_to_json(pd.DataFrame())
            result = df_to_json(df)
            cache.set(cache_key, result, TTL_REALTIME)
            return result
        except Exception as e:
            return error_response(
                f"获取百度热搜失败: {e}", "get_hot_search"
            )

    @mcp.tool()
    async def get_wencai_query(query: str, query_type: str = "stock", loop: bool = False) -> str:
        """
        同花顺问财自然语言查询（需安装 pywencai 和 Node.js）。v3.3.0 新增。
        
        通过自然语言描述筛选条件，获取符合条件的股票/基金/指数列表。
        例如："市值大于100亿，市盈率小于30，连续3年ROE大于15%"
        
        Args:
            query: 自然语言查询语句，如 "市值大于100亿 市盈率小于30"
            query_type: 查询类型，可选 {"stock", "fund", "index"}，默认 "stock"
            loop: 是否获取所有分页数据，默认 False
        
        Returns:
            查询结果 (JSON)，包含符合条件的标的信息。
            需要安装 pywencai: pip install pywencai
        """
        cache_key = f"wencai_query:{query}:{query_type}:{loop}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            df, _src = _router.route("wencai_query", query=query, query_type=query_type, loop=loop)
            if df is None or df.empty:
                return df_to_json(pd.DataFrame())
            result = df_to_json(df, max_rows=50)
            cache.set(cache_key, result, TTL_REALTIME)
            return result
        except Exception as e:
            return error_response(
                f"问财查询失败: {e}", "get_wencai_query"
            )

    @mcp.tool()
    async def get_wencai_news(keyword: str, channel: str = "news", limit: int = 20) -> str:
        """
        同花顺问财新闻/公告/研报搜索（需设置 IWENCAI_API_KEY 环境变量）。v3.3.0 新增。
        
        通过 iwencai OpenAPI 搜索财经新闻、公司公告或研究报告。
        
        Args:
            keyword: 搜索关键词，如 "新能源汽车"、"贵州茅台"
            channel: 搜索频道，可选 {"news": 财经新闻, "announcement": 公司公告, "report": 研究报告}，默认 "news"
            limit: 返回条数，默认 20，最大 50
        
        Returns:
            搜索结果 (JSON)，包含标题、发布时间、来源、摘要、链接。
            需要设置环境变量 IWENCAI_API_KEY
        """
        cache_key = f"wencai_news:{keyword}:{channel}:{limit}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            df, _src = _router.route("wencai_news", keyword=keyword, channel=channel, limit=limit)
            if df is None or df.empty:
                return df_to_json(pd.DataFrame())
            result = df_to_json(df)
            cache.set(cache_key, result, TTL_REALTIME)
            return result
        except Exception as e:
            return error_response(
                f"问财搜索失败: {e}", "get_wencai_news"
            )