"""tradex.metrics —— Prometheus 指标定义与采集（工单 11）。

指标清单（spec 第三章 3.2）：
  - requests_total              Counter   请求总数（含 method/path/code 标签）
  - request_duration_seconds    Histogram 请求耗时分布
  - errors_total                Counter   错误请求数
  - data_source_health          Gauge     各数据源健康状态（1=健康/0=不健康）
  - data_source_latency_seconds Gauge    各数据源最近一次响应延迟
  - slow_queries_total          Counter   慢查询计数
  - gateway_uptime_seconds      Gauge     网关启动至今秒数
  - tools_registered            Gauge     注册的 MCP 工具数
  - cache_hits_total            Counter   缓存命中次数
  - cache_misses_total          Counter   缓存未命中次数

输出：
  - GET /metrics                 Prometheus 文本格式
  - GET /api/v1/metrics/json     包裹式 JSON（前端可直接消费）

设计：
  - 用 prometheus_client 官方客户端（已是 tradex 依赖），无需重新发明
  - FastAPI 中间件自动埋点 requests_total / request_duration_seconds / errors_total
  - 缓存指标由 cache.stats dict 同步（无需侵入 cache 模块）
  - 慢查询日志：超过阈值写 tradex_slow_query.log
"""

from __future__ import annotations

import logging
import os
import time
from collections import deque
from pathlib import Path
from typing import Any

from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    CollectorRegistry,
    generate_latest,
)

logger = logging.getLogger(__name__)

# 单独 registry 避免和可能存在的其他 prometheus 实例冲突
REGISTRY = CollectorRegistry()

# 全局启动时间
_START_TIME = time.time()

# 慢查询阈值（env TRADEX_SLOW_QUERY_MS，默认 800ms）
SLOW_QUERY_THRESHOLD_MS = int(os.environ.get("TRADEX_SLOW_QUERY_MS", "800"))

# 慢查询日志路径（tradex-hub/tradex_slow_query.log）
_HUB_ROOT = Path(__file__).resolve().parents[3]
_SLOW_QUERY_LOG = _HUB_ROOT / "tradex_slow_query.log"

# ───────────────────────── 工单 16：端点统计 ─────────────────────────
# 内存结构：path -> method -> {durations: deque, count, error_count}
# 滑动窗口默认保留 1000 条耗时记录，用于算 P50/P95/P99
_ENDPOINT_WINDOW = 1000
_endpoint_stats: dict[str, dict[str, dict[str, Any]]] = {}


def record_endpoint_call(method: str, path: str, duration_s: float, is_error: bool = False) -> None:
    """记录一次端点调用到内存统计结构（工单 16）。

    与 record_request 互补 —— record_request 写 Prometheus Counter/Histogram，
    本函数写内存滑动窗口用于算 P50/P95/P99 分位数（Prometheus Histogram 只给
    预定义 bucket，P95 需额外计算）。失败安全：异常绝不影响主请求。
    """
    try:
        path_stats = _endpoint_stats.setdefault(path, {})
        method_stats = path_stats.setdefault(method, {
            "durations": deque(maxlen=_ENDPOINT_WINDOW),
            "count": 0,
            "error_count": 0,
        })
        method_stats["durations"].append(duration_s * 1000.0)  # 存 ms
        method_stats["count"] += 1
        if is_error:
            method_stats["error_count"] += 1
    except Exception as e:
        logger.debug("record_endpoint_call 失败（不影响主流程）: %s", e)


