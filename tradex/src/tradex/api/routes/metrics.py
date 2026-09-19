"""指标导出端点（工单 11 + 工单 15）。

路径：
- GET /api/v1/metrics/json          指标 JSON 快照（包裹式）
- GET /api/v1/metrics/slow-queries  慢查询日志读取（工单 15）

注意：GET /metrics（Prometheus 文本格式）由 http_server.py 直接挂载（不带 /api/v1 前缀，
Prometheus 标准约定）。
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Query

from ...api.schemas import Envelope, envelope_ok
from ...metrics import render_json_snapshot, _SLOW_QUERY_LOG

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/json", response_model=Envelope[dict])
def metrics_json() -> Envelope[dict]:
    """指标 JSON 快照 —— 供前端/告警系统直接消费。"""
    return envelope_ok(render_json_snapshot())


# ────────────────────── 工单 15：慢查询日志读取 ──────────────────────────

# 日志行格式："2026-09-19 10:30:00 GET /api/v1/price/quote 1230ms"
# 用正则一次性解析；非法行静默跳过（不抛异常）
_SLOW_LOG_PATTERN = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+(\S+)\s+(\S+)\s+(\d+)ms\s*$"
)

# 大文件保护：日志超过此大小只读尾部
_TAIL_BYTES = 100 * 1024  # 100KB
_LOG_SIZE_LIMIT = 10 * 1024 * 1024  # 10MB


def _parse_slow_log_line(line: str) -> dict[str, Any] | None:
    """解析单行慢查询日志，非法返回 None。"""
    m = _SLOW_LOG_PATTERN.match(line.strip())
    if not m:
        return None
    return {
        "timestamp": m.group(1),
        "method": m.group(2),
        "path": m.group(3),
        "duration_ms": int(m.group(4)),
    }


def _read_slow_log_tail(limit: int) -> list[dict[str, Any]]:
    """读慢查询日志尾部 limit 条，解析为结构化列表。

    边界处理：
    - 文件不存在 → 返回 []
    - 文件 > 10MB → 只读最后 100KB（避免内存爆 + 解析慢）
    - 非法行 → 静默跳过
    - 尾部可用条数不足 limit → 返回全部可用
    """
    try:
        if not _SLOW_QUERY_LOG.exists():
            return []
        size = _SLOW_QUERY_LOG.stat().st_size
        with open(_SLOW_QUERY_LOG, "rb") as f:
            if size > _LOG_SIZE_LIMIT:
                f.seek(-_TAIL_BYTES, 2)  # 距文件尾 100KB 处
                f.readline()  # 丢弃第一行（很可能被截断）
            lines = f.readlines()
    except OSError:
        return []

    parsed = [_parse_slow_log_line(line.decode("utf-8", errors="replace"))
              for line in lines]
    parsed = [p for p in parsed if p is not None]
    # 日志按时间追加；返回尾部 limit 条，保持时间顺序（最新在后）
    return parsed[-limit:]


@router.get("/slow-queries", response_model=Envelope[list])
def slow_queries(
    limit: int = Query(10, ge=1, le=200, description="返回最近 N 条慢查询"),
) -> Envelope[list]:
    """读取最近的慢查询日志（工单 15）。

    数据源：阶段一已写的 `tradex_slow_query.log` 文件。
    返回结构化数组，每条含 `{timestamp, method, path, duration_ms}`。
    """
    return envelope_ok(_read_slow_log_tail(limit))
