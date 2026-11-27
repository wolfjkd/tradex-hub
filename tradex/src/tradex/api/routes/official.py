"""境外官方公告 REST 端点（OFFSRC-00 P01，2026-11-27）。

路径前缀：/api/v1（由 http_server.py 挂载时加上）。

端点：
- GET /official/disclosures?source=&doc_type=&limit=   境外官方公告（可聚合）
- GET /official/sources                                已接入源清单

业务层 service/official_disclosure_service.py；错误语义 serve_envelope 唯一口径。
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from ._helpers import serve_envelope

from ...api.schemas import Envelope
from ...service import official_disclosure_service

router = APIRouter(prefix="/official", tags=["official"])


@router.get("/disclosures", response_model=Envelope[dict])
def get_disclosures(
    source: str = Query("", description="源 key（fed/...），留空 = 聚合全部已接入源"),
    doc_type: str = Query(
        "",
        description="文档类型过滤：index_review/filing/press_release/macro_release，留空全部",
    ),
    limit: int = Query(30, ge=1, le=100),
) -> Envelope[dict]:
    """境外官方机构一手公告（UTC 存储 + 北京时间双标）。"""
    return serve_envelope(
        lambda: official_disclosure_service.get_official_disclosures(
            source=source, doc_type=doc_type, limit=limit
        )
    )


@router.get("/sources", response_model=Envelope[dict])
def official_sources() -> Envelope[dict]:
    """已接入境外官方源清单。"""
    return serve_envelope(official_disclosure_service.get_official_sources)
