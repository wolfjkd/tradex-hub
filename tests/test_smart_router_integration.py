"""
SmartRouter 集成测试 — 验证 signal_data_flow.py 的 3 个工具与 SmartRouter 的端到端集成。

测试范围:
  1. get_router() 全局单例
  2. signal_data_flow 注册 6 个数据源（3 数据类型 × 2 源）
  3. route() 按优先级选择最高优先级源
  4. 东财源失败时降级到 AKShare
  5. SourceHealth 健康评分动态更新（成功+5/失败-20×consecutive/5次归零）
  6. get_health_report() 返回结构

与 tests/test_smart_router.py（纯函数单测）的区别：
  - 本测试 import signal_data_flow 模块，验证真实的数据源注册副作用
  - 使用与生产代码相同的源命名（em_push2 / akshare / em_datacenter）
  - 测试模块间交互，而非 SourceHealth/SmartRouter 的孤立单元行为
"""

import pytest
from unittest.mock import MagicMock

from astock_signals.smart_router import SmartRouter, SourceHealth, get_router


# ---------------------------------------------------------------------------
# 确保 cn_financial_mcp.tools.signal_data_flow 可被 import（注册 6 个源）
# ---------------------------------------------------------------------------
import os
import sys

_CN_MCP_SRC = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "cn-financial-mcp", "src")
)
if _CN_MCP_SRC not in sys.path:
    sys.path.insert(0, _CN_MCP_SRC)

_HUB_SRC = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "src"))
if _HUB_SRC not in sys.path:
    sys.path.insert(0, _HUB_SRC)


class TestSmartRouterSingleton:
    """get_router() 单例行为。"""

    def test_get_router_returns_same_instance(self):
        """get_router() 多次调用返回同一实例。"""
        r1 = get_router()
        r2 = get_router()
        assert r1 is r2

    def test_get_router_is_smart_router(self):
        """单例是 SmartRouter 类型。"""
        assert isinstance(get_router(), SmartRouter)


class TestSignalDataFlowRegistration:
    """signal_data_flow 模块导入后注册 6 个数据源到全局 SmartRouter。"""

    def test_six_sources_registered(self):
        """导入 signal_data_flow 后全局 router 注册 6 个源（3 类型 × 2 源）。"""
        # 导入触发模块级 _router.register() 调用（6 次）
        from cn_financial_mcp.tools import signal_data_flow  # noqa: F401

        router = get_router()
        report = router.get_health_report()
        source_keys = {entry["source"] for entry in report}

        expected_keys = {
            "fund_flow:em_push2",
            "fund_flow:akshare",
            "dragon_tiger:em_datacenter",
            "dragon_tiger:akshare",
            "industry_comparison:em_push2",
            "industry_comparison:akshare",
        }
        assert expected_keys.issubset(source_keys), (
            f"Missing sources: {expected_keys - source_keys}"
        )

    def test_data_types_have_two_sources_each(self):
        """每种数据类型恰好有 2 个源（一主一备）。"""
        from cn_financial_mcp.tools import signal_data_flow  # noqa: F401

        router = get_router()
        for data_type in ("fund_flow", "dragon_tiger", "industry_comparison"):
            sources = router._sources.get(data_type, [])
            assert len(sources) == 2, (
                f"{data_type} expected 2 sources, got {len(sources)}"
            )


class TestRouteSelectsHighestPriority:
    """route() 按优先级选择数据源。"""

    def test_priority_1_preferred_over_priority_100(self):
        """priority=1 的源应优先于 priority=100 被选中。"""
        router = SmartRouter()
        primary_fn = MagicMock(return_value={"data": "primary"})
        backup_fn = MagicMock(return_value={"data": "backup"})
        router.register("test_type", "primary", primary_fn, priority=1)
        router.register("test_type", "backup", backup_fn, priority=100)

        result, source = router.route("test_type")

        assert source == "primary"
        assert result == {"data": "primary"}
        primary_fn.assert_called_once()
        backup_fn.assert_not_called()


