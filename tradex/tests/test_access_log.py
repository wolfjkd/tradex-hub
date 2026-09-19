"""工单 19 测试 —— 结构化访问日志（文件 + SQLite 双写）。"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tradex.api.schemas import ERR_OK


@pytest.fixture
def isolated_app(monkeypatch):
    """每个测试用独立临时目录 + 独立 SQLite 文件。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        from tradex.service import write_service
        from tradex.middleware import access_log

        db_path = tmp_path / "written.db"
        monkeypatch.setattr(write_service, "_DATA_DIR", tmp_path)
        monkeypatch.setattr(write_service, "_WRITTEN_DIR", tmp_path / "written")
        monkeypatch.setattr(write_service, "_STRATEGY_DIR", tmp_path / "written" / "strategies")
        monkeypatch.setattr(write_service, "_WATCHLIST_FILE", tmp_path / "written" / "watchlist.json")
        monkeypatch.setattr(write_service, "_DB_PATH", db_path)
        monkeypatch.setattr(write_service, "_bootstrap_done", False)
        monkeypatch.setattr(access_log, "_LOGS_DIR", tmp_path / "logs")
        # 重置 access_log schema 标志（每个测试独立数据库）
        monkeypatch.setattr(access_log, "_schema_done", False)
        # 重定向 _HUB_ROOT 也指向 tmp（避免污染真实 logs）
        monkeypatch.setattr(access_log, "_HUB_ROOT", tmp_path)

        # 构建最小 app 挂载中间件
        app = FastAPI()
        from tradex.middleware.access_log import AccessLogMiddleware
        app.add_middleware(AccessLogMiddleware)
        from tradex.api.routes import access_log as access_log_routes
        app.include_router(access_log_routes.router, prefix="/api/v1")
        from tradex.api.schemas import Envelope, envelope_ok

        @app.get("/api/v1/test/ping", response_model=Envelope[dict])
        def ping():
            return envelope_ok({"pong": True})

        yield app, tmp_path


class TestAccessLogMiddleware:
    def test_api_request_logged_to_sqlite(self, isolated_app):
        """调 /api/v1/* 后 SQLite access_log 表应有对应记录。"""
        app, _ = isolated_app
        client = TestClient(app)
        client.get("/api/v1/test/ping")
        # 查询日志端点验证
        r = client.get("/api/v1/access-log?limit=5")
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == ERR_OK
        # 至少有刚才的 ping 记录
        items = body["data"]
        assert any(item["path"] == "/api/v1/test/ping" for item in items)

    def test_non_api_request_not_logged(self, isolated_app):
        """非 /api/v1/* 请求（如 /health）不应被记录。"""
        app, _ = isolated_app
        client = TestClient(app)
        # /health 在测试 app 里没挂载，会返 404 但中间件不应记录
        client.get("/health")
        # 查日志
        r = client.get("/api/v1/access-log?limit=50")
        items = r.json()["data"]
        # 不应有 /health 的记录
        assert all(item["path"] != "/health" for item in items)

    def test_log_record_contains_all_fields(self, isolated_app):
        """记录应包含 spec 要求的全部字段。"""
        app, _ = isolated_app
        client = TestClient(app)
        client.get("/api/v1/test/ping")
        r = client.get("/api/v1/access-log?limit=1")
        items = r.json()["data"]
        assert len(items) >= 1
        record = items[0]
        # 工单 19 spec 要求的字段
        expected_keys = {"timestamp", "method", "path", "status", "duration_ms"}
        assert expected_keys.issubset(set(record.keys()))

    def test_access_log_filter_by_path(self, isolated_app):
        """path 参数过滤生效。"""
        app, _ = isolated_app
        client = TestClient(app)
        client.get("/api/v1/test/ping")
        # 故意取一个不存在的路径前缀
        r = client.get("/api/v1/access-log?path=/api/v1/nonexistent")
        items = r.json()["data"]
        assert all(item["path"].startswith("/api/v1/nonexistent") for item in items)
        assert len(items) == 0

    def test_access_log_limit_validation(self, isolated_app):
        """limit 参数校验：ge=1, le=500。"""
        app, _ = isolated_app
        client = TestClient(app)
        # 0 应被拒
        assert client.get("/api/v1/access-log?limit=0").status_code == 422
        # 501 应被拒
        assert client.get("/api/v1/access-log?limit=501").status_code == 422


class TestAccessLogFileLog:
    def test_json_lines_file_written(self, isolated_app):
        """访问日志应写入 JSON Lines 文件。"""
        app, tmp_path = isolated_app
        client = TestClient(app)
        client.get("/api/v1/test/ping")
        # 找今天的日志文件
        from tradex.middleware.access_log import _today_log_file
        log_file = _today_log_file()
        assert log_file.exists()
        content = log_file.read_text(encoding="utf-8")
        # 应包含至少一条 JSON Lines 记录
        lines = [ln for ln in content.splitlines() if ln.strip()]
        assert len(lines) >= 1
        record = json.loads(lines[-1])
        assert record["method"] == "GET"
        assert "/api/v1" in record["path"]


class TestSQLiteSchema:
    def test_access_log_table_created(self, isolated_app):
        """首次写入后 access_log 表应存在。"""
        app, tmp_path = isolated_app
        client = TestClient(app)
        client.get("/api/v1/test/ping")
        # 直接连 SQLite 检查
        from tradex.service.write_service import _get_db_path
        conn = sqlite3.connect(str(_get_db_path()))
        try:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='access_log'"
            ).fetchall()
            assert len(tables) == 1
            # 索引也应存在
            indexes = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND name IN ('idx_access_timestamp', 'idx_access_path')"
            ).fetchall()
            assert len(indexes) == 2
        finally:
            conn.close()
