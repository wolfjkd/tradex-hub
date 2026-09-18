"""技术指标类 REST 端点（工单 08）。

路径前缀：/api/v1。

端点（全部接收 symbol，内部自动取 K 线后计算指标）：
- GET /indicator/macd?symbol=600519&period=daily
- GET /indicator/kdj?symbol=600519&period=daily
- GET /indicator/rsi?symbol=600519&period=daily&rsi_period=14
- GET /indicator/boll?symbol=600519&period=daily&boll_period=20&k=2.0

注：MCP 工具 calculate_macd/kdj/rsi/boll 接收价格数组（更适合 AI Agent 在已有
K 线数据时直接计算）；REST 端点接收 symbol（更适合前端/外部系统按股票查询）。
两条路径通过 service/indicator_service.py 的两套函数分别提供。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ...api.schemas import (
    ERR_BAD_REQUEST,
    ERR_DATA_SOURCE_UNREACHABLE,
    Envelope,
    envelope_ok,
)
from ...service import indicator_service

router = APIRouter(prefix="/indicator", tags=["indicator"])


def _validate_symbol(symbol: str) -> None:
    if not (len(symbol) == 6 and symbol.isdigit()):
        raise HTTPException(
            status_code=400,
            detail=f"symbol 必须是 6 位数字代码，收到: {symbol}",
            headers={"X-ErrCode": str(ERR_BAD_REQUEST)},
        )


def _validate_period(period: str) -> None:
    if period not in ("daily", "weekly", "monthly"):
        raise HTTPException(
            status_code=400,
            detail=f"period 只能是 daily/weekly/monthly，收到: {period}",
            headers={"X-ErrCode": str(ERR_BAD_REQUEST)},
        )


@router.get("/macd", response_model=Envelope[dict])
def macd(
    symbol: str = Query(..., min_length=6, max_length=6),
    period: str = Query("daily"),
    fast_period: int = Query(12, ge=2, le=50),
    slow_period: int = Query(26, ge=2, le=100),
    signal_period: int = Query(9, ge=2, le=50),
) -> Envelope[dict]:
    """MACD 指标（按 symbol 自动取 K 线计算）。"""
    _validate_symbol(symbol)
    _validate_period(period)
    try:
        return envelope_ok(indicator_service.calc_macd_by_symbol(
            symbol=symbol, period=period,
            fast_period=fast_period, slow_period=slow_period,
            signal_period=signal_period,
        ))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e),
                            headers={"X-ErrCode": str(ERR_BAD_REQUEST)})
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"数据源不可达: {e}",
                            headers={"X-ErrCode": str(ERR_DATA_SOURCE_UNREACHABLE)})


@router.get("/kdj", response_model=Envelope[dict])
def kdj(
    symbol: str = Query(..., min_length=6, max_length=6),
    period: str = Query("daily"),
    kdj_period: int = Query(9, ge=2, le=30),
    k_period: int = Query(3, ge=2, le=10),
    d_period: int = Query(3, ge=2, le=10),
) -> Envelope[dict]:
    """KDJ 指标。"""
    _validate_symbol(symbol)
    _validate_period(period)
    try:
        return envelope_ok(indicator_service.calc_kdj_by_symbol(
            symbol=symbol, period=period,
            kdj_period=kdj_period, k_period=k_period, d_period=d_period,
        ))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e),
                            headers={"X-ErrCode": str(ERR_BAD_REQUEST)})
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"数据源不可达: {e}",
                            headers={"X-ErrCode": str(ERR_DATA_SOURCE_UNREACHABLE)})


@router.get("/rsi", response_model=Envelope[dict])
def rsi(
    symbol: str = Query(..., min_length=6, max_length=6),
    period: str = Query("daily"),
    rsi_period: int = Query(14, ge=2, le=50),
) -> Envelope[dict]:
    """RSI 指标。"""
    _validate_symbol(symbol)
    _validate_period(period)
    try:
        return envelope_ok(indicator_service.calc_rsi_by_symbol(
            symbol=symbol, period=period, rsi_period=rsi_period,
        ))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e),
                            headers={"X-ErrCode": str(ERR_BAD_REQUEST)})
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"数据源不可达: {e}",
                            headers={"X-ErrCode": str(ERR_DATA_SOURCE_UNREACHABLE)})


@router.get("/boll", response_model=Envelope[dict])
def boll(
    symbol: str = Query(..., min_length=6, max_length=6),
    period: str = Query("daily"),
    boll_period: int = Query(20, ge=5, le=100),
    k: float = Query(2.0, ge=0.5, le=5.0),
) -> Envelope[dict]:
    """BOLL 布林带。"""
    _validate_symbol(symbol)
    _validate_period(period)
    try:
        return envelope_ok(indicator_service.calc_boll_by_symbol(
            symbol=symbol, period=period, boll_period=boll_period, k=k,
        ))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e),
                            headers={"X-ErrCode": str(ERR_BAD_REQUEST)})
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"数据源不可达: {e}",
                            headers={"X-ErrCode": str(ERR_DATA_SOURCE_UNREACHABLE)})
