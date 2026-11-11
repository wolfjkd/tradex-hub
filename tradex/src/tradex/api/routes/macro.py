"""官方宏观类 REST 端点（工单 T34）。

路径前缀：/api/v1（由 http_server.py 挂载时加上）。

端点：
- GET /macro/pmi                      统计局 PMI
- GET /macro/bond-yield-curve         中债收益率曲线
- GET /macro/sw-industry-history      申万行业变迁史
- GET /macro/sw-industry-as-of        按 (code, date) 查询申万行业归属

2026-09-28 死源剥离（老板拍板）：/macro/social-financing（人行 404）、
/macro/repo-fixing-rate 与 /macro/lpr（货币网静态 json 404）已随死源移除。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from ._helpers import serve_envelope, validate_symbol

from ...api.schemas import (
    ERR_BAD_REQUEST,
    ERR_DATA_SOURCE_UNREACHABLE,
    Envelope,
    envelope_ok,
)
from ...service import macro_service, sw_industry_service

router = APIRouter(prefix="/macro", tags=["macro"])


@router.get("/pmi", response_model=Envelope[dict])
def pmi() -> Envelope[dict]:
    """统计局 PMI。"""
    return serve_envelope(lambda: macro_service.get_pmi())

@router.get("/bond-yield-curve", response_model=Envelope[dict])
def bond_yield_curve(
    curve: str = Query("国债", description="曲线类型：国债 / 国开债 / 农发债 等"),
) -> Envelope[dict]:
    """中债收益率曲线。"""
    return serve_envelope(lambda: macro_service.get_bond_yield_curve(curve=curve))

@router.get("/index-valuation", response_model=Envelope[dict])
def index_valuation(
    index_code: str = Query("000300", description="指数代码，如 000300 沪深300"),
) -> Envelope[dict]:
    """中证指数官方估值（PE + 股息率）。"""
    return serve_envelope(lambda: macro_service.get_index_valuation(index_code=index_code))

@router.get("/index-constituents", response_model=Envelope[dict])
def index_constituents(
    index_code: str = Query("000300", description="指数代码，如 000300 沪深300"),
) -> Envelope[dict]:
    """中证指数官方成分股名单（仅中证系，国证 399 开头无文件）。"""
    return serve_envelope(lambda: macro_service.get_index_constituents(index_code=index_code))

@router.get("/sw-industry-history", response_model=Envelope[dict])
def sw_industry_history(
    force_refresh: bool = Query(False, description="强制刷新缓存"),
) -> Envelope[dict]:
    """申万行业分类变迁史（首次下载会耗时，后续走内存缓存）。"""
    return serve_envelope(lambda: sw_industry_service.get_sw_industry_history(
            force_refresh=force_refresh
        ))

@router.get("/sw-industry-as-of", response_model=Envelope[dict])
def sw_industry_as_of(
    symbol: str = Query(..., min_length=6, max_length=6),
    date: str = Query("", description="查询日期 YYYY-MM-DD，默认今天"),
) -> Envelope[dict]:
    """按 (code, date) 查询申万行业归属（历史回测用）。"""
    validate_symbol(symbol)
    return serve_envelope(lambda: sw_industry_service.get_sw_industry_as_of(
            symbol=symbol, date=date
        ))