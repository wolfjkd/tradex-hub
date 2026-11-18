"""产业链资讯类 REST 端点（工单 T34）。

路径前缀：/api/v1（由 http_server.py 挂载时加上）。

端点：
- GET /industry-news/get?track=ai&days=7    按赛道抓取产业链资讯
- GET /industry-news/tracks                 列出所有赛道 + 源总数

产业链资讯数据源：106 个海外英文 RSS 直连，对应 A 股 12 个板块。
不做 AI 提炼（保留原始数据，AI 提炼由下游 TradeX 看板负责）。
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from ._helpers import serve_envelope

from ...api.schemas import Envelope
from ...data_sources.industry_news_fetchers import list_tracks, get_source_count
from ...data_sources import get_router

router = APIRouter(prefix="/industry-news", tags=["industry-news"])

_router = get_router()

_VALID_TRACKS = {
    "ai", "semi", "robot", "auto", "energy", "bio",
    "space", "security", "tech", "consumer", "macro", "science",
}


@router.get("/get", response_model=Envelope[dict])
def get_news(
    track: str = Query("", description="赛道 key，留空 = 全部 12 个赛道"),
    days: int = Query(7, ge=1, le=30),
    per_source: int = Query(6, ge=1, le=20),
) -> Envelope[dict]:
    """按赛道抓取产业链资讯（海外英文 RSS 直连）。

    QI-STD-04（2026-11-18）：残留手写 try/except 收拢进 serve_envelope
    唯一语义——「未知赛道」400 改 ValueError→400（business_error 同文案
    同 X-ErrCode），其余异常走 serve_envelope 502（原 data_source_error 等价）。
    """
    def _build() -> dict:
        t = track.strip().lower() if track else track
        if t and t not in _VALID_TRACKS:
            raise ValueError(f"未知赛道: {t}; 可用: {sorted(_VALID_TRACKS)}")
        df, src = _router.route(
            "industry_news", track=t, days=days, per_source=per_source,
        )
        import pandas as pd
        records = (
            df.where(pd.notnull(df), None).to_dict(orient="records")
            if df is not None and not df.empty else []
        )
        return {"track": t, "news": records, "source": src, "count": len(records)}

    return serve_envelope(_build)


@router.get("/tracks", response_model=Envelope[dict])
def tracks() -> Envelope[dict]:
    """列出所有可用赛道 + 当前冻结版源总数。"""
    return serve_envelope(lambda: {
            "tracks": list_tracks(),
            "source_count": get_source_count(),
            "frozen_at": "2026-09-23",
        })