class TestEmPush2FailureDegradesToAkshare:
    """模拟东财 em_push2 失败时降级到 AKShare。"""

    def test_em_push2_exception_falls_back_to_akshare(self):
        """em_push2 抛异常时，route() 自动降级到 akshare 源。"""
        router = SmartRouter()

        def em_push2_failure(**kwargs):
            raise RuntimeError("em_push2 connection refused")

        def akshare_success(**kwargs):
            return {"symbol": kwargs.get("code"), "source": "akshare", "data": "ok"}

        router.register("fund_flow", "em_push2", em_push2_failure, priority=1)
        router.register("fund_flow", "akshare", akshare_success, priority=100)

        result, source = router.route("fund_flow", code="600519")

        assert source == "akshare"
        assert result["source"] == "akshare"
        assert result["data"] == "ok"

    def test_em_push2_empty_data_falls_back_to_akshare(self):
        """em_push2 返回空数据（通过抛 RuntimeError）时降级。"""
        router = SmartRouter()

        def em_push2_empty(**kwargs):
            raise RuntimeError("东财返回空数据")

        def akshare_success(**kwargs):
            return {"realtime": [], "history": [{"date": "2026-08-01"}]}

        router.register("fund_flow", "em_push2", em_push2_empty, priority=1)
        router.register("fund_flow", "akshare", akshare_success, priority=100)

        result, source = router.route("fund_flow", code="000001")

        assert source == "akshare"
        assert len(result["history"]) == 1

    def test_all_sources_fail_raises_runtime_error(self):
        """所有源都失败时抛 RuntimeError。"""
        router = SmartRouter()

        def always_fail(**kwargs):
            raise RuntimeError("connection failed")

        router.register("fund_flow", "em_push2", always_fail, priority=1)
        router.register("fund_flow", "akshare", always_fail, priority=100)

        with pytest.raises(RuntimeError, match="All sources"):
            router.route("fund_flow", code="600519")


class TestHealthScoreUpdate:
    """SourceHealth 健康评分动态更新。"""

    def test_success_increases_score(self):
        """成功调用后评分上升（+5，上限 100）。"""
        h = SourceHealth(name="test")
        h.score = 80.0
        h.record_success(100.0)
        assert h.score == 85.0

    def test_success_capped_at_100(self):
        """评分上限 100。"""
        h = SourceHealth(name="test")
        h.score = 98.0
        h.record_success(50.0)
        assert h.score == 100.0

    def test_failure_decreases_score(self):
        """单次失败扣 20 分。"""
        h = SourceHealth(name="test")
        h.record_failure()
        assert h.score == 80.0
        assert h.consecutive_fails == 1

    def test_five_consecutive_failures_zero_score(self):
        """连续 5 次失败评分归零。"""
        h = SourceHealth(name="test")
        for _ in range(5):
            h.record_failure()
        assert h.score == 0.0
        assert h.is_healthy is False

    def test_router_updates_health_on_route(self):
        """route() 调用后 SourceHealth 反映调用结果。"""
        router = SmartRouter()
        ok_fn = MagicMock(return_value="ok")
        router.register("quote", "src", ok_fn, priority=1)

        router.route("quote")

        report = router.get_health_report()
        assert len(report) == 1
        assert report[0]["total_calls"] == 1
        assert report[0]["success_rate"] == 100.0


class TestHealthReportStructure:
    """get_health_report() 返回结构验证。"""

    def test_report_is_list_of_dicts(self):
        """报告是 list[dict]。"""
        router = SmartRouter()
        router.register("quote", "src1", MagicMock(return_value="ok"))
        report = router.get_health_report()
        assert isinstance(report, list)
        assert all(isinstance(entry, dict) for entry in report)

    def test_report_has_required_fields(self):
        """每个条目包含所有必需字段。"""
        router = SmartRouter()
        router.register("quote", "src1", MagicMock(return_value="ok"))
        router.route("quote")
        report = router.get_health_report()
        required_fields = {
            "source", "score", "success_rate", "avg_latency_ms",
            "total_calls", "fail_count", "consecutive_fails",
            "last_success_ts", "last_fail_ts", "is_healthy",
        }
        assert required_fields.issubset(report[0].keys())

    def test_report_sorted_by_score_desc(self):
        """报告按 score 降序排列。"""
        router = SmartRouter()
        router.register("quote", "high", MagicMock(return_value="ok"), priority=1)
        router.register("quote", "low", MagicMock(side_effect=Exception("fail")), priority=2)
        # 让 low 失败
        try:
            router.route("quote")
        except RuntimeError:
            pass

        report = router.get_health_report()
        scores = [e["score"] for e in report]
        assert scores == sorted(scores, reverse=True)
