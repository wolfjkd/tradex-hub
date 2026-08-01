"""
Tests for price_data tools (Category 2).
"""

import json

import pytest


@pytest.mark.network
class TestGetRealtimeQuote:
    async def test_basic(self):
        from tradex.tools.price_data import register
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register(mcp)
        fn = mcp._tool_manager._tools["get_realtime_quote"].fn
        result = await fn(symbol="600519")
        data = json.loads(result)
        assert isinstance(data, list)
        assert len(data) > 0

    async def test_invalid_symbol(self):
        from tradex.tools.price_data import register
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register(mcp)
        fn = mcp._tool_manager._tools["get_realtime_quote"].fn
        result = await fn(symbol="999999")
        data = json.loads(result)
        # Should return an error or empty result
        assert isinstance(data, (list, dict))


@pytest.mark.network
class TestGetHistoricalPrice:
    async def test_basic(self):
        from tradex.tools.price_data import register
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register(mcp)
        fn = mcp._tool_manager._tools["get_historical_price"].fn
        result = await fn(
            symbol="600519",
            period="daily",
            start_date="20250101",
            end_date="20250131",
        )
        data = json.loads(result)
        assert isinstance(data, list)
        assert len(data) > 0
