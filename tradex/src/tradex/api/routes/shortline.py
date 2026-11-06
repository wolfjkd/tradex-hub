"""短线类 REST 端点（工单 H1 起）。

路径前缀 /api/v1（由 http_server.py 挂载时添加）。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ...api.schemas import (
    ERR_DATA_SOURCE_UNREACHABLE,
    ERR_INTERNAL,
    Envelope,
    envelope_ok,
)
from ...service import bigcaps_service
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
