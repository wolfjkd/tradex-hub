"""kpl_service：开盘啦（KPL）业务逻辑层（QI-ARCH-05 补接缝，2026-11-18）。

从 routes/kpl.py 抽出——路由层越过 service 直伸手 SmartRouter 违硬约定#9
（REST 与 MCP 共享同一 service 层），回到既有接缝。

幂等注册（双检锁）随迁：TestClient / 独立挂载场景下保证 KPL 数据源已登记。
"""

from __future__ import annotations

import pandas as pd

from ..data_sources import get_router, register_all_sources

register_all_sources()
_router = get_router()


def limit_up(date: str = "", pid_type: int = 0) -> list[dict]:
    """开盘啦涨停复盘（KPL 口径：原因/封单/主力/801xxx 板块码/板位）。"""
    df, _src = _router.route("kpl_limit_up", date=date, pid_type=pid_type)
    if df is None or df.empty:
        return []
    return df.head(200).to_dict(orient="records")


def sentiment() -> dict:
    """市场情绪读数（涨停/跌停/炸板率 + 情绪值/连板高度）。"""
    payload, _src = _router.route("kpl_sentiment")
    return payload


def boards(date: str = "") -> list[dict]:
    """精选板块列表（801xxx 板块码/强度/主力净额）。"""
    df, _src = _router.route("kpl_boards", date=date)
    if df is None or df.empty:
        return []
    return df.head(100).to_dict(orient="records")


def bidding(date: str = "") -> list[dict]:
    """竞价涨停委买额榜（历史保留期短，交易日盘中调用）。"""
    df, _src = _router.route("kpl_bidding", date=date)
    if df is None or df.empty:
        return []
    return df.head(100).to_dict(orient="records")
