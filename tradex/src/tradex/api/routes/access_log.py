"""访问日志查询端点（工单 19）。

路径：
- GET /api/v1/access-log  查询最近的访问日志（按时间倒序）
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from ...api.schemas import Envelope, envelope_ok
from ...middleware.access_log import query_access_log

router = APIRouter(prefix="/access-log", tags=["access-log"])


@router.get("", response_model=Envelope[list])
def list_access_log(
    limit: int = Query(50, ge=1, le=500, description="返回最近 N 条访问日志"),
    path: str = Query("", description="路径前缀过滤（如 /api/v1/price）"),
) -> Envelope[list]:
    """查询访问日志（工单 19）。

    数据源：SQLite access_log 表（中间件双写）。
    排序：按 id 倒序（最新在前）。
    """
    items = query_access_log(limit=limit, path_filter=path)
    return envelope_ok(items)
