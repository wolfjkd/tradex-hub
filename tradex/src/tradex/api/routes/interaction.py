"""投资者互动类 REST 端点（工单 T34）。

路径前缀：/api/v1（由 http_server.py 挂载时加上）。

端点：
- GET /interaction/cninfo-irm?symbol=000001       互动易（深市）
- GET /interaction/sse-e-interaction?symbol=600519 上证 e 互动（沪市）
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ...api.schemas import (
    ERR_BAD_REQUEST,
    ERR_DATA_SOURCE_UNREACHABLE,
    Envelope,
    envelope_ok,
)
from ...service import interaction_service

router = APIRouter(prefix="/interaction", tags=["interaction"])


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


@router.get("/cninfo-irm", response_model=Envelope[dict])
def cninfo_irm(
    symbol: str = Query(..., min_length=6, max_length=6, description="深市股票代码"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> Envelope[dict]:
    """互动易（深市投资者问答）。"""
    _validate_symbol(symbol)
    try:
        return envelope_ok(interaction_service.get_cninfo_irm(
            symbol=symbol, page=page, page_size=page_size
        ))
    except Exception as e:
        raise _data_source_error(e)


@router.get("/sse-e-interaction", response_model=Envelope[dict])
def sse_e_interaction(
    symbol: str = Query(..., min_length=6, max_length=6, description="沪市股票代码"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    kind: str = Query("", description="问答类型筛选，留空返回全部"),
) -> Envelope[dict]:
    """上证 e 互动（沪市投资者问答）。"""
    _validate_symbol(symbol)
    try:
        return envelope_ok(interaction_service.get_sse_e_interaction(
            symbol=symbol, page=page, page_size=page_size, kind=kind
        ))
    except Exception as e:
        raise _data_source_error(e)
