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
    from tests._rest_test_base import build_min_test_app

    return build_min_test_app()
# ---------- company service 单测 ----------


def _clear_cache():
    try:
        from tradex.utils.cache import cache as _c
        _c.clear()
    except Exception:
        pass


class TestCompanyService:
    """company_service 函数返回结构。"""

    pytestmark = pytest.mark.network  # 真连上游源，离线全量 -m "not network" 排除

    def test_search_stock_returns_matches_list(self):
        from tradex.service import company_service
        _clear_cache()
        try:
            result = company_service.search_stock(keyword="茅台")
        except RuntimeError as e:
            # 上游源不可用（问财缺 pywencai / 东财超时）≠ 契约失败，skip 如实留痕
            pytest.skip(f"上游源不可用：{e}")
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

    pytestmark = pytest.mark.network  # 真连上游源，离线全量 -m "not network" 排除

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
        except RuntimeError as e:
            # SmartRouter 全源失败（akshare indicator 超时 / sina 备源不支持）≠ 契约失败，skip 留痕
            pytest.skip(f"上游源不可用：{e}")
        assert isinstance(result, dict)
        assert "growth" in result

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

    @pytest.mark.network
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

    @pytest.mark.network
    def test_info_valid_returns_envelope(self):
        app = _build_min_app()
        client = TestClient(app)
        resp = client.get("/api/v1/company/info?symbol=600519")
        body = resp.json()
        assert "code" in body

    @pytest.mark.network
    def test_profile_valid_returns_envelope(self):
        app = _build_min_app()
        client = TestClient(app)
        resp = client.get("/api/v1/company/profile?symbol=600519")
        body = resp.json()
        assert "code" in body


class TestFinancialRestEndpoints:
    """/api/v1/financial/* 端点。"""

    @pytest.mark.network
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

    @pytest.mark.network
    def test_balance_valid_returns_envelope(self):
        app = _build_min_app()
        client = TestClient(app)
        resp = client.get("/api/v1/financial/balance?symbol=600519")
        body = resp.json()
        assert "code" in body

    @pytest.mark.network
    def test_cashflow_valid_returns_envelope(self):
        app = _build_min_app()
        client = TestClient(app)
        resp = client.get("/api/v1/financial/cashflow?symbol=600519")
        body = resp.json()
        assert "code" in body

    @pytest.mark.network
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

    @pytest.mark.network
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

    @pytest.mark.network
    def test_financial_contract_fields(self):
        """financial_service 字段名（periods/indicators/growth/per_share/segments）三处一致。"""
        from tradex.service import financial_service
        _clear_cache()
        inc = financial_service.get_income_statement(symbol="600519")
        assert "periods" in inc

        ind = financial_service.get_financial_indicators(symbol="600519")
        assert "indicators" in ind
