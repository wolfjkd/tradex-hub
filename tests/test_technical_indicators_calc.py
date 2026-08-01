"""
Task 16: technical_indicators 纯函数单测 (V2.5.0).

覆盖：
  - _sma / _ema 模块级纯函数
  - calculate_ma_ema / calculate_macd / calculate_kdj /
    calculate_rsi / calculate_boll / calculate_atr 六个 MCP 工具
  - 边界场景：空数组、数据不足、参数错误、长度不一致

策略：
  - 用 MockMCP 捕获 register() 内部注册的 async 工具函数
  - 用 asyncio.run 同步调用 async 工具
  - 所有输入为本地构造的常量数组，无网络依赖
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import sys

import pytest

# ── 路径设置：让 cn_financial_mcp 包可被导入 ───────────────────
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CN_MCP_SRC = os.path.join(_PROJECT_ROOT, "cn-financial-mcp", "src")
if _CN_MCP_SRC not in sys.path:
    sys.path.insert(0, _CN_MCP_SRC)

from cn_financial_mcp.tools import technical_indicators as ti  # noqa: E402


# ── 公共辅助 ──────────────────────────────────────────────────

class _MockMCP:
    """捕获 register() 中通过 @mcp.tool() 注册的 async 工具函数。"""

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


_TOOLS = _capture_tools(ti)


def _call(func, *args, **kwargs) -> dict:
    """同步运行 async MCP 工具并解析 JSON 结果。"""
    raw = asyncio.run(func(*args, **kwargs))
    return json.loads(raw)


# ── 测试数据 ──────────────────────────────────────────────────

# 已知输入输出对 (任务要求)
_SIMPLE_CLOSES = [10.0, 11.0, 12.0, 13.0, 14.0]


def _gen_closes(n: int = 60, base: float = 10.0) -> list[float]:
    """生成 n 日收盘价序列（带 sin 波动 + 线性趋势），便于 MACD/BOLL 等计算。"""
    return [round(base + i * 0.1 + math.sin(i * 0.3) * 0.5, 4) for i in range(n)]


def _gen_hlc(n: int = 30, base: float = 10.0) -> tuple[list, list, list]:
    """生成 n 日 high/low/close 数据。"""
    closes = _gen_closes(n, base)
    highs = [round(c + 0.3 + (i % 3) * 0.05, 4) for i, c in enumerate(closes)]
    lows = [round(c - 0.3 - (i % 3) * 0.05, 4) for i, c in enumerate(closes)]
    return highs, lows, closes


# ════════════════════════════════════════════════════════════════
# _sma 纯函数测试
# ════════════════════════════════════════════════════════════════

class TestSma:
    def test_sma_known_input_output(self):
        """任务要求: 输入 [10,11,12,13,14], period=3 → [None,None,11,12,13]"""
        result = ti._sma(_SIMPLE_CLOSES, 3)
        assert result == [None, None, 11.0, 12.0, 13.0]

    def test_sma_period_1(self):
        """period=1 时每个值等于输入。"""
        result = ti._sma([10.0, 11.0, 12.0], 1)
        assert result == [10.0, 11.0, 12.0]

    def test_sma_period_equal_length(self):
        """period 等于数组长度时仅返回一个有效值。"""
        result = ti._sma([10.0, 11.0, 12.0], 3)
        assert result == [None, None, 11.0]

    def test_sma_empty_array(self):
        """空数组返回空数组。"""
        assert ti._sma([], 3) == []

    def test_sma_insufficient_data(self):
        """长度 < period 返回全 None。"""
        result = ti._sma([10.0, 11.0], 3)
        assert result == [None, None]

    def test_sma_invalid_period_zero(self):
        """period <= 0 返回全 None。"""
        assert ti._sma([10.0, 11.0, 12.0], 0) == [None, None, None]

    def test_sma_invalid_period_negative(self):
        """period 为负数返回全 None。"""
        assert ti._sma([10.0, 11.0, 12.0], -1) == [None, None, None]

    def test_sma_precision_4_decimals(self):
        """结果应保留 4 位小数。"""
        result = ti._sma([1.5, 2.5, 3.5, 4.5], 2)
        # (1.5+2.5)/2 = 2.0, (2.5+3.5)/2 = 3.0, (3.5+4.5)/2 = 4.0
        assert result == [None, 2.0, 3.0, 4.0]
        # 验证精度：构造精确可表示的小数
        result2 = ti._sma([10.1234, 20.5678, 30.9012], 3)
        assert result2 == [None, None, round((10.1234 + 20.5678 + 30.9012) / 3, 4)]
        assert result2[2] == 20.5308


# ════════════════════════════════════════════════════════════════
# _ema 纯函数测试
# ════════════════════════════════════════════════════════════════

class TestEma:
    def test_ema_first_value_equals_sma(self):
        """任务要求: 首值用 SMA 初始化。"""
        closes = _SIMPLE_CLOSES
        ema_result = ti._ema(closes, 3)
        sma_result = ti._sma(closes, 3)
        # EMA 的第一个非空值应等于 SMA 的第一个非空值
        assert ema_result[2] == sma_result[2] == 11.0

    def test_ema_follows_formula(self):
        """任务要求: 后续按 EMA 公式 (multiplier = 2/(period+1))。"""
        closes = _SIMPLE_CLOSES
        period = 3
        multiplier = 2.0 / (period + 1)
        # 手算预期值
        prev_ema = sum(closes[:period]) / period  # 11.0
        expected = [None, None, round(prev_ema, 4)]
        for i in range(period, len(closes)):
            prev_ema = closes[i] * multiplier + prev_ema * (1 - multiplier)
            expected.append(round(prev_ema, 4))
        assert ti._ema(closes, period) == expected

    def test_ema_period_1_equals_input(self):
        """period=1 时 EMA 等于输入序列（首值=SMA=自身，后续 multiplier=1）。"""
        closes = [10.0, 11.0, 12.0, 13.0]
        result = ti._ema(closes, 1)
        assert result == [10.0, 11.0, 12.0, 13.0]

    def test_ema_empty_array(self):
        assert ti._ema([], 3) == []

    def test_ema_insufficient_data(self):
        assert ti._ema([10.0], 3) == [None]

    def test_ema_invalid_period(self):
        assert ti._ema([10.0, 11.0, 12.0], 0) == [None, None, None]
        assert ti._ema([10.0, 11.0, 12.0], -2) == [None, None, None]


# ════════════════════════════════════════════════════════════════
# calculate_ma_ema 工具测试
# ════════════════════════════════════════════════════════════════

class TestCalculateMaEma:
    def test_type_sma_returns_only_ma(self):
        """type=sma 仅返回 ma 字段。"""
        out = _call(_TOOLS["calculate_ma_ema"], _SIMPLE_CLOSES, 3, "sma")
        assert out["success"] is True
        assert out["type"] == "sma"
        assert out["ma"] == [None, None, 11.0, 12.0, 13.0]
        assert "ema" not in out
        assert out["ma_valid_points"] == 3
        assert out["period"] == 3
        assert out["data_points"] == 5

    def test_type_ema_returns_only_ema(self):
        """type=ema 仅返回 ema 字段。"""
        out = _call(_TOOLS["calculate_ma_ema"], _SIMPLE_CLOSES, 3, "ema")
        assert out["success"] is True
        assert out["type"] == "ema"
        assert "ema" in out and out["ema"][2] == 11.0
        assert "ma" not in out
        assert out["ema_valid_points"] == 3

    def test_type_both_returns_both(self):
        """type=both 同时返回 ma 和 ema 字段。"""
        out = _call(_TOOLS["calculate_ma_ema"], _SIMPLE_CLOSES, 3, "both")
        assert out["success"] is True
        assert out["type"] == "both"
        assert "ma" in out and "ema" in out
        # 首值应相等（均用 SMA 初始化）
        assert out["ma"][2] == out["ema"][2] == 11.0

    def test_invalid_type_returns_error(self):
        """type 不在 sma/ema/both 中应返回 error。"""
        out = _call(_TOOLS["calculate_ma_ema"], _SIMPLE_CLOSES, 3, "wma")
        assert out.get("error") is True
        assert "calculate_ma_ema" == out.get("tool")

    def test_empty_closes_returns_error(self):
        """空 closes 应返回 error。"""
        out = _call(_TOOLS["calculate_ma_ema"], [], 3, "sma")
        assert out.get("error") is True

    def test_invalid_period_returns_error(self):
        """period <= 0 应返回 error。"""
        out = _call(_TOOLS["calculate_ma_ema"], _SIMPLE_CLOSES, 0, "sma")
        assert out.get("error") is True

    def test_default_period_is_20(self):
        """默认 period 应为 20。"""
        closes = list(range(1, 31))  # 30 个点
        out = _call(_TOOLS["calculate_ma_ema"], closes)
        assert out["period"] == 20
        # 前 19 个应为 None
        assert all(v is None for v in out["ma"][:19])
        assert out["ma"][19] is not None

    def test_default_type_is_both(self):
        """默认 type 应为 both。"""
        out = _call(_TOOLS["calculate_ma_ema"], _SIMPLE_CLOSES, 3)
        assert out["type"] == "both"


# ════════════════════════════════════════════════════════════════
# calculate_macd 工具测试
# ════════════════════════════════════════════════════════════════

class TestCalculateMacd:
    def test_returns_dif_dea_macd_fields(self):
        """任务要求: 60 日收盘价序列，返回含 dif/dea/macd_hist 三个字段。"""
        closes = _gen_closes(60)
        out = _call(_TOOLS["calculate_macd"], closes)
        assert out["success"] is True
        # 三个核心字段
        assert "dif" in out
        assert "dea" in out
        assert "macd" in out
        # 周期参数
        assert out["fast_period"] == 12
        assert out["slow_period"] == 26
        assert out["signal_period"] == 9
        assert out["data_points"] == 60
        # 长度应等于 closes 长度
        assert len(out["dif"]) == 60
        assert len(out["dea"]) == 60
        assert len(out["macd"]) == 60

    def test_dif_leading_none_count(self):
        """前 slow_period-1=25 个 DIF 应为 None。"""
        closes = _gen_closes(60)
        out = _call(_TOOLS["calculate_macd"], closes)
        assert all(v is None for v in out["dif"][:25])
        assert out["dif"][25] is not None  # 第 26 个开始有值

    def test_macd_hist_formula(self):
        """验证 MACD 柱 = 2 * (DIF - DEA)。"""
        closes = _gen_closes(60)
        out = _call(_TOOLS["calculate_macd"], closes)
        for d, e, m in zip(out["dif"], out["dea"], out["macd"]):
            if d is None or e is None:
                assert m is None
            else:
                assert m == round(2 * (d - e), 4)

    def test_insufficient_data_returns_error(self):
        """任务要求: 数据不足返回 error 或空结果。"""
        out = _call(_TOOLS["calculate_macd"], _SIMPLE_CLOSES)
        assert out.get("error") is True
        assert "数据不足" in out.get("message", "")

    def test_empty_closes_returns_error(self):
        out = _call(_TOOLS["calculate_macd"], [])
        assert out.get("error") is True

    def test_custom_periods(self):
        """自定义 fast/slow/signal 周期。"""
        closes = _gen_closes(40)
        out = _call(_TOOLS["calculate_macd"], closes, 5, 15, 4)
        assert out["fast_period"] == 5
        assert out["slow_period"] == 15
        assert out["signal_period"] == 4
        # 前 14 个 DIF 为 None
        assert all(v is None for v in out["dif"][:14])
        assert out["dif"][14] is not None


# ════════════════════════════════════════════════════════════════
# calculate_kdj 工具测试
# ════════════════════════════════════════════════════════════════

class TestCalculateKdj:
    def test_returns_k_d_j_fields(self):
        """任务要求: 30 日 H/L/C 数据，返回含 k/d/j 字段。"""
        highs, lows, closes = _gen_hlc(30)
        out = _call(_TOOLS["calculate_kdj"], highs, lows, closes)
        assert out["success"] is True
        assert "k" in out
        assert "d" in out
        assert "j" in out
        # 数组长度应等于 closes 长度
        assert len(out["k"]) == 30
        assert len(out["d"]) == 30
        assert len(out["j"]) == 30
        # 周期参数
        assert out["period"] == 9
        assert out["k_period"] == 3
        assert out["d_period"] == 3

    def test_j_formula(self):
        """验证 J ≈ 3K - 2D (内部用未round的K/D算J，故近似相等)。"""
        highs, lows, closes = _gen_hlc(20)
        out = _call(_TOOLS["calculate_kdj"], highs, lows, closes)
        for k, d, j in zip(out["k"], out["d"], out["j"]):
            # 内部 j 用未round的 K/D 计算,再 round 到4位，故差值不超 1e-3
            assert j == pytest.approx(round(3 * k - 2 * d, 4), abs=1e-3)

    def test_initial_kd_is_50(self):
        """第一个 K/D 应基于初始值 50 平滑。"""
        # 单点数据，period=1: RSV = (close - low) / (high - low) * 100 = 50 (对称数据)
        highs = [10.5]
        lows = [9.5]
        closes = [10.0]
        out = _call(_TOOLS["calculate_kdj"], highs, lows, closes, period=1)
        # K = 2/3 * 50 + 1/3 * 50 = 50
        assert out["k"][0] == 50.0
        assert out["d"][0] == 50.0

    def test_length_mismatch_returns_error(self):
        """长度不一致返回 error。"""
        out = _call(_TOOLS["calculate_kdj"], [10, 11], [9, 10], [10.0])
        assert out.get("error") is True
        assert "长度必须相同" in out.get("message", "")

    def test_insufficient_data_returns_error(self):
        """数据不足返回 error。"""
        highs = [10.0, 11.0]
        lows = [9.0, 10.0]
        closes = [9.5, 10.5]
        out = _call(_TOOLS["calculate_kdj"], highs, lows, closes, period=9)
        assert out.get("error") is True
        assert "数据不足" in out.get("message", "")

    def test_zero_range_rsv_is_50(self):
        """高低价相等时 RSV 应取 50（防除零）。"""
        highs = [10.0] * 5
        lows = [10.0] * 5
        closes = [10.0] * 5
        out = _call(_TOOLS["calculate_kdj"], highs, lows, closes, period=3)
        # RSV=50 → K 趋向 50, D 趋向 50
        assert out["k"][-1] == 50.0
        assert out["d"][-1] == 50.0


# ════════════════════════════════════════════════════════════════
# calculate_rsi 工具测试
# ════════════════════════════════════════════════════════════════

class TestCalculateRsi:
    def test_rsi_in_range_0_to_100(self):
        """任务要求: 20 日收盘价，验证 RSI 在 0-100 之间。"""
        closes = _gen_closes(20)
        out = _call(_TOOLS["calculate_rsi"], closes, period=14)
        assert out["success"] is True
        rsi_values = [v for v in out["rsi"] if v is not None]
        assert len(rsi_values) > 0
        for v in rsi_values:
            assert 0.0 <= v <= 100.0

    def test_rsi_leading_none_count(self):
        """前 period 个应为 None。"""
        closes = _gen_closes(20)
        out = _call(_TOOLS["calculate_rsi"], closes, period=14)
        # rsi 数组前 14 个为 None，第 14 个 (索引 13) 是首个有效值
        assert all(v is None for v in out["rsi"][:13])
        assert out["rsi"][13] is not None

    def test_rsi_all_gains_is_100(self):
        """纯上涨序列 RSI 应为 100。"""
        closes = [10.0 + i * 0.5 for i in range(20)]
        out = _call(_TOOLS["calculate_rsi"], closes, period=14)
        rsi_values = [v for v in out["rsi"] if v is not None]
        assert all(v == 100.0 for v in rsi_values)

    def test_rsi_all_losses_is_0(self):
        """纯下跌序列 RSI 应为 0。"""
        closes = [20.0 - i * 0.5 for i in range(20)]
        out = _call(_TOOLS["calculate_rsi"], closes, period=14)
        rsi_values = [v for v in out["rsi"] if v is not None]
        assert all(v == 0.0 for v in rsi_values)

    def test_insufficient_data_returns_error(self):
        """数据不足（< period+1）应返回 error。"""
        closes = [10.0, 11.0, 12.0]
        out = _call(_TOOLS["calculate_rsi"], closes, period=14)
        assert out.get("error") is True
        assert "数据不足" in out.get("message", "")

    def test_valid_points_count(self):
        closes = _gen_closes(20)
        out = _call(_TOOLS["calculate_rsi"], closes, period=14)
        # 20 个数据点，period=14 → 6 个有效 RSI
        assert out["valid_points"] == 6
        assert out["data_points"] == 20
        assert out["period"] == 14


# ════════════════════════════════════════════════════════════════
# calculate_boll 工具测试
# ════════════════════════════════════════════════════════════════

class TestCalculateBoll:
    def test_returns_upper_middle_lower_fields(self):
        """任务要求: 30 日收盘价，返回含 upper/middle/lower 字段。"""
        closes = _gen_closes(30)
        out = _call(_TOOLS["calculate_boll"], closes)
        assert out["success"] is True
        assert "upper" in out
        assert "middle" in out
        assert "lower" in out
        # 扩展字段
        assert "bandwidth" in out
        assert "percent_b" in out
        assert out["period"] == 20
        assert out["k"] == 2.0
        assert out["data_points"] == 30

    def test_upper_gt_middle_gt_lower(self):
        """上轨 > 中轨 > 下轨。"""
        closes = _gen_closes(30)
        out = _call(_TOOLS["calculate_boll"], closes)
        for u, m, l in zip(out["upper"], out["middle"], out["lower"]):
            if u is not None and m is not None and l is not None:
                assert u >= m >= l, f"u={u} m={m} l={l}"

    def test_middle_equals_sma(self):
        """中轨应等于 SMA。"""
        closes = _gen_closes(30)
        out = _call(_TOOLS["calculate_boll"], closes, period=20, k=2.0)
        sma_arr = ti._sma(closes, 20)
        for m, s in zip(out["middle"], sma_arr):
            if m is not None and s is not None:
                assert m == s

    def test_upper_lower_formula(self):
        """上轨 = 中轨 + k*std, 下轨 = 中轨 - k*std。"""
        closes = _gen_closes(30)
        out = _call(_TOOLS["calculate_boll"], closes, period=20, k=2.0)
        # 取最后一个有效点验证
        u = out["upper"][-1]
        m = out["middle"][-1]
        l = out["lower"][-1]
        # 半带宽
        half = (u - l) / 2
        assert abs(m - half - l) < 1e-6 or abs(u - m - (m - l)) < 1e-6
        # 中轨居中
        assert abs((u + l) / 2 - m) < 1e-4

    def test_leading_none_count(self):
        """前 period-1=19 个为 None。"""
        closes = _gen_closes(30)
        out = _call(_TOOLS["calculate_boll"], closes, period=20)
        assert all(v is None for v in out["upper"][:19])
        assert out["upper"][19] is not None

    def test_insufficient_data_returns_error(self):
        """数据不足应返回 error。"""
        closes = _gen_closes(15)
        out = _call(_TOOLS["calculate_boll"], closes, period=20)
        assert out.get("error") is True
        assert "数据不足" in out.get("message", "")

    def test_custom_k(self):
        """自定义 k 倍数。"""
        closes = _gen_closes(25)
        out = _call(_TOOLS["calculate_boll"], closes, 20, 1.5)
        assert out["k"] == 1.5


# ════════════════════════════════════════════════════════════════
# calculate_atr 工具测试
# ════════════════════════════════════════════════════════════════

class TestCalculateAtr:
    def test_atr_is_positive(self):
        """任务要求: 20 日 H/L/C，验证 ATR 为正数。"""
        highs, lows, closes = _gen_hlc(20)
        out = _call(_TOOLS["calculate_atr"], highs, lows, closes)
        assert out["success"] is True
        atr_values = [v for v in out["atr"] if v is not None]
        assert len(atr_values) > 0
        for v in atr_values:
            assert v > 0, f"ATR should be positive, got {v}"

    def test_returns_tr_and_atr_fields(self):
        """返回 atr 和 tr 字段。"""
        highs, lows, closes = _gen_hlc(20)
        out = _call(_TOOLS["calculate_atr"], highs, lows, closes)
        assert "atr" in out
        assert "tr" in out
        assert out["period"] == 14
        assert out["data_points"] == 20

    def test_first_tr_is_none(self):
        """首个 TR 应为 None（无前收盘）。"""
        highs, lows, closes = _gen_hlc(20)
        out = _call(_TOOLS["calculate_atr"], highs, lows, closes)
        assert out["tr"][0] is None
        assert out["tr"][1] is not None

    def test_tr_formula(self):
        """TR = max(high-low, |high-pre_close|, |low-pre_close|)。"""
        highs, lows, closes = _gen_hlc(20)
        out = _call(_TOOLS["calculate_atr"], highs, lows, closes)
        for i in range(1, 20):
            expected = round(max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            ), 4)
            assert out["tr"][i] == expected

    def test_atr_leading_none_count(self):
        """前 period 个 ATR 应为 None（1 个 TR None + period-1 个 EMA warmup）。"""
        highs, lows, closes = _gen_hlc(20)
        out = _call(_TOOLS["calculate_atr"], highs, lows, closes, period=14)
        # ATR 前 14 个为 None
        assert all(v is None for v in out["atr"][:14])
        assert out["atr"][14] is not None

    def test_length_mismatch_returns_error(self):
        """长度不一致返回 error。"""
        out = _call(_TOOLS["calculate_atr"], [10, 11], [9, 10], [9.5])
        assert out.get("error") is True
        assert "长度必须相同" in out.get("message", "")

    def test_insufficient_data_returns_error(self):
        """数据不足（< period+1）应返回 error。"""
        highs, lows, closes = _gen_hlc(10)
        out = _call(_TOOLS["calculate_atr"], highs, lows, closes, period=14)
        assert out.get("error") is True
        assert "数据不足" in out.get("message", "")

    def test_valid_points_count(self):
        """20 日数据，period=14，ATR 有效点 = 20-14 = 6。"""
        highs, lows, closes = _gen_hlc(20)
        out = _call(_TOOLS["calculate_atr"], highs, lows, closes, period=14)
        assert out["valid_points"] == 6


# ════════════════════════════════════════════════════════════════
# _stddev 辅助函数测试（顺带覆盖）
# ════════════════════════════════════════════════════════════════

class TestStddev:
    def test_known_value(self):
        """[1,2,3,4,5] 均值 3, 总体方差 2, 标准差 sqrt(2)。"""
        assert ti._stddev([1, 2, 3, 4, 5], 3.0) == pytest.approx(math.sqrt(2), rel=1e-9)

    def test_empty_returns_zero(self):
        assert ti._stddev([], 0.0) == 0.0

    def test_single_value_zero_std(self):
        """单个值标准差为 0。"""
        assert ti._stddev([5.0], 5.0) == 0.0
