"""
Task 17: signal_generation 纯函数单测 (V2.5.0).

覆盖：
  - generate_trading_signal: 单票交易信号生成（5 级信号）
  - scan_stocks_for_signals: 批量扫描股票信号
  - validate_signal_quality: 信号质量验证（前瞻收益）

策略：
  - 用 MockMCP 捕获 register() 中注册的 async 工具函数
  - 同时直接测试模块级纯函数 _generate_signal_for_stock
  - 构造本地 H/L/C/V 数组（无网络依赖）
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

from cn_financial_mcp.tools import signal_generation as sg  # noqa: E402


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


_TOOLS = _capture_tools(sg)


def _call(func, *args, **kwargs) -> dict:
    raw = asyncio.run(func(*args, **kwargs))
    return json.loads(raw)


# ── 测试数据生成 ──────────────────────────────────────────────

def _gen_hlcv(n: int, trend: str = "up") -> tuple[list, list, list, list]:
    """生成 n 日 high/low/close/volume 数据。

    trend:
      - "up": 上涨趋势（MA5 上穿 MA20）
      - "down": 下跌趋势
      - "flat": 横盘
      - "volatile": 大幅波动
    """
    if trend == "up":
        # 收盘价线性上涨，MA5 在 MA20 上方
        closes = [round(10.0 + i * 0.2 + math.sin(i * 0.4) * 0.1, 4) for i in range(n)]
    elif trend == "down":
        closes = [round(20.0 - i * 0.2 + math.sin(i * 0.4) * 0.1, 4) for i in range(n)]
    elif trend == "volatile":
        closes = [round(15.0 + math.sin(i * 0.6) * 2.0, 4) for i in range(n)]
    else:  # flat
        closes = [round(10.0 + math.sin(i * 0.2) * 0.05, 4) for i in range(n)]

    highs = [round(c + 0.15 + (i % 3) * 0.03, 4) for i, c in enumerate(closes)]
    lows = [round(c - 0.15 - (i % 3) * 0.03, 4) for i, c in enumerate(closes)]
    volumes = [1_000_000 + (i % 7) * 100_000 for i in range(n)]
    return highs, lows, closes, volumes


# ════════════════════════════════════════════════════════════════
# _generate_signal_for_stock 内部纯函数测试
# ════════════════════════════════════════════════════════════════

class TestGenerateSignalInternal:
    def test_returns_5_level_signal(self):
        """任务要求: 返回 5 级信号之一。"""
        highs, lows, closes, _ = _gen_hlcv(60, "up")
        result = sg._generate_signal_for_stock(highs, lows, closes)
        valid_signals = {
            "strong_buy", "buy", "neutral", "sell", "strong_sell",
        }
        assert result["signal"] in valid_signals

    def test_score_in_0_to_100(self):
        """评分应在 0-100 之间。"""
        highs, lows, closes, _ = _gen_hlcv(60, "up")
        result = sg._generate_signal_for_stock(highs, lows, closes)
        assert 0 <= result["score"] <= 100

    def test_insufficient_data_returns_insufficient_signal(self):
        """数据不足 30 根应返回 insufficient_data。"""
        highs, lows, closes, _ = _gen_hlcv(20, "up")
        result = sg._generate_signal_for_stock(highs, lows, closes)
        assert result["signal"] == "insufficient_data"
        assert result["score"] == 0
        assert "数据不足" in result["reason"]

    def test_returns_reasons_list(self):
        """返回触发明细列表。"""
        highs, lows, closes, _ = _gen_hlcv(60, "up")
        result = sg._generate_signal_for_stock(highs, lows, closes)
        assert "reasons" in result
        assert isinstance(result["reasons"], list)

    def test_returns_indicators(self):
        """返回最新技术指标值。"""
        highs, lows, closes, _ = _gen_hlcv(60, "up")
        result = sg._generate_signal_for_stock(highs, lows, closes)
        ind = result["indicators"]
        for key in ("ma5", "ma20", "macd_dif", "macd_dea",
                    "kdj_k", "kdj_d", "kdj_j", "rsi",
                    "boll_upper", "boll_middle", "boll_lower"):
            assert key in ind

    def test_volumes_affect_score(self):
        """带成交量时应参与量能评分。"""
        highs, lows, closes, volumes = _gen_hlcv(60, "up")
        with_vol = sg._generate_signal_for_stock(highs, lows, closes, volumes)
        without_vol = sg._generate_signal_for_stock(highs, lows, closes)
        # 两者都应生成有效信号
        assert with_vol["signal"] in {"strong_buy", "buy", "neutral", "sell", "strong_sell"}
        assert without_vol["signal"] in {"strong_buy", "buy", "neutral", "sell", "strong_sell"}


# ════════════════════════════════════════════════════════════════
# generate_trading_signal MCP 工具测试
# ════════════════════════════════════════════════════════════════

class TestGenerateTradingSignal:
    def test_returns_5_level_signal(self):
        """任务要求: 验证返回 5 级信号。"""
        highs, lows, closes, _ = _gen_hlcv(60, "up")
        out = _call(_TOOLS["generate_trading_signal"], highs, lows, closes)
        assert out["success"] is True
        assert out["signal"] in {"strong_buy", "buy", "neutral", "sell", "strong_sell"}
        assert "score" in out
        assert "reasons" in out
        assert "indicators" in out
        assert out["data_points"] == 60

    def test_with_volumes(self):
        """传入成交量参数。"""
        highs, lows, closes, volumes = _gen_hlcv(60, "up")
        out = _call(_TOOLS["generate_trading_signal"], highs, lows, closes, volumes)
        assert out["success"] is True
        assert out["signal"] in {"strong_buy", "buy", "neutral", "sell", "strong_sell"}

    def test_insufficient_data_signal(self):
        """数据不足 30 根时返回 insufficient_data 信号。"""
        highs, lows, closes, _ = _gen_hlcv(25, "up")
        out = _call(_TOOLS["generate_trading_signal"], highs, lows, closes)
        assert out["success"] is True
        assert out["signal"] == "insufficient_data"
        assert out["score"] == 0

    def test_score_in_range(self):
        """评分应在 0-100。"""
        for trend in ("up", "down", "flat", "volatile"):
            highs, lows, closes, _ = _gen_hlcv(60, trend)
            out = _call(_TOOLS["generate_trading_signal"], highs, lows, closes)
            assert 0 <= out["score"] <= 100, f"trend={trend} score={out['score']}"

    def test_length_mismatch_returns_error(self):
        """长度不一致返回 error。"""
        out = _call(
            _TOOLS["generate_trading_signal"],
            [10.0, 11.0, 12.0],
            [9.0, 10.0],
            [9.5, 10.5, 11.5],
        )
        assert out.get("error") is True
        assert "长度必须相同" in out.get("message", "")

    def test_volumes_length_mismatch_returns_error(self):
        """volumes 长度与 closes 不一致返回 error。"""
        highs, lows, closes, _ = _gen_hlcv(60, "up")
        out = _call(
            _TOOLS["generate_trading_signal"],
            highs, lows, closes,
            [1_000_000, 2_000_000],  # 长度不匹配
        )
        assert out.get("error") is True
        assert "volumes 长度必须与 closes 相同" in out.get("message", "")

    def test_indicators_complete(self):
        """返回的技术指标字段完整。"""
        highs, lows, closes, _ = _gen_hlcv(60, "up")
        out = _call(_TOOLS["generate_trading_signal"], highs, lows, closes)
        ind = out["indicators"]
        for key in ("ma5", "ma20", "macd_dif", "macd_dea",
                    "kdj_k", "kdj_d", "kdj_j", "rsi",
                    "boll_upper", "boll_middle", "boll_lower"):
            assert key in ind, f"missing indicator: {key}"


# ════════════════════════════════════════════════════════════════
# scan_stocks_for_signals MCP 工具测试
# ════════════════════════════════════════════════════════════════

class TestScanStocksForSignals:
    def test_returns_sorted_by_score_desc(self):
        """任务要求: 验证返回按评分降序。"""
        stocks_data = {}
        for code, trend in [("000001", "up"), ("600519", "down"),
                            ("300750", "volatile"), ("688981", "flat")]:
            highs, lows, closes, volumes = _gen_hlcv(60, trend)
            stocks_data[code] = {
                "highs": highs, "lows": lows, "closes": closes, "volumes": volumes,
            }
        out = _call(_TOOLS["scan_stocks_for_signals"], stocks_data)
        assert out["success"] is True
        results = out["results"]
        # 验证按评分降序
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True), f"scores not desc: {scores}"

    def test_summary_statistics(self):
        """返回的 summary 统计正确。"""
        stocks_data = {}
        for code in ("000001", "600519", "300750"):
            highs, lows, closes, _ = _gen_hlcv(60, "up")
            stocks_data[code] = {"highs": highs, "lows": lows, "closes": closes}
        out = _call(_TOOLS["scan_stocks_for_signals"], stocks_data)
        summary = out["summary"]
        assert summary["total_scanned"] == 3
        assert summary["total_returned"] == 3
        assert summary["errors_count"] == 0
        # signal_counts 累加应等于扫描数
        assert sum(summary["signal_counts"].values()) == 3

    def test_min_score_filter(self):
        """min_score 过滤低于阈值的股票。"""
        stocks_data = {}
        for code, trend in [("000001", "up"), ("600519", "down")]:
            highs, lows, closes, _ = _gen_hlcv(60, trend)
            stocks_data[code] = {"highs": highs, "lows": lows, "closes": closes}
        # 用高阈值过滤
        out = _call(_TOOLS["scan_stocks_for_signals"], stocks_data, min_score=100)
        for r in out["results"]:
            assert r["score"] >= 100

    def test_signal_filter(self):
        """signal_filter 过滤信号级别。"""
        stocks_data = {}
        for code, trend in [("000001", "up"), ("600519", "down"),
                            ("300750", "flat")]:
            highs, lows, closes, _ = _gen_hlcv(60, trend)
            stocks_data[code] = {"highs": highs, "lows": lows, "closes": closes}
        # 只保留 strong_buy 和 buy
        out = _call(
            _TOOLS["scan_stocks_for_signals"],
            stocks_data,
            signal_filter="strong_buy,buy",
        )
        for r in out["results"]:
            assert r["signal"] in {"strong_buy", "buy"}

    def test_empty_input_returns_error(self):
        """空 stocks_data 返回 error。"""
        out = _call(_TOOLS["scan_stocks_for_signals"], {})
        assert out.get("error") is True

    def test_each_result_has_code_and_signal(self):
        """每个结果应含 code 和 signal 字段。"""
        stocks_data = {"000001": dict(zip(
            ["highs", "lows", "closes"],
            _gen_hlcv(60, "up")[:3],
        ))}
        out = _call(_TOOLS["scan_stocks_for_signals"], stocks_data)
        for r in out["results"]:
            assert "code" in r
            assert "signal" in r
            assert "score" in r

    def test_invalid_stock_data_logged_to_errors(self):
        """数据长度不一致的股票应进入 errors 列表，不中断扫描。"""
        stocks_data = {
            "000001": {"highs": [10, 11], "lows": [9, 10], "closes": [9.5, 10.5]},
            "600519": {"highs": [10, 11, 12], "lows": [9, 10], "closes": [9.5, 10.5, 11.5]},
        }
        out = _call(_TOOLS["scan_stocks_for_signals"], stocks_data)
        assert out["summary"]["errors_count"] >= 1

    def test_results_count_at_most_input_count(self):
        """返回数量不超过输入数量。"""
        stocks_data = {}
        for code in ("000001", "600519", "300750"):
            highs, lows, closes, _ = _gen_hlcv(60, "up")
            stocks_data[code] = {"highs": highs, "lows": lows, "closes": closes}
        out = _call(_TOOLS["scan_stocks_for_signals"], stocks_data)
        assert len(out["results"]) <= 3


# ════════════════════════════════════════════════════════════════
# validate_signal_quality MCP 工具测试
# ════════════════════════════════════════════════════════════════

class TestValidateSignalQuality:
    def test_returns_forward_returns(self):
        """返回 forward_returns 字典。"""
        closes = [round(10.0 + i * 0.1, 4) for i in range(50)]
        out = _call(_TOOLS["validate_signal_quality"], closes, signal_idx=10, forward_days=5)
        assert out["success"] is True
        assert "forward_returns_pct" in out
        # 至少有 d1/d3/d5 三个时点
        for d in ("d1", "d3", "d5"):
            assert d in out["forward_returns_pct"]

    def test_signal_price_correctness(self):
        """signal_price 应等于 closes[signal_idx]。"""
        closes = [round(10.0 + i * 0.1, 4) for i in range(50)]
        out = _call(_TOOLS["validate_signal_quality"], closes, signal_idx=10, forward_days=5)
        assert out["signal_price"] == closes[10]
        assert out["signal_idx"] == 10

    def test_end_price_correctness(self):
        """end_price 应等于 closes[signal_idx + forward_days]。"""
        closes = [round(10.0 + i * 0.1, 4) for i in range(50)]
        out = _call(_TOOLS["validate_signal_quality"], closes, signal_idx=10, forward_days=5)
        assert out["end_price"] == closes[15]
        assert out["end_idx"] == 15
        assert out["forward_days"] == 5

    def test_upward_curve_positive_return(self):
        """上涨曲线前瞻收益为正。"""
        closes = [round(10.0 + i * 0.2, 4) for i in range(50)]
        out = _call(_TOOLS["validate_signal_quality"], closes, signal_idx=10, forward_days=10)
        assert out["total_return_pct"] > 0
        assert out["max_gain_pct"] > 0
        assert out["win_rate"] == 1.0  # 全部上涨

    def test_downward_curve_negative_return(self):
        """下跌曲线前瞻收益为负。"""
        closes = [round(30.0 - i * 0.2, 4) for i in range(50)]
        out = _call(_TOOLS["validate_signal_quality"], closes, signal_idx=10, forward_days=10)
        assert out["total_return_pct"] < 0
        assert out["max_loss_pct"] < 0
        assert out["win_rate"] == 0.0  # 全部下跌

    def test_max_gain_max_loss_correctness(self):
        """max_gain_pct 和 max_loss_pct 正确性。"""
        # 构造已知序列：信号位置 10.0，后续 11.0, 9.0, 12.0
        closes = [10.0] * 10 + [10.0, 11.0, 9.0, 12.0, 10.0]
        out = _call(_TOOLS["validate_signal_quality"], closes, signal_idx=10, forward_days=4)
        # 期间最高 12.0, 最低 9.0
        assert out["max_gain_pct"] == round((12.0 - 10.0) / 10.0 * 100, 4)
        assert out["max_loss_pct"] == round((9.0 - 10.0) / 10.0 * 100, 4)

    def test_win_rate_calculation(self):
        """win_rate 计算正确性。"""
        # 涨跌交替：1 0 1 0 1 0 → win_rate = 0.5
        closes = [10.0, 11.0, 10.5, 11.5, 11.0, 12.0, 11.5]
        out = _call(_TOOLS["validate_signal_quality"], closes, signal_idx=0, forward_days=6)
        # 6 个日收益：[+, -, +, -, +, -]
        assert out["up_days"] == 3
        assert out["down_days"] == 3
        assert out["win_rate"] == 0.5

    def test_signal_idx_out_of_range_returns_error(self):
        """signal_idx 越界返回 error。"""
        closes = [10.0, 11.0, 12.0]
        out = _call(_TOOLS["validate_signal_quality"], closes, signal_idx=5)
        assert out.get("error") is True

    def test_negative_signal_idx_returns_error(self):
        """signal_idx 为负返回 error。"""
        closes = [10.0, 11.0, 12.0]
        out = _call(_TOOLS["validate_signal_quality"], closes, signal_idx=-1)
        assert out.get("error") is True

    def test_invalid_forward_days_returns_error(self):
        """forward_days <= 0 返回 error。"""
        closes = [10.0, 11.0, 12.0]
        out = _call(_TOOLS["validate_signal_quality"], closes, signal_idx=0, forward_days=0)
        assert out.get("error") is True

    def test_forward_days_beyond_data_clamped(self):
        """forward_days 超过数据长度时被截断到末尾。"""
        closes = [10.0, 11.0, 12.0]
        out = _call(_TOOLS["validate_signal_quality"], closes, signal_idx=1, forward_days=100)
        # end_idx 应被截断到 len(closes) - 1 = 2
        assert out["end_idx"] == 2
        assert out["forward_days"] == 1

    def test_check_points_coverage(self):
        """应覆盖 d1/d3/d5/d10/d20 检查点（如数据足够）。"""
        closes = [round(10.0 + i * 0.05, 4) for i in range(100)]
        out = _call(_TOOLS["validate_signal_quality"], closes, signal_idx=10, forward_days=50)
        for d in ("d1", "d3", "d5", "d10", "d20"):
            assert d in out["forward_returns_pct"]
