"""工单 H6 测试：题材 / 首板 / 盘面事实 / 题材轮动。

覆盖：
- 题材事件树：整条原因归组 + 关键词拆分 + 未归因
- 首板：按首封时间排序 + 反包单标
- 盘面事实：封板质量 / 亏钱效应 / 反馈矩阵
- 题材轮动：缺天画「—」、连续、回流
- 归因兜底：问财失败自动切同花顺并标 source；两源皆挂时写明原因
"""

from __future__ import annotations

import asyncio
import json

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tradex.api import routes as rest_routes
from tradex.service import shortline_service
from tradex.shortline import compute, store
from tradex.shortline.compute import PoolSnapshot
from tradex.shortline.meta import cache_key
from tradex.utils.cache import cache


def _snapshot():
    zt = [
        {"code": "600519", "name": "贵州茅台", "consecutive_days": 1, "change_pct": 10.0,
         "first_seal_time": "09:35:00", "limit_up_stats": "1/3", "sealed_capital": 1_000_000_000,
         "break_count": 0},
        {"code": "300750", "name": "宁德时代", "consecutive_days": 1, "change_pct": 20.0,
         "first_seal_time": "10:20:00", "limit_up_stats": "1/1", "sealed_capital": 500_000_000,
         "break_count": 1},
        {"code": "002384", "name": "东山精密", "consecutive_days": 3, "change_pct": 10.0,
         "first_seal_time": "13:10:00", "limit_up_stats": "3/5", "sealed_capital": 200_000_000,
         "break_count": 2},
    ]
    prev_zt = [
        {"code": "600519", "name": "贵州茅台", "consecutive_days": 1, "change_pct": 5.0},
        {"code": "300750", "name": "宁德时代", "consecutive_days": 1, "change_pct": 2.0},
        {"code": "002384", "name": "东山精密", "consecutive_days": 1, "change_pct": 9.0},
        {"code": "000001", "name": "平安银行", "consecutive_days": 2, "change_pct": -1.0},
        {"code": "601398", "name": "工商银行", "consecutive_days": 3, "change_pct": -3.0},
    ]
    zb = [{"code": "600000", "name": "浦发银行", "consecutive_days": 1, "change_pct": 5.0},
          {"code": "000002", "name": "万科A", "consecutive_days": 1, "change_pct": 3.0}]
    dt = [{"code": "600111", "name": "北方稀土", "consecutive_days": 1, "change_pct": -10.0}]
    return PoolSnapshot(date="20261106", zt=zt, zb=zb, dt=dt, prev_zt=prev_zt,
                        fields={"zt": ["代码", "名称"], "zb": ["代码"], "dt": ["代码"],
                                "prev_zt": ["代码"]})


class TestThemesCompute:
    def test_grouping_and_keywords(self):
        reasons = {
            "600519": "白酒、消费",
            "300750": "固态电池、锂电池",
            "002384": "消费电子、苹果链",
        }
        result, text = compute.themes(_snapshot(), reasons, "同花顺涨停归因")
        assert result["reason_source"] == "同花顺涨停归因"
        assert len(result["events"]) == 3
        keyword_map = {k["theme"]: k["count"] for k in result["keywords"]}
        assert keyword_map["白酒"] == 1
        assert keyword_map["固态电池"] == 1
        assert result["unattributed_count"] == 0
        assert result["missing_reason"] is None

    def test_unattributed_reported(self):
        reasons = {"600519": "白酒"}
        result, _ = compute.themes(_snapshot(), reasons, "问财")
        assert result["unattributed_count"] == 2
        assert result["missing_reason"]

    def test_no_reason_source(self):
        result, _ = compute.themes(_snapshot(), {}, "无（问财与同花顺均失败）")
        assert result["events"] == []
        assert result["unattributed_count"] == 3
        assert result["missing_reason"]


