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
    source: str = Query("", description="源 key（fed/sec_edgar/...），留空 = 聚合全部已接入源"),
    doc_type: str = Query(
        "",
        description="文档类型过滤：index_review/filing/press_release/macro_release，留空全部",
    ),
    limit: int = Query(30, ge=1, le=100),
    identifier: str = Query("", description="仅 sec_edgar：ticker 或 CIK，留空聚合默认中概清单"),
    form_type: str = Query("", description="仅 sec_edgar：文书类型过滤（10-K/6-K 等），留空全部"),
    data: str = Query("", description="仅 msci：list=名单明细（默认）/dates=期次日历/summary=公告摘要"),
    review_period: str = Query("", description="仅 msci：期次 '2026-11' 或 'Nov26'，默认最新期"),
    extra_params: str = Query("", description='JSON 透传低频参数，如 hkex：{"title":"中期業績","from_date":"20260601"}'),
) -> Envelope[dict]:
    """境外官方机构一手公告（UTC 存储 + 北京时间双标）。"""
    return serve_envelope(
        lambda: official_disclosure_service.get_official_disclosures(
            source=source, doc_type=doc_type, limit=limit,
            identifier=identifier, form_type=form_type,
            data=data, review_period=review_period,
            extra_params=extra_params,
        )
    )


@router.get("/sources", response_model=Envelope[dict])
def official_sources() -> Envelope[dict]:
    """已接入境外官方源清单。"""
    return serve_envelope(official_disclosure_service.get_official_sources)
