"""sw_industry_service：申万行业历史业务逻辑层（SP-2026-09-23-001）。

从 tools/sw_industry_history.py 抽出的 2 个业务函数：
- get_sw_industry_history（变迁史）
- get_sw_industry_as_of（按日期查询）
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


def get_sw_industry_history(force_refresh: bool = False) -> dict[str, Any]:
    """申万行业分类变迁史。"""
    if not force_refresh:
        cache_key = "sw_industry_history"
        cached = cache.get(cache_key)
        if cached is not None:
            import json
            return json.loads(cached) if isinstance(cached, str) else cached

    df, src = _router.route("sw_industry_history", force_refresh=force_refresh)
    records = _df_to_records(df, max_rows=500)
    result = {"history": records, "source": src, "count": len(records)}
    if not force_refresh:
        cache.set(cache_key, result, TTL_DAILY)
    return result


def get_sw_industry_as_of(symbol: str, date: str = "") -> dict[str, Any]:
    """按 (code, date) 查询股票的申万行业归属。"""
    symbol = normalize_symbol(symbol)
    cache_key = f"sw_as_of:{symbol}:{date}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    df, src = _router.route("sw_industry_as_of", symbol=symbol, date=date)
    records = _df_to_records(df)
    result = {
        "symbol": symbol, "date": date,
        "industry": records, "source": src, "count": len(records),
    }
    cache.set(cache_key, result, TTL_DAILY)
    return result
