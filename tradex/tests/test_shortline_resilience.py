"""工单 H7 测试：数据源韧性包。

覆盖：
- 四池字段漂移：新增/消失列、语义别名缺口、可疑 0、告警
- 行业资金新浪 fallback：解析 + 归一化 + source/口径标注
- 缺数原因统一字段（missing_reason 各端点复用、落库同名字段）
- 数据源健康看板接入
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tradex.api import routes as rest_routes
from tradex.data_sources import registry as ds_registry
from tradex.data_sources import sina_fetchers
from tradex.service import shortline_service
from tradex.shortline import drift, store
from tradex.shortline.meta import SHORTLINE_ENDPOINTS


_SAMPLE_JS = (
    'var S_Finance_bankuai_sinaindustry = {'
    '"new_blhy":"new_blhy,玻璃行业,19,13.49,-0.27,-1.98,554007114,8071922060,'
    'sz300093,4.502,19.500,0.840,金刚光伏",'
    '"new_dlhy":"new_dlhy,电力行业,62,7.86,0.0735,0.9432,2962888689,'
    '25273954648,sh600644,8.247,8.400,0.640,乐山电力"};'
)


class TestFieldDrift:
    def test_compare_added_removed(self):
        current = {"zt": ["代码", "名称", "封板资金", "新增列"], "zb": ["代码"],
                   "dt": ["代码"], "prev_zt": ["代码"]}
        reference = {"zt": ["代码", "名称", "封单资金"], "zb": ["代码"],
                     "dt": ["代码"], "prev_zt": ["代码"]}
        result = drift.compare_fields(current, reference)
        assert result["drift"] is True
        assert result["removed"]["zt"] == ["封单资金"]  # 参考有、当前没有
        # added 只列当前有、参考没有的
        assert "新增列" in result["added"]["zt"]

    def test_no_drift_when_identical(self):
        fields = {"zt": ["代码", "名称", "封板资金"]}
        result = drift.compare_fields(fields, fields)
        assert result["drift"] is False
        assert result["added"] == {}
        assert result["removed"] == {}

    def test_alias_gap_and_zero_suspect(self):
        # 「封单额」被改名成「封板金额」→ 语义字段 sealed_capital 无别名匹配
        fields = {"zt": ["代码", "名称", "封板金额", "连板数", "首次封板时间", "炸板次数"]}
        gaps = drift.alias_gaps(fields)
        assert gaps == {"zt": ["sealed_capital", "last_seal_time"]}
        suspects = drift.zero_suspects(gaps)
        assert {(s["pool"], s["field"]) for s in suspects} == {
            ("zt", "sealed_capital"), ("zt", "last_seal_time"),
        }
        assert all("不可当真实值" in s["reason"] for s in suspects)

    def test_no_alias_gap_when_alias_present(self):
        fields = {"zt": ["代码", "围单资金", "封板资金", "连板数", "首次封板时间", "最后封板时间", "炸板次数"]}
        assert drift.alias_gaps(fields) == {}


class _FakeRouter:
    def __init__(self, fields_by_date: dict[str, dict], fail: tuple[str, ...] = ()):
        self.fields_by_date = fields_by_date
        self.fail = set(fail)

    def route(self, data_type, **kwargs):
        if data_type == "limit_up_board":
            bt = kwargs["board_type"]
            if bt in self.fail:
                raise RuntimeError(f"{bt} 源失败")
            day = kwargs.get("date") or "20261106"
            fields = self.fields_by_date.get(day, {}).get(bt, ["代码", "名称", "涨跌幅"])
            rows = {
                "zt": [{"code": "600519", "name": "贵州茅台", "consecutive_days": 1, "change_pct": 10.0}],
                "zb": [{"code": "600000", "name": "浦发银行", "change_pct": 5.0}],
                "dt": [{"code": "600111", "name": "北方稀土", "change_pct": -10.0}],
                "prev_zt": [{"code": "600519", "name": "贵州茅台", "consecutive_days": 1, "change_pct": 5.0}],
            }[bt]
            return {"board_type": bt, "date": day, "count": len(rows), "data": rows,
                    "fields": fields}, "akshare_em"
        if data_type == "wencai_query":
            raise RuntimeError("no key")
        if data_type == "hot_money":
            return {"date": kwargs.get("date"), "error": None, "stocks": [
                {"code": "600519", "reason": "白酒、消费"}]}, "ths_editorial"
        raise AssertionError(data_type)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SHORTLINE_DATA_DIR", str(tmp_path / "shortline"))
    store._date_locks.clear()
    yield


class TestFieldDriftStore:
    def test_no_snapshot(self):
        result = drift.field_drift()
        assert result["drift"] is None
        assert result["missing_reason"]

    def test_single_snapshot_no_reference(self, monkeypatch):
        monkeypatch.setattr(shortline_service, "_router",
                            _FakeRouter({"20261105": {"zt": ["代码", "名称", "封板资金"]}}))
        store.close_fetch(date="20261105")
        result = drift.field_drift(date="20261105")
        assert result["date"] == "20261105"
        assert result["reference_date"] is None
        assert result["drift"] is None
        assert result["missing_reason"]

    def test_drift_between_two_days(self, monkeypatch):
        router = _FakeRouter({
            "20261104": {"zt": ["代码", "名称", "封板资金"]},
            "20261105": {"zt": ["代码", "名称", "封单额", "新列"]},
        })
        monkeypatch.setattr(shortline_service, "_router", router)
        store.close_fetch(date="20261104")
        store.close_fetch(date="20261105")

        result = drift.field_drift(date="20261105")
        assert result["drift"] is True
        assert result["reference_date"] == "20261104"
        assert result["removed"]["zt"] == ["封板资金"]
        assert result["added"]["zt"] == ["封单额", "新列"]
        # 「封单额」是合法别名 → sealed_capital 不算缺口（其余语义列缺列属正常测试数据）
        assert "sealed_capital" not in result["alias_gaps"].get("zt", [])
        assert any("消失字段" in a for a in result["alerts"])
        assert any("新增字段" in a for a in result["alerts"])

    def test_alias_gap_zero_suspect_from_store(self, monkeypatch):
        router = _FakeRouter({
            "20261104": {"zt": ["代码", "名称", "封板金额"]},
            "20261105": {"zt": ["代码", "名称", "封板金额"]},
        })
        monkeypatch.setattr(shortline_service, "_router", router)
        store.close_fetch(date="20261104")
        store.close_fetch(date="20261105")
        result = drift.field_drift(date="20261105")
        assert result["drift"] is False
        assert "sealed_capital" in result["alias_gaps"]["zt"]
        assert any(s["field"] == "sealed_capital" for s in result["zero_suspects"])


class TestSinaIndustryFallback:
    def test_parse_js(self):
        rows = sina_fetchers._parse_sina_industry_js(_SAMPLE_JS)
        assert len(rows) == 2
        glass = next(r for r in rows if r["name"] == "玻璃行业")
        assert glass["change_pct"] == -1.98
        assert glass["leader"] == "金刚光伏"
        power = next(r for r in rows if r["name"] == "电力行业")
        assert power["amount"] == 25273954648.0

    def test_parse_bad_payload_raises(self):
        with pytest.raises(RuntimeError):
            sina_fetchers._parse_sina_industry_js("not a js object")

    def test_fetch_normalizes_and_marks_metric(self, monkeypatch):
        class _Resp:
            text = _SAMPLE_JS

            def raise_for_status(self):
                return None

        monkeypatch.setattr(sina_fetchers.curl_requests, "get", lambda *a, **k: _Resp())
        result = sina_fetchers.fetch_industry_comparison_sina(top_n=2, trade_date="2026-11-06")
        assert result["source"].startswith("Sina newSinaHy")
        assert result["metric"] == "amount_change"
        assert "无主力净流入" in result["note"]
        # 按涨跌幅降序：电力 +0.94 在前
        assert [i["name"] for i in result["industries"]] == ["电力行业", "玻璃行业"]
        assert result["industries"][0]["amount_yi"] == 252.74

    def test_registry_has_sina_industry_priority_300(self):
        ds_registry.register_all_sources()
        report = shortline_service._router.get_registry_report()
        rows = [r for r in report if r.get("data_type") == "industry_comparison"]
        sina_rows = [r for r in rows if r.get("source_name") == "sina_industry"]
        assert sina_rows, f"未注册 sina_industry: {rows}"
        assert sina_rows[0]["priority"] == 300


class TestUnifiedMissingReason:
    def test_endpoints_share_missing_reason_field(self, monkeypatch):
        monkeypatch.setattr(shortline_service, "_router", _FakeRouter({}, fail=("zb", "dt", "prev_zt")))
        for fn in (shortline_service.get_daily, shortline_service.get_live,
                   shortline_service.get_themes, shortline_service.get_theme_rotation):
            payload = fn() if fn is shortline_service.get_live else fn(date="20261105")
            assert "missing_reason" in payload
        store.close_fetch(date="20261105")
        record = store.load("20261105")
        assert "missing_reason" in (record or {})

    def test_store_health_exposes_errors(self):
        health = store.health()
        assert {"writes", "skips", "last_error", "last_error_at", "schema_version"} <= set(health)


class TestHealthDashboard:
    def test_shortline_health_blob(self):
        from tradex.tools.diagnostics import _shortline_health

        blob = _shortline_health()
        assert "store" in blob
        assert "field_drift" in blob
        assert blob["store"]["schema_version"] == 2


class TestChannels:
    def test_tool_and_rest(self, monkeypatch):
        monkeypatch.setattr(shortline_service, "_router", _FakeRouter({
            "20261104": {"zt": ["代码", "名称", "封板资金"]},
            "20261105": {"zt": ["代码", "名称", "封单额"]},
        }))
        store.close_fetch(date="20261104")
        store.close_fetch(date="20261105")

        from mcp.server.fastmcp import FastMCP
        from tradex.tools.shortline import register

        mcp = FastMCP("test_drift")
        register(mcp)
        fn = mcp._tool_manager._tools["get_shortline_field_drift"].fn
        data = json.loads(asyncio.run(fn(date="20261105")))
        assert data["drift"] is True

        app = FastAPI()
        app.include_router(rest_routes.router, prefix="/api/v1")
        resp = TestClient(app).get("/api/v1/shortline/field-drift?date=20261105")
        assert resp.status_code == 200
        assert resp.json()["data"]["drift"] is True

    def test_metadata_declared(self):
        endpoint = SHORTLINE_ENDPOINTS["shortline.field_drift"]
        assert endpoint.status == "implemented"
        assert endpoint.mcp_tool == "get_shortline_field_drift"
