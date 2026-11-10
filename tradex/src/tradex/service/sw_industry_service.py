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
from ..utils.formatter import df_to_records
from ..utils.symbol import normalize_symbol

logger = logging.getLogger(__name__)
_router = get_router()


def _df_to_records(df: pd.DataFrame, max_rows: int | None = None) -> list[dict]:
    if df is None or df.empty:
        return []
    if max_rows is not None:
        df = df.head(max_rows)
    return df_to_records(df, max_rows=max_rows)


def get_sw_industry_history(force_refresh: bool = False) -> dict[str, Any]:
    """申万行业分类变迁史。"""
    def _factory() -> dict[str, Any]:
        df, src = _router.route("sw_industry_history", force_refresh=force_refresh)
        records = _df_to_records(df, max_rows=500)
        return {"history": records, "source": src, "count": len(records)}

    if force_refresh:
        # 语义保留：强刷不读缓存也不写缓存（原 if not force_refresh 双跳过）
        return _factory()
    return cache.get_or_set("sw_industry_history", _factory, TTL_DAILY)


def get_sw_industry_as_of(symbol: str, date: str = "") -> dict[str, Any]:
    """按 (code, date) 查询股票的申万行业归属。"""
    symbol = normalize_symbol(symbol)

    def _factory() -> dict[str, Any]:
        df, src = _router.route("sw_industry_as_of", symbol=symbol, date=date)
        records = _df_to_records(df)
        return {
            "symbol": symbol, "date": date,
            "industry": records, "source": src, "count": len(records),
        }

    return cache.get_or_set(f"sw_as_of:{symbol}:{date}", _factory, TTL_DAILY)
