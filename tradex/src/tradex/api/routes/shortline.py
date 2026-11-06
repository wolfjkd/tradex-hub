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
from ...shortline import drift, store
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


# ---------------------------------------------------------------- H6 题材 / 首板 / 事实 / 轮动


@router.get("/themes", response_model=Envelope[dict])
def themes(date: str = Query("", description="交易日 YYYYMMDD")) -> Envelope[dict]:
    """题材事件树（问财优先 / 同花顺兜底）。"""
    return _call(lambda: shortline_service.get_themes(date=date))


@router.get("/firstboard", response_model=Envelope[dict])
def firstboard(date: str = Query("", description="交易日 YYYYMMDD")) -> Envelope[dict]:
    """首板名单（按首封时间排序，反包单标）。"""
    return _call(lambda: shortline_service.get_firstboard(date=date))


@router.get("/facts", response_model=Envelope[dict])
def facts(date: str = Query("", description="交易日 YYYYMMDD")) -> Envelope[dict]:
    """盘面事实（封板质量 / 亏钱效应 / 反馈矩阵）。"""
    return _call(lambda: shortline_service.get_facts(date=date))


@router.get("/theme-rotation", response_model=Envelope[dict])
def theme_rotation(
    days: int = Query(5, description="窗口天数 2~60"),
    date: str = Query("", description="交易日 YYYYMMDD"),
) -> Envelope[dict]:
    """题材轮动（缺天画「—」）。"""
    return _call(lambda: shortline_service.get_theme_rotation(days=days, date=date))


# ---------------------------------------------------------------- H3 落库 / 历史


@router.post("/close-fetch", response_model=Envelope[dict])
def close_fetch(
    date: str = Query("", description="交易日 YYYYMMDD，默认今天"),
    force: bool = Query(False, description="强制重算（仍拒绝 partial 覆盖 final）"),
) -> Envelope[dict]:
    """收盘定稿取数 + 落库（幂等）。"""
    return _call(lambda: store.close_fetch(date=date, force=force))


@router.get("/history", response_model=Envelope[dict])
def history(
    date: str = Query("", description="截止日期 YYYYMMDD"),
    days: int = Query(5, description="最近 N 条落库记录"),
) -> Envelope[dict]:
    """收盘定稿历史回读。"""
    return _call(lambda: store.history(days=days, date=date))


@router.get("/store-health", response_model=Envelope[dict])
def store_health() -> Envelope[dict]:
    """落库健康状态（写次数 / 跳过次数 / 最近错误）。"""
    return envelope_ok(store.health())


@router.get("/field-drift", response_model=Envelope[dict])
def field_drift(
    date: str = Query("", description="截止日期 YYYYMMDD"),
    lookback: int = Query(10, description="往回找参考快照的最大记录数"),
) -> Envelope[dict]:
    """四池字段漂移报告（新增/消失列 + 可疑 0）。"""
    return _call(lambda: drift.field_drift(date=date, lookback=lookback))
