"""官方宏观类 REST 端点（工单 T34）。

路径前缀：/api/v1（由 http_server.py 挂载时加上）。

端点：
- GET /macro/social-financing         人行社融
- GET /macro/pmi                      统计局 PMI
- GET /macro/bond-yield-curve         中债收益率曲线
- GET /macro/repo-fixing-rate         中国货币网回购定盘
- GET /macro/lpr                      LPR 历史
- GET /macro/sw-industry-history      申万行业变迁史
- GET /macro/sw-industry-as-of        按 (code, date) 查询申万行业归属
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ...api.schemas import (
    ERR_BAD_REQUEST,
    ERR_DATA_SOURCE_UNREACHABLE,
    Envelope,
    envelope_ok,
)
from ...service import macro_service, sw_industry_service

router = APIRouter(prefix="/macro", tags=["macro"])


def _validate_symbol(symbol: str) -> None:
    if not (len(symbol) == 6 and symbol.isdigit()):
        raise HTTPException(
            status_code=400,
            detail=f"symbol 必须是 6 位数字代码，收到: {symbol}",
            headers={"X-ErrCode": str(ERR_BAD_REQUEST)},
        )


def _data_source_error(e: Exception):
    return HTTPException(
        status_code=502, detail=f"数据源不可达: {e}",
        headers={"X-ErrCode": str(ERR_DATA_SOURCE_UNREACHABLE)},
    )


@router.get("/social-financing", response_model=Envelope[dict])
def social_financing(
    year: int = Query(0, ge=0, description="年份，默认 0 = 当前年"),
) -> Envelope[dict]:
    """人行社融数据。"""
    try:
        return envelope_ok(macro_service.get_social_financing(year=year))
    except Exception as e:
        raise _data_source_error(e)


@router.get("/pmi", response_model=Envelope[dict])
def pmi() -> Envelope[dict]:
    """统计局 PMI。"""
    try:
        return envelope_ok(macro_service.get_pmi())
    except Exception as e:
        raise _data_source_error(e)


@router.get("/bond-yield-curve", response_model=Envelope[dict])
def bond_yield_curve(
    curve: str = Query("国债", description="曲线类型：国债 / 国开债 / 农发债 等"),
) -> Envelope[dict]:
    """中债收益率曲线。"""
    try:
        return envelope_ok(macro_service.get_bond_yield_curve(curve=curve))
    except Exception as e:
        raise _data_source_error(e)


@router.get("/repo-fixing-rate", response_model=Envelope[dict])
def repo_fixing_rate(
    kind: str = Query("FR", description="定盘类型：FR/Shibor"),
) -> Envelope[dict]:
    """中国货币网回购定盘利率。"""
    try:
        return envelope_ok(macro_service.get_repo_fixing_rate(kind=kind))
    except Exception as e:
        raise _data_source_error(e)


@router.get("/lpr", response_model=Envelope[dict])
def lpr(
    years_back: int = Query(5, ge=1, le=30),
) -> Envelope[dict]:
    """LPR 历史。"""
    try:
        return envelope_ok(macro_service.get_lpr_history(years_back=years_back))
    except Exception as e:
        raise _data_source_error(e)


@router.get("/sw-industry-history", response_model=Envelope[dict])
def sw_industry_history(
    force_refresh: bool = Query(False, description="强制刷新缓存"),
) -> Envelope[dict]:
    """申万行业分类变迁史（首次下载会耗时，后续走内存缓存）。"""
    try:
        return envelope_ok(sw_industry_service.get_sw_industry_history(
            force_refresh=force_refresh
        ))
    except Exception as e:
        raise _data_source_error(e)


@router.get("/sw-industry-as-of", response_model=Envelope[dict])
def sw_industry_as_of(
    symbol: str = Query(..., min_length=6, max_length=6),
    date: str = Query("", description="查询日期 YYYY-MM-DD，默认今天"),
) -> Envelope[dict]:
    """按 (code, date) 查询申万行业归属（历史回测用）。"""
    _validate_symbol(symbol)
    try:
        return envelope_ok(sw_industry_service.get_sw_industry_as_of(
            symbol=symbol, date=date
        ))
    except Exception as e:
        raise _data_source_error(e)
