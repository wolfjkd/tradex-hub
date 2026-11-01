"""工单 04（2026-11-01）测试：失败分级惩罚与限流语义对齐。

背景：akshare 1.20.7+ 对东财 push2 限流立即抛 RateLimitError 且不再重试。
此前任何失败都走 record_failure() 重罚（首败 -20，连败系数递增，3 次即
掉出健康候选）—— 临时限流会把好源打进黑名单长期降权。

分级后：
  rate_limit — 轻罚 -2、不推进连败、永不触发拉黑；
  timeout    — 轻罚 -5、计入连败（连吃 5 次仍归零）；
  hard       — 原逻辑（-20×连败系数，5 次归零）。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from astock_signals.smart_router import SourceHealth, SmartRouter, _classify_failure


class FakeRateLimitError(Exception):
    """模拟 akshare.exceptions.RateLimitError（类名含 RateLimit 即命中）。"""


class FakeReadTimeout(TimeoutError):
    """模拟 requests.exceptions.ReadTimeout（内置 TimeoutError 子类）。"""


class TestClassifyFailure:
    """异常 → 分级判定（类名模式，不依赖上游包）。"""

    def test_rate_limit(self):
        assert _classify_failure(FakeRateLimitError("429")) == "rate_limit"

    def test_timeout_family(self):
        assert _classify_failure(FakeReadTimeout("read timed out")) == "timeout"

    def test_hard_default(self):
        assert _classify_failure(ValueError("bad param")) == "hard"
        assert _classify_failure(RuntimeError("boom")) == "hard"


class TestRecordFailureKinds:
    """record_failure(kind) 三档惩罚行为。"""

    def test_rate_limit_light_penalty_no_blacklist(self):
        h = SourceHealth(name="rl")
        for _ in range(20):
            h.record_failure("rate_limit")
        # 轻罚 2×20=40 分，但连败计数不推进 —— 永不拉黑
        assert h.score == 60.0
        assert h.consecutive_fails == 0
        assert h.is_healthy is True

    def test_rate_limit_success_recovers(self):
        h = SourceHealth(name="rl")
        h.record_failure("rate_limit")
        h.record_success(100.0)
        assert h.consecutive_fails == 0
        assert h.score == 100.0

    def test_timeout_medium_penalty_counts_streak(self):
        h = SourceHealth(name="to")
        for _ in range(5):
            h.record_failure("timeout")
        # 轻罚 5×5=25 分，但连败计数推进 —— 5 次仍归零拉黑
        assert h.score == 0.0
        assert h.consecutive_fails == 5

    def test_hard_keeps_legacy_penalty(self):
        h = SourceHealth(name="hd")
        h.record_failure("hard")
        assert h.score == 80.0  # 首败 -20，与旧逻辑一致
        h.record_failure("hard")
        assert h.score == 40.0  # 二败 -40
        h.record_failure("hard")
        assert h.score == 0.0   # 三败钳到 0

    def test_default_kind_is_hard(self):
        h = SourceHealth(name="df")
        h.record_failure()
        assert h.score == 80.0


class TestRouteRateLimitDegradation:
    """「限流 → 秒级降级 → 备源返回」整条路径 + 主源不被拉黑。"""

    def _make_router(self):
        router = SmartRouter()

        def rate_limited(**kwargs):
            raise FakeRateLimitError("push2 rate limit, retry later")

        def fallback_ok(**kwargs):
            return {"ok": True}

        router.register("dt_test", "akshare", rate_limited, priority=1)
        router.register("dt_test", "sina", fallback_ok, priority=100)
        return router

    def test_rate_limit_falls_through_to_backup(self):
        router = self._make_router()
        data, source = router.route("dt_test")
        assert source == "sina"
        assert data == {"ok": True}

    def test_rate_limited_source_stays_healthy(self):
        router = self._make_router()
        for _ in range(3):
            with pytest.raises(Exception):
                # 强制只走限流源（固定源不降级），连吃 3 次限流
                router.route("dt_test", source_name="akshare")
        health = router._health["dt_test:akshare"]
        # 三次限流仅 -6 分，仍为健康候选（旧逻辑连吃 3 次 hard 已归零拉黑）
        assert health.score == 94.0
        assert health.is_healthy is True
        assert health.consecutive_fails == 0

    def test_all_sources_rate_limited_raises_with_error_detail(self):
        router = SmartRouter()

        def always_limited(**kwargs):
            raise FakeRateLimitError("limited")

        router.register("dt_all", "s1", always_limited, priority=1)
        with pytest.raises(RuntimeError, match="FakeRateLimitError"):
            router.route("dt_all")
