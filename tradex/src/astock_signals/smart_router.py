"""
智能路由引擎 — 基于健康评分/响应时间/数据质量的自动路由选择。

核心逻辑：
1. 每个数据源有健康评分（0-100），基于最近N次调用的成功率/响应时间/数据质量
2. 请求时自动选评分最高的源，失败自动降级到次优源
3. 评分动态更新，自动隔离故障源
4. 独占源（exclusive=True）失败不降级，直接返回错误

设计原则：
- 一主一备：每个数据类型至少 2 个源（独占源除外）
- 自动降级：主力失败不阻断，静默切备用
- 独占源保护：独占源失败不降级，避免无意义的重试
- 健康感知：连续失败的源评分归零，不再选中
"""

from __future__ import annotations

import time
import logging
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class SourceHealth:
    """单个数据源的健康状态。"""
    name: str
    score: float = 100.0       # 0-100 健康评分
    total_calls: int = 0
    success_count: int = 0
    fail_count: int = 0
    avg_latency_ms: float = 0.0
    last_success_ts: float = 0.0
    last_fail_ts: float = 0.0
    consecutive_fails: int = 0
    _latency_window: list[float] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        if self.total_calls == 0:
            return 1.0
        return self.success_count / self.total_calls

    @property
    def is_healthy(self) -> bool:
        return self.score >= 20.0 and self.consecutive_fails < 5

    def record_success(self, latency_ms: float):
        self.total_calls += 1
        self.success_count += 1
        self.consecutive_fails = 0
        self.last_success_ts = time.time()
        # 滑动窗口记录延迟（最近50次）
        self._latency_window.append(latency_ms)
        if len(self._latency_window) > 50:
            self._latency_window = self._latency_window[-50:]
        self.avg_latency_ms = sum(self._latency_window) / len(self._latency_window)
        # 成功恢复评分
        self.score = min(100.0, self.score + 5.0)
        # 延迟惩罚：>5s扣分，>10s重罚
        if latency_ms > 10000:
            self.score = max(0, self.score - 10)
        elif latency_ms > 5000:
            self.score = max(0, self.score - 5)

    def record_failure(self):
        self.total_calls += 1
        self.fail_count += 1
        self.consecutive_fails += 1
        self.last_fail_ts = time.time()
        # 失败惩罚：连续失败加重
        penalty = 20 * min(self.consecutive_fails, 5)
        self.score = max(0, self.score - penalty)
        # 连续5次失败直接归零
        if self.consecutive_fails >= 5:
            self.score = 0.0

    def recover(self, amount: float = 10.0):
        """定时恢复评分（用于间歇性故障的源）。"""
        if self.consecutive_fails == 0 and self.score < 100:
            self.score = min(100.0, self.score + amount)

    def to_dict(self) -> dict:
        """转换为字典（供看板使用）。"""
        return {
            "name": self.name,
            "score": round(self.score, 1),
            "success_rate": round(self.success_rate * 100, 1),
            "avg_latency_ms": round(self.avg_latency_ms, 0),
            "total_calls": self.total_calls,
            "fail_count": self.fail_count,
            "consecutive_fails": self.consecutive_fails,
            "last_success_ts": self.last_success_ts,
            "last_fail_ts": self.last_fail_ts,
            "is_healthy": self.is_healthy,
        }


