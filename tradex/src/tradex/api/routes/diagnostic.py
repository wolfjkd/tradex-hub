"""诊断/分析类 REST 端点（工单 09）。

路径前缀：/api/v1（由 http_server.py 挂载时加上）。

端点：
- GET /diagnostic/stock?symbol=600519           个股综合诊断（行情/公司/财务/板块资金）
- GET /diagnostic/market                         市场全景（大盘/板块资金/涨跌停）
- GET /diagnostic/technical?symbol=600519&look_back_days=30  5 维度技术分析

对应 MCP 工具：
- analyze_stock_comprehensive (composite_analysis.py)
- analyze_market_overview     (composite_analysis.py)
- analyze_technical           (analysis_engine.py)
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ...api.schemas import (
    ERR_BAD_REQUEST,
    ERR_DATA_SOURCE_UNREACHABLE,
    Envelope,
    envelope_ok,
)
from ...service import diagnostic_service

router = APIRouter(prefix="/diagnostic", tags=["diagnostic"])


def _data_source_error(e: Exception):
    return HTTPException(
        status_code=502, detail=f"数据源不可达: {e}",
        headers={"X-ErrCode": str(ERR_DATA_SOURCE_UNREACHABLE)},
    )


@router.get("/stock", response_model=Envelope[dict])
async def stock(
    symbol: str = Query(..., min_length=6, max_length=6, description="6 位 A 股代码"),
) -> Envelope[dict]:
    """个股综合诊断 —— 行情 / 公司 / 财务 / 板块资金 4 维度并行获取。"""
    if not symbol.isdigit():
        raise HTTPException(
            status_code=400,
            detail=f"symbol 必须为 6 位数字，收到: {symbol}",
            headers={"X-ErrCode": str(ERR_BAD_REQUEST)},
        )
    try:
        data = await diagnostic_service.analyze_stock_comprehensive(symbol)
        return envelope_ok(data)
    except Exception as e:
        raise _data_source_error(e)


@router.get("/market", response_model=Envelope[dict])
async def market() -> Envelope[dict]:
    """市场全景诊断 —— 大盘 / 板块资金 / 涨跌停 3 维度并行获取。"""
    try:
        data = await diagnostic_service.analyze_market_overview()
        return envelope_ok(data)
    except Exception as e:
        raise _data_source_error(e)


@router.get("/technical", response_model=Envelope[dict])
async def technical(
    symbol: str = Query(..., min_length=6, max_length=6, description="6 位 A 股代码"),
    look_back_days: int = Query(30, ge=1, le=365, description="回溯交易日数 [1, 365]"),
) -> Envelope[dict]:
    """5 维度技术分析 —— 均线 / 趋势 / 量价 / 筹码 / 形态。"""
    if not symbol.isdigit():
        raise HTTPException(
            status_code=400,
            detail=f"symbol 必须为 6 位数字，收到: {symbol}",
            headers={"X-ErrCode": str(ERR_BAD_REQUEST)},
        )
    try:
        data = diagnostic_service.analyze_technical(symbol, look_back_days)
        # service 内部已捕获异常并返回 error_response dict（含 success: False）
        if isinstance(data, dict) and data.get("success") is False:
            raise HTTPException(
                status_code=502,
                detail=data.get("error", "技术分析失败"),
                headers={"X-ErrCode": str(ERR_DATA_SOURCE_UNREACHABLE)},
            )
        return envelope_ok(data)
    except HTTPException:
        raise
    except Exception as e:
        raise _data_source_error(e)
