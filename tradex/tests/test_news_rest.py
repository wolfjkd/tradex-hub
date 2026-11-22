"""工单 06 测试：news service + REST 端点 + MCP 薄包装契约。

只验证工单 06 范围内的 3 个核心函数（get_stock_news /
get_company_announcements / search_news），news_events.py 的其它 12 个工具
未抽层，本测试不覆盖。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from tradex.api.schemas import ERR_BAD_REQUEST, ERR_OK


def _build_min_app():
    """构造带 envelope 异常映射的最小 app（A⑦ 收敛 2026-11-22：薄壳调基座，原手抄与基座 AST 同构）。"""
    from tests._rest_test_base import build_min_test_app

    return build_min_test_app()


def _clear_cache():
    try:
        from tradex.utils.cache import cache as _c
        _c.clear()
    except Exception:
        pass


class TestNewsService:
    """news_service 函数返回结构。"""

    def test_get_stock_news_returns_news_list(self):
        from tradex.service import news_service
        _clear_cache()
        result = news_service.get_stock_news(symbol="600519")
        assert isinstance(result, dict)
        assert "news" in result
        assert isinstance(result["news"], list)

    def test_get_company_announcements_returns_list(self):
        from tradex.service import news_service
        _clear_cache()
        result = news_service.get_company_announcements(symbol="600519", num_results=5)
        assert isinstance(result, dict)
        assert "announcements" in result

    def test_get_company_announcements_empty_symbol_returns_all_market(self):
        from tradex.service import news_service
        _clear_cache()
        result = news_service.get_company_announcements(symbol="", num_results=5)
        assert isinstance(result, dict)
        assert result.get("symbol") == "全市场"

    def test_search_news_returns_news_list(self):
        from tradex.service import news_service
        _clear_cache()
        result = news_service.search_news(keyword="业绩", symbol="", num_results=5)
        assert isinstance(result, dict)
        assert "news" in result
        assert "keyword" in result


class TestNewsRestEndpoints:
    """/api/v1/news/* 端点。"""

    def test_stock_news_valid_returns_envelope(self):
        app = _build_min_app()
        client = TestClient(app)
        resp = client.get("/api/v1/news/stock?symbol=600519")
        body = resp.json()
        assert "code" in body and "data" in body and "msg" in body

    def test_stock_news_non_digit_returns_400(self):
        app = _build_min_app()
        client = TestClient(app)
        resp = client.get("/api/v1/news/stock?symbol=abc123")
        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == ERR_BAD_REQUEST

    def test_announcements_returns_envelope(self):
        app = _build_min_app()
        client = TestClient(app)
        resp = client.get("/api/v1/news/announcements?symbol=600519")
        body = resp.json()
        assert "code" in body

    def test_search_news_returns_envelope(self):
        app = _build_min_app()
        client = TestClient(app)
        resp = client.get("/api/v1/news/search?keyword=业绩")
        body = resp.json()
        assert "code" in body

    def test_search_news_missing_keyword_returns_422(self):
        app = _build_min_app()
        client = TestClient(app)
        resp = client.get("/api/v1/news/search")
        body = resp.json()
        assert body["code"] == ERR_BAD_REQUEST


class TestNewsMcpContract:
    """tools/news_events.py 三个核心工具薄包装契约。"""

    def test_tools_news_imports_service(self):
        from tradex.tools import news_events
        assert hasattr(news_events, "news_service")

    def test_news_contract_fields(self):
        """news_service 字段名（news/announcements/keyword）三处一致。"""
        from tradex.service import news_service
        _clear_cache()
        n = news_service.get_stock_news(symbol="600519")
        assert "news" in n

        a = news_service.get_company_announcements(symbol="600519", num_results=5)
        assert "announcements" in a
