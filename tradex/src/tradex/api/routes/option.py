"""ETF 期权类 REST 端点（工单 T34）。

路径前缀：/api/v1（由 http_server.py 挂载时加上）。

端点：
- GET /option/tquote?underlying=510050    ETF 期权 T 型报价
- GET /option/greeks?underlying=510050    ETF 期权希腊字母 + IV
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ...api.schemas import (
    ERR_DATA_SOURCE_UNREACHABLE,
    Envelope,
    envelope_ok,
)
from ...service import option_service

router = APIRouter(prefix="/option", tags=["option"])


def _data_source_error(e: Exception):
    return HTTPException(
        status_code=502, detail=f"数据源不可达: {e}",
        headers={"X-ErrCode": str(ERR_DATA_SOURCE_UNREACHABLE)},
    )


@router.get("/tquote", response_model=Envelope[dict])
def tquote(
    underlying: str = Query("510050", description="标的 ETF 代码，默认 510050（50ETF）"),
) -> Envelope[dict]:
    """ETF 期权 T 型报价（买卖五档 / 持仓量 / 行权价）。"""
    try:
        return envelope_ok(option_service.get_etf_option_tquote(underlying=underlying))
    except Exception as e:
        raise _data_source_error(e)


@router.get("/greeks", response_model=Envelope[dict])
def greeks(
    underlying: str = Query("510050", description="标的 ETF 代码"),
) -> Envelope[dict]:
    """ETF 期权希腊字母 + 隐含波动率。"""
    try:
        return envelope_ok(option_service.get_etf_option_greeks(underlying=underlying))
    except Exception as e:
        raise _data_source_error(e)
