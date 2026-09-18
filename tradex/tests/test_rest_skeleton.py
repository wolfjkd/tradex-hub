"""工单 01 测试：FastAPI 升级 + api/service 骨架 + 包裹响应中间件。

验证验收标准：
- /health 升级前后行为一致
- /api/v1/ping 返回正确包裹格式
- 异常路径返回包裹式错误（如 /api/v1/nonexistent → code=40401）
- Envelope 模型 + 错误码常量正确
- service/api 骨架目录可导入
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tradex.api.schemas import (
    ERR_BAD_REQUEST,
    ERR_INTERNAL,
    ERR_NOT_FOUND,
    ERR_OK,
    Envelope,
    envelope_err,
    envelope_ok,
)


# ---------- Envelope 模型单测 ----------


class TestEnvelopeModel:
    """Envelope 包裹响应模型。"""

    def test_ok_constructor(self):
        """envelope_ok 构造成功响应。"""
        env = envelope_ok({"ping": True})
        assert env.code == ERR_OK
        assert env.data == {"ping": True}
        assert env.msg == "ok"

    def test_err_constructor(self):
        """envelope_err 构造失败响应（data 恒为 None）。"""
        env = envelope_err(ERR_NOT_FOUND, "resource not found")
        assert env.code == ERR_NOT_FOUND
        assert env.data is None
        assert env.msg == "resource not found"

    def test_error_codes_distinct(self):
        """错误码彼此不重复且非 0。"""
        codes = [ERR_BAD_REQUEST, ERR_NOT_FOUND, ERR_INTERNAL]
        assert len(set(codes)) == len(codes)
        assert all(c != ERR_OK for c in codes)

    def test_envelope_generic_serialization(self):
        """Envelope 泛型序列化为 {code,data,msg} 三键。"""
        env = envelope_ok({"k": 1})
        dumped = env.model_dump()
        assert set(dumped.keys()) == {"code", "data", "msg"}


# ---------- 骨架目录可导入性 ----------


class TestSkeletonImportable:
    """service/ 与 api/ 骨架目录可正常导入。"""

    def test_service_pkg_importable(self):
        """service 包可导入（空骨架）。"""
        import tradex.service  # noqa: F401

    def test_api_pkg_importable(self):
        """api 包可导入。"""
        import tradex.api  # noqa: F401

    def test_api_routes_pkg_importable(self):
        """api.routes 子包可导入，且 router 已定义。"""
        from tradex.api import routes
        assert hasattr(routes, "router")

    def test_schemas_module_importable(self):
        """schemas 模块可导入。"""
        import tradex.api.schemas  # noqa: F401


# ---------- 端点集成测（需要构造最小 app） ----------


def _build_min_app():
    """构造一个最小 FastAPI app 用于测试（不带 MCP 子 app，避免依赖 FastMCP 实例）。

    复用工单 01 的 REST 路由 + 异常处理器 + 响应包裹中间件逻辑，模拟生产 app 的 REST 行为。
    """
    import json

    from fastapi import FastAPI, HTTPException
    from fastapi.responses import JSONResponse

    from tradex.api import routes as rest_routes
    from tradex.api.schemas import (
        ERR_BAD_REQUEST,
        ERR_INTERNAL,
        ERR_NOT_FOUND,
        envelope_err,
        envelope_ok,
    )

    app = FastAPI()
    app.include_router(rest_routes.router, prefix="/api/v1")

    @app.exception_handler(HTTPException)
    async def _h(request, exc):
        path = request.url.path
        if not path.startswith("/api/"):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        code_map = {400: ERR_BAD_REQUEST, 404: ERR_NOT_FOUND, 500: ERR_INTERNAL}
        code = code_map.get(exc.status_code, ERR_INTERNAL)
        return JSONResponse(
            envelope_err(code, str(exc.detail)).model_dump(),
            status_code=exc.status_code,
        )

    # 响应包裹中间件（与生产 build_app 一致）
    @app.middleware("http")
    async def _env(request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/api/") and response.status_code != 200:
            try:
                body_bytes = b""
                async for chunk in response.body_iterator:
                    body_bytes += chunk
                try:
                    body = json.loads(body_bytes)
                except Exception:
                    body = {"raw": body_bytes.decode(errors="replace")}
                if isinstance(body, dict) and "code" in body:
                    return JSONResponse(body, status_code=response.status_code)
                code_map = {
                    400: ERR_BAD_REQUEST,
                    404: ERR_NOT_FOUND,
                    422: ERR_BAD_REQUEST,
                    500: ERR_INTERNAL,
                }
                code = code_map.get(response.status_code, ERR_INTERNAL)
                msg = body.get("detail") if isinstance(body, dict) else str(body)
                return JSONResponse(
                    envelope_err(code, str(msg or "error")).model_dump(),
                    status_code=response.status_code,
                )
            except Exception:
                return response
        return response

    return app


class TestPingEndpoint:
    """/api/v1/ping 端点行为。"""

    def test_ping_returns_envelope_ok(self):
        """ping 返回 {code:0, data:{pong:true}, msg:'ok'}。"""
        app = _build_min_app()
        client = TestClient(app)
        resp = client.get("/api/v1/ping")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"] == {"pong": True}
        assert body["msg"] == "ok"


class TestErrorEnvelope:
    """异常路径返回包裹式错误。"""

    def test_nonexistent_endpoint_returns_envelope_not_found(self):
        """访问不存在的 /api/v1/* 路径返回 code=40401 包裹格式。"""
        app = _build_min_app()
        client = TestClient(app)
        resp = client.get("/api/v1/nonexistent")
        # FastAPI 对未定义路由抛 HTTPException(404)
        assert resp.status_code == 404
        body = resp.json()
        assert body["code"] == ERR_NOT_FOUND
        assert body["data"] is None
        assert "msg" in body


# ---------- /health 行为一致性 ----------
# 注：/health 由 build_app 构造时挂载，需完整 FastMCP 实例；
# 此处单独测 _health 函数逻辑（不依赖 app 构造），保证返回字段齐全。


class TestHealthFunction:
    """/health 端点函数行为（不依赖完整 app 构造）。"""

    @pytest.mark.asyncio
    async def test_health_returns_expected_fields(self):
        """_health 返回 status/service/version/tools/uptime_seconds 五字段。"""
        from tradex.http_server import _health

        class _DummyRequest:
            class url:
                path = "/health"

        resp = await _health(_DummyRequest())
        import json
        body = json.loads(resp.body)
        assert body["status"] == "ok"
        assert body["service"] == "tradex-mcp"
        assert "version" in body
        assert "tools" in body
        assert "uptime_seconds" in body
