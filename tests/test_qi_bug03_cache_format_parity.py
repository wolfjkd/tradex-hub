"""QI-BUG-03 锁定测试：串缓存工具 hit/miss 线上格式逐字节一致（单编码）。

票面（老板 2026-11-23 拍板修齐）：16 处 dict_to_json/json.dumps 串缓存工具，
miss 路线经 mcp_serve(dump=dict_to_json)/默认 dump=True 对预序列化 str 再套
一层 → 双重编码；hit 路线工具层 `return cached` 直出 → 单编码。同一工具
首次调用与缓存命中返回不同格式，下游消费口径随缓存状态漂移。

本文件每组抽代表点断言两点（修前双红，修后双绿）：
  1. 首调（miss）与缓存命中（hit）返回逐字节一致；
  2. 输出为单编码 JSON（json.loads 一层即得 dict，而非 JSON 字符串套娃）。

analyze_technical 另锁形态②：其缓存键与 REST diagnostic_service 共用
（analyze_technical:{symbol}:{days}，统一网关同进程共享 cache 单例），
修后两层统一存 dict、出口单次序列化，跨层键内容类型一致。

TradeX 消费面核查（2026-11-23，AGENTS.md rule 3）：16 工具名全仓
（py/ts/tsx/js/vue/json/yaml/toml，含 node_modules 外全文件类型）零命中，
无兼容面。
"""

from __future__ import annotations

import json
import sys
import types

import pandas as pd
import pytest

from tradex.tools import analysis_engine, signal_data_base, signal_data_board, signal_data_cb, signal_data_etf, signal_data_flow


class _StubRouter:
    """SmartRouter 替身：route 返回固定 payload（数据源名 "stub"）。"""

    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def route(self, _name, **_kwargs):
        self.calls += 1
        return self.payload, "stub"


def _assert_single_encoded_and_parity(first: str, second: str) -> None:
    """票面两条锁定断言：hit/miss 逐字节一致 + 输出单编码（一层 loads 得 dict）。"""
    assert first == second, (
        "QI-BUG-03: 首调（miss）与缓存命中（hit）返回不一致——"
        f"miss={first[:120]!r} hit={second[:120]!r}"
    )
    parsed = json.loads(first)
    assert isinstance(parsed, dict), (
        "QI-BUG-03: 输出非单编码 JSON（json.loads 一层应得 dict，"
        f"实际得 {type(parsed).__name__} = 双重编码字符串套娃）：{first[:120]!r}"
    )


# ---------- base 组：get_lockup_expiry（无条件缓存，mcp_serve(dump=dict_to_json) 型） ----------


async def test_lockup_expiry_hit_miss_parity(monkeypatch):
    stub = _StubRouter({"lockups": [{"code": "990001", "date": "2026-01-02"}]})
    monkeypatch.setattr(signal_data_base, "_router", stub)

    first = await signal_data_base.get_lockup_expiry("990001", "2026-01-02", 30)
    assert stub.calls == 1
    second = await signal_data_base.get_lockup_expiry("990001", "2026-01-02", 30)
    assert stub.calls == 1, "第二次调用应命中缓存（不再路由）"

    _assert_single_encoded_and_parity(first, second)


# ---------- base 组第二形态：get_technical_indicator（默认 dump=True 对 json.dumps 串双重编码） ----------


async def test_technical_indicator_hit_miss_parity(monkeypatch):
    fake_indicators = types.ModuleType("astock_signals.indicators")
    fake_indicators.get_supported_indicators = lambda: ("macd",)
    fake_indicators.get_indicator_description = lambda _name: "测试指标"
    fake_indicators.calculate_indicators = lambda df, indicator, _days: df[["Date"]].assign(**{indicator: 1.0})
    monkeypatch.setitem(sys.modules, "astock_signals.indicators", fake_indicators)

    df = pd.DataFrame({
        "Date": pd.date_range("2026-01-01", periods=5).strftime("%Y-%m-%d"),
        "Open": [1.0] * 5,
        "High": [1.0] * 5,
        "Low": [1.0] * 5,
        "Close": [1.0] * 5,
        "Volume": [100] * 5,
    })
    stub = _StubRouter(df)
    monkeypatch.setattr(signal_data_base, "_router", stub)

    first = await signal_data_base.get_technical_indicator(
        "990001", "macd", curr_date="2026-01-06", look_back_days=5
    )
    assert stub.calls == 1
    second = await signal_data_base.get_technical_indicator(
        "990001", "macd", curr_date="2026-01-06", look_back_days=5
    )
    assert stub.calls == 1, "第二次调用应命中缓存（不再路由）"

    _assert_single_encoded_and_parity(first, second)
    assert json.loads(first)["indicator"] == "macd", "业务字段保持（锁定业务语义非字节形态）"


