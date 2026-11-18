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
from ._helpers import serve_envelope_async, validate_symbol

from ...api.schemas import ERR_DATA_SOURCE_UNREACHABLE, Envelope
from ...service import diagnostic_service

router = APIRouter(prefix="/diagnostic", tags=["diagnostic"])


@router.get("/stock", response_model=Envelope[dict])
async def stock(
    symbol: str = Query(..., min_length=6, max_length=6, description="6 位 A 股代码"),
) -> Envelope[dict]:
    """个股综合诊断 —— 行情 / 公司 / 财务 / 板块资金 4 维度并行获取。"""
    validate_symbol(symbol)  # QI-STD-04：手写校验收拢 validate_symbol 单点
    # QI-STD-04：手写 try/except 收拢 serve_envelope_async 唯一语义（502 同前）
    return await serve_envelope_async(
        lambda: diagnostic_service.analyze_stock_comprehensive(symbol)
    )


@router.get("/market", response_model=Envelope[dict])
async def market() -> Envelope[dict]:
    """市场全景诊断 —— 大盘 / 板块资金 / 涨跌停 3 维度并行获取。"""
    return await serve_envelope_async(diagnostic_service.analyze_market_overview)


@router.get("/technical", response_model=Envelope[dict])
async def technical(
    symbol: str = Query(..., min_length=6, max_length=6, description="6 位 A 股代码"),
    look_back_days: int = Query(30, ge=1, le=365, description="回溯交易日数 [1, 365]"),
) -> Envelope[dict]:
    """5 维度技术分析 —— 均线 / 趋势 / 量价 / 筹码 / 形态。"""
    validate_symbol(symbol)
    # service 内部已捕获异常并返回 error_response dict（含 success: False）——
    # 判型转 502 保留（业务判型非样板），HTTPException 经 serve_envelope_async 穿透
    async def _build():
        data = diagnostic_service.analyze_technical(symbol, look_back_days)
        if isinstance(data, dict) and data.get("success") is False:
            raise HTTPException(
                status_code=502,
                detail=data.get("error", "技术分析失败"),
                headers={"X-ErrCode": str(ERR_DATA_SOURCE_UNREACHABLE)},
            )
        return data

    return await serve_envelope_async(_build)
