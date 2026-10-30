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
from ..utils.formatter import df_to_json, df_to_records
from ..utils.symbol import normalize_symbol

logger = logging.getLogger(__name__)
_router = get_router()


def _df_to_records(df: pd.DataFrame, max_rows: int | None = None) -> list[dict]:
    return df_to_records(df, max_rows=max_rows)


# 各新闻子源列名不一致，按语义归一到统一字段（顺序即优先级）
_NEWS_TITLE_ALIASES = ("标题", "新闻标题", "名称")
_NEWS_TIME_ALIASES = ("发布时间", "时间")
_NEWS_DATE_ALIASES = ("发布日期", "日期")
_NEWS_SOURCE_ALIASES = ("文章来源", "来源")
_NEWS_URL_ALIASES = ("新闻链接", "链接", "url", "URL")
_NEWS_SUMMARY_ALIASES = ("内容", "新闻内容", "摘要", "说明")


_SOURCE_TAG_COL = "_tradex_来源"


def _tag_source(df: pd.DataFrame, source: str) -> pd.DataFrame:
    """给子源加上来源标记列。

    瘦身会丢掉原始宽表，来源也随之丢失；在合并前打一列标记，
    归一后就能填进 来源 字段，不至于让调用方分不清新闻出自哪家。
    """
    tagged = df.copy()
    tagged[_SOURCE_TAG_COL] = str(source or "")
    return tagged


def _first_text(record: dict, aliases: tuple[str, ...]) -> str:
    """按别名顺序取第一个非空文本值，顺手过滤 NaN/NaT 的字符串残留。"""
    for key in aliases:
        value = record.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text and text.lower() not in ("nan", "nat", "none"):
            return text
    return ""


def _unify_news_record(record: dict) -> dict:
    """把任意子源的一行归一成统一的 5 字段。

    输出字段固定为 标题/时间/来源/链接/摘要 —— 不再输出源表里的其余 40 列。
    """
    time_text = _first_text(record, _NEWS_TIME_ALIASES)
    date_text = _first_text(record, _NEWS_DATE_ALIASES)

    if time_text and len(time_text) >= 16 and "-" in time_text:
        stamp = time_text                      # 已是完整时间戳（新浪/期货）
    elif date_text and time_text:
        stamp = f"{date_text} {time_text}"     # 财联社：日期与时刻分两列
    else:
        stamp = time_text or date_text

    # 去掉 ISO 的 T 与 +08:00 尾巴，统一成 "YYYY-MM-DD HH:MM:SS" 便于阅读与比较
    if stamp:
        stamp = stamp.replace("T", " ").split("+")[0].strip()
        if stamp.endswith("Z"):
            stamp = stamp[:-1].strip()
        stamp = stamp[:19] if len(stamp) >= 19 else stamp

    return {
        "标题": _first_text(record, _NEWS_TITLE_ALIASES),
        "时间": stamp,
        "来源": _first_text(record, _NEWS_SOURCE_ALIASES)
        or _first_text(record, (_SOURCE_TAG_COL,)),
        "链接": _first_text(record, _NEWS_URL_ALIASES),
        "摘要": _first_text(record, _NEWS_SUMMARY_ALIASES),
    }


def get_stock_news(symbol: str) -> dict[str, Any]:
    """个股相关新闻资讯。

    Args:
        symbol: 6 位股票代码。

    Returns:
        dict：含 news（list，最多 30 条，每条固定 5 字段：
        标题/时间/来源/链接/摘要）。

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
    # 与 search_news 用同一套归一：两个新闻工具的返回结构必须一致，
    # 否则调用方要按工具分别适配字段（2026-10-30 专项重构统一）
    records = [
        _unify_news_record(rec)
        for rec in _df_to_records(_tag_source(df, _src), max_rows=30)
    ]
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
                all_dfs.append(_tag_source(df, _src))
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
                    all_dfs.append(_tag_source(df, _src))
            except Exception as exc:
                logger.debug("%s 源失败: %s", route_type, exc)
        # 百度交易提醒（多个 endpoint）
        try:
            for ep in ["suspend", "dividend", "report_time"]:
                df, _src = _router.route("baidu_trade_notify", endpoint=ep, date="")
                if df is not None and not df.empty:
                    all_dfs.append(_tag_source(df, _src))
        except Exception as exc:
            logger.debug("百度交易提醒源失败: %s", exc)

    if not all_dfs:
        result = {"keyword": keyword, "symbol": symbol, "news": [], "count": 0}
        cache.set(cache_key, result, TTL_REALTIME)
        return result

    combined = pd.concat(all_dfs, ignore_index=True)

    # 各子源 schema 不同，直接 union 会得到 40+ 列、绝大多数为 NaN 的宽表
    # （单条约 500 字节无效负载，纯烧 LLM 上下文）。先归一到统一字段再过滤。
    records = [_unify_news_record(rec) for rec in _df_to_records(combined)]

    keywords = [
        kw.strip() for kw in keyword.replace(",", " ").replace("，", " ").split()
        if kw.strip()
    ]

    def _match(record: dict, kws: list[str]) -> bool:
        haystack = f"{record['标题']} {record['摘要']}".lower()
        return any(kw.lower() in haystack for kw in kws)

    matched = [r for r in records if _match(r, keywords)] if keywords else records
    # 过滤后为空 → 退回未过滤结果（宁可给全量，也不返回空列表让上层误判无新闻）
    news = (matched or records)[:num_results]

    result = {
        "keyword": keyword,
        "symbol": symbol,
        "news": news,
        "count": len(news),
    }
    cache.set(cache_key, result, TTL_REALTIME)
    return result
