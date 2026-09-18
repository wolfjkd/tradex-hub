"""工单 12 测试 —— 监控看板 HTML 页。

策略：
- 验证 HTML 返回 200 + 正确 Content-Type
- 验证 HTML 含关键区域标识（status-card、metrics-table 等 id）
- 验证 JS 的 fetch URL 正确指向 /api/v1/metrics/json
- 验证刷新间隔设置为 30000ms
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _build_dashboard_app() -> FastAPI:
    """构建带 dashboard + metrics 端点的测试 app。"""
    from tradex.api.routes.dashboard import _DASHBOARD_HTML
    from tradex.api.routes import metrics as metrics_routes
    from fastapi.responses import HTMLResponse

    app = FastAPI()

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard():
        return HTMLResponse(_DASHBOARD_HTML)

    app.include_router(metrics_routes.router, prefix="/api/v1")
    return app


class TestDashboardEndpoint:
    def test_dashboard_returns_html(self):
        app = _build_dashboard_app()
        client = TestClient(app)
        r = client.get("/dashboard")
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", "")

    def test_dashboard_has_status_card(self):
        """HTML 应含 id='status-card'。"""
        app = _build_dashboard_app()
        client = TestClient(app)
        html = client.get("/dashboard").text
        assert 'id="status-card"' in html

    def test_dashboard_has_metrics_table(self):
        """HTML 应含 id='metrics-table'。"""
        app = _build_dashboard_app()
        client = TestClient(app)
        html = client.get("/dashboard").text
        assert 'id="metrics-table"' in html

    def test_dashboard_has_correct_fetch_url(self):
        """JS 应 fetch /api/v1/metrics/json。"""
        app = _build_dashboard_app()
        client = TestClient(app)
        html = client.get("/dashboard").text
        assert "/api/v1/metrics/json" in html

    def test_dashboard_has_refresh_interval(self):
        """JS 应设置 30000ms 刷新间隔。"""
        app = _build_dashboard_app()
        client = TestClient(app)
        html = client.get("/dashboard").text
        assert "REFRESH_INTERVAL" in html
        assert "30000" in html

    def test_dashboard_has_uptime_element(self):
        """应有 id='uptime' 元素。"""
        app = _build_dashboard_app()
        client = TestClient(app)
        html = client.get("/dashboard").text
        assert 'id="uptime"' in html

    def test_dashboard_has_tools_element(self):
        """应有 id='tools' 元素。"""
        app = _build_dashboard_app()
        client = TestClient(app)
        html = client.get("/dashboard").text
        assert 'id="tools"' in html

    def test_dashboard_title_correct(self):
        """HTML title 应含 TradeX。"""
        app = _build_dashboard_app()
        client = TestClient(app)
        html = client.get("/dashboard").text
        assert "<title>TradeX" in html

    def test_dashboard_has_error_banner(self):
        """应有错误提示 banner。"""
        app = _build_dashboard_app()
        client = TestClient(app)
        html = client.get("/dashboard").text
        assert 'id="error-banner"' in html

    def test_dashboard_responsive_meta(self):
        """应有 viewport meta 支持响应式。"""
        app = _build_dashboard_app()
        client = TestClient(app)
        html = client.get("/dashboard").text
        assert "viewport" in html
        assert "width=device-width" in html

    def test_dashboard_has_dark_mode_support(self):
        """应支持暗色模式（响应老板偏好）。"""
        app = _build_dashboard_app()
        client = TestClient(app)
        html = client.get("/dashboard").text
        assert "prefers-color-scheme" in html


class TestDashboardFullApp:
    """通过完整 build_app 流程验证（如果可行）。"""

    def test_dashboard_via_full_http_server(self):
        """验证 http_server.py 的 _dashboard_page 函数能正常返回 HTML。"""
        import asyncio
        from tradex.http_server import _dashboard_page

        async def run():
            # _dashboard_page 接受 request 但不使用，传 None
            response = await _dashboard_page(None)
            return response

        response = asyncio.run(run())
        assert response.status_code == 200
        body = response.body.decode("utf-8")
        assert 'id="status-card"' in body
        assert 'id="metrics-table"' in body
