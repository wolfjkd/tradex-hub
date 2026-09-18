"""资金类 REST 端点（工单 03）。

路径前缀：/api/v1（由 http_server.py 挂载时加上）。

端点：
- GET /fund/flow?symbol=600519       个股资金流向（主力/超大单/大单/中单/小单净流入）
- GET /fund/northbound               北向资金（沪股通+深股通）净流入

工单 03 的 service 层函数（get_money_flow / get_north_bound_flow）已在工单 02
一并抽到 service/market_service.py（同属"行情/资金"领域）；本文件只挂 REST 端点。

后续若资金类工具扩展（板块资金流、行业资金流等），可新建独立 service/fund_service.py
并把这两个函数迁过去；当前阶段保持与 market 同域不拆，避免过度设计。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ...api.schemas import (
    ERR_BAD_REQUEST,
    ERR_DATA_SOURCE_UNREACHABLE,
    Envelope,
    envelope_ok,
)
from ...service import market_service

router = APIRouter(prefix="/fund", tags=["fund"])


@router.get("/flow", response_model=Envelope[dict])
def flow(
    symbol: str = Query(..., min_length=6, max_length=6, description="6 位 A 股代码，如 600519"),
) -> Envelope[dict]:
    """个股资金流向数据（主力/超大单/大单/中单/小单净流入序列）。"""
    # 简单格式校验：6 位数字（Query 的 min/max_length 已限长度，这里补内容校验）
    if not symbol.isdigit():
        raise HTTPException(
            status_code=400,
            detail=f"symbol 必须是 6 位数字代码，收到: {symbol}",
            headers={"X-ErrCode": str(ERR_BAD_REQUEST)},
        )
    try:
        return envelope_ok(market_service.get_money_flow(symbol=symbol))
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"数据源不可达: {e}",
            headers={"X-ErrCode": str(ERR_DATA_SOURCE_UNREACHABLE)},
        )


@router.get("/northbound", response_model=Envelope[dict])
def northbound() -> Envelope[dict]:
    """北向资金（沪股通+深股通）净流入历史数据。"""
    try:
        return envelope_ok(market_service.get_north_bound_flow())
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"数据源不可达: {e}",
            headers={"X-ErrCode": str(ERR_DATA_SOURCE_UNREACHABLE)},
        )
