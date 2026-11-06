"""短线类 REST 端点（工单 H1 起）。

路径前缀 /api/v1（由 http_server.py 挂载时添加）。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ...api.schemas import (
    ERR_BAD_REQUEST,
    ERR_DATA_SOURCE_UNREACHABLE,
    ERR_INTERNAL,
    Envelope,
    envelope_ok,
)
from ...service import bigcaps_service, shortline_service, turnover_service
from ...shortline.catalog import build_catalog

router = APIRouter(prefix="/shortline", tags=["shortline"])


@router.get("/catalog", response_model=Envelope[dict])
def catalog() -> Envelope[dict]:
    """短线端点目录（声明式元数据）。"""
    try:
        return envelope_ok(build_catalog())
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"生成短线端点目录失败: {e}",
            headers={"X-ErrCode": str(ERR_INTERNAL)},
        )


@router.get("/bigcaps", response_model=Envelope[dict])
def bigcaps(
    min_mktcap_yi: float = Query(500, description="总市值门槛（亿元）"),
    limit: int = Query(0, description="只返回前 N 只，0 = 全部"),
) -> Envelope[dict]:
    """大市值名单（新浪主源，东财快照兜底，1 小时缓存）。"""
    try:
        return envelope_ok(
            bigcaps_service.get_bigcaps(min_mktcap_yi=min_mktcap_yi, limit=limit)
        )
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"数据源不可达: {e}",
            headers={"X-ErrCode": str(ERR_DATA_SOURCE_UNREACHABLE)},
        )


@router.get("/turnover-top", response_model=Envelope[dict])
def turnover_top(
    date: str = Query("", description="交易日 YYYYMMDD，默认今天"),
    limit: int = Query(20, description="返回前 N 只（上限 500）"),
    kind: str = Query("auto", description="auto / history / realtime"),
) -> Envelope[dict]:
    """全市场成交额榜（通达信盘后包主源，失败降级实时榜）。"""
    try:
        return envelope_ok(
            turnover_service.get_turnover_top(date=date, limit=limit, kind=kind)
        )
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


# ---------------------------------------------------------------- H2 读数端点


def _call(fn) -> Envelope[dict]:
    """统一调用读数 service：参数错误 → 400，数据源不可达 → 502。"""
    try:
        return envelope_ok(fn())
    except ValueError as e:
        raise HTTPException(
            status_code=400, detail=str(e), headers={"X-ErrCode": str(ERR_BAD_REQUEST)}
        )
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"数据源不可达: {e}",
            headers={"X-ErrCode": str(ERR_DATA_SOURCE_UNREACHABLE)},
        )


@router.get("/emotion", response_model=Envelope[dict])
def emotion(date: str = Query("", description="交易日 YYYYMMDD")) -> Envelope[dict]:
    """情绪四项（赚钱效应 / 晋级率 / 连板溢价 / 梯队断层）。"""
    return _call(lambda: shortline_service.get_emotion(date=date))


@router.get("/cycle", response_model=Envelope[dict])
def cycle(
    days: int = Query(5, description="窗口天数 2~60"),
    date: str = Query("", description="交易日 YYYYMMDD"),
) -> Envelope[dict]:
    """情绪周期（窗口分位）。"""
    return _call(lambda: shortline_service.get_cycle(days=days, date=date))


@router.get("/daily", response_model=Envelope[dict])
def daily(date: str = Query("", description="交易日 YYYYMMDD")) -> Envelope[dict]:
    """每日读数。"""
    return _call(lambda: shortline_service.get_daily(date=date))


@router.get("/settled", response_model=Envelope[dict])
def settled(date: str = Query("", description="交易日 YYYYMMDD")) -> Envelope[dict]:
    """昨日涨停股当日表现明细。"""
    return _call(lambda: shortline_service.get_settled(date=date))


@router.get("/live", response_model=Envelope[dict])
def live() -> Envelope[dict]:
    """盘中情绪（此刻快照，15 秒缓存）。"""
    return _call(shortline_service.get_live)


@router.get("/ladder", response_model=Envelope[dict])
def ladder(date: str = Query("", description="交易日 YYYYMMDD")) -> Envelope[dict]:
    """昨日梯队。"""
    return _call(lambda: shortline_service.get_ladder(date=date))


@router.get("/board-ladder", response_model=Envelope[dict])
def board_ladder(date: str = Query("", description="交易日 YYYYMMDD")) -> Envelope[dict]:
    """连板天梯 + 未晋级去向。"""
    return _call(lambda: shortline_service.get_board_ladder(date=date))


@router.get("/structure", response_model=Envelope[dict])
def structure(date: str = Query("", description="交易日 YYYYMMDD")) -> Envelope[dict]:
    """涨停结构 + 四池上游字段清单。"""
    return _call(lambda: shortline_service.get_structure(date=date))