class SmartRouter:
    """智能路由引擎。

    Usage:
        router = SmartRouter()
        router.register("quote", "akshare", akshare_fetch_fn, priority=1)
        router.register("quote", "tencent", tencent_fetch_fn, priority=2)
        result = router.route("quote", code="600519")

        # 独占源（失败不降级）
        router.register("auction", "eltdx", eltdx_fetch_fn, priority=1, exclusive=True)
        result = router.route("auction", code="600519")
    """

    def __init__(self):
        # _sources: data_type -> list of (source_name, fetch_fn, priority, exclusive)
        self._sources: dict[str, list[tuple[str, Callable, int, bool]]] = defaultdict(list)
        self._health: dict[str, SourceHealth] = {}
        self._lock = threading.Lock()

    def register(
        self,
        data_type: str,
        source_name: str,
        fetch_fn: Callable,
        priority: int = 100,
        exclusive: bool = False,
    ):
        """注册数据源。

        Args:
            data_type: 数据类型（如 "quote", "kline", "auction"）
            source_name: 数据源名称（如 "akshare", "eltdx", "tencent"）
            fetch_fn: 获取数据的可调用对象，接受 **kwargs，返回数据
            priority: 优先级（越小越高，1=主源, 100=备源, 200=兜底）
            exclusive: 是否独占源（True=失败不降级，直接返回错误）
        """
        key = f"{data_type}:{source_name}"
        with self._lock:
            if key not in self._health:
                self._health[key] = SourceHealth(name=source_name)
            self._sources[data_type].append((source_name, fetch_fn, priority, exclusive))
            # 按优先级排序
            self._sources[data_type].sort(key=lambda x: x[2])

    def route(self, data_type: str, **kwargs) -> tuple[Any, str]:
        """智能路由：按健康评分选择数据源，失败自动降级。

        独占源（exclusive=True）失败后不降级，直接 raise。

        Returns:
            (data, source_name) — 数据内容和来源名称
        Raises:
            RuntimeError: 所有数据源都失败（或独占源失败）
        """
        candidates = self._sources.get(data_type, [])
        if not candidates:
            raise RuntimeError(f"No data source registered for '{data_type}'")

        # 按健康评分排序（评分高的优先）
        with self._lock:
            scored = []
            for name, fn, priority, exclusive in candidates:
                key = f"{data_type}:{name}"
                health = self._health.get(key)
                if health is None:
                    # 新源：注册时已创建 SourceHealth，这里兜底
                    health = SourceHealth(name=name)
                    self._health[key] = health
                if health.is_healthy:
                    # 综合评分 = 健康分 * 0.7 + 优先级分 * 0.3
                    priority_score = max(0, 100 - priority)
                    combined = health.score * 0.7 + priority_score * 0.3
                    scored.append((combined, name, fn, health, exclusive))

        scored.sort(key=lambda x: x[0], reverse=True)

        errors = []
        for _, source_name, fetch_fn, health, exclusive in scored:
            t0 = time.time()
            try:
                result = fetch_fn(**kwargs)
                latency_ms = (time.time() - t0) * 1000
                health.record_success(latency_ms)
                logger.debug(
                    "SmartRouter: %s via %s OK (%.0fms)", data_type, source_name, latency_ms
                )
                return result, source_name
            except Exception as e:
                health.record_failure()
                errors.append(f"{source_name}: {e}")
                logger.warning(
                    "SmartRouter: %s via %s FAILED: %s", data_type, source_name, e
                )
                # 独占源失败不降级，直接 raise
                if exclusive:
                    raise RuntimeError(
                        f"Exclusive source '{source_name}' for '{data_type}' failed: {e}"
                    ) from e

        raise RuntimeError(
            f"All sources for '{data_type}' failed: {'; '.join(errors)}"
        )

    def get_health_report(self) -> list[dict]:
        """获取所有数据源的健康报告。"""
        report = []
        with self._lock:
            for key, health in self._health.items():
                report.append({
                    "source": key,
                    "score": round(health.score, 1),
                    "success_rate": round(health.success_rate * 100, 1),
                    "avg_latency_ms": round(health.avg_latency_ms, 0),
                    "total_calls": health.total_calls,
                    "fail_count": health.fail_count,
                    "consecutive_fails": health.consecutive_fails,
                    "last_success_ts": health.last_success_ts,
                    "last_fail_ts": health.last_fail_ts,
                    "is_healthy": health.is_healthy,
                })
        return sorted(report, key=lambda x: x["score"], reverse=True)

    def get_registry_report(self) -> list[dict]:
        """获取全量注册表（供看板使用）。

        返回每个注册的数据源及其优先级/独占标记/健康状态。
        """
        report = []
        with self._lock:
            for data_type, sources in self._sources.items():
                for source_name, _, priority, exclusive in sources:
                    key = f"{data_type}:{source_name}"
                    health = self._health.get(key)
                    report.append({
                        "data_type": data_type,
                        "source_name": source_name,
                        "priority": priority,
                        "exclusive": exclusive,
                        "health": health.to_dict() if health else None,
                    })
        # 按 data_type + priority 排序
        report.sort(key=lambda x: (x["data_type"], x["priority"]))
        return report

    def recover_all(self, amount: float = 10.0):
        """定时调用：为所有健康的源恢复评分。"""
        with self._lock:
            for health in self._health.values():
                health.recover(amount)


# 全局单例
_global_router: SmartRouter | None = None

def get_router() -> SmartRouter:
    global _global_router
    if _global_router is None:
        _global_router = SmartRouter()
    return _global_router
