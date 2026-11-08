"""开盘啦（KPL）REST 端点（交接文档 09 票5）。

路径前缀 /api/v1（由 http_server.py 挂载时添加），本路由自带 /kpl 前缀。
数据层 data_sources/kpl_fetchers.py（2026-11-07 六接口实测）。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ...api.schemas import (
    ERR_DATA_SOURCE_UNREACHABLE,
    ERR_INTERNAL,
    Envelope,
    envelope_ok,
)
from ...data_sources import get_router, register_all_sources

router = APIRouter(prefix="/kpl", tags=["kpl"])

# 幂等注册（双检锁）：TestClient / 独立挂载场景下保证 KPL 数据源已登记
register_all_sources()
_router = get_router()


def _validate_date(date: str) -> str:
    """交易日参数前置校验：非法直接 400，不进 router（SmartRouter 会把
    ValueError 包装成记账失败，REST 层无法还原 4xx 语义）。"""
    s = str(date or "").strip()
    if not s:
        return ""
    compact = s.replace("-", "")
    if len(compact) != 8 or not compact.isdigit():
        raise HTTPException(
            status_code=400,
            detail=f"非法日期参数：{date!r}（期望 YYYYMMDD 或 YYYY-MM-DD）",
            headers={"X-ErrCode": str(ERR_INTERNAL)},
        )
    return s


@router.get("/limit-up", response_model=Envelope[list])
def limit_up(
    date: str = Query("", description="交易日 YYYYMMDD，空 = 实时"),
    pid_type: int = Query(0, description="板位 1~5；0 = 全部（循环 1~5 拼接）"),
) -> Envelope[list]:
    """开盘啦涨停复盘（KPL 口径：原因/封单/主力/801xxx 板块码/板位）。"""
    date = _validate_date(date)
    try:
        df, _src = _router.route("kpl_limit_up", date=date, pid_type=pid_type)
        if df is None or df.empty:
            return envelope_ok([])
        return envelope_ok(df.head(200).to_dict(orient="records"))
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e),
            headers={"X-ErrCode": str(ERR_INTERNAL)},
        )
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"数据源不可达: {e}",
            headers={"X-ErrCode": str(ERR_DATA_SOURCE_UNREACHABLE)},
        )


@router.get("/sentiment", response_model=Envelope[dict])
def sentiment() -> Envelope[dict]:
    """开盘啦市场情绪读数（涨停/跌停/炸板率 + 情绪值/连板高度）。"""
    try:
        payload, _src = _router.route("kpl_sentiment")
        return envelope_ok(payload)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"数据源不可达: {e}",
            headers={"X-ErrCode": str(ERR_DATA_SOURCE_UNREACHABLE)},
        )


@router.get("/boards", response_model=Envelope[list])
def boards(
    date: str = Query("", description="交易日 YYYYMMDD，空 = 实时"),
) -> Envelope[list]:
    """开盘啦精选板块列表（801xxx 板块码/强度/主力净额）。"""
    date = _validate_date(date)
    try:
        df, _src = _router.route("kpl_boards", date=date)
        if df is None or df.empty:
            return envelope_ok([])
        return envelope_ok(df.head(100).to_dict(orient="records"))
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e),
            headers={"X-ErrCode": str(ERR_INTERNAL)},
        )
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"数据源不可达: {e}",
            headers={"X-ErrCode": str(ERR_DATA_SOURCE_UNREACHABLE)},
        )


@router.get("/bidding", response_model=Envelope[list])
def bidding(
    date: str = Query("", description="交易日 YYYYMMDD，空 = 实时"),
) -> Envelope[list]:
    """开盘啦竞价涨停委买额榜（历史保留期短，交易日盘中调用）。"""
    date = _validate_date(date)
    try:
        df, _src = _router.route("kpl_bidding", date=date)
        if df is None or df.empty:
            return envelope_ok([])
        return envelope_ok(df.head(100).to_dict(orient="records"))
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e),
            headers={"X-ErrCode": str(ERR_INTERNAL)},
        )
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"数据源不可达: {e}",
            headers={"X-ErrCode": str(ERR_DATA_SOURCE_UNREACHABLE)},
        )