class TestFirstboardCompute:
    def test_sorted_by_seal_time_and_reversal(self):
        result, _ = compute.firstboard(_snapshot())
        assert result["count"] == 2
        assert [s["code"] for s in result["stocks"]] == ["600519", "300750"]
        assert result["stocks"][0]["is_reversal"] is True   # 涨停统计 1/3
        assert result["stocks"][1]["is_reversal"] is False  # 涨停统计 1/1
        assert result["reversal_count"] == 1

    def test_no_firstboard(self):
        snap = _snapshot()
        snap.zt = [r for r in snap.zt if r["consecutive_days"] > 1]
        result, _ = compute.firstboard(snap)
        assert result["count"] == 0
        assert result["missing_reason"]

    def test_missing_seal_time_sorted_last(self):
        snap = _snapshot()
        for row in snap.zt:
            if row["code"] == "600519":
                row["first_seal_time"] = ""
        result, _ = compute.firstboard(snap)
        assert [s["code"] for s in result["stocks"]] == ["300750", "600519"]


class TestFactsCompute:
    def test_seal_quality_and_losing_effect(self):
        result, text = compute.facts(_snapshot())
        quality = result["seal_quality"]
        assert quality["avg_sealed_capital_yi"] == 5.6667  # (10+5+2)/3 亿
        assert quality["median_first_seal_time"] == "10:20"
        assert quality["avg_break_count"] == 1.0
        assert quality["seal_rate"] == 60.0
        losing = result["losing_effect"]
        assert losing["down_ratio"] == 40.0
        assert losing["median_change"] == 2.0
        assert losing["limit_down_count"] == 1

    def test_feedback_matrix(self):
        result, _ = compute.facts(_snapshot())
        matrix = result["feedback_matrix"]
        assert matrix["首板"]["上涨"] == 3
        assert matrix["2板"]["下跌"] == 1
        assert matrix["3板+"]["下跌"] == 1

    def test_missing_prev(self):
        snap = _snapshot()
        snap.prev_zt = []
        snap.missing = ["prev_zt"]
        result, _ = compute.facts(snap)
        assert result["losing_effect"]["down_ratio"] is None
        assert result["missing_reason"]


class TestRotationCompute:
    def test_missing_day_drawn_as_dash(self):
        records = [
            {"date": "20261103", "available": True, "theme_counts": {"固态电池": 2, "白酒": 1}},
            {"date": "20261104", "available": False, "theme_counts": None},
            {"date": "20261105", "available": True, "theme_counts": {"固态电池": 3, "白酒": 1, "机器人": 1}},
        ]
        result, text = compute.theme_rotation(records, missing_dates=["20261104"])
        rows = {r["theme"]: r for r in result["rows"]}
        assert rows["固态电池"]["counts"] == [2, None, 3]
        assert rows["固态电池"]["display"] == "2 / — / 3"
        assert rows["固态电池"]["ranks"] == [1, None, 1]
        assert result["missing_dates"] == ["20261104"]
        assert "—" in text

    def test_streak_and_returning(self):
        records = [
            {"date": "20261103", "available": True, "theme_counts": {"固态电池": 2, "机器人": 0}},
            {"date": "20261104", "available": True, "theme_counts": {"固态电池": 1, "机器人": 0}},
            {"date": "20261105", "available": True, "theme_counts": {"固态电池": 3, "机器人": 2}},
        ]
        result, _ = compute.theme_rotation(records, missing_dates=[])
        rows = {r["theme"]: r for r in result["rows"]}
        assert rows["固态电池"]["streak"] == 3
        assert rows["固态电池"]["is_returning"] is False
        assert rows["机器人"]["is_returning"] is True
        assert rows["机器人"]["streak"] == 1

    def test_empty_history(self):
        result, text = compute.theme_rotation([])
        assert result["rows"] == []
        assert result["missing_reason"]
        assert "无历史数据" in text


# ---------------------------------------------------------------- service


