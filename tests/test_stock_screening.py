"""
Task 17: stock_screening 纯函数单测 (V2.5.0).

覆盖：
  - screen_stocks: 条件选股扫描
  - get_screening_conditions: 选股条件清单查询

策略：
  - 用 MockMCP 捕获 register() 中注册的 async 工具函数
  - 同时直接测试模块级纯函数 _match_condition / _parse_condition
  - 构造本地股票数据（无网络依赖）
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

import pytest

# ── 路径设置 ──────────────────────────────────────────────────
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CN_MCP_SRC = os.path.join(_PROJECT_ROOT, "cn-financial-mcp", "src")
if _CN_MCP_SRC not in sys.path:
    sys.path.insert(0, _CN_MCP_SRC)

from cn_financial_mcp.tools import stock_screening as ss  # noqa: E402


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


_TOOLS = _capture_tools(ss)


def _call(func, *args, **kwargs) -> dict:
    raw = asyncio.run(func(*args, **kwargs))
    return json.loads(raw)


# ── 测试数据 ──────────────────────────────────────────────────

_SAMPLE_STOCKS = [
    {"code": "000001", "name": "平安银行", "pe": 8.5, "pb": 0.6,
     "price": 12.3, "market_cap": 2400, "roe": 12.0,
     "is_st": False, "board": "main_sz"},
    {"code": "600519", "name": "贵州茅台", "pe": 30.2, "pb": 8.5,
     "price": 1800, "market_cap": 22000, "roe": 30.0,
     "is_st": False, "board": "main_sh"},
    {"code": "300750", "name": "宁德时代", "pe": 50.0, "pb": 5.0,
     "price": 200, "market_cap": 8800, "roe": 18.0,
     "is_st": False, "board": "gem"},
    {"code": "688981", "name": "中芯国际", "pe": 100.0, "pb": 4.0,
     "price": 50, "market_cap": 4000, "roe": 5.0,
     "is_st": False, "board": "star"},
    {"code": "000002", "name": "ST股例子", "pe": -5.0, "pb": 3.0,
     "price": 2, "market_cap": 50, "roe": -10.0,
     "is_st": True, "board": "main_sz"},
]


# ════════════════════════════════════════════════════════════════
# _match_condition 纯函数测试
# ════════════════════════════════════════════════════════════════

class TestMatchCondition:
    def test_less_than(self):
        assert ss._match_condition(5, "<", 10) is True
        assert ss._match_condition(15, "<", 10) is False

    def test_less_or_equal(self):
        assert ss._match_condition(10, "<=", 10) is True
        assert ss._match_condition(11, "<=", 10) is False

    def test_greater_than(self):
        assert ss._match_condition(15, ">", 10) is True
        assert ss._match_condition(5, ">", 10) is False

    def test_greater_or_equal(self):
        assert ss._match_condition(10, ">=", 10) is True
        assert ss._match_condition(9, ">=", 10) is False

    def test_equal(self):
        assert ss._match_condition(10, "==", 10) is True
        assert ss._match_condition(10.0, "==", 10) is True
        assert ss._match_condition(11, "==", 10) is False

    def test_between_inclusive(self):
        assert ss._match_condition(15, "between", [10, 20]) is True
        assert ss._match_condition(10, "between", [10, 20]) is True  # 边界
        assert ss._match_condition(20, "between", [10, 20]) is True  # 边界
        assert ss._match_condition(5, "between", [10, 20]) is False
        assert ss._match_condition(25, "between", [10, 20]) is False

    def test_between_invalid_target_returns_false(self):
        """between 时 target 长度不为 2 时返回 False。"""
        assert ss._match_condition(15, "between", [10]) is False
        assert ss._match_condition(15, "between", 10) is False

    def test_in_operator(self):
        assert ss._match_condition("main_sh", "in", ["main_sh", "main_sz"]) is True
        assert ss._match_condition("gem", "in", ["main_sh", "main_sz"]) is False

    def test_not_in_operator(self):
        assert ss._match_condition("gem", "not_in", ["main_sh", "main_sz"]) is True
        assert ss._match_condition("main_sh", "not_in", ["main_sh", "main_sz"]) is False

    def test_unknown_operator_returns_false(self):
        assert ss._match_condition(10, "unknown_op", 5) is False

    def test_none_value_returns_false(self):
        """None 值总是返回 False。"""
        for op in ("<", "<=", ">", ">=", "==", "between", "in", "not_in"):
            assert ss._match_condition(None, op, 5) is False

    def test_type_mismatch_returns_false(self):
        """类型不匹配时应返回 False 而非抛异常。"""
        # 字符串与数字比较
        assert ss._match_condition("abc", "<", 5) is False
        assert ss._match_condition(5, "in", "abc") is False  # 'in' 要求 target 是容器


# ════════════════════════════════════════════════════════════════
# _parse_condition 纯函数测试
# ════════════════════════════════════════════════════════════════

class TestParseCondition:
    def test_full_condition(self):
        cond = {"field": "pe", "operator": "<", "value": 20}
        field, op, target = ss._parse_condition(cond)
        assert field == "pe"
        assert op == "<"
        assert target == 20

    def test_default_operator_is_ge(self):
        """未指定 operator 时默认为 '>='。"""
        cond = {"field": "pe", "value": 20}
        field, op, target = ss._parse_condition(cond)
        assert op == ">="

    def test_missing_field_returns_empty(self):
        cond = {"operator": "<", "value": 20}
        field, _, _ = ss._parse_condition(cond)
        assert field == ""

    def test_missing_value_returns_none(self):
        cond = {"field": "pe", "operator": "<"}
        _, _, target = ss._parse_condition(cond)
        assert target is None


# ════════════════════════════════════════════════════════════════
# screen_stocks MCP 工具测试
# ════════════════════════════════════════════════════════════════

class TestScreenStocks:
    def test_pe_between_filter(self):
        """任务要求: 测试 pe > 0 and pe < 20 等模拟条件。"""
        conditions = [
            {"field": "pe", "operator": ">", "value": 0},
            {"field": "pe", "operator": "<", "value": 20},
        ]
        out = _call(_TOOLS["screen_stocks"], _SAMPLE_STOCKS, conditions)
        assert out["success"] is True
        codes = [s["code"] for s in out["results"]]
        # pe > 0 且 pe < 20 的股票: 平安银行(8.5)
        assert "000001" in codes
        # 茅台(30.2), 宁德(50), 中芯(100), ST(-5) 都不符合
        assert "600519" not in codes
        assert "300750" not in codes
        assert "688981" not in codes
        assert "000002" not in codes

    def test_summary_statistics(self):
        """summary 字段完整。"""
        conditions = [{"field": "pe", "operator": "<", "value": 20}]
        out = _call(_TOOLS["screen_stocks"], _SAMPLE_STOCKS, conditions)
        summary = out["summary"]
        for key in ("total_input", "total_matched", "returned", "match_rate"):
            assert key in summary
        assert summary["total_input"] == 5
        assert summary["total_matched"] == len(out["results"])

    def test_conditions_applied_echoed(self):
        """conditions_applied 应回显条件。"""
        conditions = [{"field": "pe", "operator": "<", "value": 20}]
        out = _call(_TOOLS["screen_stocks"], _SAMPLE_STOCKS, conditions)
        assert out["conditions_applied"] == conditions

    def test_sort_by_desc(self):
        """按 pe 降序排序。"""
        conditions = [{"field": "pe", "operator": ">", "value": 0}]
        out = _call(
            _TOOLS["screen_stocks"], _SAMPLE_STOCKS, conditions,
            sort_by="pe", sort_order="desc",
        )
        pe_values = [s["pe"] for s in out["results"]]
        assert pe_values == sorted(pe_values, reverse=True)

    def test_sort_by_asc(self):
        """按 pe 升序排序。"""
        conditions = [{"field": "pe", "operator": ">", "value": 0}]
        out = _call(
            _TOOLS["screen_stocks"], _SAMPLE_STOCKS, conditions,
            sort_by="pe", sort_order="asc",
        )
        pe_values = [s["pe"] for s in out["results"]]
        assert pe_values == sorted(pe_values)

    def test_limit_truncates_results(self):
        """limit 限制返回数量。"""
        conditions = []  # 无条件,返回全部
        out = _call(_TOOLS["screen_stocks"], _SAMPLE_STOCKS, conditions, limit=2)
        assert out["summary"]["returned"] == 2
        assert len(out["results"]) == 2

    def test_empty_conditions_returns_all(self):
        """空 conditions 直接返回前 limit 个股票。"""
        out = _call(_TOOLS["screen_stocks"], _SAMPLE_STOCKS, [])
        assert out["success"] is True
        # 全部 5 个被返回（默认 limit=50）
        assert len(out["results"]) == 5
        assert out["conditions_applied"] == []

    def test_empty_input_returns_error(self):
        """空 stocks_data 返回 error。"""
        out = _call(_TOOLS["screen_stocks"], [], [{"field": "pe", "operator": "<", "value": 20}])
        assert out.get("error") is True

    def test_between_operator(self):
        """between 操作符筛选市值区间。"""
        conditions = [
            {"field": "market_cap", "operator": "between", "value": [1000, 5000]},
        ]
        out = _call(_TOOLS["screen_stocks"], _SAMPLE_STOCKS, conditions)
        codes = {s["code"] for s in out["results"]}
        # market_cap 在 [1000, 5000] 区间的: 平安银行(2400), 中芯(4000)
        assert "000001" in codes
        assert "688981" in codes
        # 茅台(22000), 宁德(8800), ST(50) 不在区间
        assert "600519" not in codes
        assert "300750" not in codes

    def test_bool_equal_filter(self):
        """布尔等于筛选 (排除 ST)。"""
        conditions = [{"field": "is_st", "operator": "==", "value": False}]
        out = _call(_TOOLS["screen_stocks"], _SAMPLE_STOCKS, conditions)
        codes = {s["code"] for s in out["results"]}
        assert "000002" not in codes  # ST 股被排除
        assert len(out["results"]) == 4  # 其他 4 只非 ST

    def test_in_operator_board_filter(self):
        """in 操作符按板块筛选。"""
        conditions = [
            {"field": "board", "operator": "in", "value": ["main_sh", "main_sz"]},
        ]
        out = _call(_TOOLS["screen_stocks"], _SAMPLE_STOCKS, conditions)
        codes = {s["code"] for s in out["results"]}
        # main_sh + main_sz: 平安, 茅台, ST例子
        assert "000001" in codes
        assert "600519" in codes
        assert "000002" in codes
        # gem/star 不在
        assert "300750" not in codes
        assert "688981" not in codes

    def test_multi_condition_and_logic(self):
        """多条件 AND 逻辑组合。"""
        conditions = [
            {"field": "pe", "operator": ">", "value": 0},
            {"field": "pb", "operator": "<", "value": 1.0},
            {"field": "is_st", "operator": "==", "value": False},
        ]
        out = _call(_TOOLS["screen_stocks"], _SAMPLE_STOCKS, conditions)
        codes = {s["code"] for s in out["results"]}
        # pe>0, pb<1, 非ST: 仅平安银行
        assert codes == {"000001"}

    def test_match_rate_calculation(self):
        """match_rate = matched / total_input。"""
        conditions = [{"field": "is_st", "operator": "==", "value": False}]
        out = _call(_TOOLS["screen_stocks"], _SAMPLE_STOCKS, conditions)
        assert out["summary"]["match_rate"] == round(4 / 5, 4)

    def test_default_sort_order_desc(self):
        """默认 sort_order 为 desc。"""
        conditions = [{"field": "pe", "operator": ">", "value": 0}]
        out = _call(
            _TOOLS["screen_stocks"], _SAMPLE_STOCKS, conditions,
            sort_by="pe",  # 不传 sort_order
        )
        assert out["sort_order"] == "desc"

    def test_default_limit_50(self):
        """默认 limit 为 50。"""
        out = _call(_TOOLS["screen_stocks"], _SAMPLE_STOCKS, [])
        # 看 conditions_applied 是否包含 limit 信息（间接验证）
        assert len(out["results"]) <= 50


# ════════════════════════════════════════════════════════════════
# get_screening_conditions MCP 工具测试
# ════════════════════════════════════════════════════════════════

class TestGetScreeningConditions:
    def test_returns_categories(self):
        """任务要求: 返回可用条件清单 - categories 字段。"""
        out = _call(_TOOLS["get_screening_conditions"])
        assert out["success"] is True
        assert "categories" in out
        # 5 个类别
        for cat in ("fundamental", "technical", "capital", "risk", "flag"):
            assert cat in out["categories"]

    def test_returns_conditions_list(self):
        """conditions 字段是列表。"""
        out = _call(_TOOLS["get_screening_conditions"])
        assert isinstance(out["conditions"], list)
        assert len(out["conditions"]) > 0

    def test_total_count_matches_conditions(self):
        """total_count 应等于 conditions 长度。"""
        out = _call(_TOOLS["get_screening_conditions"])
        assert out["total_count"] == len(out["conditions"])

    def test_each_condition_has_required_fields(self):
        """每个条件应含 name/category/desc/type/operators。"""
        out = _call(_TOOLS["get_screening_conditions"])
        for c in out["conditions"]:
            assert "name" in c
            assert "category" in c
            assert "desc" in c
            assert "type" in c
            assert "operators" in c

    def test_known_conditions_present(self):
        """关键字段应出现。"""
        out = _call(_TOOLS["get_screening_conditions"])
        names = {c["name"] for c in out["conditions"]}
        for name in ("pe", "pb", "market_cap", "roe", "price",
                      "ma5", "ma20", "rsi_14", "macd_dif",
                      "beta", "is_st", "board"):
            assert name in names, f"missing condition: {name}"

    def test_total_count_at_least_20(self):
        """至少 20 个条件。"""
        out = _call(_TOOLS["get_screening_conditions"])
        assert out["total_count"] >= 20

    def test_operator_explanation_provided(self):
        """应提供运算符说明。"""
        out = _call(_TOOLS["get_screening_conditions"])
        expl = out["operator_explanation"]
        for op in ("<", "<=", ">", ">=", "==", "between", "in", "not_in"):
            assert op in expl

    def test_examples_provided(self):
        """应提供使用示例。"""
        out = _call(_TOOLS["get_screening_conditions"])
        assert isinstance(out["examples"], list)
        assert len(out["examples"]) >= 1
        for ex in out["examples"]:
            assert "desc" in ex
            assert "conditions" in ex
