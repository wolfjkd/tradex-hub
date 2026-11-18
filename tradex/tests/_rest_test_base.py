"""REST 测试应用基座（QI-ARCH-08，2026-11-19 质检整改续批）。

Envelope 异常映射 + 兜底 middleware 的测试替身，原在 11 个 REST 测试文件
各抄一份（实测 9 份定义完全同构）——收敛此单点后**测试面 = 接口面**
（真身 = http_server.py:212 同款语义）。

用法：
    def _build_min_app_with_fund():
        from tradex.tests._rest_test_base import build_min_test_app
        return build_min_test_app()
"""

import json

from fastapi import FastAPI


def build_min_test_app() -> FastAPI:
    """构造带全量 REST 路由 + envelope 异常映射的最小 FastAPI app。"""
    from fastapi import HTTPException, Request
    from fastapi.responses import JSONResponse

    from tradex.api import routes as rest_routes
    from tradex.api.schemas import (
        ERR_BAD_REQUEST,
        ERR_INTERNAL,
        ERR_NOT_FOUND,
        envelope_err,
    )

    app = FastAPI()
    app.include_router(rest_routes.router, prefix="/api/v1")

    @app.exception_handler(HTTPException)
    async def _h(request: Request, exc: HTTPException) -> JSONResponse:
        path = request.url.path
        if not path.startswith("/api/"):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        err_code = (
            int(exc.headers.get("X-ErrCode"))
            if exc.headers and exc.headers.get("X-ErrCode")
            else {400: ERR_BAD_REQUEST, 404: ERR_NOT_FOUND, 500: ERR_INTERNAL}.get(
                exc.status_code, ERR_INTERNAL
            )
        )
        return JSONResponse(
            envelope_err(err_code, str(exc.detail)).model_dump(),
            status_code=exc.status_code,
        )

    @app.middleware("http")
    async def _env(request: Request, call_next):
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
                if response.status_code == 422 and isinstance(body, dict):
                    msg = json.dumps(body.get("detail", "validation error"), ensure_ascii=False)
                else:
                    msg = body.get("detail") if isinstance(body, dict) else str(body)
                return JSONResponse(
                    envelope_err(code, str(msg or "error")).model_dump(),
                    status_code=response.status_code,
                )
            except Exception:
                return response
        return response

    return app
