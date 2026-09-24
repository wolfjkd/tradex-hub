"""指数追踪类 REST 端点（工单 T34）。

路径前缀：/api/v1（由 http_server.py 挂载时加上）。

端点：
- GET /index/constituents?index_code=000300    指数成分股
- GET /index/weights?index_code=000300         指数权重
- GET /index/valuation?index_code=000300       指数估值（PE / 股息率）
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ...api.schemas import (
    ERR_DATA_SOURCE_UNREACHABLE,
    Envelope,
    envelope_ok,
)
from ...service import index_service

router = APIRouter(prefix="/index", tags=["index"])


def _data_source_error(e: Exception):
    return HTTPException(
        status_code=502, detail=f"数据源不可达: {e}",
        headers={"X-ErrCode": str(ERR_DATA_SOURCE_UNREACHABLE)},
    )


@router.get("/constituents", response_model=Envelope[dict])
def constituents(
    index_code: str = Query("000300", description="指数代码，默认 000300（沪深 300）"),
) -> Envelope[dict]:
    """指数成分股。"""
    try:
        return envelope_ok(index_service.get_index_constituents(index_code=index_code))
    except Exception as e:
        raise _data_source_error(e)


@router.get("/weights", response_model=Envelope[dict])
def weights(
    index_code: str = Query("000300", description="指数代码"),
) -> Envelope[dict]:
    """指数权重。"""
    try:
        return envelope_ok(index_service.get_index_weights(index_code=index_code))
    except Exception as e:
        raise _data_source_error(e)


@router.get("/valuation", response_model=Envelope[dict])
def valuation(
    index_code: str = Query("000300", description="指数代码，仅中证指数支持估值"),
) -> Envelope[dict]:
    """指数估值（PE 与股息率，仅中证指数支持）。"""
    try:
        return envelope_ok(index_service.get_index_valuation(index_code=index_code))
    except Exception as e:
        raise _data_source_error(e)
