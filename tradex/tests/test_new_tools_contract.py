"""工单 T35 测试：新增 MCP 工具契约（10 个模块 33 个工具）。

验证：
- 工具全部注册成功
- 工具函数可调用（用 mock 跳过真实网络）
- 返回 JSON 可解析
- 错误响应也走 JSON 而非抛异常
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest


def _make_mock_router():
    """构造一个永远返回空 DataFrame 的 mock router。"""
    mock = MagicMock()
    mock.route.return_value = (pd.DataFrame(), "mock_source")
    return mock


@pytest.fixture(autouse=True)
def _ensure_registered():
    from tradex.data_sources import register_all_sources
    register_all_sources()


def _get_tool_fn(mcp_instance, name: str):
    """从 FastMCP 实例取出工具的底层函数。"""
    return mcp_instance._tool_manager._tools[name].fn


class TestNewToolsRegistration:
    """23 个新工具全部成功注册到 mcp。

    2026-09-28 死源剥离：etf_option(2) / index_tracking(3) /
    investor_interaction(2) / macro_official 的 social+repo+lpr(3) 共 10 个
    工具已随上游死源移除。
    """

    NEW_TOOLS = [
        # event_driven.py (6)
        "get_earnings_forecast", "get_institution_survey", "get_holder_trades",
        "get_share_buyback", "get_equity_pledge", "get_ipo_calendar",
        # macro_official.py (2)
        "get_pmi", "get_bond_yield_curve_official",
        # global_market_news.py (3)
        "get_wallstreetcn_lives", "get_macro_calendar", "get_cctv_news",
        # sw_industry_history.py (2)
        "get_sw_industry_history", "get_sw_industry_as_of",
        # backup_source_tools.py (4)
        "get_sina_research_reports", "get_sina_fund_flow",
        "get_baidu_kline", "get_baostock_valuation",
        # exchange_official.py (4)
        "get_sse_dragon_tiger", "get_szse_dragon_tiger",
        "get_cninfo_announcement_backup", "get_trading_calendar",
        # industry_news.py (2)
        "get_industry_news", "list_industry_tracks",
    ]

    def test_all_new_tools_registered(self):
        from mcp.server.fastmcp import FastMCP
        import tradex.tools as tools_pkg
        from tradex.tools.registry import ToolRegistry

        mcp = FastMCP("contract_test")
        ToolRegistry.discover_and_register(tools_package=tools_pkg, mcp=mcp)

        registered = set(mcp._tool_manager._tools.keys())
        missing = [n for n in self.NEW_TOOLS if n not in registered]
        assert not missing, f"未注册的工具: {missing}"


class TestIndustryNewsTools:
    """industry_news 工具调用契约。"""

    def test_list_industry_tracks_returns_json(self):
        from mcp.server.fastmcp import FastMCP
        from tradex.tools.industry_news import register
        mcp = FastMCP("test_ind_news")
        register(mcp)
        fn = _get_tool_fn(mcp, "list_industry_tracks")
        result = asyncio.run(fn())
        data = json.loads(result)
        assert isinstance(data, dict)
        assert "tracks" in data
        assert "source_count" in data
        assert data["source_count"] == 106
        assert data["frozen_at"] == "2026-09-23"

    def test_get_industry_news_unknown_track(self):
        from mcp.server.fastmcp import FastMCP
        from tradex.tools.industry_news import register
        mcp = FastMCP("test_ind_news_2")
        register(mcp)
        fn = _get_tool_fn(mcp, "get_industry_news")
        result = asyncio.run(fn(track="not_a_track", days=1, per_source=1))
        data = json.loads(result)
        # 未知赛道应返回 error 响应（而非抛异常）
        assert data.get("error") is True or "未知赛道" in str(data)


class TestBackupSourceToolsContract:
    """backup_source_tools 工具调用走 mock 不真实连网。"""

    def test_sina_research_reports_mock(self):
        from mcp.server.fastmcp import FastMCP
        from tradex.tools.backup_source_tools import register
        mcp = FastMCP("test_backup")
        register(mcp)
        fn = _get_tool_fn(mcp, "get_sina_research_reports")
        with patch("tradex.tools.backup_source_tools._router") as mock_r:
            mock_r.route.return_value = (
                pd.DataFrame([{"标题": "测试研报", "机构": "XX证券"}]),
                "sina_research",
            )
            result = asyncio.run(fn(symbol="600519", page=1, page_size=5))
            data = json.loads(result)
            # df_to_json 返回 list of dict 或 dict（非 error）
            assert not (isinstance(data, dict) and data.get("error")), \
                f"工具不应返回 error: {data}"


class TestExchangeOfficialToolsContract:
    """exchange_official 工具调用走 mock。"""

    def test_get_trading_calendar_mock(self):
        from mcp.server.fastmcp import FastMCP
        from tradex.tools.exchange_official import register
        mcp = FastMCP("test_exchange")
        register(mcp)
        fn = _get_tool_fn(mcp, "get_trading_calendar")
        with patch("tradex.tools.exchange_official._router") as mock_r:
            mock_r.route.return_value = (
                pd.DataFrame([{"日期": "2026-01-02", "是否交易日": "是"}]),
                "szse_official",
            )
            result = asyncio.run(fn(year=2026, month=1))
            data = json.loads(result)
            assert not (isinstance(data, dict) and data.get("error")), \
                f"工具不应返回 error: {data}"


