"""macro_service：官方宏观业务逻辑层（SP-2026-09-23-001）。

业务函数：
- get_pmi（统计局 PMI）
- get_bond_yield_curve（中债收益率曲线）

2026-09-28 死源剥离（老板拍板）：get_social_financing / get_repo_fixing_rate /
get_lpr_history 已随上游死源移除。
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from ..data_sources import get_router
from ..utils.cache import TTL_DAILY, cache
from ..utils.formatter import df_to_records

logger = logging.getLogger(__name__)
_router = get_router()


def _df_to_records(df: pd.DataFrame, max_rows: int | None = None) -> list[dict]:
    if df is None or df.empty:
        return []
    if max_rows is not None:
        df = df.head(max_rows)
    return df_to_records(df, max_rows=max_rows)


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


def get_index_valuation(index_code: str = "000300") -> dict[str, Any]:
    """中证指数官方估值（PE + 股息率，oss-ch.csindex.com.cn 一手文件）。"""
    cache_key = f"index_valuation:{index_code}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    df, src = _router.route("index_valuation", index_code=index_code)
    records = _df_to_records(df)
    result = {
        "index_code": index_code,
        "data": records,
        "source": src,
        "count": len(records),
    }
    cache.set(cache_key, result, TTL_DAILY)
    return result