# ---------- etf 组：get_etf_realtime_data（条件缓存 result.get("etfs")） ----------


async def test_etf_realtime_hit_miss_parity(monkeypatch):
    stub = _StubRouter({"etfs": [{"code": "990300"}]})
    monkeypatch.setattr(signal_data_etf, "_router", stub)

    first = await signal_data_etf.get_etf_realtime_data(top_n=5, sort_by="测试排序")
    assert stub.calls == 1
    second = await signal_data_etf.get_etf_realtime_data(top_n=5, sort_by="测试排序")
    assert stub.calls == 1, "第二次调用应命中缓存（不再路由）"

    _assert_single_encoded_and_parity(first, second)


# ---------- board 组：get_board_sentiment（条件缓存 not result.get("error")） ----------


async def test_board_sentiment_hit_miss_parity(monkeypatch):
    stub = _StubRouter({"date": "20261123", "zt_count": 10, "zhaban_rate": 0.1})
    monkeypatch.setattr(signal_data_board, "_router", stub)

    first = await signal_data_board.get_board_sentiment(date="20261123")
    assert stub.calls == 1
    second = await signal_data_board.get_board_sentiment(date="20261123")
    assert stub.calls == 1, "第二次调用应命中缓存（不再路由）"

    _assert_single_encoded_and_parity(first, second)


# ---------- cb 组：get_cb_realtime_data（条件缓存 result.get("bonds")） ----------


async def test_cb_realtime_hit_miss_parity(monkeypatch):
    stub = _StubRouter({"bonds": [{"code": "990527"}]})
    monkeypatch.setattr(signal_data_cb, "_router", stub)

    first = await signal_data_cb.get_cb_realtime_data(top_n=5, sort_by="测试排序")
    assert stub.calls == 1
    second = await signal_data_cb.get_cb_realtime_data(top_n=5, sort_by="测试排序")
    assert stub.calls == 1, "第二次调用应命中缓存（不再路由）"

    _assert_single_encoded_and_parity(first, second)


# ---------- flow 组：get_fund_flow_signal（条件缓存 result.get("realtime")） ----------


async def test_fund_flow_signal_hit_miss_parity(monkeypatch):
    stub = _StubRouter({"realtime": [{"net": 1.0}]})
    monkeypatch.setattr(signal_data_flow, "_router", stub)

    first = await signal_data_flow.get_fund_flow_signal("990001", "2026-01-02", include_history=False)
    assert stub.calls == 1
    second = await signal_data_flow.get_fund_flow_signal("990001", "2026-01-02", include_history=False)
    assert stub.calls == 1, "第二次调用应命中缓存（不再路由）"

    _assert_single_encoded_and_parity(first, second)


# ---------- analysis_engine 组：analyze_technical（与 REST diagnostic_service 共键，形态②） ----------


class _FakeEngine:
    def __init__(self, _df, symbol=""):
        self.symbol = symbol

    def analyze_all(self):
        return {"data_points": 30, "summary": {"signal": "stub"}, "symbol": self.symbol}


async def test_analyze_technical_hit_miss_parity(monkeypatch):
    monkeypatch.setattr(analysis_engine, "_load_ohlcv", lambda _s, _d: pd.DataFrame({"close": [1.0]}))
    monkeypatch.setattr(analysis_engine, "AnalysisEngine", _FakeEngine)

    first = await analysis_engine.analyze_technical("990001", look_back_days=30)
    second = await analysis_engine.analyze_technical("990001", look_back_days=30)

    _assert_single_encoded_and_parity(first, second)
    assert json.loads(first)["data_points"] == 30, "业务字段保持（锁定业务语义非字节形态）"

    # 跨层共键一致性：REST diagnostic_service 读同键应得 dict（形态②统一缓存存对象）
    from tradex.service import diagnostic_service

    rest_result = diagnostic_service.analyze_technical("990001", look_back_days=30)
    assert isinstance(rest_result, dict), (
        "QI-BUG-03 形态②: MCP 工具缓存后，REST 共键消费应得 dict（缓存统一存对象），"
        f"实际得 {type(rest_result).__name__}"
    )
    assert rest_result.get("data_points") == 30
