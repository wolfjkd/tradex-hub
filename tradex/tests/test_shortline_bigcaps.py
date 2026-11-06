"""工单 H4 测试：大市值名单端点。

覆盖：
- 新浪 / 东财原始行归一化（单位、门槛、停牌、缺市值）
- 1 小时缓存命中（同参数只取数一次）
- 源切换标注（source / source_route / source_note）
- MCP 工具 + REST 路由双通道
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tradex.api import routes as rest_routes
from tradex.data_sources.sina_fetchers import _normalize_bigcap_rows
from tradex.service import bigcaps_service
from tradex.shortline.catalog import missing_compute_refs
from tradex.shortline.meta import SHORTLINE_ENDPOINTS, cache_key
from tradex.utils.cache import cache


# ---------------------------------------------------------------- 纯函数


class TestSinaNormalize:
    def test_threshold_and_units(self):
        rows = [
            {"code": "601398", "name": "工商银行", "mktcap": "300806880", "nmc": "227552707",
             "trade": "8.44", "changepercent": "1.078", "amount": "4046422115",
             "turnoverratio": "0.17921"},
            {"code": "000001", "name": "平安银行", "mktcap": "20000000", "nmc": "18000000",
             "trade": "11.64", "changepercent": "1.0", "amount": "1429433016",
             "turnoverratio": "1.2"},
            {"code": "000002", "name": "低于门槛", "mktcap": "4000000", "nmc": "3000000",
             "trade": "9.0", "changepercent": "0.5", "amount": "100", "turnoverratio": "0.1"},
        ]
        out = _normalize_bigcap_rows(rows, 500)
        codes = [s["code"] for s in out["stocks"]]
        assert codes == ["601398", "000001"]
        # 300806880 万元 = 30080.69 亿元
        assert out["stocks"][0]["market_cap_yi"] == 30080.69
        assert out["stocks"][0]["float_cap_yi"] == 22755.27

    def test_missing_market_cap_not_dropped(self):
        rows = [{"code": "000004", "name": "某票", "mktcap": "-", "nmc": "", "trade": "3.2"}]
        out = _normalize_bigcap_rows(rows, 500)
        assert out["stocks"] == []
        assert out["unpriced"] == [
            {"code": "000004", "name": "某票", "reason": "mktcap_missing"}
        ]

    def test_suspended_kept_with_reason(self):
        rows = [{"code": "600000", "name": "浦发银行", "mktcap": "10000000", "nmc": "9000000",
                 "trade": "0", "changepercent": "0", "amount": "0", "turnoverratio": "0"}]
        out = _normalize_bigcap_rows(rows, 500)
        stock = out["stocks"][0]
        assert stock["suspended"] is True
        assert stock["reason"] == "suspended"
        assert stock["price"] is None

    def test_sorted_by_market_cap_desc(self):
        rows = [
            {"code": "A", "name": "小", "mktcap": "6000000", "trade": "1"},
            {"code": "B", "name": "大", "mktcap": "90000000", "trade": "1"},
        ]
        out = _normalize_bigcap_rows(rows, 500)
        assert [s["code"] for s in out["stocks"]] == ["B", "A"]


# ---------------------------------------------------------------- service


class _FakeRouter:
    def __init__(self, payload, source="sina_bigcaps", error=None):
        self.payload = payload
        self.source = source
        self.error = error
        self.calls: list[tuple[str, dict]] = []

    def route(self, data_type, **kwargs):
        self.calls.append((data_type, kwargs))
        if self.error:
            raise self.error
        return self.payload, self.source


def _payload(source="sina_bigcaps", stocks=None):
    return {
        "as_of": "2026-11-06 15:00:00",
        "source": source,
        "threshold_yi": 500,
        "count": 2,
        "stocks": stocks or [
            {"code": "601398", "name": "工商银行", "market_cap_yi": 30080.69},
            {"code": "600519", "name": "贵州茅台", "market_cap_yi": 18400.0},
        ],
        "unpriced": [{"code": "000004", "name": "某票", "reason": "mktcap_missing"}],
        "source_note": "测试口径",
    }


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.invalidate(cache_key("shortline.bigcaps", threshold=500.0))
    cache.invalidate(cache_key("shortline.bigcaps", threshold=300.0))
    yield


class TestBigcapsService:
    def test_cache_hit_avoids_second_call(self, monkeypatch):
        fake = _FakeRouter(_payload())
        monkeypatch.setattr(bigcaps_service, "_router", fake)

        first = bigcaps_service.get_bigcaps()
        second = bigcaps_service.get_bigcaps()

        assert len(fake.calls) == 1
        assert fake.calls[0][0] == "bigcaps"
        assert first["cache_hit"] is False
        assert second["cache_hit"] is True
        assert second["count"] == 2
        assert second["as_of"] == "2026-11-06 15:00:00"

    def test_source_annotation_and_compliance(self, monkeypatch):
        fake = _FakeRouter(_payload(source="akshare_em"), source="akshare_em")
        monkeypatch.setattr(bigcaps_service, "_router", fake)
        result = bigcaps_service.get_bigcaps()
        assert result["source"] == "akshare_em"
        assert result["source_route"] == "akshare_em"
        assert result["compliance"] == "cn-public"
        assert result["unpriced"][0]["reason"] == "mktcap_missing"

    def test_limit_only_truncates_stocks(self, monkeypatch):
        fake = _FakeRouter(_payload())
        monkeypatch.setattr(bigcaps_service, "_router", fake)
        result = bigcaps_service.get_bigcaps(limit=1)
        assert result["count"] == 2
        assert result["returned"] == 1
        assert len(result["stocks"]) == 1

    def test_threshold_param_passed_through(self, monkeypatch):
        fake = _FakeRouter(_payload())
        monkeypatch.setattr(bigcaps_service, "_router", fake)
        bigcaps_service.get_bigcaps(min_mktcap_yi=300)
        assert fake.calls[0][1]["min_mktcap_yi"] == 300.0

    def test_bad_payload_raises(self, monkeypatch):
        fake = _FakeRouter({"unexpected": True})
        monkeypatch.setattr(bigcaps_service, "_router", fake)
        with pytest.raises(RuntimeError):
            bigcaps_service.get_bigcaps()

    def test_source_error_propagates(self, monkeypatch):
        fake = _FakeRouter(None, error=RuntimeError("sina down"))
        monkeypatch.setattr(bigcaps_service, "_router", fake)
        with pytest.raises(RuntimeError, match="sina down"):
            bigcaps_service.get_bigcaps()


# ---------------------------------------------------------------- 双通道


class TestBigcapsChannels:
    def test_mcp_tool_returns_json(self, monkeypatch):
        from mcp.server.fastmcp import FastMCP
        from tradex.tools.shortline import register

        fake = _FakeRouter(_payload())
        monkeypatch.setattr(bigcaps_service, "_router", fake)

        mcp = FastMCP("test_bigcaps")
        register(mcp)
        fn = mcp._tool_manager._tools["get_shortline_bigcaps"].fn
        data = json.loads(asyncio.run(fn(min_mktcap_yi=500, limit=0)))
        assert data["count"] == 2
        assert data["source"] == "sina_bigcaps"
        assert data["cache"]["ttl_seconds"] == 3600

    def test_rest_route_returns_envelope(self, monkeypatch):
        fake = _FakeRouter(_payload())
        monkeypatch.setattr(bigcaps_service, "_router", fake)

        app = FastAPI()
        app.include_router(rest_routes.router, prefix="/api/v1")
        client = TestClient(app)
        resp = client.get("/api/v1/shortline/bigcaps?min_mktcap_yi=500&limit=0")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["count"] == 2

    def test_rest_route_maps_source_error_to_502(self, monkeypatch):
        fake = _FakeRouter(None, error=RuntimeError("all sources down"))
        monkeypatch.setattr(bigcaps_service, "_router", fake)

        app = FastAPI()
        app.include_router(rest_routes.router, prefix="/api/v1")
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/shortline/bigcaps")
        assert resp.status_code == 502

    def test_metadata_and_compute_ref(self):
        endpoint = SHORTLINE_ENDPOINTS["shortline.bigcaps"]
        assert endpoint.status == "implemented"
        assert endpoint.cache_policy == "hourly"
        assert "shortline.bigcaps" not in missing_compute_refs()
        assert missing_compute_refs() == []
