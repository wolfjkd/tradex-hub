"""事件驱动类 REST 端点（工单 T34）。

路径前缀：/api/v1（由 http_server.py 挂载时加上）。

端点：
- GET /event/earnings-forecast?symbol=600519    业绩预告
- GET /event/institution-survey?symbol=600519   机构调研
- GET /event/holder-trades?symbol=600519        股东增减持
- GET /event/share-buyback?symbol=600519        股票回购
- GET /event/equity-pledge?symbol=600519        股权质押
- GET /event/ipo-calendar                       新股日历
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
from ...service import event_service

router = APIRouter(prefix="/event", tags=["event"])


@router.get("/earnings-forecast", response_model=Envelope[dict])
def earnings_forecast(
    symbol: str = Query(..., min_length=6, max_length=6),
    report_date: str = Query("", description="报告期 YYYY-MM-DD，留空返回全部"),
    limit: int = Query(50, ge=1, le=200),
) -> Envelope[dict]:
    """业绩预告。"""
    validate_symbol(symbol)
    return serve_envelope(lambda: event_service.get_earnings_forecast(
            symbol=symbol, report_date=report_date, limit=limit
        ))

@router.get("/institution-survey", response_model=Envelope[dict])
def institution_survey(
    symbol: str = Query(..., min_length=6, max_length=6),
    start_date: str = Query(""),
    end_date: str = Query(""),
    limit: int = Query(50, ge=1, le=200),
) -> Envelope[dict]:
    """机构调研。"""
    validate_symbol(symbol)
    return serve_envelope(lambda: event_service.get_institution_survey(
            symbol=symbol, start_date=start_date, end_date=end_date, limit=limit
        ))

@router.get("/holder-trades", response_model=Envelope[dict])
def holder_trades(
    symbol: str = Query(..., min_length=6, max_length=6),
    direction: str = Query("", description="增/减，留空返回全部"),
    start_date: str = Query(""),
    end_date: str = Query(""),
    limit: int = Query(50, ge=1, le=200),
) -> Envelope[dict]:
    """股东增减持。"""
    validate_symbol(symbol)
    return serve_envelope(lambda: event_service.get_holder_trades(
            symbol=symbol, direction=direction,
            start_date=start_date, end_date=end_date, limit=limit
        ))

@router.get("/share-buyback", response_model=Envelope[dict])
def share_buyback(
    symbol: str = Query(..., min_length=6, max_length=6),
    progress: str = Query("", description="实施/完成，留空返回全部"),
    limit: int = Query(50, ge=1, le=200),
) -> Envelope[dict]:
    """股票回购。"""
    validate_symbol(symbol)
    return serve_envelope(lambda: event_service.get_share_buyback(
            symbol=symbol, progress=progress, limit=limit
        ))

@router.get("/equity-pledge", response_model=Envelope[dict])
def equity_pledge(
    symbol: str = Query(..., min_length=6, max_length=6),
    date: str = Query("", description="截止日期 YYYY-MM-DD"),
    limit: int = Query(50, ge=1, le=200),
) -> Envelope[dict]:
    """股权质押。"""
    validate_symbol(symbol)
    return serve_envelope(lambda: event_service.get_equity_pledge(
            symbol=symbol, date=date, limit=limit
        ))

@router.get("/ipo-calendar", response_model=Envelope[dict])
def ipo_calendar(
    days_ahead: int = Query(30, ge=1, le=120, description="未来 N 天"),
    limit: int = Query(50, ge=1, le=200),
) -> Envelope[dict]:
    """新股申购日历。"""
    return serve_envelope(lambda: event_service.get_ipo_calendar(
            days_ahead=days_ahead, limit=limit
        ))