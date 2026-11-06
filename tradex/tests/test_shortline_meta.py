"""工单 H1 测试：短线端点声明式元数据 + CATALOG + 缓存策略。

验收对应：
- 每个 shortline 端点都有完整元数据
- 元数据可被 MCP / REST / 文档三方读取
- CATALOG 幂等
- 缓存策略由元数据驱动
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tradex.api import routes as rest_routes
from tradex.shortline.catalog import (
    build_catalog,
    missing_compute_refs,
    render_markdown,
    write_catalog,
)
from tradex.shortline.meta import (
    CACHE_POLICIES,
    SHORTLINE_ENDPOINTS,
    cache_key,
    resolve_cache,
    validate_registry,
)


class TestRegistry:
    """声明完整性。"""

    def test_registry_is_valid(self):
        assert validate_registry() == []

    def test_every_endpoint_has_complete_metadata(self):
        for endpoint in SHORTLINE_ENDPOINTS.values():
            assert endpoint.id.startswith("shortline.")
            assert endpoint.title.strip()
            assert endpoint.description.strip()
            assert endpoint.fields, f"{endpoint.id} 缺少产出字段"
            assert endpoint.source.strip()
            assert endpoint.cache_policy in CACHE_POLICIES
            assert endpoint.compliance == "cn-public"
            assert ":" in endpoint.compute
            assert endpoint.mcp_tool.startswith(("get_shortline", "shortline_"))
            assert endpoint.rest_path.startswith("/api/v1/shortline/")

    def test_expected_endpoints_declared(self):
        expected = {
            "shortline.emotion",
            "shortline.cycle",
            "shortline.daily",
            "shortline.settled",
            "shortline.live",
            "shortline.ladder",
            "shortline.board_ladder",
            "shortline.structure",
            "shortline.themes",  # 工单 H6
            "shortline.firstboard",  # 工单 H6
            "shortline.facts",  # 工单 H6
            "shortline.theme_rotation",  # 工单 H6
            "shortline.bigcaps",  # 工单 H4 新增（只改声明）
            "shortline.turnover_top",  # 工单 H5 新增（只改声明）
            "shortline.close_fetch",
            "shortline.history",
        }
        assert set(SHORTLINE_ENDPOINTS) == expected

    def test_live_uses_15s_cache_and_never_persists(self):
        live = SHORTLINE_ENDPOINTS["shortline.live"]
        decision = resolve_cache(live.cache_policy)
        assert decision.ttl_seconds == 15
        assert decision.file_cache is False
        assert decision.enabled is True

    def test_live_partial_still_cached_for_15s(self):
        # live 天生是「此刻」partial 读数：允许 15 秒内存缓存，但绝不落文件
        decision = resolve_cache("live_15s", partial=True)
        assert decision.ttl_seconds == 15
        assert decision.file_cache is False


class TestCachePolicy:
    """缓存策略解析。"""

    def test_closed_long_caches_final_only(self):
        final = resolve_cache("closed_long", partial=False)
        partial = resolve_cache("closed_long", partial=True)
        assert final.enabled and final.ttl_seconds == 7 * 86400
        assert final.file_cache is True
        assert partial.enabled is False

    def test_live_policy_only(self):
        assert resolve_cache("none").enabled is False

    def test_unknown_policy_raises(self):
        with pytest.raises(KeyError):
            resolve_cache("does_not_exist")

    def test_cache_key_stable_and_param_sensitive(self):
        assert cache_key("shortline.daily", date="20261105", days=0) == (
            "shortline-v2|shortline.daily|date=20261105"
        )
        assert cache_key("shortline.daily", days=5, date="20261105") == (
            cache_key("shortline.daily", date="20261105", days=5)
        )


class TestCatalog:
    """CATALOG 可复现 + 幂等。"""

    def test_catalog_is_deterministic(self):
        a = build_catalog(include_generated_at=False)
        b = build_catalog(include_generated_at=False)
        assert a == b
        assert a["count"] == len(SHORTLINE_ENDPOINTS)
        assert a["validation"]["ok"] is True
        assert [e["id"] for e in a["endpoints"]] == sorted(SHORTLINE_ENDPOINTS)

    def test_markdown_contains_all_endpoints(self):
        text = render_markdown(build_catalog(include_generated_at=False))
        for endpoint in SHORTLINE_ENDPOINTS.values():
            assert endpoint.id in text
            assert endpoint.mcp_tool in text
            assert endpoint.rest_path in text

    def test_write_catalog_is_idempotent(self, tmp_path):
        target = tmp_path / "SHORTLINE.md"
        assert write_catalog(target) is True
        content = target.read_text(encoding="utf-8")
        assert write_catalog(target) is False
        assert target.read_text(encoding="utf-8") == content

    def test_catalog_is_json_safe(self):
        json.dumps(build_catalog(), ensure_ascii=False)


class TestThreeConsumers:
    """元数据可被 MCP / REST / 文档三方读取。"""

    def test_mcp_tool_returns_catalog(self):
        from mcp.server.fastmcp import FastMCP
        from tradex.tools.shortline import register

        mcp = FastMCP("test_shortline_meta")
        register(mcp)
        fn = mcp._tool_manager._tools["get_shortline_catalog"].fn
        payload = json.loads(asyncio.run(fn()))
        assert payload["count"] == len(SHORTLINE_ENDPOINTS)
        assert payload["schema_version"] == "1.0"
        assert any(e["id"] == "shortline.daily" for e in payload["endpoints"])

    def test_rest_route_returns_catalog(self):
        app = FastAPI()
        app.include_router(rest_routes.router, prefix="/api/v1")
        client = TestClient(app)
        resp = client.get("/api/v1/shortline/catalog")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["count"] == len(SHORTLINE_ENDPOINTS)

    def test_docs_script_output_matches_render(self, tmp_path, monkeypatch):
        """文档渲染与 CATALOG 渲染同源（同一函数，不存在第二份口径）。"""
        target = tmp_path / "doc.md"
        write_catalog(target)
        assert target.read_text(encoding="utf-8") == render_markdown(
            build_catalog(include_generated_at=False)
        )


class TestComputeRefs:
    """已实现端点的 compute 引用必须真实存在（planned 不检查）。"""

    def test_planned_endpoints_have_no_broken_compute_refs(self):
        # H1 阶段所有端点均为 planned，检查结果应为空
        assert missing_compute_refs() == []
