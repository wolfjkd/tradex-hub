"""公司基本信息 REST 端点（工单 05）。

路径前缀：/api/v1（由 http_server.py 挂载时加上）。

端点：
- GET /company/search?keyword=贵州       模糊搜索（名称或代码）
- GET /company/info?symbol=600519        公司基本信息（行业/市值/股本）
- GET /company/profile?symbol=600519     主营业务构成
- GET /company/competitors?symbol=600519  同行业竞争对手
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ...api.schemas import (
    ERR_BAD_REQUEST,
    ERR_DATA_SOURCE_UNREACHABLE,
    Envelope,
    envelope_ok,
)
from ...service import company_service

router = APIRouter(prefix="/company", tags=["company"])


@router.get("/search", response_model=Envelope[dict])
def search(
    keyword: str = Query(..., min_length=1, description="搜索关键词（名称或代码）"),
) -> Envelope[dict]:
    """模糊搜索 A 股股票。"""
    try:
        return envelope_ok(company_service.search_stock(keyword=keyword))
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"数据源不可达: {e}",
            headers={"X-ErrCode": str(ERR_DATA_SOURCE_UNREACHABLE)},
        )


@router.get("/info", response_model=Envelope[dict])
def info(
    symbol: str = Query(..., min_length=6, max_length=6, description="6 位 A 股代码"),
) -> Envelope[dict]:
    """公司基本信息。"""
    if not symbol.isdigit():
        raise HTTPException(
            status_code=400,
            detail=f"symbol 必须是 6 位数字代码，收到: {symbol}",
            headers={"X-ErrCode": str(ERR_BAD_REQUEST)},
        )
    try:
        return envelope_ok(company_service.get_company_info(symbol=symbol))
    except ValueError as e:
        raise HTTPException(
            status_code=400, detail=str(e),
            headers={"X-ErrCode": str(ERR_BAD_REQUEST)},
        )
    except Exception as e:
        raise HTTPException(
            status_code=502, detail=f"数据源不可达: {e}",
            headers={"X-ErrCode": str(ERR_DATA_SOURCE_UNREACHABLE)},
        )


@router.get("/profile", response_model=Envelope[dict])
def profile(
    symbol: str = Query(..., min_length=6, max_length=6),
) -> Envelope[dict]:
    """主营业务构成。"""
    if not symbol.isdigit():
        raise HTTPException(
            status_code=400, detail=f"symbol 必须是 6 位数字代码，收到: {symbol}",
            headers={"X-ErrCode": str(ERR_BAD_REQUEST)},
        )
    try:
        return envelope_ok(company_service.get_company_profile(symbol=symbol))
    except Exception as e:
        raise HTTPException(
            status_code=502, detail=f"数据源不可达: {e}",
            headers={"X-ErrCode": str(ERR_DATA_SOURCE_UNREACHABLE)},
        )


@router.get("/competitors", response_model=Envelope[dict])
def competitors(
    symbol: str = Query(..., min_length=6, max_length=6),
    industry: str = Query("", description="行业板块名；空则自动推断"),
) -> Envelope[dict]:
    """同行业竞争对手。"""
    if not symbol.isdigit():
        raise HTTPException(
            status_code=400, detail=f"symbol 必须是 6 位数字代码，收到: {symbol}",
            headers={"X-ErrCode": str(ERR_BAD_REQUEST)},
        )
    try:
        return envelope_ok(company_service.get_competitors(symbol=symbol, industry=industry))
    except ValueError as e:
        raise HTTPException(
            status_code=400, detail=str(e),
            headers={"X-ErrCode": str(ERR_BAD_REQUEST)},
        )
    except Exception as e:
        raise HTTPException(
            status_code=502, detail=f"数据源不可达: {e}",
            headers={"X-ErrCode": str(ERR_DATA_SOURCE_UNREACHABLE)},
        )
