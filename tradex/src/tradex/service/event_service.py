"""event_service：事件驱动业务逻辑层（SP-2026-09-23-001）。

从 tools/event_driven.py 抽出的 6 个业务函数：
- get_earnings_forecast（业绩预告）
- get_institution_survey（机构调研）
- get_holder_trades（股东增减持）
- get_share_buyback（股票回购）
- get_equity_pledge（股权质押）
- get_ipo_calendar（新股日历）
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from ..data_sources import get_router
from ..utils.cache import TTL_DAILY, cache
from ..utils.symbol import normalize_symbol

logger = logging.getLogger(__name__)
_router = get_router()


def _df_to_records(df: pd.DataFrame, max_rows: int | None = None) -> list[dict]:
    if df is None or df.empty:
        return []
    if max_rows is not None:
        df = df.head(max_rows)
    return df.where(pd.notnull(df), None).to_dict(orient="records")


def get_earnings_forecast(
    symbol: str, report_date: str = "", limit: int = 50
) -> dict[str, Any]:
    """业绩预告。"""
    symbol = normalize_symbol(symbol)
    cache_key = f"earnings_forecast:{symbol}:{report_date}:{limit}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    df, src = _router.route(
        "earnings_forecast", symbol=symbol, report_date=report_date, limit=limit
    )
    records = _df_to_records(df, max_rows=limit)
    result = {"symbol": symbol, "forecasts": records, "source": src, "count": len(records)}
    cache.set(cache_key, result, TTL_DAILY)
    return result


def get_institution_survey(
    symbol: str, start_date: str = "", end_date: str = "", limit: int = 50
) -> dict[str, Any]:
    """机构调研。"""
    symbol = normalize_symbol(symbol)
    cache_key = f"institution_survey:{symbol}:{start_date}:{end_date}:{limit}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    df, src = _router.route(
        "institution_survey",
        symbol=symbol, start_date=start_date, end_date=end_date, limit=limit,
    )
    records = _df_to_records(df, max_rows=limit)
    result = {"symbol": symbol, "surveys": records, "source": src, "count": len(records)}
    cache.set(cache_key, result, TTL_DAILY)
    return result


def get_holder_trades(
    symbol: str, direction: str = "",
    start_date: str = "", end_date: str = "", limit: int = 50,
) -> dict[str, Any]:
    """股东增减持。"""
    symbol = normalize_symbol(symbol)
    cache_key = f"holder_trades:{symbol}:{direction}:{start_date}:{end_date}:{limit}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    df, src = _router.route(
        "holder_trades",
        symbol=symbol, direction=direction,
        start_date=start_date, end_date=end_date, limit=limit,
    )
    records = _df_to_records(df, max_rows=limit)
    result = {"symbol": symbol, "trades": records, "source": src, "count": len(records)}
    cache.set(cache_key, result, TTL_DAILY)
    return result


def get_share_buyback(symbol: str, progress: str = "", limit: int = 50) -> dict[str, Any]:
    """股票回购。"""
    symbol = normalize_symbol(symbol)
    cache_key = f"share_buyback:{symbol}:{progress}:{limit}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    df, src = _router.route(
        "share_buyback", symbol=symbol, progress=progress, limit=limit
    )
    records = _df_to_records(df, max_rows=limit)
    result = {"symbol": symbol, "buybacks": records, "source": src, "count": len(records)}
    cache.set(cache_key, result, TTL_DAILY)
    return result


def get_equity_pledge(symbol: str, date: str = "", limit: int = 50) -> dict[str, Any]:
    """股权质押。"""
    symbol = normalize_symbol(symbol)
    cache_key = f"equity_pledge:{symbol}:{date}:{limit}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    df, src = _router.route(
        "equity_pledge", symbol=symbol, date=date, limit=limit
    )
    records = _df_to_records(df, max_rows=limit)
    result = {"symbol": symbol, "pledges": records, "source": src, "count": len(records)}
    cache.set(cache_key, result, TTL_DAILY)
    return result


def get_ipo_calendar(days_ahead: int = 30, limit: int = 50) -> dict[str, Any]:
    """新股申购日历。"""
    cache_key = f"ipo_calendar:{days_ahead}:{limit}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    df, src = _router.route(
        "ipo_calendar", days_ahead=days_ahead, limit=limit
    )
    records = _df_to_records(df, max_rows=limit)
    result = {"ipos": records, "source": src, "count": len(records)}
    cache.set(cache_key, result, TTL_DAILY)
    return result
