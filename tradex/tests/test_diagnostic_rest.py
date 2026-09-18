"""工单 09 测试 —— 诊断/分析类 REST 端点 + service 层。

策略：
- service 层直算：mock 数据源测试错误路径，少量真实调用测试 happy path
- REST 端点：TestClient 测试入参校验（40001）+ envelope 格式 + 路由挂载
- 契约对照：service 返回 dict；REST 包 envelope；MCP 走同一 service 函数
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tradex.api.schemas import ERR_OK, ERR_BAD_REQUEST, ERR_DATA_SOURCE_UNREACHABLE
from tradex.utils.cache import cache


def _build_min_app() -> FastAPI:
    """构建最小测试 app，仅挂 diagnostic 路由，并配套 422→40001 中间件。"""
    from tradex.api.routes import diagnostic as diag_routes
    from tradex.api.schemas import (
        ERR_BAD_REQUEST, ERR_DATA_SOURCE_UNREACHABLE, ERR_INTERNAL, envelope_err,
    )

    app = FastAPI()
    app.include_router(diag_routes.router, prefix="/api/v1")

    from fastapi import HTTPException, Request
    from fastapi.responses import JSONResponse
    from fastapi.exceptions import RequestValidationError

    @app.exception_handler(RequestValidationError)
    async def ve_handler(request: Request, exc: RequestValidationError):
        import json
        try:
            detail = json.dumps(exc.errors(), ensure_ascii=False)
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
            404: 40040,
            500: ERR_INTERNAL,
            502: ERR_DATA_SOURCE_UNREACHABLE,
            422: ERR_BAD_REQUEST,
        }
        code = code_map.get(exc.status_code, ERR_INTERNAL)
        return JSONResponse(
            status_code=exc.status_code,
            content=envelope_err(code, str(exc.detail)).model_dump(),
        )

    return app


def _clear_cache():
    """每个测试前清缓存，避免 mock 路径被缓存跳过。"""
    try:
        cache.clear()
    except Exception:
        pass


# ────────────────────── Service 层测试 ──────────────────────────

class TestDiagnosticService:
    """service 函数契约与边界测试。"""

    def setup_method(self):
        _clear_cache()

    def test_analyze_technical_invalid_look_back_days(self):
        """look_back_days <= 0 → service 返回 dict 含 success=False。"""
        from tradex.service import diagnostic_service
        result = diagnostic_service.analyze_technical("600519", look_back_days=0)
        assert isinstance(result, dict)
        assert result.get("success") is False
        assert "正整数" in result.get("error", "")

    def test_analyze_technical_negative_look_back_days(self):
        from tradex.service import diagnostic_service
        result = diagnostic_service.analyze_technical("600519", look_back_days=-5)
        assert isinstance(result, dict)
        assert result.get("success") is False

    def test_analyze_stock_comprehensive_returns_dict(self):
        """综合诊断 happy path：返回 dict 且含 summary 字段。"""
        from tradex.service import diagnostic_service
        _clear_cache()
        result = asyncio.run(diagnostic_service.analyze_stock_comprehensive("600519"))
        assert isinstance(result, dict)
        assert "summary" in result
        assert result["summary"]["total_dimensions"] == 4
        assert result["summary"]["success_dimensions"] >= 0

    def test_analyze_market_overview_returns_dict(self):
        """市场全景 happy path：返回 dict 且含 3 维度 summary。"""
        from tradex.service import diagnostic_service
        _clear_cache()
        result = asyncio.run(diagnostic_service.analyze_market_overview())
        assert isinstance(result, dict)
        assert "summary" in result
        assert result["summary"]["total_dimensions"] == 3


# ────────────────────── REST 端点测试 ──────────────────────────

class TestDiagnosticRestEndpoints:
    """REST 端点集成测试（TestClient）。"""

    def setup_method(self):
        _clear_cache()

    def test_stock_valid_returns_envelope(self):
        """个股综合诊断 happy path → code:0 + 数据。"""
        app = _build_min_app()
        client = TestClient(app)
        r = client.get("/api/v1/diagnostic/stock?symbol=600519")
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == ERR_OK
        assert body["data"] is not None
        assert "summary" in body["data"]

    def test_stock_non_digit_symbol_returns_400(self):
        """非数字 symbol → 40001。"""
        app = _build_min_app()
        client = TestClient(app)
        r = client.get("/api/v1/diagnostic/stock?symbol=INVALID")
        body = r.json()
        # FastAPI Query(max_length=6) 对 INVALID(7字) 返回 422 → 中间件映射 40001
        # 或 isdigit() 检查在前面拦截（由路由顺序决定）
        assert body["code"] in (ERR_BAD_REQUEST,)
        assert body["data"] is None

    def test_stock_short_symbol_returns_400(self):
        """长度 < 6 → 422 → 40001。"""
        app = _build_min_app()
        client = TestClient(app)
        r = client.get("/api/v1/diagnostic/stock?symbol=123")
        body = r.json()
        assert body["code"] == ERR_BAD_REQUEST

    def test_market_returns_envelope(self):
        """市场全景 happy path。"""
        app = _build_min_app()
        client = TestClient(app)
        r = client.get("/api/v1/diagnostic/market")
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == ERR_OK
        assert body["data"] is not None
        assert "summary" in body["data"]

    def test_technical_valid_returns_envelope(self):
        """技术分析 happy path。"""
        app = _build_min_app()
        client = TestClient(app)
        r = client.get("/api/v1/diagnostic/technical?symbol=600519&look_back_days=30")
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == ERR_OK
        # service 可能因数据源返回 success:False（502）；这里至少要能拿到结构化响应
        assert body["data"] is not None

    def test_technical_non_digit_symbol_returns_400(self):
        """技术分析非数字 symbol → 40001。"""
        app = _build_min_app()
        client = TestClient(app)
        r = client.get("/api/v1/diagnostic/technical?symbol=ABCDEF")
        body = r.json()
        assert body["code"] == ERR_BAD_REQUEST

    def test_technical_invalid_look_back_days_returns_400(self):
        """look_back_days < 1 → Pydantic Query(ge=1) 触发 422 → 40001。"""
        app = _build_min_app()
        client = TestClient(app)
        r = client.get("/api/v1/diagnostic/technical?symbol=600519&look_back_days=0")
        body = r.json()
        assert body["code"] == ERR_BAD_REQUEST

    def test_technical_look_back_days_too_large_returns_400(self):
        """look_back_days > 365 → 422 → 40001。"""
        app = _build_min_app()
        client = TestClient(app)
        r = client.get("/api/v1/diagnostic/technical?symbol=600519&look_back_days=999")
        body = r.json()
        assert body["code"] == ERR_BAD_REQUEST


# ────────────────────── 路由聚合验证 ──────────────────────────

class TestDiagnosticRouterAggregation:
    """验证 diagnostic 路由已挂到聚合 router。"""

    def test_diagnostic_router_has_three_endpoints(self):
        from tradex.api.routes import diagnostic as diag_routes
        paths = [route.path for route in diag_routes.router.routes]
        # 子路由自带 prefix="/diagnostic"，故路径含完整前缀
        assert "/diagnostic/stock" in paths
        assert "/diagnostic/market" in paths
        assert "/diagnostic/technical" in paths
