"""option_service：ETF 期权业务逻辑层（SP-2026-09-23-001）。

从 tools/etf_option.py 抽出的 2 个业务函数：
- get_etf_option_tquote（T 型报价）
- get_etf_option_greeks（希腊字母 + IV）
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from ..data_sources import get_router
from ..utils.cache import TTL_REALTIME, cache

logger = logging.getLogger(__name__)
_router = get_router()


def _df_to_records(df: pd.DataFrame, max_rows: int | None = None) -> list[dict]:
    if df is None or df.empty:
        return []
    if max_rows is not None:
        df = df.head(max_rows)
    return df.where(pd.notnull(df), None).to_dict(orient="records")


def get_etf_option_tquote(underlying: str = "510050") -> dict[str, Any]:
    """ETF 期权 T 型报价（买卖五档 / 持仓量 / 行权价）。"""
    cache_key = f"etf_option_tquote:{underlying}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    df, src = _router.route("etf_option_tquote", underlying=underlying)
    records = _df_to_records(df)
    result = {"underlying": underlying, "contracts": records, "source": src, "count": len(records)}
    cache.set(cache_key, result, TTL_REALTIME)
    return result


def get_etf_option_greeks(underlying: str = "510050") -> dict[str, Any]:
    """ETF 期权希腊字母 + 隐含波动率。"""
    cache_key = f"etf_option_greeks:{underlying}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    df, src = _router.route("etf_option_greeks", underlying=underlying)
    records = _df_to_records(df)
    result = {"underlying": underlying, "greeks": records, "source": src, "count": len(records)}
    cache.set(cache_key, result, TTL_REALTIME)
    return result
