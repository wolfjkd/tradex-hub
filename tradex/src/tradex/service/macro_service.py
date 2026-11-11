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
    def _factory() -> dict[str, Any]:
        df, src = _router.route("pmi_data")
        records = _df_to_records(df)
        return {"data": records, "source": src, "count": len(records)}

    return cache.get_or_set("pmi_data", _factory, TTL_DAILY)


def get_bond_yield_curve(curve: str = "国债") -> dict[str, Any]:
    """中债收益率曲线。"""
    def _factory() -> dict[str, Any]:
        df, src = _router.route("bond_yield_curve", curve=curve)
        records = _df_to_records(df)
        return {"curve": curve, "data": records, "source": src, "count": len(records)}

    return cache.get_or_set(f"bond_yield_curve:{curve}", _factory, TTL_DAILY)


def get_index_valuation(index_code: str = "000300") -> dict[str, Any]:
    """中证指数官方估值（PE + 股息率，oss-ch.csindex.com.cn 一手文件）。"""
    def _factory() -> dict[str, Any]:
        df, src = _router.route("index_valuation", index_code=index_code)
        records = _df_to_records(df)
        return {
            "index_code": index_code,
            "data": records,
            "source": src,
            "count": len(records),
        }

    return cache.get_or_set(f"index_valuation:{index_code}", _factory, TTL_DAILY)


def get_index_constituents(index_code: str = "000300") -> dict[str, Any]:
    """中证指数官方成分股名单（oss-ch.csindex.com.cn 一手文件，仅中证系）。

    2026-11-11 老板裁决：index_constituents 加 MCP/REST 暴露（此前仅 hub
    内部路由可达）。国证系（399 开头）无源文件，路由层会抛错（fetcher 404
    转译已注明覆盖范围）。
    """
    def _factory() -> dict[str, Any]:
        df, src = _router.route("index_constituents", index_code=index_code)
        records = _df_to_records(df)
        return {
            "index_code": index_code,
            "constituents": records,
            "source": src,
            "count": len(records),
        }

    return cache.get_or_set(f"index_constituents:{index_code}", _factory, TTL_DAILY)