def _percentile(sorted_values: list[float], p: float) -> float:
    """纯 Python 百分位计算（不依赖 numpy）。

    Args:
        sorted_values: 已升序排列的数值列表
        p: 百分位（0-100）
    Returns:
        对应百分位的值
    """
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    # 最近秩方法（与 numpy.percentile 默认 linear 插值一致）
    k = (len(sorted_values) - 1) * (p / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = k - lo
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac


def get_endpoint_breakdown() -> dict[str, dict[str, dict[str, float]]]:
    """聚合端点统计，返回供 /metrics/json 消费的结构（工单 16）。

    输出格式：
        {
          "/api/v1/price/quote": {
            "GET": {
              "count": 42, "p50_ms": 35.2, "p95_ms": 120.5, "p99_ms": 180.0,
              "error_count": 0, "error_rate": 0.0
            }
          }
        }
    """
    breakdown: dict[str, dict[str, dict[str, float]]] = {}
    for path, methods in _endpoint_stats.items():
        path_entry: dict[str, dict[str, float]] = {}
        for method, stats in methods.items():
            durations = sorted(stats["durations"])
            count = stats["count"]
            error_count = stats["error_count"]
            path_entry[method] = {
                "count": count,
                "p50_ms": round(_percentile(durations, 50), 2),
                "p95_ms": round(_percentile(durations, 95), 2),
                "p99_ms": round(_percentile(durations, 99), 2),
                "error_count": error_count,
                "error_rate": round(error_count / count, 4) if count else 0.0,
            }
        breakdown[path] = path_entry
    return breakdown

# ───────────────────────── 指标定义 ─────────────────────────

requests_total = Counter(
    "tradex_requests_total",
    "Total HTTP requests handled by REST gateway",
    ["method", "path", "code"],
    registry=REGISTRY,
)

request_duration_seconds = Histogram(
    "tradex_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=REGISTRY,
)

errors_total = Counter(
    "tradex_errors_total",
    "Total requests returning non-2xx",
    ["method", "path"],
    registry=REGISTRY,
)

data_source_health = Gauge(
    "tradex_data_source_health",
    "Data source health (1=healthy, 0=unhealthy)",
    ["source"],
    registry=REGISTRY,
)

data_source_latency_seconds = Gauge(
    "tradex_data_source_latency_seconds",
    "Latest data source response latency in seconds",
    ["source"],
    registry=REGISTRY,
)

slow_queries_total = Counter(
    "tradex_slow_queries_total",
    "Requests exceeding slow query threshold",
    ["method", "path"],
    registry=REGISTRY,
)

gateway_uptime_seconds = Gauge(
    "tradex_gateway_uptime_seconds",
    "Gateway uptime in seconds since start",
    registry=REGISTRY,
)

tools_registered = Gauge(
    "tradex_tools_registered",
    "Number of MCP tools registered",
    registry=REGISTRY,
)

cache_hits_total = Counter(
    "tradex_cache_hits_total",
    "Cache hit count",
    registry=REGISTRY,
)

cache_misses_total = Counter(
    "tradex_cache_misses_total",
    "Cache miss count",
    registry=REGISTRY,
)


# ───────────────────────── 采集辅助 ─────────────────────────

def record_request(method: str, path: str, status_code: int, duration_s: float) -> None:
    """FastAPI 中间件调：记录一次请求的指标。

    Args:
        method: HTTP 方法
        path: 请求路径（已归一化，如 /api/v1/price/quote 而非含具体参数）
        status_code: HTTP 状态码
        duration_s: 耗时（秒）
    """
    code_str = str(status_code)
    requests_total.labels(method=method, path=path, code=code_str).inc()
    request_duration_seconds.labels(method=method, path=path).observe(duration_s)
    if status_code >= 400:
        errors_total.labels(method=method, path=path).inc()
    if duration_s * 1000 >= SLOW_QUERY_THRESHOLD_MS:
        slow_queries_total.labels(method=method, path=path).inc()
        _log_slow_query(method, path, duration_s)


def _log_slow_query(method: str, path: str, duration_s: float) -> None:
    """慢查询写日志文件（追加模式）。"""
    try:
        with open(_SLOW_QUERY_LOG, "a", encoding="utf-8") as f:
            f.write(
                f"{time.strftime('%Y-%m-%d %H:%M:%S')} "
                f"{method} {path} {duration_s*1000:.0f}ms\n"
            )
    except OSError as e:
        logger.warning("写慢查询日志失败: %s", e)


def update_cache_metrics() -> None:
    """从 cache.stats 同步 hits/misses 到 Prometheus Counter。

    cache.stats 是 dict 快照（非单调累加），故这里用差值递增。
    简化实现：仅在 `/metrics` 被抓取时调用，每次重置内部基线。
    """
    try:
        from tradex.utils.cache import cache
        stats = cache.stats
        # cache.stats 是累计计数器（非速率），直接 inc 整数值
        # 但 prometheus Counter 只支持 inc（增量），所以记录当前值到 Gauge 而非 Counter
        # 改用 Gauge 反映实时累计值更直观
    except Exception as e:
        logger.debug("更新缓存指标失败: %s", e)


def update_uptime() -> None:
    """刷新 uptime gauge。"""
    gateway_uptime_seconds.set(time.time() - _START_TIME)


def set_tools_registered(count: int) -> None:
    """设置注册工具数。"""
    tools_registered.set(count)


def record_data_source(source: str, latency_s: float, healthy: bool) -> None:
    """记录一次数据源调用的健康与延迟。"""
    data_source_health.labels(source=source).set(1 if healthy else 0)
    data_source_latency_seconds.labels(source=source).set(latency_s)


def render_prometheus_text() -> bytes:
    """渲染 Prometheus 文本格式（供 /metrics 端点）。"""
    update_uptime()
    update_cache_metrics_from_snapshot()
    return generate_latest(REGISTRY)


def render_json_snapshot() -> dict[str, Any]:
    """渲染 JSON 快照（供 /api/v1/metrics/json 端点）。"""
    update_uptime()
    cache_snap = _cache_snapshot()
    return {
        "gateway": {
            "uptime_seconds": time.time() - _START_TIME,
            "tools_registered": tools_registered._value.get()
            if hasattr(tools_registered, "_value") else 0,
        },
        "cache": cache_snap,
        "slow_query_threshold_ms": SLOW_QUERY_THRESHOLD_MS,
        "endpoint_breakdown": get_endpoint_breakdown(),  # 工单 16
        "timestamp": time.time(),
    }


def _cache_snapshot() -> dict:
    """读 cache.stats dict 快照。"""
    try:
        from tradex.utils.cache import cache
        return dict(cache.stats)
    except Exception:
        return {}


def update_cache_metrics_from_snapshot() -> None:
    """从 cache.stats 快照更新 hits/misses Gauge（避免 Counter 重置问题）。"""
    snap = _cache_snapshot()
    if "hits" in snap:
        cache_hits_total._value.set(snap["hits"])  # type: ignore[attr-defined]
    if "misses" in snap:
        cache_misses_total._value.set(snap["misses"])  # type: ignore[attr-defined]
