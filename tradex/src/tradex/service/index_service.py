"""index_service：指数追踪业务逻辑层（SP-2026-09-23-001）。

从 tools/index_tracking.py 抽出的 3 个业务函数：
- get_index_constituents（指数成分股）
- get_index_weights（指数权重）
- get_index_valuation（指数 PE 与股息率）
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


def get_index_constituents(index_code: str = "000300") -> dict[str, Any]:
    """指数成分股。"""
    cache_key = f"index_constituents:{index_code}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    df, src = _router.route("index_constituents", index_code=index_code)
    records = _df_to_records(df)
    result = {"index_code": index_code, "constituents": records, "source": src, "count": len(records)}
    cache.set(cache_key, result, TTL_DAILY)
    return result


def get_index_weights(index_code: str = "000300") -> dict[str, Any]:
    """指数权重。"""
    cache_key = f"index_weights:{index_code}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    df, src = _router.route("index_weights", index_code=index_code)
    records = _df_to_records(df)
    result = {"index_code": index_code, "weights": records, "source": src, "count": len(records)}
    cache.set(cache_key, result, TTL_DAILY)
    return result


def get_index_valuation(index_code: str = "000300") -> dict[str, Any]:
    """指数估值（PE 与股息率，仅中证支持）。"""
    cache_key = f"index_valuation:{index_code}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    df, src = _router.route("index_valuation", index_code=index_code)
    records = _df_to_records(df)
    result = {"index_code": index_code, "valuation": records, "source": src, "count": len(records)}
    cache.set(cache_key, result, TTL_DAILY)
    return result
