"""价格/K线类 REST 端点（工单 04）。

路径前缀：/api/v1（由 http_server.py 挂载时加上）。

端点：
- GET /price/quote?symbol=600519       实时报价（A 股 6 位代码或全球代码 usDJI/hkHSI）
- GET /price/kline?symbol=600519&period=daily  历史 K 线（daily/weekly/monthly）
- GET /price/intraday?symbol=600519    当日分时（1 分钟 K 线）

eltdx Rust 内核 panic 防护由 data_sources/eltdx_fetchers.py 的 _NativePanicShield 统一负责，
所有通过 SmartRouter.route() 的调用都自动经过；本端点不需要额外 panic 处理代码。
service 层异常（含 RuntimeError 包装后的原 panic）一律转 502 + code=50001。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ...api.schemas import (
    ERR_BAD_REQUEST,
    ERR_DATA_SOURCE_UNREACHABLE,
    Envelope,
    envelope_ok,
)
from ...service import price_service

router = APIRouter(prefix="/price", tags=["price"])


@router.get("/quote", response_model=Envelope[dict])
def quote(
    symbol: str = Query(..., min_length=2, description="A 股 6 位代码（600519）或全球代码（usDJI）"),
) -> Envelope[dict]:
    """实时报价。"""
    try:
        return envelope_ok(price_service.get_realtime_quote(symbol=symbol))
    except ValueError as e:
        # 业务级错误（如代码未找到） → 400
        raise HTTPException(
            status_code=400,
            detail=str(e),
            headers={"X-ErrCode": str(ERR_BAD_REQUEST)},
        )
    except Exception as e:
        # 数据源异常（含 panic 转 RuntimeError） → 502
        raise HTTPException(
            status_code=502,
            detail=f"数据源不可达: {e}",
            headers={"X-ErrCode": str(ERR_DATA_SOURCE_UNREACHABLE)},
        )


@router.get("/kline", response_model=Envelope[dict])
def kline(
    symbol: str = Query(..., min_length=6, max_length=6, description="6 位 A 股代码"),
    period: str = Query("daily", description="K 线周期：daily/weekly/monthly"),
    start_date: str = Query("", description="开始日期 YYYYMMDD，空返回所有"),
    end_date: str = Query("", description="结束日期 YYYYMMDD，空返回至今"),
    adjust: str = Query("qfq", description="复权：qfq/hfq/空串"),
) -> Envelope[dict]:
    """历史 K 线（OHLCV）。"""
    if period not in ("daily", "weekly", "monthly"):
        raise HTTPException(
            status_code=400,
            detail=f"period 只能是 daily/weekly/monthly，收到: {period}",
            headers={"X-ErrCode": str(ERR_BAD_REQUEST)},
        )
    if not symbol.isdigit():
        raise HTTPException(
            status_code=400,
            detail=f"symbol 必须是 6 位数字代码，收到: {symbol}",
            headers={"X-ErrCode": str(ERR_BAD_REQUEST)},
        )
    try:
        return envelope_ok(
            price_service.get_historical_price(
                symbol=symbol,
                period=period,
                start_date=start_date,
                end_date=end_date,
                adjust=adjust,
            )
        )
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"数据源不可达: {e}",
            headers={"X-ErrCode": str(ERR_DATA_SOURCE_UNREACHABLE)},
        )


@router.get("/intraday", response_model=Envelope[dict])
def intraday(
    symbol: str = Query(..., min_length=6, max_length=6, description="6 位 A 股代码"),
) -> Envelope[dict]:
    """当日分时数据（1 分钟 K 线）。"""
    if not symbol.isdigit():
        raise HTTPException(
            status_code=400,
            detail=f"symbol 必须是 6 位数字代码，收到: {symbol}",
            headers={"X-ErrCode": str(ERR_BAD_REQUEST)},
        )
    try:
        return envelope_ok(price_service.get_intraday_data(symbol=symbol))
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e),
            headers={"X-ErrCode": str(ERR_BAD_REQUEST)},
        )
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"数据源不可达: {e}",
            headers={"X-ErrCode": str(ERR_DATA_SOURCE_UNREACHABLE)},
        )
