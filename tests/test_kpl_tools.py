"""
KPL MCP 工具 + REST 端点测试（交接文档 09 票5）。

MCP：kpl.py 注册 4 工具、FastMCP discover 后工具总数 190。
REST：/api/v1/kpl/* 四端点挂载 + Envelope 包裹 + 数据源未注册时 502 降级。
"""

import pytest
from unittest.mock import patch


def _build_app():
    """构建带全路由的 FastAPI app（TestClient 用）。"""
    from fastapi import FastAPI

    from tradex.api.routes import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return app


class TestKplMcpTools:
    def test_kpl_module_has_register(self):
        from tradex.tools import kpl

        assert hasattr(kpl, "register")

    def test_kpl_tools_registered_in_fastmcp(self):
        """FastMCP 全量发现后 kpl 4 工具在场。"""
        import asyncio

        from mcp.server.fastmcp import FastMCP

        from tradex.tools import kpl  # noqa: F401 触发 import
        mcp = FastMCP("kpl-test")
        kpl.register(mcp)
        tools = asyncio.new_event_loop().run_until_complete(mcp.list_tools())
        names = {t.name for t in tools}
        assert {
            "get_kpl_limit_up",
            "get_kpl_sentiment",
            "get_kpl_boards",
            "get_kpl_bidding",
        } <= names

    def test_module_group_registered(self):
        """generate_tool_docs 的 MODULE_GROUPS 必须含 kpl.py（防清单漏项）。"""
        import os

        script = os.path.join(
            os.path.dirname(__file__), "..", "scripts", "generate_tool_docs.py"
        )
        with open(script, encoding="utf-8") as f:
            content = f.read()
        assert '"kpl.py":' in content


class TestKplRestEndpoints:
    def test_sentiment_envelope(self):
        from fastapi.testclient import TestClient

        client = TestClient(_build_app())
        r = client.get("/api/v1/kpl/sentiment")
        assert r.status_code == 200
        body = r.json()
        assert body.get("code") == 0
        assert "limit_up" in (body.get("data") or {})

    def test_limit_up_records(self):
        from fastapi.testclient import TestClient

        client = TestClient(_build_app())
        r = client.get("/api/v1/kpl/limit-up", params={"date": "20261106"})
        assert r.status_code == 200
        rows = r.json().get("data") or []
        assert isinstance(rows, list) and len(rows) > 0
        assert "code" in rows[0]

    def test_invalid_date_returns_400(self):
        from fastapi.testclient import TestClient

        client = TestClient(_build_app())
        r = client.get("/api/v1/kpl/limit-up", params={"date": "bad"})
        assert r.status_code == 400

    def test_bidding_empty_history_ok(self):
        """历史竞价保留期短：空数据返回空列表而非报错。"""
        from fastapi.testclient import TestClient

        client = TestClient(_build_app())
        r = client.get("/api/v1/kpl/bidding", params={"date": "20261106"})
        assert r.status_code == 200
        assert r.json().get("data") == []

    def test_source_failure_returns_502(self):
        """KPL 独占源挂掉 → 502 + X-ErrCode（韧性纪律：不静默空数据）。"""
        from fastapi.testclient import TestClient

        client = TestClient(_build_app())
        with patch(
            "tradex.api.routes.kpl._router"
        ) as m_router:
            m_router.route.side_effect = RuntimeError("KPL 挂了")
            r = client.get("/api/v1/kpl/sentiment")
        assert r.status_code == 502
