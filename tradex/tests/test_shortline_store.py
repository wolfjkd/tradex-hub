"""工单 H3 测试：15:35 收盘定稿落库 + 历史回读。

覆盖：
- 首次落库：6 个读数 + raw_fields + daily_metrics + schema_version
- 幂等：同日重复调用不重复写
- 防覆盖：partial 永不覆盖 final；partial→final 允许升级
- 缺数写 missing_reason（不当 0）
- 写失败：ERROR 留痕 + health 可查
- 历史读取：记录 + 缺天（工作日推算）
- MCP / REST 双通道；cycle 从落库读历史
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tradex.api import routes as rest_routes
from tradex.service import shortline_service
from tradex.shortline import store
from tradex.shortline.meta import cache_key
from tradex.utils.cache import cache


_ZT = [
    {"code": "600519", "name": "贵州茅台", "consecutive_days": 1, "change_pct": 10.0},
    {"code": "300750", "name": "宁德时代", "consecutive_days": 2, "change_pct": 20.0},
    {"code": "002384", "name": "东山精密", "consecutive_days": 3, "change_pct": 10.0},
]
_PREV = [
    {"code": "600519", "name": "贵州茅台", "consecutive_days": 1, "change_pct": 5.0},
    {"code": "300750", "name": "宁德时代", "consecutive_days": 1, "change_pct": 2.0},
    {"code": "000001", "name": "平安银行", "consecutive_days": 2, "change_pct": -1.0},
]
_ZB = [{"code": "600000", "name": "浦发银行", "consecutive_days": 1, "change_pct": 5.0}]
_DT = [{"code": "600111", "name": "北方稀土", "consecutive_days": 1, "change_pct": -10.0}]
_FIELDS = {
    "zt": ["代码", "名称", "涨跌幅", "连板数"],
    "zb": ["代码", "名称", "涨跌幅"],
    "dt": ["代码", "名称", "涨跌幅"],
    "prev_zt": ["代码", "名称", "涨跌幅", "昨日连板数"],
}
_ROWS = {"zt": _ZT, "zb": _ZB, "dt": _DT, "prev_zt": _PREV}
_DEFAULT_DATE = "20261105"


class _FakeRouter:
    def __init__(self, fail: tuple[str, ...] = (), error: Exception | None = None):
        self.fail = set(fail)
        self.error = error

    def route(self, data_type, **kwargs):
        assert data_type == "limit_up_board"
        board_type = kwargs.get("board_type")
        if board_type in self.fail:
            raise self.error or RuntimeError(f"{board_type} 源失败")
        return {
            "board_type": board_type,
            "date": kwargs.get("date") or _DEFAULT_DATE,
            "count": len(_ROWS[board_type]),
            "data": _ROWS[board_type],
            "fields": _FIELDS[board_type],
        }, "akshare_em"


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    monkeypatch.setenv("SHORTLINE_DATA_DIR", str(tmp_path / "shortline"))
    store._date_locks.clear()
    store._health.update({
        "writes": 0, "skips": 0, "last_write_at": None, "last_date": None,
        "last_error": None, "last_error_at": None,
    })
    yield tmp_path / "shortline"


@pytest.fixture(autouse=True)
def _clean_cache():
    for date_key in (_DEFAULT_DATE, "20261103", "20261104", "20261102", "latest"):
        cache.invalidate(cache_key("shortline.cycle", date=date_key, days=5))
    yield


class TestCloseFetch:
    def test_first_write_contains_all_readings(self, monkeypatch):
        monkeypatch.setattr(shortline_service, "_router", _FakeRouter())
        result = store.close_fetch(date=_DEFAULT_DATE)

        assert result["written"] is True
        assert result["status"] == "final"
        assert result["schema_version"] == 2

        record = store.load(_DEFAULT_DATE)
        assert record["schema_version"] == 2
        assert record["status"] == "final"
        assert set(record["readings"]) == {
            "emotion", "daily", "settled", "ladder", "board_ladder", "structure", "themes",
        }
        assert record["daily_metrics"]["limit_up_count"] == 3
        assert record["theme_counts"] == {}  # 测试 router 无归因源 → 空表，不当 0
        assert record["raw_fields"]["zt"] == _FIELDS["zt"]
        assert record["missing_reason"]["pools"] == {}
        assert record["missing_reason"]["themes"]  # 归因缺失必须写原因

    def test_idempotent_second_call_does_not_rewrite(self, monkeypatch, _isolated_store):
        monkeypatch.setattr(shortline_service, "_router", _FakeRouter())
        first = store.close_fetch(date=_DEFAULT_DATE)
        path = store.record_path(_DEFAULT_DATE)
        content = path.read_text(encoding="utf-8")

        second = store.close_fetch(date=_DEFAULT_DATE)
        assert second["written"] is False
        assert "幂等跳过" in second["reason"]
        assert path.read_text(encoding="utf-8") == content
        assert store.health()["skips"] >= 1

    def test_force_recomputes_final(self, monkeypatch):
        monkeypatch.setattr(shortline_service, "_router", _FakeRouter())
        store.close_fetch(date=_DEFAULT_DATE)
        again = store.close_fetch(date=_DEFAULT_DATE, force=True)
        assert again["written"] is True
        assert "force" in again["reason"]

    def test_partial_never_overwrites_final(self, monkeypatch):
        monkeypatch.setattr(shortline_service, "_router", _FakeRouter())
        store.close_fetch(date=_DEFAULT_DATE)

        monkeypatch.setattr(shortline_service, "_router", _FakeRouter(fail=("zb",)))
        partial = store.close_fetch(date=_DEFAULT_DATE, force=True)

        assert partial["written"] is False
        assert partial["status"] == "final"  # 文件里仍是 final
        assert "拒绝 partial 覆盖" in partial["reason"]
        assert store.load(_DEFAULT_DATE)["status"] == "final"

    def test_partial_then_final_upgrades(self, monkeypatch):
        monkeypatch.setattr(shortline_service, "_router", _FakeRouter(fail=("zb",)))
        first = store.close_fetch(date=_DEFAULT_DATE)
        assert first["written"] is True
        assert first["status"] == "partial"
        assert "zb" in first["missing_reasons"]["pools"]

        monkeypatch.setattr(shortline_service, "_router", _FakeRouter())
        second = store.close_fetch(date=_DEFAULT_DATE)
        assert second["written"] is True
        assert second["status"] == "final"
        assert "升级" in second["reason"]
        assert store.load(_DEFAULT_DATE)["status"] == "final"

    def test_missing_pool_written_as_reason_not_zero(self, monkeypatch):
        monkeypatch.setattr(shortline_service, "_router", _FakeRouter(fail=("zb",)))
        store.close_fetch(date=_DEFAULT_DATE)
        record = store.load(_DEFAULT_DATE)
        daily = record["readings"]["daily"]["result"]
        assert daily["broken_count"] is None
        assert daily["break_rate"] is None
        assert record["missing_reason"]["pools"]["zb"]

    def test_write_failure_marks_health(self, monkeypatch):
        monkeypatch.setattr(shortline_service, "_router", _FakeRouter())

        def _boom(src, dst):
            raise OSError("disk full")

        monkeypatch.setattr(store.os, "replace", _boom)
        with pytest.raises(OSError, match="disk full"):
            store.close_fetch(date=_DEFAULT_DATE)
        health = store.health()
        assert "disk full" in health["last_error"]
        assert health["last_error_at"]

    def test_schema_upgrade_rewrites_final(self, monkeypatch):
        """回归：旧 schema 的 final 记录必须能被新 schema 自动升级，否则历史永久卡住。"""
        monkeypatch.setattr(shortline_service, "_router", _FakeRouter())
        store.close_fetch(date=_DEFAULT_DATE)
        path = store.record_path(_DEFAULT_DATE)
        record = json.loads(path.read_text(encoding="utf-8"))
        record["schema_version"] = 1
        record.pop("theme_counts", None)
        path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")

        result = store.close_fetch(date=_DEFAULT_DATE)  # 不带 force
        assert result["written"] is True
        assert "schema 升级" in result["reason"]
        upgraded = store.load(_DEFAULT_DATE)
        assert upgraded["schema_version"] == 2
        assert "theme_counts" in upgraded


class TestHistory:
    def _seed_dates(self, monkeypatch, dates):
        for day in dates:
            monkeypatch.setattr(shortline_service, "_router", _FakeRouter())
            store.close_fetch(date=day)

    def test_history_records_and_missing_dates(self, monkeypatch):
        self._seed_dates(monkeypatch, ["20261102", "20261105"])
        result = store.history(days=5, date="20261105")
        assert result["count"] == 2
        assert result["dates"] == ["20261102", "20261105"]
        assert result["missing_dates"] == ["20261103", "20261104"]
        assert result["schema_version"] == 2
        assert result["records"][0]["limit_up_count"] == 3

    def test_history_respects_days_window(self, monkeypatch):
        self._seed_dates(monkeypatch, ["20261102", "20261103", "20261104", "20261105"])
        result = store.history(days=2, date="20261105")
        assert result["dates"] == ["20261104", "20261105"]

    def test_empty_history(self):
        result = store.history()
        assert result["count"] == 0
        assert result["records"] == []


class TestCycleReadsHistory:
    def test_cycle_uses_persisted_history(self, monkeypatch):
        for day in ("20261102", "20261103"):
            monkeypatch.setattr(shortline_service, "_router", _FakeRouter())
            store.close_fetch(date=day)
        monkeypatch.setattr(shortline_service, "_router", _FakeRouter())

        result = shortline_service.get_cycle(days=5, date=_DEFAULT_DATE)
        assert result["partial"] is False
        assert result["result"]["window_days"] == 3  # 2 天历史 + 今日
        assert result["result"]["metrics"]["limit_up_count"]["percentile"] is not None
        assert result["missing_reason"] is None


class TestChannels:
    def test_tools_registered(self):
        from mcp.server.fastmcp import FastMCP
        from tradex.tools.shortline import register

        mcp = FastMCP("test_store_tools")
        register(mcp)
        names = set(mcp._tool_manager._tools)
        assert {"shortline_close_fetch", "get_shortline_history"} <= names

    def test_close_fetch_tool_and_history_tool(self, monkeypatch):
        from mcp.server.fastmcp import FastMCP
        from tradex.tools.shortline import register

        monkeypatch.setattr(shortline_service, "_router", _FakeRouter())
        mcp = FastMCP("test_store_tools2")
        register(mcp)
        close_fn = mcp._tool_manager._tools["shortline_close_fetch"].fn
        hist_fn = mcp._tool_manager._tools["get_shortline_history"].fn
        close_data = json.loads(asyncio.run(close_fn(date=_DEFAULT_DATE)))
        hist_data = json.loads(asyncio.run(hist_fn(date=_DEFAULT_DATE, days=5)))
        assert close_data["written"] is True
        assert hist_data["count"] == 1

    def test_rest_close_fetch_history_health(self, monkeypatch):
        monkeypatch.setattr(shortline_service, "_router", _FakeRouter())
        app = FastAPI()
        app.include_router(rest_routes.router, prefix="/api/v1")
        client = TestClient(app)

        resp = client.post(f"/api/v1/shortline/close-fetch?date={_DEFAULT_DATE}")
        assert resp.status_code == 200
        assert resp.json()["data"]["written"] is True

        hist = client.get(f"/api/v1/shortline/history?date={_DEFAULT_DATE}&days=5")
        assert hist.status_code == 200
        assert hist.json()["data"]["count"] == 1

        health = client.get("/api/v1/shortline/store-health")
        assert health.status_code == 200
        assert health.json()["data"]["schema_version"] == 2
