"""短线类 REST 端点（工单 H1 起）。

路径前缀 /api/v1（由 http_server.py 挂载时添加）。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ...api.schemas import ERR_INTERNAL, Envelope, envelope_ok
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
