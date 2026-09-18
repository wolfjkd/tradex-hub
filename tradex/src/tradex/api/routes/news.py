"""新闻/公告类 REST 端点（工单 06）。

路径前缀：/api/v1（由 http_server.py 挂载时加上）。

端点：
- GET /news/stock?symbol=600519               个股新闻
- GET /news/announcements?symbol=600519       公司公告（symbol 空则全市场）
- GET /news/search?keyword=业绩预增           关键词搜索（可选 symbol 限定）
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ...api.schemas import (
    ERR_BAD_REQUEST,
    ERR_DATA_SOURCE_UNREACHABLE,
    Envelope,
    envelope_ok,
)
from ...service import news_service

router = APIRouter(prefix="/news", tags=["news"])


@router.get("/stock", response_model=Envelope[dict])
def stock(
    symbol: str = Query(..., min_length=6, max_length=6, description="6 位 A 股代码"),
) -> Envelope[dict]:
    """个股新闻列表。"""
    if not symbol.isdigit():
        raise HTTPException(
            status_code=400, detail=f"symbol 必须是 6 位数字代码，收到: {symbol}",
            headers={"X-ErrCode": str(ERR_BAD_REQUEST)},
        )
    try:
        return envelope_ok(news_service.get_stock_news(symbol=symbol))
    except Exception as e:
        raise HTTPException(
            status_code=502, detail=f"数据源不可达: {e}",
            headers={"X-ErrCode": str(ERR_DATA_SOURCE_UNREACHABLE)},
        )


@router.get("/announcements", response_model=Envelope[dict])
def announcements(
    symbol: str = Query("", description="6 位 A 股代码；为空返回全市场最新"),
    num_results: int = Query(30, ge=1, le=100, description="最大返回条数"),
) -> Envelope[dict]:
    """上市公司公告。"""
    if symbol and not symbol.isdigit():
        raise HTTPException(
            status_code=400, detail=f"symbol 必须是 6 位数字代码，收到: {symbol}",
            headers={"X-ErrCode": str(ERR_BAD_REQUEST)},
        )
    try:
        return envelope_ok(
            news_service.get_company_announcements(symbol=symbol, num_results=num_results)
        )
    except Exception as e:
        raise HTTPException(
            status_code=502, detail=f"数据源不可达: {e}",
            headers={"X-ErrCode": str(ERR_DATA_SOURCE_UNREACHABLE)},
        )


@router.get("/search", response_model=Envelope[dict])
def search(
    keyword: str = Query(..., min_length=1, description="搜索关键词"),
    symbol: str = Query("", description="可选 6 位股票代码，限定范围"),
    num_results: int = Query(20, ge=1, le=100),
) -> Envelope[dict]:
    """关键词搜索财经新闻。"""
    if symbol and not symbol.isdigit():
        raise HTTPException(
            status_code=400, detail=f"symbol 必须是 6 位数字代码，收到: {symbol}",
            headers={"X-ErrCode": str(ERR_BAD_REQUEST)},
        )
    try:
        return envelope_ok(
            news_service.search_news(keyword=keyword, symbol=symbol, num_results=num_results)
        )
    except Exception as e:
        raise HTTPException(
            status_code=502, detail=f"数据源不可达: {e}",
            headers={"X-ErrCode": str(ERR_DATA_SOURCE_UNREACHABLE)},
        )
