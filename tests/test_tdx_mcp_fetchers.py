"""
tdx_mcp_fetchers 单元测试。

锁行为（TDD）：
  - token（TDX_MCP_TOKEN）缺失时：fetch_* 抛 TDXSourceUnavailable（RuntimeError 子类），
    供 SmartRouter 当作源失败自动切到 eltdx（非独占、自动降级）。
  - token 存在时：能构造客户端，走 MCP JSON-RPC 2.0 streamable-HTTP；
    端点可用 TDX_MCP_ENDPOINT 覆盖，默认指向 txmcp.tdx.com.cn。
  - 兼容 symbol/code 两种参数名。
  - _parse_mcp_response 兼容纯 JSON 与 SSE 流。
"""

import os
import sys
from unittest import mock

import pytest

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "..", "tradex", "src"))

from tradex.data_sources import tdx_mcp_fetchers as tdxf  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("TDX_MCP_TOKEN", "TDX_MCP_ENDPOINT"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(tdxf, "_CLIENT", None)
    yield


class TestTokenMissingDegradation:
    def test_realtime_raises(self):
        with pytest.raises(RuntimeError):
            tdxf.fetch_realtime_quote(symbol="600519")

    def test_screener_raises(self):
        with pytest.raises(RuntimeError):
            tdxf.fetch_screener(query="市盈率低于20且ROE高于15%")

    def test_research_raises(self):
        with pytest.raises(RuntimeError):
            tdxf.fetch_research_report(code="600519")

    def test_error_is_tdxsourceunavailable_for_clean_degrade(self):
        # 断言确实是 TDXSourceUnavailable（RuntimeError 子类），语义明确
        with pytest.raises(tdxf.TDXSourceUnavailable):
            tdxf.fetch_realtime_quote(symbol="600519")


class TestTokenPresentClient:
    def test_client_uses_env_token_and_endpoint(self, monkeypatch):
        monkeypatch.setenv("TDX_MCP_TOKEN", "secret")
        monkeypatch.setenv("TDX_MCP_ENDPOINT", "https://txmcp.tdx.com.cn:3001/txmcp")
        cli = tdxf._get_client()
        assert cli is not None
        assert cli.endpoint.endswith("/txmcp")
        assert cli.headers.get("Authorization") == "Bearer secret"

    def test_default_endpoint_targets_tdx(self, monkeypatch):
        monkeypatch.setenv("TDX_MCP_TOKEN", "secret")
        cli = tdxf._get_client()
        assert "txmcp.tdx.com.cn" in cli.endpoint


class TestParamCompatAndWire:
    def test_symbol_and_code_both_pass_through(self, monkeypatch):
        monkeypatch.setenv("TDX_MCP_TOKEN", "secret")
        cli = tdxf._get_client()
        # mock 一个返回“响应对象”（有 .text/.headers/.json）的 post
        resp = mock.Mock()
        resp.text = '{"result":{"content":[{"type":"text","text":"[]"}]}}'
        resp.headers = {}

        def fake_post(*args, **kwargs):
            return resp

        cli._client.post = fake_post
        out_sym = tdxf.fetch_realtime_quote(symbol="600519")
        out_code = tdxf.fetch_realtime_quote(code="600519")
        assert out_sym is not None
        assert out_code is not None

    def test_parse_mcp_json(self):
        assert tdxf._parse_mcp_response('{"result":{"ok":1}}') == {"result": {"ok": 1}}

    def test_parse_mcp_sse_stream(self):
        sse = 'event: message\ndata: {"jsonrpc":"2.0","result":{"x":1}}\n\ndata: {"jsonrpc":"2.0","result":{"x":2}}\n'
        parsed = tdxf._parse_mcp_response(sse)
        # 取最后一个 data 块
        assert parsed.get("result") == {"x": 2}