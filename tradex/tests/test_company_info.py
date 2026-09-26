"""
Tests for company_info tools (Category 1).

These tests verify the tool functions can be called and return valid JSON.
Note: Tests that call AKShare require network access and may be slow.
Mark them with @pytest.mark.network to skip in CI.
"""

import json

import pytest


@pytest.mark.network
class TestSearchStock:
    async def test_search_by_name(self):
        from tradex.tools.company_info import register
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register(mcp)
        fn = mcp._tool_manager._tools["search_stock"].fn
        result = await fn(keyword="茅台")
        print(f"\n[search_by_name] raw result:\n{result[:500]}")
        data = json.loads(result)
        print(f"[search_by_name] type={type(data).__name__}, keys={list(data.keys()) if isinstance(data, dict) else 'N/A'}")
        if isinstance(data, dict) and data.get("error"):
            pytest.skip(f"Network error: {data['message'][:100]}")
        # v3.4.0 起 service 层返回 dict: {keyword, matches, source}
        assert isinstance(data, dict), f"Expected dict, got {type(data).__name__}: {result[:200]}"
        assert "matches" in data, f"Missing 'matches' key: {list(data.keys())}"
        assert len(data["matches"]) > 0, "Expected non-empty matches for '茅台'"

    async def test_search_by_code(self):
        from tradex.tools.company_info import register
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register(mcp)
        fn = mcp._tool_manager._tools["search_stock"].fn
        result = await fn(keyword="600519")
        print(f"\n[search_by_code] raw result:\n{result[:500]}")
        data = json.loads(result)
        print(f"[search_by_code] type={type(data).__name__}, keys={list(data.keys()) if isinstance(data, dict) else 'N/A'}")
        if isinstance(data, dict) and data.get("error"):
            pytest.skip(f"Network error: {data['message'][:100]}")
        assert isinstance(data, dict), f"Expected dict, got {type(data).__name__}: {result[:200]}"
        assert "matches" in data
        assert len(data["matches"]) > 0, "Expected non-empty matches for '600519'"

    async def test_search_no_results(self):
        from tradex.tools.company_info import register
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register(mcp)
        fn = mcp._tool_manager._tools["search_stock"].fn
        result = await fn(keyword="zzzzzzzzzz_no_match")
        print(f"\n[search_no_results] raw result:\n{result[:500]}")
        data = json.loads(result)
        print(f"[search_no_results] type={type(data).__name__}")
        if isinstance(data, dict) and data.get("error"):
            pytest.skip(f"Network error: {data['message'][:100]}")
        assert isinstance(data, dict), f"Expected dict, got {type(data).__name__}: {result[:200]}"
        assert "matches" in data
        assert len(data["matches"]) == 0, f"Expected empty matches, got {len(data['matches'])}"


@pytest.mark.network
class TestGetCompanyInfo:
    async def test_basic(self):
        from tradex.tools.company_info import register
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register(mcp)
        fn = mcp._tool_manager._tools["get_company_info"].fn
        result = await fn(symbol="600519")
        print(f"\n[get_company_info] raw result:\n{result[:500]}")
        data = json.loads(result)
        print(f"[get_company_info] type={type(data).__name__}, keys={list(data.keys())[:5] if isinstance(data, dict) else 'N/A'}")
        if isinstance(data, dict) and data.get("error"):
            pytest.skip(f"Network error: {data['message'][:100]}")
        assert isinstance(data, dict), f"Expected dict, got {type(data).__name__}: {result[:200]}"
        assert len(data) > 0, "Expected non-empty company info"
