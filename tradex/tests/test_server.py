"""
Tests for the MCP server setup and tool registration.
"""

import pytest


class TestServerSetup:
    def test_server_name(self, mcp_server):
        assert mcp_server.name == "tradex"

    def test_all_192_tools_registered(self, mcp_server):
        """2026-09-28 死源剥离: 176→166 tools.
        历史：129→132→165→176→166 (数据源扩充 T01-T33 → akshare_em 包装层 →
        死源剥离移除期权 2 + 指数 3 + 互动 2 + 宏观 3) → 186（2026-11-06
        vibe-astock 借鉴批次：短线元数据 1 + 大市值 1 + 成交额榜 1 + 读数 8 +
        落库 2 + 题材 4 + 字段漂移 1）→ 190（2026-11-07 KPL 批次 +4：
        limit_up/sentiment/boards/bidding）.
        数量精确锁定，版本演进需同步更新本断言。
        测试名 90→192 名实对齐（QI-ARCH-16，2026-11-22：断言早已 192，名沿旧账）。"""
        tools = mcp_server._tool_manager._tools
        assert len(tools) == 192, f"Expected 192 tools, got {len(tools)}"

    # ── V0.1–V0.6 六批手抄清单（QI-ARCH-16 处置注记，2026-11-22）──────────
    # 清单性质：按历史交付批次（V0.1–V0.6）逐批回归守卫——每批交付的工具必须
    # 仍在册；与 visibility_catalog.GROUPS 的功能归组不同轴（GROUPS 无批次
    # 维度），集合断言不能等价替代其「这 64 个历史工具永不消失」的承诺。
    # 保守路径（票文预案）：名单保留原地不裁剪，是否退役待总控裁决；
    # 漂移史与三处手抄同步问题见台账 .scratch/qc-20261122/ledger.md QI-ARCH-16。
    def test_v01_tools_present(self, mcp_server):
        """V0.1 company info + price data tools (8 tools)."""
        tools = mcp_server._tool_manager._tools
        v01_tools = [
            "search_stock",
            "get_company_info",
            "get_company_profile",
            "get_competitors",
            "get_realtime_quote",
            "get_historical_price",
            "get_market_capitalization",
            "get_stock_list",
        ]
        for tool_name in v01_tools:
            assert tool_name in tools, f"V0.1 tool '{tool_name}' not registered"

    def test_v02_tools_present(self, mcp_server):
        """V0.2 financial statements + valuation tools (12 tools)."""
        tools = mcp_server._tool_manager._tools
        v02_tools = [
            "get_income_statement",
            "get_balance_sheet",
            "get_cash_flow_statement",
            "get_financial_line_item",
            "get_financial_indicators",
            "get_growth_rates",
            "get_per_share_data",
            "get_segments_revenue",
            "get_valuation_metrics",
            "get_dividend_data",
            "get_institutional_holdings",
            "get_analyst_rating",
        ]
        for tool_name in v02_tools:
            assert tool_name in tools, f"V0.2 tool '{tool_name}' not registered"

    def test_v03_tools_present(self, mcp_server):
        """V0.3 industry + market + news tools (14 tools)."""
        tools = mcp_server._tool_manager._tools
        v03_tools = [
            "get_industry_list",
            "get_industry_stocks",
            "get_concept_list",
            "get_sector_fund_flow",
            "get_industry_pe",
            "get_market_overview",
            "get_money_flow",
            "get_north_bound_flow",
            "get_limit_up_down",
            "get_dragon_tiger",
            "get_stock_news",
            "get_financial_calendar",
            "get_company_announcements",
            "search_news",
        ]
        for tool_name in v03_tools:
            assert tool_name in tools, f"V0.3 tool '{tool_name}' not registered"

    def test_v04_tools_present(self, mcp_server):
        """V0.4 macro & FX tools (8 tools)."""
        tools = mcp_server._tool_manager._tools
        v04_tools = [
            "get_macro_gdp",
            "get_macro_cpi",
            "get_macro_pmi",
            "get_macro_money_supply",
            "get_fx_rate",
            "get_bond_yield_curve",
            "get_margin_trading",
            "get_insider_trading",
        ]
        for tool_name in v04_tools:
            assert tool_name in tools, f"V0.4 tool '{tool_name}' not registered"

    def test_v05_signal_data_tools_present(self, mcp_server):
        """V0.5 signal data tools (17 tools)."""
        tools = mcp_server._tool_manager._tools
        v05_tools = [
            "get_hot_stocks",
            "get_lockup_expiry",
            "get_concept_attribution",
            "get_profit_forecast",
            "get_technical_indicator",
            "list_technical_indicators",
            "get_northbound_flow_signal",
            "get_fund_flow_signal",
            "get_dragon_tiger_signal",
            "get_industry_comparison_signal",
            "get_etf_realtime_data",
            "get_etf_kline_data",
            "get_cb_realtime_data",
            "get_cb_value_analysis_data",
            "get_limit_up_board",
            "get_board_sentiment",
            "get_limit_up_insight",
        ]
        for tool_name in v05_tools:
            assert tool_name in tools, f"V0.5 tool '{tool_name}' not registered"

    def test_v06_eltdx_tools_present(self, mcp_server):
        """V0.6 eltdx tools (5 tools)."""
        tools = mcp_server._tool_manager._tools
        v06_tools = [
            "eltdx_get_auction",
            "eltdx_get_ticks",
            "eltdx_get_f10",
            "eltdx_get_minutes",
            "eltdx_get_kline",
        ]
        for tool_name in v06_tools:
            assert tool_name in tools, f"V0.6 tool '{tool_name}' not registered"

    def test_tool_count_per_version(self, mcp_server):
        """SP-2026-10-13-001: tq 源工具 +2 (166→168)；2026-11-06 shortline 批次 +18（168→186）；
        2026-11-08 中证估值复活 +1（190→191）；2026-11-11 裁决① index_constituents 暴露 +1（191→192）.
        防重复注册回归。版本演进需同步更新本断言。"""
        tools = mcp_server._tool_manager._tools
        assert len(tools) == 192

    # ── QI-ARCH-16 集合断言（2026-11-22）：visibility_catalog.GROUPS ↔ 注册全集
    #    对账单点化——GROUPS 是 mcp_profile/TradeX 看板共用分组数据（自称单一
    #    真源），目录与注册表双向对齐后，加/删/改名工具只对 GROUPS 一处记账，
    #    测试侧不再新增手抄名单。
    def test_visibility_catalog_subset_of_registered(self, mcp_server):
        """GROUPS 目录工具必须全部真实在册（目录 ⊆ 注册全集）。

        目录漂移（注册侧改名/删除而目录未同步）在此红——lean 预设按目录
        隐藏工具，目录含死名 = 隐藏动作空转、看板出死条目。"""
        from tradex.tools.visibility_catalog import ALL_TOOLS
        tools = mcp_server._tool_manager._tools
        catalog = set(ALL_TOOLS)
        missing = sorted(catalog - set(tools))
        assert not missing, f"GROUPS 目录含未注册工具: {missing}"

    def test_visibility_catalog_covers_registered(self, mcp_server):
        """注册全集必须全部归组入目录（AGENTS.md 硬约定 8：加 MCP 工具后在此归组）。

        新增工具不入 GROUPS = mcp_profile/TradeX 看板工具页缺席，此处红。"""
        from tradex.tools.visibility_catalog import ALL_TOOLS
        tools = mcp_server._tool_manager._tools
        uncataloged = sorted(set(tools) - set(ALL_TOOLS))
        assert not uncataloged, f"注册工具未归组入 visibility_catalog: {uncataloged}"

    def test_visibility_catalog_counts(self, mcp_server):
        """目录计数断言（2026-11-22 实跑口径）：26 组 / 192 项 / 目录无重复。

        与 tests/test_dashboard_mcp.py::test_catalog_shape（dashboard 推导路径）
        互为双保险；此处直测 GROUPS/ALL_TOOLS 数据本体。"""
        from tradex.tools.visibility_catalog import ALL_TOOLS, GROUPS
        assert len(GROUPS) == 26, f"GROUPS 组数漂移: {len(GROUPS)}"
        assert len(ALL_TOOLS) == 192, f"GROUPS 目录工具项数漂移: {len(ALL_TOOLS)}"
        assert len(set(ALL_TOOLS)) == len(ALL_TOOLS), "GROUPS 目录有重复工具名"
