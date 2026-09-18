"""news_service：新闻/公告类业务逻辑层（工单 06 抽出）。

从 tools/news_events.py 的 @mcp.tool() 装饰器内抽出 3 个核心业务函数：
- get_stock_news（个股新闻）
- get_company_announcements（公司公告）
- search_news（关键词搜索）

news_events.py 还有 12+ 个其它工具（telegraph/calendar/sentiment/futures_news/
hot_rank/hot_keywords/xueqiu_hot/fund_hold/hot_search/wencai_query/wencai_news
等），暂不抽层（不在工单 06 范围）。
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from ..data_sources import get_router
from ..utils.cache import TTL_DAILY, TTL_REALTIME, cache
from ..utils.formatter import df_to_json
from ..utils.symbol import normalize_symbol

logger = logging.getLogger(__name__)
_router = get_router()


def _df_to_records(df: pd.DataFrame, max_rows: int | None = None) -> list[dict]:
    if df is None or df.empty:
        return []
    if max_rows is not None:
        df = df.head(max_rows)
    return df.where(pd.notnull(df), None).to_dict(orient="records")


def get_stock_news(symbol: str) -> dict[str, Any]:
    """个股相关新闻资讯。

    Args:
        symbol: 6 位股票代码。

    Returns:
        dict：含 news（list，最多 30 条）。

    Raises:
        Exception: 数据源异常。
    """
    symbol = normalize_symbol(symbol)
    cache_key = f"stock_news:{symbol}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    df, _src = _router.route("news_data", symbol=symbol)
    records = _df_to_records(df, max_rows=30)
    result = {"symbol": symbol, "news": records, "source": _src}
    cache.set(cache_key, result, TTL_REALTIME)
    return result


def get_company_announcements(symbol: str = "", num_results: int = 30) -> dict[str, Any]:
    """上市公司公告。

    Args:
        symbol: 6 位股票代码；为空则获取全市场最新公告。
        num_results: 最大返回条数，默认 30。

    Returns:
        dict：含 announcements（list）。

    Raises:
        Exception: 数据源异常。
    """
    if symbol:
        symbol = normalize_symbol(symbol)
    cache_key = f"announcements:{symbol}:{num_results}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    df, _src = _router.route("cninfo_announcement", symbol=symbol)
    df = df.head(num_results)
    records = _df_to_records(df)
    result = {
        "symbol": symbol or "全市场",
        "announcements": records,
        "count": len(records),
        "source": _src,
    }
    cache.set(cache_key, result, TTL_DAILY)
    return result


def search_news(
    keyword: str, symbol: str = "", num_results: int = 20
) -> dict[str, Any]:
    """按关键词搜索财经新闻。

    纯新闻搜索，不含公告。多源聚合（财联社/新浪/百度交易提醒/期货新闻/百度热搜）。

    Args:
        keyword: 搜索关键词（多个用空格或逗号分隔）。
        symbol: 可选 6 位股票代码，限定搜索范围。
        num_results: 最大返回条数，默认 20。

    Returns:
        dict：含 keyword/news（list）。

    Raises:
        Exception: 数据源异常。
    """
    cache_key = f"search_news:{keyword}:{symbol}:{num_results}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    all_dfs: list[pd.DataFrame] = []

    if symbol:
        symbol = normalize_symbol(symbol)
        try:
            df, _src = _router.route("news_data", symbol=symbol)
            if df is not None and not df.empty:
                all_dfs.append(df)
        except Exception as exc:
            logger.debug("个股新闻源失败(%s): %s", symbol, exc)

    if not all_dfs:
        # 多源全市场
        for source_cmd in [
            ("telegraph_news", {"num_results": num_results}),
            ("sina_finance_news", {"num_results": 20}),
            ("futures_news", {"symbol": "全部"}),
            ("hot_search", {"symbol": "A股"}),
        ]:
            try:
                route_type, kwargs = source_cmd
                df, _src = _router.route(route_type, **kwargs)
                if df is not None and not df.empty:
                    all_dfs.append(df)
            except Exception as exc:
                logger.debug("%s 源失败: %s", route_type, exc)
        # 百度交易提醒（多个 endpoint）
        try:
            for ep in ["suspend", "dividend", "report_time"]:
                df, _src = _router.route("baidu_trade_notify", endpoint=ep, date="")
                if df is not None and not df.empty:
                    all_dfs.append(df)
        except Exception as exc:
            logger.debug("百度交易提醒源失败: %s", exc)

    if not all_dfs:
        result = {"keyword": keyword, "symbol": symbol, "news": [], "count": 0}
        cache.set(cache_key, result, TTL_REALTIME)
        return result

    combined = pd.concat(all_dfs, ignore_index=True)

    # 关键词过滤
    _TEXT_COLS = {"标题", "内容", "新闻标题", "文章来源", "新闻内容", "名称", "说明", "摘要"}
    _text_cols = [
        c for c in combined.columns
        if c in _TEXT_COLS or "标题" in c or "内容" in c or "名称" in c
    ]
    keywords = [
        kw.strip() for kw in keyword.replace(",", " ").replace("，", " ").split()
        if kw.strip()
    ]
    if keywords and _text_cols:
        mask = pd.Series(False, index=combined.index)
        for col in _text_cols:
            for kw in keywords:
                try:
                    mask = mask | combined[col].astype(str).str.contains(
                        kw, case=False, na=False
                    )
                except Exception:
                    continue
        combined = combined[mask]

    # 文本列落空 → 全列兜底
    if combined.empty and keywords:
        mask = pd.Series(False, index=combined.index)
        for col in combined.columns:
            for kw in keywords:
                try:
                    mask = mask | combined[col].astype(str).str.contains(
                        kw, case=False, na=False
                    )
                except Exception:
                    continue
        combined = combined[mask]

    # 仍为空 → 返回未过滤前 num_results 条
    if combined.empty:
        combined = pd.concat(all_dfs, ignore_index=True).head(num_results)

    combined = combined.head(num_results)
    records = _df_to_records(combined)
    result = {
        "keyword": keyword,
        "symbol": symbol,
        "news": records,
        "count": len(records),
    }
    cache.set(cache_key, result, TTL_REALTIME)
    return result
