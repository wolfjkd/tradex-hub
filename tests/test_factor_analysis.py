"""
Task 17: factor_analysis 纯函数单测 (V2.5.0).

覆盖：
  - calculate_factor_score: 多因子综合评分
  - get_factor_catalog: 因子库清单查询

策略：
  - 用 MockMCP 捕获 register() 中注册的 async 工具函数
  - 同时直接测试模块级纯函数 _zscore_normalize / _adjust_direction /
    _calculate_single_factor
  - 构造本地因子数据（无网络依赖）
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
_CN_MCP_SRC = os.path.join(_PROJECT_ROOT, "tradex", "src")
if _CN_MCP_SRC not in sys.path:
    sys.path.insert(0, _CN_MCP_SRC)

from tradex.tools import factor_analysis as fa  # noqa: E402


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


_TOOLS = _capture_tools(fa)


def _call(func, *args, **kwargs) -> dict:
    raw = asyncio.run(func(*args, **kwargs))
    return json.loads(raw)


# ════════════════════════════════════════════════════════════════
# _zscore_normalize 纯函数测试
# ════════════════════════════════════════════════════════════════

class TestZscoreNormalize:
    def test_mean_approx_zero(self):
        """任务要求: 验证 Z-Score 标准化后均值 ≈ 0。"""
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        normalized = fa._zscore_normalize(values)
        mean = sum(normalized) / len(normalized)
        assert abs(mean) < 1e-9, f"mean={mean}"

    def test_std_approx_one(self):
        """任务要求: 验证 Z-Score 标准化后标准差 ≈ 1。"""
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        normalized = fa._zscore_normalize(values)
        mean = sum(normalized) / len(normalized)
        # 样本标准差（n-1 自由度）
        var = sum((v - mean) ** 2 for v in normalized) / (len(normalized) - 1)
        std = math.sqrt(var)
        assert abs(std - 1.0) < 1e-9, f"std={std}"

    def test_known_values(self):
        """[1,2,3,4,5] 样本方差=2.5,std=sqrt(2.5),
        Z-Score 应为 [-1.2649, -0.6325, 0, 0.6325, 1.2649]。"""
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        normalized = fa._zscore_normalize(values)
        std = math.sqrt(2.5)  # 样本标准差 (n-1 自由度)
        expected = [(v - 3.0) / std for v in values]
        for actual, exp in zip(normalized, expected):
            assert actual == pytest.approx(exp, rel=1e-4)

    def test_empty_returns_empty(self):
        """空数组返回空数组。"""
        assert fa._zscore_normalize([]) == []

    def test_single_value_returns_zero(self):
        """单值时方差为 0,返回 [0.0]。"""
        assert fa._zscore_normalize([5.0]) == [0.0]

    def test_constant_values_returns_zeros(self):
        """恒定数组（方差为 0）返回全 0。"""
        values = [3.0, 3.0, 3.0, 3.0]
        assert fa._zscore_normalize(values) == [0.0, 0.0, 0.0, 0.0]

    def test_preserves_order(self):
        """Z-Score 单调性应保持（对单调数据）。"""
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        normalized = fa._zscore_normalize(values)
        # 原数组单调递增 → Z-Score 也应单调递增
        for i in range(1, len(normalized)):
            assert normalized[i] > normalized[i - 1]


# ════════════════════════════════════════════════════════════════
# _adjust_direction 纯函数测试
# ════════════════════════════════════════════════════════════════

class TestAdjustDirection:
    def test_negative_reverses_sign(self):
        """direction=negative 应反转符号。"""
        scores = [1.0, -2.0, 3.0]
        result = fa._adjust_direction(scores, "negative")
        assert result == [-1.0, 2.0, -3.0]

    def test_positive_keeps_sign(self):
        """direction=positive 应保持原值。"""
        scores = [1.0, -2.0, 3.0]
        assert fa._adjust_direction(scores, "positive") == scores

    def test_neutral_keeps_sign(self):
        """direction=neutral 应保持原值。"""
        scores = [1.0, -2.0, 3.0]
        assert fa._adjust_direction(scores, "neutral") == scores


# ════════════════════════════════════════════════════════════════
# _calculate_single_factor 纯函数测试
# ════════════════════════════════════════════════════════════════

class TestCalculateSingleFactor:
    def test_returns_dict_keyed_by_code(self):
        """返回以 stock_code 为 key 的字典。"""
        codes = ["000001", "600519", "300750"]
        values = [10.0, 20.0, 30.0]
        result = fa._calculate_single_factor(codes, values, "positive")
        assert set(result.keys()) == set(codes)
        assert len(result) == 3

    def test_zscore_properties(self):
        """标准化后值近似满足 Z-Score 性质。"""
        codes = ["s1", "s2", "s3", "s4", "s5"]
        values = [10.0, 20.0, 30.0, 40.0, 50.0]
        result = fa._calculate_single_factor(codes, values, "positive")
        # 均值应近似为 0
        mean = sum(result.values()) / len(result)
        assert abs(mean) < 1e-9

    def test_negative_direction_reverses(self):
        """direction=negative 时,大值应得小分。"""
        codes = ["s1", "s2", "s3"]
        values = [10.0, 20.0, 30.0]
        result = fa._calculate_single_factor(codes, values, "negative")
        # 30 应得最低分（负向），10 应得最高分（正向）
        assert result["s1"] > result["s3"]

    def test_handles_none_values(self):
        """None 值应被中位数填充。"""
        codes = ["s1", "s2", "s3", "s4"]
        values = [10.0, None, 30.0, 40.0]
        result = fa._calculate_single_factor(codes, values, "positive")
        # s2 被中位数 30.0 填充
        assert "s2" in result
        assert isinstance(result["s2"], float)

    def test_all_none_returns_zeros(self):
        """全部 None 时返回全 0。"""
        codes = ["s1", "s2"]
        values = [None, None]
        result = fa._calculate_single_factor(codes, values, "positive")
        assert result == {"s1": 0.0, "s2": 0.0}

    def test_precision_4_decimals(self):
        """结果应保留 4 位小数。"""
        codes = ["s1", "s2", "s3"]
        values = [1.23456, 2.34567, 3.45678]
        result = fa._calculate_single_factor(codes, values, "positive")
        for v in result.values():
            assert abs(v - round(v, 4)) < 1e-9


# ════════════════════════════════════════════════════════════════
# calculate_factor_score MCP 工具测试
# ════════════════════════════════════════════════════════════════

class TestCalculateFactorScore:
    def test_returns_scores_sorted_desc(self):
        """任务要求: 多因子综合评分, 返回按分数降序。"""
        stock_codes = ["000001", "600519", "300750", "688981"]
        factor_data = {
            "pe": [10.5, 30.2, 15.8, 25.0],          # negative
            "pb": [1.2, 8.5, 2.3, 4.0],              # negative
            "revenue_growth": [0.15, 0.20, 0.08, 0.18],  # positive
        }
        out = _call(
            _TOOLS["calculate_factor_score"],
            stock_codes, factor_data,
        )
        assert out["success"] is True
        scores = out["scores"]
        # 验证按分数降序
        values = [s["total_score"] for s in scores]
        assert values == sorted(values, reverse=True)
        # 每个结果含 code 和 total_score
        for s in scores:
            assert "code" in s
            assert "total_score" in s
            assert "factor_scores" in s

    def test_summary_statistics(self):
        """返回统计摘要字段完整。"""
        stock_codes = ["s1", "s2", "s3", "s4", "s5"]
        factor_data = {"pe": [10, 20, 30, 40, 50], "roe": [15, 20, 10, 5, 25]}
        out = _call(_TOOLS["calculate_factor_score"], stock_codes, factor_data)
        summary = out["summary"]
        for key in ("total_stocks", "mean_score", "max_score", "min_score"):
            assert key in summary
        assert summary["total_stocks"] == 5

    def test_equal_weights_when_not_specified(self):
        """未指定 weights 时使用等权。"""
        stock_codes = ["s1", "s2", "s3"]
        factor_data = {"pe": [10, 20, 30], "pb": [1, 2, 3]}
        out = _call(_TOOLS["calculate_factor_score"], stock_codes, factor_data)
        weights = out["weights_used"]
        # 两个因子,等权各 0.5
        assert abs(weights["pe"] - 0.5) < 1e-9
        assert abs(weights["pb"] - 0.5) < 1e-9

    def test_custom_weights_normalized(self):
        """自定义权重应归一化到 1。"""
        stock_codes = ["s1", "s2", "s3"]
        factor_data = {"pe": [10, 20, 30], "pb": [1, 2, 3], "roe": [10, 20, 30]}
        weights = {"pe": 3, "pb": 2, "roe": 5}  # 总和 10
        out = _call(_TOOLS["calculate_factor_score"], stock_codes, factor_data, weights)
        w = out["weights_used"]
        assert abs(w["pe"] - 0.3) < 1e-9
        assert abs(w["pb"] - 0.2) < 1e-9
        assert abs(w["roe"] - 0.5) < 1e-9

    def test_factor_scores_detail(self):
        """每个股票的 factor_scores 字段应含每个因子得分。"""
        stock_codes = ["s1", "s2", "s3"]
        factor_data = {"pe": [10, 20, 30], "roe": [15, 10, 5]}
        out = _call(_TOOLS["calculate_factor_score"], stock_codes, factor_data)
        for s in out["scores"]:
            assert "pe" in s["factor_scores"]
            assert "roe" in s["factor_scores"]

    def test_empty_stock_codes_returns_error(self):
        """空 stock_codes 返回 error。"""
        out = _call(_TOOLS["calculate_factor_score"], [], {"pe": []})
        assert out.get("error") is True

    def test_empty_factor_data_returns_error(self):
        """空 factor_data 返回 error。"""
        out = _call(_TOOLS["calculate_factor_score"], ["s1"], {})
        assert out.get("error") is True

    def test_length_mismatch_returns_error(self):
        """因子值长度与股票数不一致返回 error。"""
        out = _call(
            _TOOLS["calculate_factor_score"],
            ["s1", "s2", "s3"],
            {"pe": [10, 20]},  # 长度不匹配
        )
        assert out.get("error") is True
        assert "数据长度" in out.get("message", "")

    def test_invalid_factor_name_returns_error(self):
        """不支持的因子名返回 error。"""
        out = _call(
            _TOOLS["calculate_factor_score"],
            ["s1", "s2"],
            {"unknown_factor": [1, 2]},
        )
        assert out.get("error") is True
        assert "不支持的因子" in out.get("message", "")

    def test_zero_total_weight_returns_error(self):
        """权重总和为 0 返回 error。"""
        stock_codes = ["s1", "s2"]
        factor_data = {"pe": [10, 20]}
        out = _call(
            _TOOLS["calculate_factor_score"],
            stock_codes, factor_data,
            weights={"pe": 0},  # 总和 0
        )
        assert out.get("error") is True
        assert "权重总和" in out.get("message", "")

    def test_top_10_pct_threshold_when_enough_stocks(self):
        """股票数 >= 10 时返回 top_10_pct_threshold。"""
        stock_codes = [f"s{i}" for i in range(15)]
        factor_data = {"pe": list(range(1, 16))}
        out = _call(_TOOLS["calculate_factor_score"], stock_codes, factor_data)
        assert out["summary"]["top_10_pct_threshold"] is not None

    def test_top_10_pct_threshold_none_when_few_stocks(self):
        """股票数 < 10 时 top_10_pct_threshold 为 None。"""
        stock_codes = ["s1", "s2", "s3"]
        factor_data = {"pe": [10, 20, 30]}
        out = _call(_TOOLS["calculate_factor_score"], stock_codes, factor_data)
        assert out["summary"]["top_10_pct_threshold"] is None


# ════════════════════════════════════════════════════════════════
# get_factor_catalog MCP 工具测试
# ════════════════════════════════════════════════════════════════

class TestGetFactorCatalog:
    def test_returns_categories(self):
        """任务要求: 返回因子清单 - categories 字段。"""
        out = _call(_TOOLS["get_factor_catalog"])
        assert out["success"] is True
        assert "categories" in out
        # 5 个因子类别
        for cat in ("value", "growth", "quality", "momentum", "risk"):
            assert cat in out["categories"]

    def test_returns_factors_list(self):
        """factors 字段是列表。"""
        out = _call(_TOOLS["get_factor_catalog"])
        assert isinstance(out["factors"], list)
        assert len(out["factors"]) > 0

    def test_total_count_matches_factors(self):
        """total_count 应等于 factors 长度。"""
        out = _call(_TOOLS["get_factor_catalog"])
        assert out["total_count"] == len(out["factors"])

    def test_each_factor_has_required_fields(self):
        """每个因子应含 name/category/desc/direction/unit。"""
        out = _call(_TOOLS["get_factor_catalog"])
        for f in out["factors"]:
            assert "name" in f
            assert "category" in f
            assert "desc" in f
            assert "direction" in f
            assert "unit" in f

    def test_direction_values_valid(self):
        """direction 字段值应为 positive/negative/neutral 之一。"""
        out = _call(_TOOLS["get_factor_catalog"])
        valid = {"positive", "negative", "neutral"}
        for f in out["factors"]:
            assert f["direction"] in valid

    def test_known_factors_present(self):
        """关键因子应出现。"""
        out = _call(_TOOLS["get_factor_catalog"])
        names = {f["name"] for f in out["factors"]}
        for name in ("pe", "pb", "roe", "revenue_growth",
                      "momentum_5d", "beta", "volatility_20d"):
            assert name in names, f"missing factor: {name}"

    def test_total_count_at_least_20(self):
        """至少 20 个因子。"""
        out = _call(_TOOLS["get_factor_catalog"])
        assert out["total_count"] >= 20

    def test_direction_explanation_provided(self):
        """应提供 direction 含义说明。"""
        out = _call(_TOOLS["get_factor_catalog"])
        expl = out["direction_explanation"]
        for d in ("positive", "negative", "neutral"):
            assert d in expl
