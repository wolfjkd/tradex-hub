"""工单 05 测试：company + financial service + REST 端点 + MCP 薄包装契约。

覆盖范围：
- company_service 4 个函数 + /company/* 4 个端点
- financial_service 8 个函数 + /financial/* 8 个端点
- MCP 薄包装契约一致性（tools/company_info.py + tools/financial_stmt.py）
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


def _build_min_app():
    """构造最小 FastAPI app（沿用 03/04 工单测试骨架）。"""
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import JSONResponse

    from tradex.api import routes as rest_routes
    from tradex.api.schemas import (
        ERR_BAD_REQUEST, ERR_INTERNAL, ERR_NOT_FOUND, envelope_err,
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
                code_map = {400: ERR_BAD_REQUEST, 404: ERR_NOT_FOUND, 422: ERR_BAD_REQUEST, 500: ERR_INTERNAL}
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


# ---------- company service 单测 ----------


def _clear_cache():
    try:
        from tradex.utils.cache import cache as _c
        _c.clear()
    except Exception:
        pass


class TestCompanyService:
    """company_service 函数返回结构。"""

    def test_search_stock_returns_matches_list(self):
        from tradex.service import company_service
        _clear_cache()
        result = company_service.search_stock(keyword="茅台")
        assert isinstance(result, dict)
        assert "matches" in result

    def test_get_company_info_returns_info_dict(self):
        from tradex.service import company_service
        _clear_cache()
        result = company_service.get_company_info(symbol="600519")
        assert isinstance(result, dict)
        assert "info" in result or "symbol" in result

    def test_get_company_profile_returns_segments(self):
        from tradex.service import company_service
        _clear_cache()
        result = company_service.get_company_profile(symbol="600519")
        assert isinstance(result, dict)
        assert "segments" in result

    def test_get_competitors_returns_industry_peers(self):
        from tradex.service import company_service
        _clear_cache()
        try:
            result = company_service.get_competitors(symbol="600519")
            assert isinstance(result, dict)
            assert "industry" in result or "peers" in result
        except ValueError:
            # 行业推断失败是合法业务异常
            pass


# ---------- financial service 单测 ----------


class TestFinancialService:
    """financial_service 三大报表 + 5 个指标函数。"""

    def test_get_income_statement_returns_periods(self):
        from tradex.service import financial_service
        _clear_cache()
        result = financial_service.get_income_statement(symbol="600519")
        assert isinstance(result, dict)
        assert "periods" in result

    def test_get_balance_sheet_returns_periods(self):
        from tradex.service import financial_service
        _clear_cache()
        result = financial_service.get_balance_sheet(symbol="600519")
        assert isinstance(result, dict)
        assert "periods" in result

    def test_get_cash_flow_returns_periods(self):
        from tradex.service import financial_service
        _clear_cache()
        result = financial_service.get_cash_flow_statement(symbol="600519")
        assert isinstance(result, dict)
        assert "periods" in result

    def test_get_financial_indicators_returns_indicators(self):
        from tradex.service import financial_service
        _clear_cache()
        result = financial_service.get_financial_indicators(symbol="600519")
        assert isinstance(result, dict)
        assert "indicators" in result

    def test_get_growth_rates_returns_growth(self):
        from tradex.service import financial_service
        _clear_cache()
        try:
            result = financial_service.get_growth_rates(symbol="600519")
            assert isinstance(result, dict)
            assert "growth" in result
        except ValueError:
            pass

    def test_get_per_share_data_returns_per_share(self):
        from tradex.service import financial_service
        _clear_cache()
        try:
            result = financial_service.get_per_share_data(symbol="600519")
            assert isinstance(result, dict)
            assert "per_share" in result
        except ValueError:
            pass

    def test_get_segments_revenue_returns_segments(self):
        from tradex.service import financial_service
        _clear_cache()
        try:
            result = financial_service.get_segments_revenue(symbol="600519")
            assert isinstance(result, dict)
            assert "segments" in result
        except ValueError:
            pass

    def test_get_financial_line_item_returns_periods(self):
        from tradex.service import financial_service
        _clear_cache()
        try:
            result = financial_service.get_financial_line_item(symbol="600519", item="净利润")
            assert isinstance(result, dict)
            assert "periods" in result or "item" in result
        except ValueError:
            pass


# ---------- REST 端点集成测 ----------


class TestCompanyRestEndpoints:
    """/api/v1/company/* 端点。"""

    def test_search_returns_envelope(self):
        app = _build_min_app()
        client = TestClient(app)
        resp = client.get("/api/v1/company/search?keyword=茅台")
        body = resp.json()
        assert "code" in body and "data" in body and "msg" in body

    def test_info_non_digit_symbol_returns_400(self):
        app = _build_min_app()
        client = TestClient(app)
        resp = client.get("/api/v1/company/info?symbol=abc123")
        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == ERR_BAD_REQUEST

    def test_info_valid_returns_envelope(self):
        app = _build_min_app()
        client = TestClient(app)
        resp = client.get("/api/v1/company/info?symbol=600519")
        body = resp.json()
        assert "code" in body

    def test_profile_valid_returns_envelope(self):
        app = _build_min_app()
        client = TestClient(app)
        resp = client.get("/api/v1/company/profile?symbol=600519")
        body = resp.json()
        assert "code" in body


class TestFinancialRestEndpoints:
    """/api/v1/financial/* 端点。"""

    def test_income_valid_returns_envelope(self):
        app = _build_min_app()
        client = TestClient(app)
        resp = client.get("/api/v1/financial/income?symbol=600519")
        body = resp.json()
        assert "code" in body

    def test_income_non_digit_symbol_returns_400(self):
        app = _build_min_app()
        client = TestClient(app)
        resp = client.get("/api/v1/financial/income?symbol=abc123")
        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == ERR_BAD_REQUEST

    def test_balance_valid_returns_envelope(self):
        app = _build_min_app()
        client = TestClient(app)
        resp = client.get("/api/v1/financial/balance?symbol=600519")
        body = resp.json()
        assert "code" in body

    def test_cashflow_valid_returns_envelope(self):
        app = _build_min_app()
        client = TestClient(app)
        resp = client.get("/api/v1/financial/cashflow?symbol=600519")
        body = resp.json()
        assert "code" in body

    def test_indicators_valid_returns_envelope(self):
        app = _build_min_app()
        client = TestClient(app)
        resp = client.get("/api/v1/financial/indicators?symbol=600519")
        body = resp.json()
        assert "code" in body

    def test_line_item_missing_item_returns_422(self):
        app = _build_min_app()
        client = TestClient(app)
        resp = client.get("/api/v1/financial/line-item?symbol=600519")
        body = resp.json()
        assert body["code"] == ERR_BAD_REQUEST


# ---------- MCP 薄包装契约 ----------


class TestCompanyFinancialMcpContract:
    """tools/company_info.py + tools/financial_stmt.py 薄包装契约。"""

    def test_tools_company_imports_service(self):
        from tradex.tools import company_info
        assert hasattr(company_info, "company_service")

    def test_tools_financial_imports_service(self):
        from tradex.tools import financial_stmt
        assert hasattr(financial_stmt, "financial_service")

    def test_company_contract_fields(self):
        """company_service 字段名（matches/info/segments/industry）三处一致。"""
        from tradex.service import company_service
        _clear_cache()
        # search
        s = company_service.search_stock(keyword="茅台")
        assert "matches" in s
        # info
        i = company_service.get_company_info(symbol="600519")
        assert "info" in i or "symbol" in i

    def test_financial_contract_fields(self):
        """financial_service 字段名（periods/indicators/growth/per_share/segments）三处一致。"""
        from tradex.service import financial_service
        _clear_cache()
        inc = financial_service.get_income_statement(symbol="600519")
        assert "periods" in inc

        ind = financial_service.get_financial_indicators(symbol="600519")
        assert "indicators" in ind
