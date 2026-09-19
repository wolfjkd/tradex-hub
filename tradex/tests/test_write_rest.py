"""工单 10 测试 —— 写操作 CRUD（阶段一 JSON 后端 → 阶段二 SQLite 后端兼容验证）。

阶段二（工单 17-18）后端切到 SQLite，对外契约不变，本测试同步更新：
- monkeypatch 同时覆盖 `_DATA_DIR` 与 `_DB_PATH`，保证隔离
- 文件存在性断言改为 SQLite 数据库存在性断言
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tradex.api.schemas import ERR_OK, ERR_BAD_REQUEST, ERR_NOT_FOUND


@pytest.fixture(autouse=True)
def isolated_data_dir(monkeypatch):
    """每个测试用独立临时目录 + 独立 SQLite 文件，避免污染真实数据。

    yield 后强制关闭残留连接 + 清理 WAL/SHM 文件，避免 Windows 文件锁阻碍清理。
    """
    import gc
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        from tradex.service import write_service
        db_path = tmp_path / "written.db"
        # 替换所有路径常量（_DB_PATH 是关键，SQLite 后端用它定位数据库）
        monkeypatch.setattr(write_service, "_DATA_DIR", tmp_path)
        monkeypatch.setattr(write_service, "_WRITTEN_DIR", tmp_path / "written")
        monkeypatch.setattr(
            write_service, "_STRATEGY_DIR", tmp_path / "written" / "strategies"
        )
        monkeypatch.setattr(
            write_service, "_WATCHLIST_FILE", tmp_path / "written" / "watchlist.json"
        )
        monkeypatch.setattr(write_service, "_DB_PATH", db_path)
        # 重置 bootstrap 标志，确保下一次调用会用新路径重新初始化
        monkeypatch.setattr(write_service, "_bootstrap_done", False)
        yield tmp_path
        # 清理：强制 GC 释放 sqlite 连接（否则 WAL 锁住）
        gc.collect()
        # 试图清理 WAL/SHM 文件（允许失败，TemporaryDirectory 会再尝试）
        for suffix in ("-wal", "-shm"):
            try:
                (db_path.with_name(db_path.name + suffix)).unlink(missing_ok=True)
            except OSError:
                pass


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
        # SQLite 数据库已落盘
        assert (isolated_data_dir / "written.db").exists()

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
        """多次写应保持 SQLite 数据完整性。"""
        from tradex.service import write_service
        for i in range(5):
            write_service.add_to_watchlist(f"60051{i}", f"note{i}")
        # 直接查 SQLite 应可读取全部 5 条
        result = write_service.list_watchlist()
        assert result["count"] == 5


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


# ────────────────────── 工单 17：SQLite schema + 迁移 ──────────────────────────

class TestSQLiteSchema:
    """验证 SQLite schema 创建。"""

    def test_init_schema_creates_tables(self, isolated_data_dir):
        from tradex.service import write_service
        write_service.init_schema()
        conn = write_service._connect()
        try:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            names = {row["name"] for row in tables}
            assert "strategies" in names
            assert "watchlist" in names
        finally:
            conn.close()

    def test_init_schema_is_idempotent(self, isolated_data_dir):
        """多次调用 init_schema 不应报错。"""
        from tradex.service import write_service
        write_service.init_schema()
        write_service.init_schema()
        write_service.init_schema()

    def test_index_created(self, isolated_data_dir):
        """idx_strategies_created 索引应创建。"""
        from tradex.service import write_service
        write_service.init_schema()
        conn = write_service._connect()
        try:
            indexes = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
            names = {row["name"] for row in indexes}
            assert "idx_strategies_created" in names
        finally:
            conn.close()

    def test_wal_mode_enabled(self, isolated_data_dir):
        """init_schema 后数据库应启用 WAL 模式（持久属性）。"""
        from tradex.service import write_service
        write_service.init_schema()
        conn = write_service._connect()
        try:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert mode.lower() == "wal"
        finally:
            conn.close()


class TestMigrationFromJson:
    """验证阶段一 JSON 文件迁移到 SQLite。"""

    def test_migrate_strategies(self, isolated_data_dir):
        """造 JSON 策略文件 → 触发迁移 → SQLite 有数据 + 原文件改名。"""
        from tradex.service import write_service
        # 造一个 JSON 策略文件
        strategy_dir = isolated_data_dir / "written" / "strategies"
        strategy_dir.mkdir(parents=True, exist_ok=True)
        strategy_file = strategy_dir / "1234567890.json"
        strategy_file.write_text(json.dumps({
            "id": "1234567890",
            "name": "迁移测试策略",
            "content": "测试内容",
            "tags": ["test"],
            "created_at": 1234567890.0,
        }), encoding="utf-8")

        # 触发迁移
        result = write_service.migrate_from_json()

        assert result["strategies_migrated"] == 1
        # SQLite 有数据
        with write_service._connect() as conn:
            row = conn.execute(
                "SELECT * FROM strategies WHERE id = '1234567890'"
            ).fetchone()
            assert row is not None
            assert row["name"] == "迁移测试策略"
        # 原文件改名为 .migrated
        assert not strategy_file.exists()
        assert strategy_file.with_suffix(".json.migrated").exists()

    def test_migrate_watchlist(self, isolated_data_dir):
        """造 watchlist.json → 触发迁移 → SQLite 有数据。"""
        from tradex.service import write_service
        written_dir = isolated_data_dir / "written"
        written_dir.mkdir(parents=True, exist_ok=True)
        wl_file = written_dir / "watchlist.json"
        wl_file.write_text(json.dumps([
            {"symbol": "600519", "note": "茅台", "added_at": 1234567890.0},
            {"symbol": "000001", "note": "平安", "added_at": 1234567891.0},
        ]), encoding="utf-8")

        result = write_service.migrate_from_json()
        assert result["watchlist_migrated"] == 2

        # SQLite 有数据
        result = write_service.list_watchlist()
        assert result["count"] == 2

        # 原文件改名
        assert not wl_file.exists()
        assert wl_file.with_suffix(".json.migrated").exists()

    def test_migration_is_idempotent(self, isolated_data_dir):
        """重复迁移不应导致重复数据。"""
        from tradex.service import write_service
        strategy_dir = isolated_data_dir / "written" / "strategies"
        strategy_dir.mkdir(parents=True, exist_ok=True)
        strategy_file = strategy_dir / "9999999999.json"
        strategy_file.write_text(json.dumps({
            "id": "9999999999",
            "name": "幂等测试",
            "content": "X",
            "created_at": 9999999999.0,
        }), encoding="utf-8")

        write_service.migrate_from_json()
        # 恢复 .migrated 为 .json 再迁移一次
        migrated = strategy_file.with_suffix(".json.migrated")
        migrated.rename(strategy_file)
        write_service.migrate_from_json()
        # SQLite 不应有重复
        with write_service._connect() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM strategies WHERE id = '9999999999'"
            ).fetchone()[0]
            assert count == 1


# ────────────────────── 工单 18：并发写测试 ──────────────────────────

class TestConcurrentWrites:
    """验证 SQLite WAL + BEGIN IMMEDIATE 在多线程并发写下的安全性。"""

    def test_concurrent_strategy_creation(self, isolated_data_dir):
        """10 个线程并发创建策略，应全部成功且无锁错误。"""
        import concurrent.futures
        from tradex.service import write_service

        def _create(idx):
            return write_service.create_strategy(
                name=f"并发策略{idx}", content=f"内容{idx}"
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(_create, i) for i in range(10)]
            results = [f.result() for f in futures]

        # 应得到 10 个不同的 id
        ids = [r["id"] for r in results]
        assert len(set(ids)) == 10
        # SQLite 应有 10 条记录
        result = write_service.list_strategies()
        assert result["count"] == 10

    def test_concurrent_watchlist_writes(self, isolated_data_dir):
        """10 个线程并发添加不同 symbol，应全部成功。"""
        import concurrent.futures
        from tradex.service import write_service

        def _add(idx):
            return write_service.add_to_watchlist(f"60051{idx}", f"note{idx}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(_add, i) for i in range(10)]
            results = [f.result() for f in futures]

        result = write_service.list_watchlist()
        assert result["count"] == 10

    def test_concurrent_writes_to_same_symbol(self, isolated_data_dir):
        """多线程并发写同一 symbol，最终应只 1 条且无重复。"""
        import concurrent.futures
        from tradex.service import write_service

        def _update():
            return write_service.add_to_watchlist("600519", "并发更新")

        # 并发 5 次同 symbol 的 UPSERT
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(_update) for _ in range(5)]
            [f.result() for f in futures]

        # 最终应只 1 条
        result = write_service.list_watchlist()
        assert result["count"] == 1
        assert result["watchlist"][0]["symbol"] == "600519"

    def test_sequential_writes_100_strategies(self, isolated_data_dir):
        """连续写 100 个策略无错误（spec 验收要求）。"""
        from tradex.service import write_service
        for i in range(100):
            write_service.create_strategy(name=f"批量{i}", content=f"c{i}")
        result = write_service.list_strategies()
        assert result["count"] == 100

    def test_database_integrity_after_stress(self, isolated_data_dir):
        """压力测试后数据库完整性检查应通过。"""
        import concurrent.futures
        from tradex.service import write_service

        # 并发混合操作
        def _mixed(idx):
            if idx % 2 == 0:
                return write_service.create_strategy(name=f"s{idx}", content=f"c{idx}")
            else:
                return write_service.add_to_watchlist(f"60051{idx % 9}", f"n{idx}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(_mixed, i) for i in range(50)]
            [f.result() for f in futures]

        # integrity_check 应返回 1（OK）
        with write_service._connect() as conn:
            result = conn.execute("PRAGMA integrity_check").fetchone()[0]
            assert result == "ok"
