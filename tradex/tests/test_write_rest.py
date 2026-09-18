"""工单 10 测试 —— 写操作（本地文件存储 CRUD）。

策略：在临时目录跑全流程测试，避免污染真实 data/written/。
所有 CRUD 用 service 层直调 + REST 端点 TestClient 双轨验证。
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tradex.api.schemas import ERR_OK, ERR_BAD_REQUEST, ERR_NOT_FOUND


@pytest.fixture(autouse=True)
def isolated_data_dir(monkeypatch):
    """每个测试用独立临时目录，避免污染真实数据。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        from tradex.service import write_service
        # 替换路径常量
        monkeypatch.setattr(write_service, "_DATA_DIR", tmp_path)
        monkeypatch.setattr(
            write_service, "_STRATEGY_DIR", tmp_path / "strategies"
        )
        monkeypatch.setattr(
            write_service, "_WATCHLIST_FILE", tmp_path / "watchlist.json"
        )
        yield tmp_path


def _build_min_app() -> FastAPI:
    """构建最小测试 app，仅挂 write 路由 + 异常处理中间件。"""
    from tradex.api.routes import write as write_routes
    from tradex.api.schemas import (
        ERR_BAD_REQUEST, ERR_NOT_FOUND, ERR_INTERNAL, envelope_err,
    )

    app = FastAPI()
    app.include_router(write_routes.router, prefix="/api/v1")

    from fastapi import HTTPException, Request
    from fastapi.responses import JSONResponse
    from fastapi.exceptions import RequestValidationError

    @app.exception_handler(RequestValidationError)
    async def ve_handler(request: Request, exc: RequestValidationError):
        import json as _json
        try:
            detail = _json.dumps(exc.errors(), ensure_ascii=False)
        except Exception:
            detail = str(exc)
        return JSONResponse(
            status_code=400,
            content=envelope_err(ERR_BAD_REQUEST, detail).model_dump(),
        )

    @app.exception_handler(HTTPException)
    async def he_handler(request: Request, exc: HTTPException):
        code_map = {
            400: ERR_BAD_REQUEST,
            404: ERR_NOT_FOUND,
            500: ERR_INTERNAL,
            502: 50001,
            422: ERR_BAD_REQUEST,
        }
        code = code_map.get(exc.status_code, ERR_INTERNAL)
        return JSONResponse(
            status_code=exc.status_code,
            content=envelope_err(code, str(exc.detail)).model_dump(),
        )

    return app


# ────────────────────── 策略 service 层 ──────────────────────────

class TestStrategyService:
    def test_create_strategy(self, isolated_data_dir):
        from tradex.service import write_service
        result = write_service.create_strategy(name="双均线", content="MA5 上穿 MA20 买入")
        assert "id" in result
        assert result["name"] == "双均线"
        # 文件已落盘
        assert (isolated_data_dir / "strategies" / f"{result['id']}.json").exists()

    def test_list_strategies_empty(self, isolated_data_dir):
        from tradex.service import write_service
        result = write_service.list_strategies()
        assert result["count"] == 0

    def test_list_strategies_after_create(self, isolated_data_dir):
        from tradex.service import write_service
        write_service.create_strategy(name="策略A", content="A")
        write_service.create_strategy(name="策略B", content="B", tags=["momentum"])
        result = write_service.list_strategies()
        assert result["count"] == 2
        names = [s["name"] for s in result["strategies"]]
        assert "策略A" in names and "策略B" in names

    def test_get_strategy(self, isolated_data_dir):
        from tradex.service import write_service
        created = write_service.create_strategy(name="X", content="正文")
        fetched = write_service.get_strategy(created["id"])
        assert fetched is not None
        assert fetched["content"] == "正文"

    def test_get_strategy_not_found(self, isolated_data_dir):
        from tradex.service import write_service
        assert write_service.get_strategy("nonexistent") is None

    def test_delete_strategy(self, isolated_data_dir):
        from tradex.service import write_service
        created = write_service.create_strategy(name="临时", content="待删")
        assert write_service.delete_strategy(created["id"]) is True
        # 二次删应返回 False（已不存在）
        assert write_service.delete_strategy(created["id"]) is False

    def test_strategy_tags_persisted(self, isolated_data_dir):
        from tradex.service import write_service
        created = write_service.create_strategy(
            name="带标签", content="X", tags=["momentum", "intraday"]
        )
        fetched = write_service.get_strategy(created["id"])
        assert fetched["tags"] == ["momentum", "intraday"]


# ────────────────────── 自选股 service 层 ──────────────────────────

