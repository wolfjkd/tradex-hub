"""
Task 17: performance_metrics 纯函数单测 (V2.5.0).

覆盖：
  - calculate_performance: 完整绩效指标计算
  - list_performance_metrics: 指标清单查询

策略：
  - 用 MockMCP 捕获 register() 中注册的 async 工具函数
  - 构造本地权益曲线（无网络依赖）
  - 验证返回字段存在性 + 数值合理性
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import sys

import pytest

# ── 路径设置 ──────────────────────────────────────────────────
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CN_MCP_SRC = os.path.join(_PROJECT_ROOT, "cn-financial-mcp", "src")
if _CN_MCP_SRC not in sys.path:
    sys.path.insert(0, _CN_MCP_SRC)

from cn_financial_mcp.tools import performance_metrics as pm  # noqa: E402


# ── 公共辅助 ──────────────────────────────────────────────────

class _MockMCP:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(func):
            self.tools[func.__name__] = func
            return func
        return decorator


def _capture_tools(module) -> dict[str, object]:
    mock = _MockMCP()
    module.register(mock)
    return mock.tools


_TOOLS = _capture_tools(pm)


def _call(func, *args, **kwargs) -> dict:
    raw = asyncio.run(func(*args, **kwargs))
    return json.loads(raw)


# ── 测试数据生成 ──────────────────────────────────────────────

def _equity_curve_from_returns(
    returns: list[float],
    initial: float = 1_000_000.0,
) -> list[float]:
    """将日收益率序列转换为权益曲线。"""
    equity = [initial]
    for r in returns:
        equity.append(round(equity[-1] * (1 + r), 4))
    return equity


def _gen_upward_curve(n: int = 60, daily_rate: float = 0.001) -> list[float]:
    """生成稳定上涨权益曲线。"""
    return _equity_curve_from_returns([daily_rate] * n)


def _gen_downward_curve(n: int = 60, daily_rate: float = -0.002) -> list[float]:
    """生成稳定下跌权益曲线。"""
    return _equity_curve_from_returns([daily_rate] * n)


def _gen_volatile_curve(n: int = 100, seed: int = 42) -> list[float]:
    """生成带波动的权益曲线（确定性伪随机）。"""
    # 简单 LCG 伪随机，避免依赖 random 模块
    rng = seed
    returns: list[float] = []
    for _ in range(n):
        rng = (1103515245 * rng + 12345) & 0x7FFFFFFF
        # 映射到 [-0.02, 0.025] 区间
        r = (rng / 0x7FFFFFFF - 0.5) * 0.045
        returns.append(round(r, 6))
    return _equity_curve_from_returns(returns)


# ════════════════════════════════════════════════════════════════
# calculate_performance 测试
# ════════════════════════════════════════════════════════════════

class TestCalculatePerformance:
    def test_returns_all_metric_groups(self):
        """任务要求: 返回的指标数值合理 - 验证返回结构完整。"""
        curve = _gen_volatile_curve(100)
        out = _call(_TOOLS["calculate_performance"], curve)
        assert out["success"] is True
        # 五个指标组必须存在
        for group in ("return_metrics", "risk_metrics",
                      "risk_adjusted_metrics", "trade_quality_metrics",
                      "cost_metrics"):
            assert group in out, f"missing metric group: {group}"

    def test_return_metrics_fields(self):
        """收益类指标字段完整。"""
        curve = _gen_upward_curve(30)
        rm = _call(_TOOLS["calculate_performance"], curve)["return_metrics"]
        for key in ("total_return", "annualized_return", "days",
                    "initial_equity", "final_equity"):
            assert key in rm
        assert rm["days"] == 31  # 30 日收益 → 31 个权益点
        assert rm["initial_equity"] == 1_000_000.0
        assert rm["final_equity"] == curve[-1]

    def test_total_return_correctness(self):
        """任务要求: 总收益率数值合理。"""
        # 1% 涨幅一日
        curve = [1_000_000.0, 1_010_000.0]
        out = _call(_TOOLS["calculate_performance"], curve)
        assert out["return_metrics"]["total_return"] == 0.01

    def test_upward_curve_positive_return(self):
        """上涨曲线总收益率为正。"""
        curve = _gen_upward_curve(60, daily_rate=0.005)
        out = _call(_TOOLS["calculate_performance"], curve)
        assert out["return_metrics"]["total_return"] > 0
        # 年化收益率应为正且较大
        assert out["return_metrics"]["annualized_return"] > 0

    def test_downward_curve_negative_return(self):
        """下跌曲线总收益率为负。"""
        curve = _gen_downward_curve(60, daily_rate=-0.005)
        out = _call(_TOOLS["calculate_performance"], curve)
        assert out["return_metrics"]["total_return"] < 0
        assert out["return_metrics"]["annualized_return"] < 0

    def test_max_drawdown_in_range(self):
        """任务要求: 最大回撤数值合理（0-1 之间）。"""
        curve = _gen_volatile_curve(100)
        out = _call(_TOOLS["calculate_performance"], curve)
        mdd = out["risk_metrics"]["max_drawdown"]
        assert 0.0 <= mdd <= 1.0
        # 峰值/谷值索引为非负整数
        assert isinstance(out["risk_metrics"]["max_drawdown_peak_idx"], int)
        assert isinstance(out["risk_metrics"]["max_drawdown_trough_idx"], int)

    def test_max_drawdown_correctness(self):
        """构造已知回撤验证。"""
        # 100 → 120 → 90 → 110, max_dd = (120-90)/120 = 0.25
        curve = [100.0, 120.0, 90.0, 110.0]
        out = _call(_TOOLS["calculate_performance"], curve)
        assert out["risk_metrics"]["max_drawdown"] == 0.25
        assert out["risk_metrics"]["max_drawdown_peak_idx"] == 1
        assert out["risk_metrics"]["max_drawdown_trough_idx"] == 2

    def test_volatility_non_negative(self):
        """波动率为非负数。"""
        curve = _gen_volatile_curve(50)
        out = _call(_TOOLS["calculate_performance"], curve)
        assert out["risk_metrics"]["volatility"] >= 0
        assert out["risk_metrics"]["downside_volatility"] >= 0

    def test_volatility_zero_for_constant_curve(self):
        """恒定曲线波动率为 0。"""
        curve = [1_000_000.0] * 10
        out = _call(_TOOLS["calculate_performance"], curve)
        assert out["risk_metrics"]["volatility"] == 0

    def test_sharpe_ratio_finite_for_volatile(self):
        """任务要求: 夏普比率数值合理。"""
        curve = _gen_volatile_curve(100)
        sharpe = _call(_TOOLS["calculate_performance"], curve)["risk_adjusted_metrics"]["sharpe_ratio"]
        # 可能是有限数或 "inf"
        assert sharpe == "inf" or isinstance(sharpe, (int, float))

    def test_sharpe_zero_for_constant_curve(self):
        """恒定曲线夏普为 0（无波动）。"""
        curve = [1_000_000.0] * 10
        out = _call(_TOOLS["calculate_performance"], curve)
        assert out["risk_adjusted_metrics"]["sharpe_ratio"] == 0
        assert out["risk_adjusted_metrics"]["sortino_ratio"] == 0

    def test_risk_free_rate_propagated(self):
        """无风险利率应回显到结果。"""
        curve = _gen_upward_curve(30)
        out = _call(_TOOLS["calculate_performance"], curve, risk_free_rate=0.05)
        assert out["risk_adjusted_metrics"]["risk_free_rate"] == 0.05

    def test_trading_days_propagated(self):
        """trading_days 参数应生效（影响年化）。"""
        curve = _gen_upward_curve(30, daily_rate=0.01)
        out_252 = _call(_TOOLS["calculate_performance"], curve, trading_days=252)
        out_365 = _call(_TOOLS["calculate_performance"], curve, trading_days=365)
        # 不同年化天数应导致不同年化收益率
        assert out_252["return_metrics"]["annualized_return"] != \
               out_365["return_metrics"]["annualized_return"]

    def test_trades_quality_metrics(self):
        """交易质量指标字段完整。"""
        curve = _gen_upward_curve(20)
        trades = [
            {"profit": 1000, "commission": 5, "stamp_tax": 1, "slippage": 2},
            {"profit": -500, "commission": 5, "stamp_tax": 1, "slippage": 2},
            {"profit": 2000, "commission": 5, "stamp_tax": 1, "slippage": 2},
        ]
        tqm = _call(_TOOLS["calculate_performance"], curve, trades)["trade_quality_metrics"]
        assert tqm["total_trades"] == 3
        assert tqm["win_count"] == 2
        assert tqm["loss_count"] == 1
        assert tqm["win_rate"] == round(2 / 3, 4)
        assert tqm["total_profit"] == 2500  # 1000 - 500 + 2000

    def test_win_rate_zero_for_no_trades(self):
        """无交易时胜率为 0。"""
        curve = _gen_upward_curve(20)
        tqm = _call(_TOOLS["calculate_performance"], curve)["trade_quality_metrics"]
        assert tqm["total_trades"] == 0
        assert tqm["win_rate"] == 0
        assert tqm["profit_factor"] == 0

    def test_cost_metrics(self):
        """费用统计字段完整。"""
        curve = _gen_upward_curve(20)
        trades = [
            {"profit": 1000, "commission": 10, "stamp_tax": 2, "slippage": 3},
            {"profit": -500, "commission": 10, "stamp_tax": 2, "slippage": 3},
        ]
        cm = _call(_TOOLS["calculate_performance"], curve, trades)["cost_metrics"]
        assert cm["total_commission"] == 20
        assert cm["total_tax"] == 4
        assert cm["total_slippage"] == 6
        assert cm["total_cost"] == 30
        assert cm["cost_per_trade"] == 15  # 30 / 2

    def test_benchmark_metrics_when_provided(self):
        """传入基准曲线时应返回 benchmark_metrics。"""
        strategy_curve = _gen_upward_curve(30, daily_rate=0.003)
        benchmark_curve = _gen_upward_curve(30, daily_rate=0.001)
        out = _call(
            _TOOLS["calculate_performance"],
            strategy_curve,
            benchmark_curve=benchmark_curve,
        )
        bm = out["benchmark_metrics"]
        assert "benchmark_total_return" in bm
        assert "benchmark_annualized_return" in bm
        assert "excess_return" in bm
        assert "excess_total_return" in bm
        # 策略日收益 0.003 > 基准 0.001，超额收益应为正
        assert bm["excess_return"] > 0

    def test_no_benchmark_metrics_when_absent(self):
        """未传基准曲线时不应有 benchmark_metrics 字段。"""
        curve = _gen_upward_curve(20)
        out = _call(_TOOLS["calculate_performance"], curve)
        assert "benchmark_metrics" not in out

    def test_insufficient_data_returns_error(self):
        """权益曲线少于 2 个点应返回 error。"""
        out = _call(_TOOLS["calculate_performance"], [1_000_000.0])
        assert out.get("error") is True
        assert "至少需要 2 个数据点" in out.get("message", "")

    def test_empty_curve_returns_error(self):
        """空曲线应返回 error。"""
        out = _call(_TOOLS["calculate_performance"], [])
        assert out.get("error") is True

    def test_var95_cvar95_non_negative(self):
        """VaR/CVaR 应为非负数。"""
        curve = _gen_volatile_curve(50)
        out = _call(_TOOLS["calculate_performance"], curve)
        assert out["risk_metrics"]["var_95"] >= 0
        assert out["risk_metrics"]["cvar_95"] >= 0

    def test_expected_return_calculation(self):
        """期望收益（单笔平均）正确。"""
        curve = _gen_upward_curve(20)
        trades = [{"profit": 100}, {"profit": 200}, {"profit": -150}]
        tqm = _call(_TOOLS["calculate_performance"], curve, trades)["trade_quality_metrics"]
        assert tqm["expected_return"] == round((100 + 200 - 150) / 3, 4)
        assert tqm["avg_profit_per_trade"] == round((100 + 200 - 150) / 3, 4)

    def test_profit_factor_inf_when_no_loss(self):
        """无亏损交易时 profit_factor 应为 inf。"""
        curve = _gen_upward_curve(20)
        trades = [{"profit": 100}, {"profit": 200}]
        tqm = _call(_TOOLS["calculate_performance"], curve, trades)["trade_quality_metrics"]
        assert tqm["profit_factor"] == "inf"


# ════════════════════════════════════════════════════════════════
# list_performance_metrics 测试
# ════════════════════════════════════════════════════════════════

class TestListPerformanceMetrics:
    def test_returns_categories(self):
        """任务要求: 返回指标清单 - categories 字段。"""
        out = _call(_TOOLS["list_performance_metrics"])
        assert out["success"] is True
        assert "categories" in out
        # 五个类别
        for cat in ("return", "risk", "risk_adjusted", "trade_quality", "cost"):
            assert cat in out["categories"]

    def test_returns_metrics_list(self):
        """metrics 字段是列表。"""
        out = _call(_TOOLS["list_performance_metrics"])
        assert isinstance(out["metrics"], list)
        assert len(out["metrics"]) > 0

    def test_total_count_matches_metrics(self):
        """total_count 应等于 metrics 列表长度。"""
        out = _call(_TOOLS["list_performance_metrics"])
        assert out["total_count"] == len(out["metrics"])

    def test_each_metric_has_required_fields(self):
        """每个指标应含 name/category/desc/formula。"""
        out = _call(_TOOLS["list_performance_metrics"])
        for m in out["metrics"]:
            assert "name" in m
            assert "category" in m
            assert "desc" in m
            assert "formula" in m

    def test_known_metrics_present(self):
        """关键指标应出现在清单中。"""
        out = _call(_TOOLS["list_performance_metrics"])
        names = {m["name"] for m in out["metrics"]}
        for name in ("total_return", "annualized_return", "volatility",
                      "max_drawdown", "sharpe_ratio", "sortino_ratio",
                      "calmar_ratio", "win_rate", "profit_factor", "var_95"):
            assert name in names, f"missing metric: {name}"

    def test_total_count_at_least_20(self):
        """至少 20 个指标。"""
        out = _call(_TOOLS["list_performance_metrics"])
        assert out["total_count"] >= 20
