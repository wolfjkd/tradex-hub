"""global_news_service：全球新闻业务逻辑层（SP-2026-09-23-001）。

从 tools/global_market_news.py 抽出的 3 个业务函数：
- get_wallstreetcn_lives（华尔街见闻 7×24 快讯）
- get_macro_calendar（全球宏观日历）
- get_cctv_news（央视新闻联播）
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from ..data_sources import get_router
from ..utils.cache import TTL_DAILY, cache

logger = logging.getLogger(__name__)
_router = get_router()

# 较短 TTL（30 分钟级）
_TTL_FAST = 1800


def _df_to_records(df: pd.DataFrame, max_rows: int | None = None) -> list[dict]:
    if df is None or df.empty:
        return []
    if max_rows is not None:
        df = df.head(max_rows)
    return df.where(pd.notnull(df), None).to_dict(orient="records")


def get_wallstreetcn_lives(
    channel: str = "global", limit: int = 30, cursor: str = ""
) -> dict[str, Any]:
    """华尔街见闻 7×24 全球财经快讯。"""
    cache_key = f"ws_lives:{channel}:{limit}:{cursor}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    df, src = _router.route(
        "wallstreetcn_lives", channel=channel, limit=limit, cursor=cursor
    )
    records = _df_to_records(df, max_rows=limit)
    result = {
        "channel": channel, "lives": records,
        "source": src, "count": len(records),
    }
    cache.set(cache_key, result, _TTL_FAST)
    return result


def get_macro_calendar(
    start_date: str = "", end_date: str = "",
    country: str = "", min_importance: str = "",
) -> dict[str, Any]:
    """全球宏观日历。"""
    cache_key = f"macro_cal:{start_date}:{end_date}:{country}:{min_importance}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    df, src = _router.route(
        "macro_calendar",
        start_date=start_date, end_date=end_date,
        country=country, min_importance=min_importance,
    )
    records = _df_to_records(df)
    result = {
        "start_date": start_date, "end_date": end_date,
        "country": country, "events": records,
        "source": src, "count": len(records),
    }
    cache.set(cache_key, result, TTL_DAILY)
    return result


def get_cctv_news(date: str = "", with_content: bool = False) -> dict[str, Any]:
    """央视新闻联播。"""
    cache_key = f"cctv_news:{date}:{with_content}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    df, src = _router.route(
        "cctv_news_main", date=date, with_content=with_content
    )
    records = _df_to_records(df)
    result = {"date": date, "news": records, "source": src, "count": len(records)}
    cache.set(cache_key, result, TTL_DAILY)
    return result
