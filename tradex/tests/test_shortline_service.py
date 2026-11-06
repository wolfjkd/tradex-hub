"""工单 H2 测试（二）：读数 service / 缓存策略 / 双通道。

覆盖：
- 正常读数：partial=False，closed_long 允许长期缓存
- 辅助池缺数：partial=True，长期缓存被拒（不冻坏数据）
- live：永远 partial，但允许 15 秒缓存
- zt 失败：向上抛（REST 502）
- cycle：历史未积累时标 missing_reason
- 8 个工具注册 + REST 路由
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tradex.api import routes as rest_routes
from tradex.service import shortline_service
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
_DATE = "20261105"


class _FakeRouter:
    def __init__(self, fail: tuple[str, ...] = (), error: Exception | None = None):
        self.fail = set(fail)
        self.error = error
        self.calls: list[str] = []

    def route(self, data_type, **kwargs):
        assert data_type == "limit_up_board", f"unexpected {data_type}"
        board_type = kwargs.get("board_type")
        self.calls.append(board_type)
        if board_type in self.fail:
            raise self.error or RuntimeError(f"{board_type} 源失败")
        return {
            "board_type": board_type,
            "date": _DATE,
            "count": len(_ROWS[board_type]),
            "data": _ROWS[board_type],
            "fields": _FIELDS[board_type],
        }, "akshare_em"


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    """隔离落库目录：避免真实的 data/shortline 影响 cycle 的「无历史」断言。"""
    monkeypatch.setenv("SHORTLINE_DATA_DIR", str(tmp_path / "shortline"))
    yield


@pytest.fixture(autouse=True)
def _clean_cache():
    today = shortline_service.datetime.now().strftime("%Y%m%d")
    for endpoint in (
        "shortline.emotion", "shortline.daily", "shortline.settled",
        "shortline.live", "shortline.ladder", "shortline.board_ladder",
        "shortline.structure", "shortline.cycle",
    ):
        for date_key in (_DATE, today):
            cache.invalidate(cache_key(endpoint, date=date_key))
    cache.invalidate(cache_key("shortline.cycle", date=_DATE, days=5))
    cache.invalidate(cache_key("shortline.cycle", date=shortline_service.datetime.now().strftime("%Y%m%d"), days=5))
    yield


class TestServe:
    def test_daily_success_and_cache(self, monkeypatch):
        fake = _FakeRouter()
        monkeypatch.setattr(shortline_service, "_router", fake)

        first = shortline_service.get_daily(date=_DATE)
        second = shortline_service.get_daily(date=_DATE)

        assert first["partial"] is False
        assert first["cache"]["ttl_seconds"] == 7 * 86400
        assert first["result"]["limit_up_count"] == 3
        assert first["result"]["break_rate"] == 25.0  # 1 / (3+1)
        assert first["text"]
        assert first["computation"]["definitions"]
        assert second["cache_hit"] is True
        assert second["cache"]["ttl_seconds"] == 7 * 86400
        # zt + zb + prev_zt = 3 次取数，第二次全缓存
        assert fake.calls == ["zt", "zb", "prev_zt"]

    def test_missing_pool_blocks_long_cache(self, monkeypatch):
        fake = _FakeRouter(fail=("zb",))
        monkeypatch.setattr(shortline_service, "_router", fake)

        result = shortline_service.get_daily(date=_DATE)
        assert result["partial"] is True
        assert result["cache"]["ttl_seconds"] is None
        assert "zb" in result["missing_reason"]
        assert result["result"]["break_rate"] is None

    def test_live_partial_but_cached_15s(self, monkeypatch):
        fake = _FakeRouter()
        monkeypatch.setattr(shortline_service, "_router", fake)
        result = shortline_service.get_live()
        assert result["partial"] is True
        assert result["cache"]["ttl_seconds"] == 15
        assert result["result"]["seal_rate"] == 75.0  # 3 / (3+1)
        assert result["result"]["limit_down"] == 1

    def test_zt_failure_raises(self, monkeypatch):
        fake = _FakeRouter(fail=("zt",), error=RuntimeError("涨停池源挂了"))
        monkeypatch.setattr(shortline_service, "_router", fake)
        with pytest.raises(RuntimeError, match="涨停池源挂了"):
            shortline_service.get_daily(date=_DATE)

    def test_structure_exposes_upstream_fields(self, monkeypatch):
        fake = _FakeRouter()
        monkeypatch.setattr(shortline_service, "_router", fake)
        result = shortline_service.get_structure(date=_DATE)
        assert result["result"]["upstream_fields"]["zt"] == _FIELDS["zt"]
        assert result["result"]["boards"]["主板"]["count"] == 2

    def test_emotion_ladder_board_ladder_settled(self, monkeypatch):
        fake = _FakeRouter()
        monkeypatch.setattr(shortline_service, "_router", fake)
        for fn in (
            shortline_service.get_emotion,
            shortline_service.get_ladder,
            shortline_service.get_board_ladder,
            shortline_service.get_settled,
        ):
            result = fn(date=_DATE)
            assert result["endpoint"]
            assert "result" in result and "text" in result and "computation" in result

    def test_cycle_without_store_marks_missing(self, monkeypatch):
        fake = _FakeRouter()
        monkeypatch.setattr(shortline_service, "_router", fake)
        result = shortline_service.get_cycle(days=5, date=_DATE)
        assert result["partial"] is True
        assert result["result"]["missing_reason"]
        # H3 之前历史库不存在：必须明确写「历史未积累/不可读」，不能当 0
        assert result["missing_reason"]


class TestChannels:
    def test_eight_tools_registered(self):
        from mcp.server.fastmcp import FastMCP
        from tradex.tools.shortline import register

        mcp = FastMCP("test_shortline_tools")
        register(mcp)
        names = set(mcp._tool_manager._tools)
        expected = {
            "get_shortline_emotion", "get_shortline_cycle", "get_shortline_daily",
            "get_shortline_settled", "get_shortline_live", "get_shortline_ladder",
            "get_shortline_board_ladder", "get_shortline_structure",
        }
        assert expected <= names

    def test_daily_tool_returns_json(self, monkeypatch):
        from mcp.server.fastmcp import FastMCP
        from tradex.tools.shortline import register

        fake = _FakeRouter()
        monkeypatch.setattr(shortline_service, "_router", fake)
        mcp = FastMCP("test_shortline_tools2")
        register(mcp)
        fn = mcp._tool_manager._tools["get_shortline_daily"].fn
        data = json.loads(asyncio.run(fn(date=_DATE)))
        assert data["result"]["limit_up_count"] == 3
        assert data["partial"] is False

    def test_rest_daily_and_emotion(self, monkeypatch):
        fake = _FakeRouter()
        monkeypatch.setattr(shortline_service, "_router", fake)
        app = FastAPI()
        app.include_router(rest_routes.router, prefix="/api/v1")
        client = TestClient(app)
        for path in ("daily", "emotion", "settled", "ladder", "board-ladder", "structure"):
            resp = client.get(f"/api/v1/shortline/{path}?date={_DATE}")
            assert resp.status_code == 200, path
            assert resp.json()["code"] == 0

    def test_rest_live(self, monkeypatch):
        fake = _FakeRouter()
        monkeypatch.setattr(shortline_service, "_router", fake)
        app = FastAPI()
        app.include_router(rest_routes.router, prefix="/api/v1")
        resp = TestClient(app).get("/api/v1/shortline/live")
        assert resp.status_code == 200

    def test_rest_zt_failure_502(self, monkeypatch):
        fake = _FakeRouter(fail=("zt",), error=RuntimeError("源挂了"))
        monkeypatch.setattr(shortline_service, "_router", fake)
        app = FastAPI()
        app.include_router(rest_routes.router, prefix="/api/v1")
        resp = TestClient(app, raise_server_exceptions=False).get(
            f"/api/v1/shortline/daily?date={_DATE}"
        )
        assert resp.status_code == 502
