"""interaction_service：投资者互动业务逻辑层（SP-2026-09-23-001）。

从 tools/investor_interaction.py 抽出的 2 个业务函数：
- get_cninfo_irm（互动易 / 深市）
- get_sse_e_interaction（上证 e 互动 / 沪市）
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


def get_cninfo_irm(symbol: str, page: int = 1, page_size: int = 20) -> dict[str, Any]:
    """互动易（深市投资者问答）。"""
    symbol = normalize_symbol(symbol)
    cache_key = f"cninfo_irm:{symbol}:{page}:{page_size}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    df, src = _router.route(
        "cninfo_irm", symbol=symbol, page=page, page_size=page_size
    )
    records = _df_to_records(df)
    result = {"symbol": symbol, "qa": records, "source": src, "count": len(records)}
    cache.set(cache_key, result, TTL_DAILY)
    return result


def get_sse_e_interaction(
    symbol: str, page: int = 1, page_size: int = 20, kind: str = ""
) -> dict[str, Any]:
    """上证 e 互动（沪市投资者问答）。"""
    symbol = normalize_symbol(symbol)
    cache_key = f"sse_e_interaction:{symbol}:{page}:{page_size}:{kind}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    df, src = _router.route(
        "sse_e_interaction",
        symbol=symbol, page=page, page_size=page_size, kind=kind,
    )
    records = _df_to_records(df)
    result = {"symbol": symbol, "qa": records, "source": src, "count": len(records)}
    cache.set(cache_key, result, TTL_DAILY)
    return result