class TestWatchlistService:
    def test_add_and_list(self, isolated_data_dir):
        from tradex.service import write_service
        write_service.add_to_watchlist("600519", "茅台")
        write_service.add_to_watchlist("000001", "平安")
        result = write_service.list_watchlist()
        assert result["count"] == 2

    def test_add_duplicate_updates_note(self, isolated_data_dir):
        from tradex.service import write_service
        write_service.add_to_watchlist("600519", "原备注")
        result = write_service.add_to_watchlist("600519", "新备注")
        assert result["action"] == "updated"
        assert result["total"] == 1  # 不重复
        items = write_service.list_watchlist()["watchlist"]
        assert items[0]["note"] == "新备注"

    def test_remove(self, isolated_data_dir):
        from tradex.service import write_service
        write_service.add_to_watchlist("600519", "X")
        result = write_service.remove_from_watchlist("600519")
        assert result["action"] == "removed"
        assert result["total"] == 0

    def test_remove_not_found(self, isolated_data_dir):
        from tradex.service import write_service
        result = write_service.remove_from_watchlist("999999")
        assert result["action"] == "not_found"

    def test_atomic_write_integrity(self, isolated_data_dir):
        """多次写应保持文件是合法 JSON。"""
        from tradex.service import write_service
        for i in range(5):
            write_service.add_to_watchlist(f"60051{i}", f"note{i}")
        # 直接读文件应可解析
        with open(isolated_data_dir / "watchlist.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, list)
        assert len(data) == 5


# ────────────────────── REST 端点集成 ──────────────────────────

class TestWriteRestEndpoints:
    def setup_method(self):
        # 确保每个测试方法都用临时目录（fixture 会注入 monkeypatch）
        pass

    def test_strategy_create_and_list(self, isolated_data_dir):
        app = _build_min_app()
        client = TestClient(app)
        # POST 创建
        r = client.post("/api/v1/write/strategy", json={
            "name": "REST测试策略", "content": "测试内容", "tags": ["test"]
        })
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == ERR_OK
        sid = body["data"]["id"]
        # GET list
        r2 = client.get("/api/v1/write/strategy/list")
        body2 = r2.json()
        assert body2["code"] == ERR_OK
        assert body2["data"]["count"] >= 1
        # GET by id
        r3 = client.get(f"/api/v1/write/strategy/{sid}")
        body3 = r3.json()
        assert body3["code"] == ERR_OK
        assert body3["data"]["content"] == "测试内容"

    def test_strategy_get_not_found(self, isolated_data_dir):
        app = _build_min_app()
        client = TestClient(app)
        r = client.get("/api/v1/write/strategy/nonexistent")
        body = r.json()
        assert body["code"] == ERR_NOT_FOUND

    def test_strategy_delete(self, isolated_data_dir):
        app = _build_min_app()
        client = TestClient(app)
        # 先创建
        r = client.post("/api/v1/write/strategy", json={"name": "X", "content": "Y"})
        sid = r.json()["data"]["id"]
        # 删除
        r2 = client.delete(f"/api/v1/write/strategy/{sid}")
        assert r2.json()["code"] == ERR_OK
        # 二次删除应 404
        r3 = client.delete(f"/api/v1/write/strategy/{sid}")
        assert r3.json()["code"] == ERR_NOT_FOUND

    def test_strategy_create_missing_name_returns_400(self, isolated_data_dir):
        """Pydantic 校验缺字段 → 422 → 40001。"""
        app = _build_min_app()
        client = TestClient(app)
        r = client.post("/api/v1/write/strategy", json={"content": "缺 name"})
        body = r.json()
        assert body["code"] == ERR_BAD_REQUEST

    def test_watchlist_add_list_remove(self, isolated_data_dir):
        app = _build_min_app()
        client = TestClient(app)
        # 添加
        r = client.post("/api/v1/write/watchlist", json={"symbol": "600519", "note": "茅台"})
        assert r.json()["code"] == ERR_OK
        assert r.json()["data"]["action"] == "added"
        # 列表
        r2 = client.get("/api/v1/write/watchlist/list")
        assert r2.json()["data"]["count"] == 1
        # 移除
        r3 = client.delete("/api/v1/write/watchlist/600519")
        assert r3.json()["code"] == ERR_OK
        # 再列应为空
        r4 = client.get("/api/v1/write/watchlist/list")
        assert r4.json()["data"]["count"] == 0

    def test_watchlist_non_digit_symbol_returns_400(self, isolated_data_dir):
        app = _build_min_app()
        client = TestClient(app)
        r = client.post("/api/v1/write/watchlist", json={"symbol": "ABCDEF"})
        body = r.json()
        assert body["code"] == ERR_BAD_REQUEST

    def test_watchlist_remove_not_found(self, isolated_data_dir):
        app = _build_min_app()
        client = TestClient(app)
        r = client.delete("/api/v1/write/watchlist/999999")
        assert r.json()["code"] == ERR_NOT_FOUND


# ────────────────────── 路由聚合验证 ──────────────────────────

class TestWriteRouterAggregation:
    def test_write_router_has_seven_endpoints(self):
        from tradex.api.routes import write as write_routes
        paths = {(route.path, tuple(sorted(route.methods))) for route in write_routes.router.routes}
        expected = {
            ("/write/strategy", ("POST",)),
            ("/write/strategy/list", ("GET",)),
            ("/write/strategy/{sid}", ("GET",)),
            ("/write/strategy/{sid}", ("DELETE",)),
            ("/write/watchlist", ("POST",)),
            ("/write/watchlist/list", ("GET",)),
            ("/write/watchlist/{symbol}", ("DELETE",)),
        }
        assert expected.issubset(paths)
