"""产业链资讯类 REST 端点（工单 T34）。

路径前缀：/api/v1（由 http_server.py 挂载时加上）。

端点：
- GET /industry-news/get?track=ai&days=7    按赛道抓取产业链资讯
- GET /industry-news/tracks                 列出所有赛道 + 源总数

业务层 service/industry_news_service.py（QI-ARCH-05，2026-11-18 补接缝——
原路由越层直伸手 SmartRouter 违硬约定#9）；错误语义 serve_envelope 唯一口径。
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from ._helpers import serve_envelope

from ...api.schemas import Envelope
from ...service import industry_news_service

router = APIRouter(prefix="/industry-news", tags=["industry-news"])


@router.get("/get", response_model=Envelope[dict])
def get_news(
    track: str = Query("", description="赛道 key，留空 = 全部 12 个赛道"),
    days: int = Query(7, ge=1, le=30),
    per_source: int = Query(6, ge=1, le=20),
) -> Envelope[dict]:
    """按赛道抓取产业链资讯（海外英文 RSS 直连）。

    「未知赛道」400 走 ValueError→400（serve_envelope 唯一语义，QI-STD-04
    收拢 + QI-ARCH-05 补 service 接缝）。
    """
    return serve_envelope(
        lambda: industry_news_service.get_news(track=track, days=days, per_source=per_source)
    )


@router.get("/tracks", response_model=Envelope[dict])
def tracks() -> Envelope[dict]:
    """列出所有可用赛道 + 当前冻结版源总数。"""
    return serve_envelope(industry_news_service.tracks)