_ZT = _snapshot().zt
_PREV = _snapshot().prev_zt
_ZB = _snapshot().zb
_DT = _snapshot().dt
_ROWS = {"zt": _ZT, "zb": _ZB, "dt": _DT, "prev_zt": _PREV}
_DATE = "20261106"


class _FakeRouter:
    def __init__(self, wencai: str = "fail", ths: bool = True, date: str = _DATE):
        self.wencai = wencai  # "fail" / "ok"
        self.ths = ths
        self.date = date

    def route(self, data_type, **kwargs):
        if data_type == "limit_up_board":
            bt = kwargs["board_type"]
            return {"board_type": bt, "date": kwargs.get("date") or self.date,
                    "count": len(_ROWS[bt]), "data": _ROWS[bt],
                    "fields": ["代码", "名称"]}, "akshare_em"
        if data_type == "wencai_query":
            if self.wencai != "ok":
                raise RuntimeError("IWENCAI_API_KEY 缺失")
            return pd.DataFrame([
                {"股票代码": "600519", "涨停原因": "白酒、消费"},
                {"股票代码": "300750", "涨停原因": "固态电池"},
                {"股票代码": "002384", "涨停原因": "消费电子"},
            ]), "pywencai"
        if data_type == "hot_money":
            if not self.ths:
                raise RuntimeError("同花顺挂了")
            return {"date": kwargs.get("date"), "error": None, "stocks": [
                {"code": "600519", "reason": "白酒、消费"},
                {"code": "300750", "reason": "固态电池"},
                {"code": "002384", "reason": "消费电子"},
            ]}, "ths_editorial"
        raise AssertionError(f"unexpected {data_type}")


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SHORTLINE_DATA_DIR", str(tmp_path / "shortline"))
    store._date_locks.clear()
    for endpoint in ("shortline.themes", "shortline.firstboard", "shortline.facts",
                     "shortline.theme_rotation"):
        for d in (_DATE, "20261103", "20261104", "20261105"):
            cache.invalidate(cache_key(endpoint, date=d))
            cache.invalidate(cache_key(endpoint, date=d, days=5))
    yield


class TestReasonFallback:
    def test_wencai_unavailable_switches_to_ths(self, monkeypatch):
        monkeypatch.setattr(shortline_service, "_router", _FakeRouter(wencai="fail"))
        reasons, source, problems = shortline_service.fetch_reasons(_DATE)
        assert source == "同花顺涨停归因"
        assert reasons["600519"] == "白酒、消费"
        assert any("问财" in p for p in problems)

    def test_wencai_preferred_when_available(self, monkeypatch):
        # 2026-11-07 合并制升级（wencai WAP 锁页 10 行）：问财可用也调同花顺补缺
        monkeypatch.setattr(shortline_service, "_router", _FakeRouter(wencai="ok"))
        reasons, source, problems = shortline_service.fetch_reasons(_DATE)
        assert source == "问财+同花顺补缺"
        assert problems == []
        assert reasons["300750"] == "固态电池"

    def test_wencai_only_when_ths_down(self, monkeypatch):
        monkeypatch.setattr(shortline_service, "_router", _FakeRouter(wencai="ok", ths=False))
        reasons, source, problems = shortline_service.fetch_reasons(_DATE)
        assert source == "问财"
        assert reasons["002384"] == "消费电子"
        assert any("同花顺" in p for p in problems)

    def test_both_sources_fail(self, monkeypatch):
        monkeypatch.setattr(shortline_service, "_router", _FakeRouter(wencai="fail", ths=False))
        reasons, source, problems = shortline_service.fetch_reasons(_DATE)
        assert reasons == {}
        assert "均失败" in source
        assert len(problems) == 2

    def test_themes_endpoint_marks_source(self, monkeypatch):
        monkeypatch.setattr(shortline_service, "_router", _FakeRouter(wencai="fail"))
        result = shortline_service.get_themes(date=_DATE)
        assert result["source"] == "同花顺涨停归因"
        assert result["result"]["reason_source"] == "同花顺涨停归因"
        assert len(result["result"]["events"]) == 3

    def test_themes_endpoint_both_fail(self, monkeypatch):
        monkeypatch.setattr(shortline_service, "_router", _FakeRouter(wencai="fail", ths=False))
        result = shortline_service.get_themes(date=_DATE)
        assert result["partial"] is True
        assert "theme_source" in result["missing_reason"]


