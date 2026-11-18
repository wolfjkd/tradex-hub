"""industry_news_service：产业链资讯业务逻辑层（QI-ARCH-05 补接缝，2026-11-18）。

从 routes/industry_news.py 抽出——路由层越过 service 直伸手 SmartRouter 违
硬约定#9，回到既有接缝。数据层 data_sources/industry_news_fetchers.py
（106 个海外英文 RSS 直连，对应 A 股 12 个板块；不做 AI 提炼）。
"""

from __future__ import annotations

import pandas as pd

from ..data_sources import get_router
from ..data_sources.industry_news_fetchers import get_source_count, list_tracks

_router = get_router()

_VALID_TRACKS = {
    "ai", "semi", "robot", "auto", "energy", "bio",
    "space", "security", "tech", "consumer", "macro", "science",
}


def get_news(track: str = "", days: int = 7, per_source: int = 6) -> dict:
    """按赛道抓取产业链资讯（海外英文 RSS 直连）。"""
    t = track.strip().lower() if track else track
    if t and t not in _VALID_TRACKS:
        raise ValueError(f"未知赛道: {t}; 可用: {sorted(_VALID_TRACKS)}")
    df, src = _router.route(
        "industry_news", track=t, days=days, per_source=per_source,
    )
    records = (
        df.where(pd.notnull(df), None).to_dict(orient="records")
        if df is not None and not df.empty
        else []
    )
    return {"track": t, "news": records, "source": src, "count": len(records)}


def tracks() -> dict:
    """列出所有可用赛道 + 当前冻结版源总数。"""
    return {
        "tracks": list_tracks(),
        "source_count": get_source_count(),
        "frozen_at": "2026-09-23",
    }
