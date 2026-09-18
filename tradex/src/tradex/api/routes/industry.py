"""板块/行业类 REST 端点（工单 07）。

路径前缀：/api/v1（由 http_server.py 挂载时加上）。

端点：
- GET /industry/list               行业板块列表
- GET /industry/stocks?industry=银行  指定行业的成分股
- GET /industry/concepts           概念板块列表
- GET /industry/fund-flow?sector_type=行业资金流&indicator=今日  板块资金流排名
- GET /industry/pe?industry=白酒    行业历史行情（PE 估值分析）
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ...api.schemas import (
    ERR_BAD_REQUEST,
    ERR_DATA_SOURCE_UNREACHABLE,
    Envelope,
    envelope_ok,
)
from ...service import industry_service

router = APIRouter(prefix="/industry", tags=["industry"])


def _data_source_error(e: Exception):
    return HTTPException(
        status_code=502, detail=f"数据源不可达: {e}",
        headers={"X-ErrCode": str(ERR_DATA_SOURCE_UNREACHABLE)},
    )


@router.get("/list", response_model=Envelope[dict])
def list_industries() -> Envelope[dict]:
    """行业板块列表。"""
    try:
        return envelope_ok(industry_service.get_industry_list())
    except Exception as e:
        raise _data_source_error(e)


@router.get("/stocks", response_model=Envelope[dict])
def stocks(
    industry: str = Query(..., min_length=1, description="行业名（如 白酒/银行/半导体）"),
) -> Envelope[dict]:
    """指定行业的成分股。"""
    try:
        return envelope_ok(industry_service.get_industry_stocks(industry=industry))
    except Exception as e:
        raise _data_source_error(e)


@router.get("/concepts", response_model=Envelope[dict])
def concepts() -> Envelope[dict]:
    """概念板块列表。"""
    try:
        return envelope_ok(industry_service.get_concept_list())
    except Exception as e:
        raise _data_source_error(e)


@router.get("/fund-flow", response_model=Envelope[dict])
def fund_flow(
    sector_type: str = Query("行业资金流", description="行业资金流/概念资金流/地域资金流"),
    indicator: str = Query("今日", description="今日/5日/10日"),
) -> Envelope[dict]:
    """板块资金流向排名。"""
    try:
        return envelope_ok(
            industry_service.get_sector_fund_flow(
                sector_type=sector_type, indicator=indicator
            )
        )
    except Exception as e:
        raise _data_source_error(e)


@router.get("/pe", response_model=Envelope[dict])
def pe(
    industry: str = Query(..., min_length=1, description="行业名"),
    start_date: str = Query("", description="YYYYMMDD"),
    end_date: str = Query("", description="YYYYMMDD"),
) -> Envelope[dict]:
    """行业历史行情（PE 估值分析）。"""
    try:
        return envelope_ok(
            industry_service.get_industry_pe(
                industry=industry, start_date=start_date, end_date=end_date
            )
        )
    except Exception as e:
        raise _data_source_error(e)