class TestThemeEndpoints:
    def test_firstboard_and_facts(self, monkeypatch):
        monkeypatch.setattr(shortline_service, "_router", _FakeRouter())
        fb = shortline_service.get_firstboard(date=_DATE)
        assert fb["result"]["count"] == 2
        assert fb["result"]["reversal_count"] == 1
        facts = shortline_service.get_facts(date=_DATE)
        assert facts["result"]["seal_quality"]["seal_rate"] == 60.0

    def test_rotation_uses_store_history(self, monkeypatch):
        fake = _FakeRouter(wencai="fail")
        monkeypatch.setattr(shortline_service, "_router", fake)
        for day in ("20261104", "20261105"):
            fake.date = day
            result = store.close_fetch(date=day)
            assert result["written"] is True
            record = store.load(day)
            assert record["theme_counts"]["固态电池"] == 1

        fake.date = _DATE
        rotation = shortline_service.get_theme_rotation(days=5, date=_DATE)
        assert rotation["result"]["days"] == ["20261104", "20261105", "20261106"]
        rows = {r["theme"]: r for r in rotation["result"]["rows"]}
        assert rows["固态电池"]["counts"] == [1, 1, 1]
        assert rows["固态电池"]["streak"] == 3
        assert rotation["partial"] is False

    def test_rotation_without_history_draws_dash(self, monkeypatch):
        monkeypatch.setattr(shortline_service, "_router", _FakeRouter(wencai="fail"))
        rotation = shortline_service.get_theme_rotation(days=5, date=_DATE)
        assert rotation["partial"] is True
        # 无历史时不伪造 0，明确写原因
        assert rotation["missing_reason"]

    def test_rotation_dedupes_today_record(self, monkeypatch):
        """今日已有落库记录时也不能把「今天」算成两天。"""
        fake = _FakeRouter(wencai="fail")
        monkeypatch.setattr(shortline_service, "_router", fake)
        fake.date = _DATE
        store.close_fetch(date=_DATE)

        rotation = shortline_service.get_theme_rotation(days=5, date=_DATE)
        assert rotation["result"]["days"] == [_DATE]


class TestChannels:
    def test_four_tools_registered(self):
        from mcp.server.fastmcp import FastMCP
        from tradex.tools.shortline import register

        mcp = FastMCP("test_theme_tools")
        register(mcp)
        names = set(mcp._tool_manager._tools)
        assert {
            "get_shortline_themes", "get_shortline_firstboard",
            "get_shortline_facts", "get_shortline_theme_rotation",
        } <= names

    def test_rest_four_endpoints(self, monkeypatch):
        monkeypatch.setattr(shortline_service, "_router", _FakeRouter(wencai="fail"))
        app = FastAPI()
        app.include_router(rest_routes.router, prefix="/api/v1")
        client = TestClient(app)
        for path in ("themes", "firstboard", "facts", "theme-rotation"):
            resp = client.get(f"/api/v1/shortline/{path}?date={_DATE}")
            assert resp.status_code == 200, path
            assert resp.json()["code"] == 0

    def test_tool_returns_json(self, monkeypatch):
        from mcp.server.fastmcp import FastMCP
        from tradex.tools.shortline import register

        monkeypatch.setattr(shortline_service, "_router", _FakeRouter(wencai="fail"))
        mcp = FastMCP("test_theme_tools2")
        register(mcp)
        fn = mcp._tool_manager._tools["get_shortline_themes"].fn
        data = json.loads(asyncio.run(fn(date=_DATE)))
        assert data["source"] == "同花顺涨停归因"
