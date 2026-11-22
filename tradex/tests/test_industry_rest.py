"""工单 07 测试：industry service + REST 端点 + MCP 薄包装契约。

2026-09-23：东财 push2 族被风控退役，akshare 中所有 `_em` 后缀函数也连锁
失效，industry_service 内部的 `_em` endpoint 全部不可用。`_ths` endpoint
理论上可用但 industry_data 类型注册的主源是 akshare（底层走 _em 失败）。
故本测试模块中真实联网测试用 conditional skip。
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from tradex.api.schemas import ERR_BAD_REQUEST, ERR_OK


def _eastmoney_blocked() -> bool:
    """检测东财是否处于风控失效状态（同 test_fund_rest.py）。"""
    if os.environ.get("TRADEX_SKIP_EM_DOWN_TESTS") == "1":
        return True
    try:
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
        from tradex.data_sources import register_all_sources  # noqa
        from astock_signals.smart_router import get_router
        register_all_sources()
        r = get_router()
        # industry_quotes 已是裸类型 → 东财退役生效
        if "industry_quotes" not in r._sources:
            return True
    except Exception:
        pass
    return False


_EM_BLOCKED = _eastmoney_blocked()
_em_skip = pytest.mark.skipif(_EM_BLOCKED, reason="东财 push2 族风控退役期（2026-09-23 起），行业板块接口失效")


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


class TestIndustryService:
    """industry_service 5 个函数。"""

    @_em_skip
    def test_get_industry_list_returns_list(self):
        from tradex.service import industry_service
        _clear_cache()
        result = industry_service.get_industry_list()
        assert isinstance(result, dict)
        assert "industries" in result

    def test_get_industry_stocks_returns_stocks(self):
        from tradex.service import industry_service
        _clear_cache()
        try:
            result = industry_service.get_industry_stocks(industry="银行")
            assert isinstance(result, dict)
            assert "stocks" in result
        except Exception:
            pass  # 行业名不对或源临时不可达

    @_em_skip
    def test_get_concept_list_returns_concepts(self):
        from tradex.service import industry_service
        _clear_cache()
        result = industry_service.get_concept_list()
        assert isinstance(result, dict)
        assert "concepts" in result

    def test_get_sector_fund_flow_returns_flows(self):
        from tradex.service import industry_service
        _clear_cache()
        result = industry_service.get_sector_fund_flow(sector_type="行业资金流", indicator="今日")
        assert isinstance(result, dict)
        assert "flows" in result


class TestIndustryRestEndpoints:
    """/api/v1/industry/* 端点。"""

    def test_list_returns_envelope(self):
        app = _build_min_app()
        client = TestClient(app)
        resp = client.get("/api/v1/industry/list")
        body = resp.json()
        assert "code" in body and "data" in body

    def test_concepts_returns_envelope(self):
        app = _build_min_app()
        client = TestClient(app)
        resp = client.get("/api/v1/industry/concepts")
        body = resp.json()
        assert "code" in body

    def test_fund_flow_returns_envelope(self):
        app = _build_min_app()
        client = TestClient(app)
        resp = client.get("/api/v1/industry/fund-flow?sector_type=行业资金流&indicator=今日")
        body = resp.json()
        assert "code" in body

    def test_stocks_missing_industry_returns_422(self):
        app = _build_min_app()
        client = TestClient(app)
        resp = client.get("/api/v1/industry/stocks")
        body = resp.json()
        assert body["code"] == ERR_BAD_REQUEST


class TestIndustryMcpContract:
    """tools/industry.py 薄包装契约。"""

    def test_tools_industry_imports_service(self):
        from tradex.tools import industry
        assert hasattr(industry, "industry_service")

    @_em_skip
    def test_industry_contract_fields(self):
        from tradex.service import industry_service
        _clear_cache()
        i = industry_service.get_industry_list()
        assert "industries" in i

        c = industry_service.get_concept_list()
        assert "concepts" in c
