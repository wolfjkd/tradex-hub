"""财务报表/指标 REST 端点（工单 05）。

路径前缀：/api/v1（由 http_server.py 挂载时加上）。

端点：
- GET /financial/income?symbol=600519            利润表
- GET /financial/balance?symbol=600519           资产负债表
- GET /financial/cashflow?symbol=600519          现金流量表
- GET /financial/line-item?symbol=600519&item=净利润  特定科目提取
- GET /financial/indicators?symbol=600519        财务指标（ROE/毛利率等）
- GET /financial/growth?symbol=600519            成长性指标
- GET /financial/per-share?symbol=600519         每股指标
- GET /financial/segments?symbol=600519          主营构成
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from ._helpers import serve_envelope_400, validate_symbol

from ...api.schemas import (
    ERR_BAD_REQUEST,
    ERR_DATA_SOURCE_UNREACHABLE,
    Envelope,
    envelope_ok,
)
from ...service import financial_service

router = APIRouter(prefix="/financial", tags=["financial"])


@router.get("/income", response_model=Envelope[dict])
def income(
    symbol: str = Query(..., min_length=6, max_length=6),
    num_quarters: int = Query(8, ge=1, le=40),
) -> Envelope[dict]:
    """利润表（按季度）。"""
    validate_symbol(symbol)
    return serve_envelope_400(lambda: financial_service.get_income_statement(symbol=symbol, num_quarters=num_quarters))

@router.get("/balance", response_model=Envelope[dict])
def balance(
    symbol: str = Query(..., min_length=6, max_length=6),
    num_quarters: int = Query(8, ge=1, le=40),
) -> Envelope[dict]:
    """资产负债表（按季度）。"""
    validate_symbol(symbol)
    return serve_envelope_400(lambda: financial_service.get_balance_sheet(symbol=symbol, num_quarters=num_quarters))

@router.get("/cashflow", response_model=Envelope[dict])
def cashflow(
    symbol: str = Query(..., min_length=6, max_length=6),
    num_quarters: int = Query(8, ge=1, le=40),
) -> Envelope[dict]:
    """现金流量表（按季度）。"""
    validate_symbol(symbol)
    return serve_envelope_400(lambda: financial_service.get_cash_flow_statement(symbol=symbol, num_quarters=num_quarters))

@router.get("/line-item", response_model=Envelope[dict])
def line_item(
    symbol: str = Query(..., min_length=6, max_length=6),
    item: str = Query(..., min_length=1, description="科目名（支持模糊匹配）"),
    num_quarters: int = Query(8, ge=1, le=40),
) -> Envelope[dict]:
    """从三大财务报表中提取特定科目。"""
    validate_symbol(symbol)
    return serve_envelope_400(lambda: financial_service.get_financial_line_item(symbol=symbol, item=item, num_quarters=num_quarters))

@router.get("/indicators", response_model=Envelope[dict])
def indicators(
    symbol: str = Query(..., min_length=6, max_length=6),
    num_periods: int = Query(8, ge=1, le=40),
) -> Envelope[dict]:
    """财务分析指标（ROE/毛利率/资产负债率等）。"""
    validate_symbol(symbol)
    return serve_envelope_400(lambda: financial_service.get_financial_indicators(symbol=symbol, num_periods=num_periods))

@router.get("/growth", response_model=Envelope[dict])
def growth(
    symbol: str = Query(..., min_length=6, max_length=6),
    num_periods: int = Query(8, ge=1, le=40),
) -> Envelope[dict]:
    """成长性指标（营收/净利润增长率）。"""
    validate_symbol(symbol)
    return serve_envelope_400(lambda: financial_service.get_growth_rates(symbol=symbol, num_periods=num_periods))

@router.get("/per-share", response_model=Envelope[dict])
def per_share(
    symbol: str = Query(..., min_length=6, max_length=6),
    num_periods: int = Query(8, ge=1, le=40),
) -> Envelope[dict]:
    """每股指标（EPS/BPS/CFPS）。"""
    validate_symbol(symbol)
    return serve_envelope_400(lambda: financial_service.get_per_share_data(symbol=symbol, num_periods=num_periods))

@router.get("/segments", response_model=Envelope[dict])
def segments(
    symbol: str = Query(..., min_length=6, max_length=6),
) -> Envelope[dict]:
    """主营业务构成（按产品/地区分拆营收）。"""
    validate_symbol(symbol)
    return serve_envelope_400(lambda: financial_service.get_segments_revenue(symbol=symbol))