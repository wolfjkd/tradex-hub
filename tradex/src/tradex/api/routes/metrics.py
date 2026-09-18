"""指标导出端点（工单 11）。

路径：
- GET /api/v1/metrics/json   指标 JSON 快照（包裹式）

注意：GET /metrics（Prometheus 文本格式）由 http_server.py 直接挂载（不带 /api/v1 前缀，
Prometheus 标准约定）。
"""

from __future__ import annotations

from fastapi import APIRouter

from ...api.schemas import Envelope, envelope_ok
from ...metrics import render_json_snapshot

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/json", response_model=Envelope[dict])
def metrics_json() -> Envelope[dict]:
    """指标 JSON 快照 —— 供前端/告警系统直接消费。"""
    return envelope_ok(render_json_snapshot())
