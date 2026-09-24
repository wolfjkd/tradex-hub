"""macro_service：官方宏观业务逻辑层（SP-2026-09-23-001）。

从 tools/macro_official.py 抽出的 5 个业务函数：
- get_social_financing（人行社融）
- get_pmi（统计局 PMI）
- get_bond_yield_curve（中债收益率曲线）
- get_repo_fixing_rate（中国货币网回购定盘）
- get_lpr_history（LPR 历史）
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from ..data_sources import get_router
from ..utils.cache import TTL_DAILY, cache

logger = logging.getLogger(__name__)
_router = get_router()


def _df_to_records(df: pd.DataFrame, max_rows: int | None = None) -> list[dict]:
    if df is None or df.empty:
        return []
    if max_rows is not None:
        df = df.head(max_rows)
    return df.where(pd.notnull(df), None).to_dict(orient="records")


def get_social_financing(year: int = 0) -> dict[str, Any]:
    """人行社融数据。"""
    cache_key = f"social_financing:{year}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    df, src = _router.route("social_financing", year=year)
    records = _df_to_records(df)
    result = {"year": year, "data": records, "source": src, "count": len(records)}
    cache.set(cache_key, result, TTL_DAILY)
    return result


def get_pmi() -> dict[str, Any]:
    """统计局 PMI。"""
    cache_key = "pmi_data"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    df, src = _router.route("pmi_data")
    records = _df_to_records(df)
    result = {"data": records, "source": src, "count": len(records)}
    cache.set(cache_key, result, TTL_DAILY)
    return result


def get_bond_yield_curve(curve: str = "国债") -> dict[str, Any]:
    """中债收益率曲线。"""
    cache_key = f"bond_yield_curve:{curve}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    df, src = _router.route("bond_yield_curve", curve=curve)
    records = _df_to_records(df)
    result = {"curve": curve, "data": records, "source": src, "count": len(records)}
    cache.set(cache_key, result, TTL_DAILY)
    return result


def get_repo_fixing_rate(kind: str = "FR") -> dict[str, Any]:
    """中国货币网回购定盘利率。"""
    cache_key = f"repo_fixing_rate:{kind}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    df, src = _router.route("repo_fixing_rate", kind=kind)
    records = _df_to_records(df)
    result = {"kind": kind, "data": records, "source": src, "count": len(records)}
    cache.set(cache_key, result, TTL_DAILY)
    return result


def get_lpr_history(years_back: int = 5) -> dict[str, Any]:
    """LPR 历史。"""
    cache_key = f"lpr_history:{years_back}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    df, src = _router.route("lpr_history", years_back=years_back)
    records = _df_to_records(df)
    result = {"years_back": years_back, "data": records, "source": src, "count": len(records)}
    cache.set(cache_key, result, TTL_DAILY)
    return result
