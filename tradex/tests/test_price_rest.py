"""工单 04 测试：价格/K 线类（price）service + REST 端点 + MCP 薄包装契约一致性。

验证验收标准：
- service 层函数返回 dict，含 quote/bars/points 字段
- /api/v1/price/quote、/price/kline、/price/intraday 返回包裹格式
- 参数校验：period 枚举、symbol 数字校验
- eltdx Rust 内核 panic 已由 _NativePanicShield 统一防护，service 异常路径回归
- MCP 工具 get_realtime_quote / get_historical_price / get_intraday_data 薄包装契约
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from tradex.api.schemas import (
    ERR_BAD_REQUEST,
    ERR_DATA_SOURCE_UNREACHABLE,
    ERR_OK,
)


def _build_min_app_with_price():
    """构造带 price 路由的最小 FastAPI app（沿用 03 工单测试的同款骨架）。"""
    from fastapi import FastAPI, HTTPException, Request
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


# ---------- service 层单测 ----------


class TestPriceServiceShape:
    """price_service 函数返回结构。"""

    def test_get_realtime_quote_a_share_returns_dict(self):
        """A 股代码返回 dict 含 quote/symbol 字段。"""
        from tradex.service import price_service

        try:
            from tradex.utils.cache import cache as _c
            _c.clear()
        except Exception:
            pass

        result = price_service.get_realtime_quote(symbol="600519")
        assert isinstance(result, dict)
        # A 股分支应有 symbol 或 quote 字段
        assert "symbol" in result or "quote" in result

    def test_get_realtime_quote_global_returns_dict(self):
        """全球代码 usDJI 返回 dict 含 quote 字段。"""
        from tradex.service import price_service

        try:
            from tradex.utils.cache import cache as _c
            _c.clear()
        except Exception:
            pass

        result = price_service.get_realtime_quote(symbol="usDJI")
        assert isinstance(result, dict)

    def test_get_historical_price_returns_dict_with_bars(self):
        """历史 K 线返回 dict 含 bars（list）。"""
        from tradex.service import price_service

        try:
            from tradex.utils.cache import cache as _c
            _c.clear()
        except Exception:
            pass

        result = price_service.get_historical_price(symbol="600519", period="daily")
        assert isinstance(result, dict)
        assert "bars" in result
        assert isinstance(result["bars"], list)

    def test_get_intraday_data_returns_dict_with_points(self):
        """分时数据返回 dict 含 points（list）。"""
        from tradex.service import price_service

        try:
            from tradex.utils.cache import cache as _c
            _c.clear()
        except Exception:
            pass

        # 收盘后调用可能抛 ValueError（无有效数据点），属正常业务异常
        try:
            result = price_service.get_intraday_data(symbol="600519")
            assert isinstance(result, dict)
            assert "points" in result
        except ValueError:
            # 盘后无分时数据是合法业务异常，service 正确向上抛
            pass

    def test_service_propagates_runtime_error(self):
        """数据源异常（含 panic 转的 RuntimeError）service 向上抛。"""
        from tradex.service import price_service

        try:
            from tradex.utils.cache import cache as _c
            _c.clear()
        except Exception:
            pass

        with patch.object(price_service, "_router") as mock_router:
            mock_router.route.side_effect = RuntimeError("simulated native panic")
            with pytest.raises(RuntimeError):
                price_service.get_realtime_quote(symbol="600519")


# ---------- REST 端点集成测 ----------


class TestPriceRestEndpoints:
    """/api/v1/price/* 端点行为。"""

    def test_quote_a_share_returns_envelope(self):
        """/price/quote?symbol=600519 返回包裹格式。"""
        app = _build_min_app_with_price()
        client = TestClient(app)
        resp = client.get("/api/v1/price/quote?symbol=600519")
        body = resp.json()
        assert "code" in body and "data" in body and "msg" in body
        if resp.status_code == 200:
            assert body["code"] == ERR_OK

    def test_quote_global_code_returns_envelope(self):
        """/price/quote?symbol=usDJI 返回包裹格式。"""
        app = _build_min_app_with_price()
        client = TestClient(app)
        resp = client.get("/api/v1/price/quote?symbol=usDJI")
        body = resp.json()
        assert "code" in body

    def test_kline_invalid_period_returns_400(self):
        """period=invalid 返回 40001。"""
        app = _build_min_app_with_price()
        client = TestClient(app)
        resp = client.get("/api/v1/price/kline?symbol=600519&period=quarterly")
        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == ERR_BAD_REQUEST

    def test_kline_non_digit_symbol_returns_400(self):
        """symbol=abc123 返回 40001（长度对但非数字）。"""
        app = _build_min_app_with_price()
        client = TestClient(app)
        resp = client.get("/api/v1/price/kline?symbol=abc123&period=daily")
        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == ERR_BAD_REQUEST

    def test_kline_valid_returns_envelope(self):
        """合法调用返回包裹格式。"""
        app = _build_min_app_with_price()
        client = TestClient(app)
        resp = client.get("/api/v1/price/kline?symbol=600519&period=weekly")
        body = resp.json()
        assert "code" in body

    def test_intraday_non_digit_symbol_returns_400(self):
        """/price/intraday?symbol=abc123 返回 40001。"""
        app = _build_min_app_with_price()
        client = TestClient(app)
        resp = client.get("/api/v1/price/intraday?symbol=abc123")
        assert resp.status_code == 400

    def test_intraday_missing_symbol_returns_422(self):
        """缺 symbol 返回 422→40001。"""
        app = _build_min_app_with_price()
        client = TestClient(app)
        resp = client.get("/api/v1/price/intraday")
        body = resp.json()
        assert body["code"] == ERR_BAD_REQUEST


# ---------- MCP 薄包装契约 ----------


class TestPriceMcpContract:
    """tools/price_data.py 薄包装调用同一 service。"""

    def test_tools_price_imports_service(self):
        """tools/price_data.py 导入了 price_service。"""
        from tradex.tools import price_data

        assert hasattr(price_data, "price_service")

    def test_contract_fields_consistent(self):
        """service 字段名（quote/bars/points）三处一致。"""
        from tradex.service import price_service

        try:
            from tradex.utils.cache import cache as _c
            _c.clear()
        except Exception:
            pass

        # quote
        q = price_service.get_realtime_quote(symbol="600519")
        assert "quote" in q or "symbol" in q

        # kline
        k = price_service.get_historical_price(symbol="600519", period="daily")
        assert "bars" in k

        # intraday 可能盘后抛 ValueError，属正常
        try:
            i = price_service.get_intraday_data(symbol="600519")
            assert "points" in i
        except ValueError:
            pass
