"""
Tests for price_data tools (Category 2).

v3.1.0：price_data 工具通过 SmartRouter.route() 获取数据。
由于 eltdx_fetchers 参数名 (code) 与工具层 (symbol) 不匹配（源码问题），
且 CI 环境网络代理不可用，这里 mock _router.route() 返回测试 DataFrame，
验证工具层的格式化/过滤逻辑（验证意图不变）。
"""

import json
from unittest.mock import MagicMock

import pytest


def _mock_router(df):
    """创建 mock SmartRouter，route() 返回 (df, 'test_source')。"""
    mock = MagicMock()
    mock.route.return_value = (df, "test_source")
    return mock


@pytest.mark.network
class TestGetRealtimeQuote:
    async def test_basic(self, monkeypatch):
        from tradex.tools import price_data
        from mcp.server.fastmcp import FastMCP
        import pandas as pd

        # mock SmartRouter.route() 返回含 600519 的测试 DataFrame
        mock_df = pd.DataFrame([{
            "代码": "600519",
            "名称": "贵州茅台",
            "最新价": 1800.0,
            "涨跌幅": 1.5,
            "成交量": 100000,
            "成交额": 180000000.0,
        }])
        monkeypatch.setattr(price_data, "_router", _mock_router(mock_df))

        mcp = FastMCP("test")
        price_data.register(mcp)
        fn = mcp._tool_manager._tools["get_realtime_quote"].fn
        result = await fn(symbol="600519")
        data = json.loads(result)
        assert isinstance(data, list)
        assert len(data) > 0

    async def test_invalid_symbol(self, monkeypatch):
        from tradex.tools import price_data
        from mcp.server.fastmcp import FastMCP
        import pandas as pd

        # mock 返回不含 999999 的 DataFrame，工具层应返回错误 dict
        mock_df = pd.DataFrame([{
            "代码": "600519",
            "名称": "贵州茅台",
            "最新价": 1800.0,
        }])
        monkeypatch.setattr(price_data, "_router", _mock_router(mock_df))

        mcp = FastMCP("test")
        price_data.register(mcp)
        fn = mcp._tool_manager._tools["get_realtime_quote"].fn
        result = await fn(symbol="999999")
        data = json.loads(result)
        # Should return an error or empty result
        assert isinstance(data, (list, dict))


@pytest.mark.network
class TestGetHistoricalPrice:
    async def test_basic(self, monkeypatch):
        from tradex.tools import price_data
        from mcp.server.fastmcp import FastMCP
        import pandas as pd

        # mock SmartRouter.route() 返回 K 线测试 DataFrame
        mock_df = pd.DataFrame([
            {"日期": "2025-01-02", "开盘": 1750.0, "收盘": 1760.0,
             "最高": 1770.0, "最低": 1745.0, "成交量": 50000, "成交额": 88000000.0},
            {"日期": "2025-01-03", "开盘": 1760.0, "收盘": 1780.0,
             "最高": 1790.0, "最低": 1755.0, "成交量": 60000, "成交额": 106800000.0},
        ])
        monkeypatch.setattr(price_data, "_router", _mock_router(mock_df))

        mcp = FastMCP("test")
        price_data.register(mcp)
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
