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

from ...api.schemas import (
    ERR_BAD_REQUEST,
    ERR_DATA_SOURCE_UNREACHABLE,
    Envelope,
    envelope_ok,
)
from ...service import financial_service

router = APIRouter(prefix="/financial", tags=["financial"])


def _validate_symbol(symbol: str) -> None:
    """统一 symbol 校验：6 位数字。"""
    if not (len(symbol) == 6 and symbol.isdigit()):
        raise HTTPException(
            status_code=400,
            detail=f"symbol 必须是 6 位数字代码，收到: {symbol}",
            headers={"X-ErrCode": str(ERR_BAD_REQUEST)},
        )


def _data_source_error(e: Exception):
    """构造数据源异常 HTTPException。"""
    return HTTPException(
        status_code=502,
        detail=f"数据源不可达: {e}",
        headers={"X-ErrCode": str(ERR_DATA_SOURCE_UNREACHABLE)},
    )


def _business_error(e: ValueError):
    """构造业务级异常 HTTPException（400）。"""
    return HTTPException(
        status_code=400, detail=str(e),
        headers={"X-ErrCode": str(ERR_BAD_REQUEST)},
    )


@router.get("/income", response_model=Envelope[dict])
def income(
    symbol: str = Query(..., min_length=6, max_length=6),
    num_quarters: int = Query(8, ge=1, le=40),
) -> Envelope[dict]:
    """利润表（按季度）。"""
    _validate_symbol(symbol)
    try:
        return envelope_ok(financial_service.get_income_statement(symbol=symbol, num_quarters=num_quarters))
    except ValueError as e:
        raise _business_error(e)
    except Exception as e:
        raise _data_source_error(e)


@router.get("/balance", response_model=Envelope[dict])
def balance(
    symbol: str = Query(..., min_length=6, max_length=6),
    num_quarters: int = Query(8, ge=1, le=40),
) -> Envelope[dict]:
    """资产负债表（按季度）。"""
    _validate_symbol(symbol)
    try:
        return envelope_ok(financial_service.get_balance_sheet(symbol=symbol, num_quarters=num_quarters))
    except ValueError as e:
        raise _business_error(e)
    except Exception as e:
        raise _data_source_error(e)


@router.get("/cashflow", response_model=Envelope[dict])
def cashflow(
    symbol: str = Query(..., min_length=6, max_length=6),
    num_quarters: int = Query(8, ge=1, le=40),
) -> Envelope[dict]:
    """现金流量表（按季度）。"""
    _validate_symbol(symbol)
    try:
        return envelope_ok(financial_service.get_cash_flow_statement(symbol=symbol, num_quarters=num_quarters))
    except ValueError as e:
        raise _business_error(e)
    except Exception as e:
        raise _data_source_error(e)


@router.get("/line-item", response_model=Envelope[dict])
def line_item(
    symbol: str = Query(..., min_length=6, max_length=6),
    item: str = Query(..., min_length=1, description="科目名（支持模糊匹配）"),
    num_quarters: int = Query(8, ge=1, le=40),
) -> Envelope[dict]:
    """从三大财务报表中提取特定科目。"""
    _validate_symbol(symbol)
    try:
        return envelope_ok(financial_service.get_financial_line_item(symbol=symbol, item=item, num_quarters=num_quarters))
    except ValueError as e:
        raise _business_error(e)
    except Exception as e:
        raise _data_source_error(e)


@router.get("/indicators", response_model=Envelope[dict])
def indicators(
    symbol: str = Query(..., min_length=6, max_length=6),
    num_periods: int = Query(8, ge=1, le=40),
) -> Envelope[dict]:
    """财务分析指标（ROE/毛利率/资产负债率等）。"""
    _validate_symbol(symbol)
    try:
        return envelope_ok(financial_service.get_financial_indicators(symbol=symbol, num_periods=num_periods))
    except ValueError as e:
        raise _business_error(e)
    except Exception as e:
        raise _data_source_error(e)


@router.get("/growth", response_model=Envelope[dict])
def growth(
    symbol: str = Query(..., min_length=6, max_length=6),
    num_periods: int = Query(8, ge=1, le=40),
) -> Envelope[dict]:
    """成长性指标（营收/净利润增长率）。"""
    _validate_symbol(symbol)
    try:
        return envelope_ok(financial_service.get_growth_rates(symbol=symbol, num_periods=num_periods))
    except ValueError as e:
        raise _business_error(e)
    except Exception as e:
        raise _data_source_error(e)


@router.get("/per-share", response_model=Envelope[dict])
def per_share(
    symbol: str = Query(..., min_length=6, max_length=6),
    num_periods: int = Query(8, ge=1, le=40),
) -> Envelope[dict]:
    """每股指标（EPS/BPS/CFPS）。"""
    _validate_symbol(symbol)
    try:
        return envelope_ok(financial_service.get_per_share_data(symbol=symbol, num_periods=num_periods))
    except ValueError as e:
        raise _business_error(e)
    except Exception as e:
        raise _data_source_error(e)


@router.get("/segments", response_model=Envelope[dict])
def segments(
    symbol: str = Query(..., min_length=6, max_length=6),
) -> Envelope[dict]:
    """主营业务构成（按产品/地区分拆营收）。"""
    _validate_symbol(symbol)
    try:
        return envelope_ok(financial_service.get_segments_revenue(symbol=symbol))
    except ValueError as e:
        raise _business_error(e)
    except Exception as e:
        raise _data_source_error(e)
