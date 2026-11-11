"""MCP 工具可见性中文分组目录（单一真源，2026-11-08）。

GROUPS：（中文名, 一句话说明, [工具名...])，26 组覆盖 190 工具——
与 docs/MCP_TOOLS.md 全集 diff 对齐（有 CI 外的脚本核对）。
消费方：scripts/mcp_profile.py（一键 CLI）、TradeX 看板 MCP 工具页。

预设：lean = 精简一档（禁宏观/转债ETF/备源/三表/基本面低频/事件低频/
产业链/eltdx 冷门/运维重复九组）；lean80 = lean + 二段 34 个观察档。
"""

from __future__ import annotations

GROUPS: list[tuple[str, str, list[str]]] = [
    ("行情与个股", "实时行情/K线/分时/市值/指数快照与量能", [
        "get_realtime_quote", "get_historical_price", "get_intraday_data",
        "get_market_capitalization", "get_stock_list",
        "get_market_overview", "get_index_volume_compare",
    ]),
    ("公司信息", "基本信息/主营/可比公司/搜索", [
        "search_stock", "get_company_info", "get_company_profile", "get_competitors",
    ]),
    ("板块与行业", "概念/行业列表与成分/行业PE/板块资金", [
        "get_concept_list", "get_industry_list", "get_industry_stocks", "get_industry_pe",
        "get_sector_fund_flow",
    ]),
    ("涨停与情绪", "涨停池/打板情绪/涨停揭秘", [
        "get_limit_up_down", "get_limit_up_board", "get_board_sentiment", "get_limit_up_insight",
    ]),
    ("KPL 开盘啦", "涨停复盘/市场情绪/精选板块/竞价委买额（免鉴权直连）", [
        "get_kpl_limit_up", "get_kpl_sentiment", "get_kpl_boards", "get_kpl_bidding",
    ]),
    ("短线读数（复盘主力）", "情绪四项/每日读数/周期/梯队/题材/首板/成交额榜等", [
        "get_shortline_emotion", "get_shortline_daily", "get_shortline_cycle",
        "get_shortline_live", "get_shortline_settled", "get_shortline_ladder",
        "get_shortline_board_ladder", "get_shortline_structure", "get_shortline_firstboard",
        "get_shortline_facts", "get_shortline_themes", "get_shortline_theme_rotation",
        "get_shortline_history", "get_shortline_bigcaps", "get_shortline_turnover_top",
        "get_shortline_catalog", "get_shortline_field_drift",
        "shortline_close_fetch",  # 收盘落库：TradeX scheduler 进程内在用
    ]),
    ("资金与龙虎榜", "个股资金/北向/龙虎榜聚合与席位", [
        "get_money_flow", "get_fund_flow_signal", "get_north_bound_flow",
        "get_northbound_flow_signal", "get_dragon_tiger", "get_dragon_tiger_signal",
        "get_dragon_tiger_detail", "get_dragon_tiger_seat_detail",
        "get_industry_comparison_signal", "get_holder_trades",
    ]),
    ("新闻与热度", "财联社电报/个股新闻/问财查询/人气榜", [
        "get_telegraph_news", "get_stock_news", "search_news", "get_wencai_query",
        "get_hot_rank", "get_hot_search", "get_xueqiu_hot", "get_hot_keywords",
        "get_hot_stocks", "get_company_announcements", "get_market_sentiment",
    ]),
    ("技术指标计算", "MACD/KDJ/BOLL/RSI/MA-EMA/ATR", [
        "calculate_macd", "calculate_kdj", "calculate_boll", "calculate_rsi",
        "calculate_ma_ema", "calculate_atr",
    ]),
    ("选股与信号", "条件选股/因子/交易信号/个股综合/技术分析", [
        "screen_stocks", "get_screening_conditions", "calculate_factor_score",
        "get_factor_catalog", "generate_trading_signal", "scan_stocks_for_signals",
        "validate_signal_quality", "analyze_stock_comprehensive", "analyze_technical",
        "analyze_market_overview", "analyze_industry_comparison",
    ]),
    ("eltdx 通达信独有", "集合竞价/逐笔/盘口/短线打板指标/F10（协议独有）", [
        "eltdx_get_auction", "eltdx_get_auction_data", "eltdx_get_opening_match",
        "eltdx_get_ticks", "eltdx_get_today_ticks", "eltdx_get_depth",
        "eltdx_get_minutes", "eltdx_get_minute_history",
        "eltdx_get_shortline_indicators", "eltdx_get_f10",
        "eltdx_get_stock_topics", "eltdx_get_topic_stocks",
        "eltdx_get_buy_sell_strength",  # 日内买卖强度（eltdx 独有）
        "eltdx_get_stock_profile",  # 个股全景档案
        "eltdx_get_kline", "eltdx_get_special_limits", "eltdx_get_security_codes",
    ]),
    ("本地与通达信生态", "本地K线(离线回测)/自然语言选股/公式/L2/研报", [
        "get_local_kline", "get_local_minute", "natural_lang_screener",
        "run_tdx_formula", "get_l2_stats", "research_report",
    ]),
    ("财务与基本面", "财务指标/成长/每股/主营构成", [
        "get_financial_indicators", "get_growth_rates", "get_per_share_data",
        "get_segments_revenue",
    ]),
    ("信号基础", "技术指标路由/概念归属", [
        "get_technical_indicator", "list_technical_indicators", "get_concept_attribution",
    ]),
    ("交易日历与官方", "交易日历（深交所官方主源）", [
        "get_trading_calendar",
    ]),
    ("绩效与统计", "策略绩效指标（回测期用）", [
        "calculate_performance", "list_performance_metrics",
    ]),
    ("系统诊断", "健康检查/数据源健康/工具清单", [
        "health_check", "get_data_source_health", "list_all_tools",
    ]),
    ("宏观与全球（低频）", "宏观指标/全球行情/债收益率/外汇/期货新闻", [
        "get_macro_cpi", "get_macro_gdp", "get_macro_money_supply", "get_macro_pmi",
        "get_pmi", "get_bond_yield_curve", "get_bond_yield_curve_official",
        "get_index_valuation",
        "get_index_constituents",
        "get_fx_rate", "get_futures_news", "get_global_market_quote",
        "get_wallstreetcn_lives", "get_macro_calendar", "query_macro_indicator",
        "get_cctv_news",
    ]),
    ("可转债与ETF（低频）", "转债行情/价值分析/ETF行情", [
        "get_cb_realtime_data", "get_cb_value_analysis_data",
        "get_etf_realtime_data", "get_etf_kline_data",
    ]),
    ("备源直取（不建议）", "绕过 router 直取百度/baostock/新浪", [
        "get_baidu_kline", "get_baostock_valuation", "get_sina_fund_flow",
        "get_sina_research_reports",
    ]),
    ("财务三表原文（低频）", "三大报表逐季原文，问基本面用聚合指标即可", [
        "get_balance_sheet", "get_income_statement", "get_cash_flow_statement",
    ]),
    ("基本面低频族（低频）", "分析师评级/分红/质押/回购/预告/估值/机构持仓", [
        "get_analyst_rating", "get_dividend_data", "get_equity_pledge",
        "get_share_buyback", "get_earnings_forecast", "get_valuation_metrics",
        "get_institutional_holdings", "get_fund_hold", "get_profit_forecast",
    ]),
    ("事件驱动低频（低频）", "大宗交易/龙虎榜统计/质押/调研/IPO/两融账户", [
        "get_block_trade_daily_stat", "get_block_trade_detail",
        "get_block_trade_market_stat", "get_dragon_tiger_branch_rank",
        "get_dragon_tiger_institution", "get_dragon_tiger_stock_stats",
        "get_unusual_fluctuation", "get_institution_survey",
        "get_margin_account_info", "get_margin_target_list", "get_margin_trading",
        "get_ipo_calendar", "get_lockup_expiry",
    ]),
    ("产业链与行业史（低频）", "106 源产业链/申万变迁史/深交所公告备源", [
        "get_industry_news", "list_industry_tracks", "get_sw_industry_as_of",
        "get_sw_industry_history", "get_cninfo_announcement_backup",
    ]),
    ("eltdx 冷门 F10（低频）", "股本/分红/北向持股/报表/历史撮合/复权K线等", [
        "eltdx_get_capital_changes", "eltdx_get_dividend_financing",
        "eltdx_get_northbound_holding", "eltdx_get_f10_extra",
        "eltdx_get_finance_report", "eltdx_get_finance_batch",
        "eltdx_get_company_news", "eltdx_get_opening_match_history",
        "eltdx_get_full_kline", "eltdx_get_adjusted_kline",
        "eltdx_get_category_quotes", "eltdx_get_special_limits_scan",
        "eltdx_get_trading_day", "eltdx_stream_health",
    ]),
    ("运维与重复（低频）", "缓存统计/看板/交易所官方龙虎榜/待配新闻/重复股东", [
        "get_cache_stats", "get_data_source_dashboard", "get_sse_dragon_tiger",
        "get_szse_dragon_tiger", "get_wencai_news", "get_insider_trading",
        "get_financial_line_item", "get_financial_calendar",
    ]),
]

# --------------------------------------------------------------- 预设

# lean = 精简一档（Obsidian《MCP工具精简启停清单》第一段 73 个）
LEAN_DISABLE = [
    "宏观与全球（低频）", "可转债与ETF（低频）", "备源直取（不建议）",
    "财务三表原文（低频）", "基本面低频族（低频）", "事件驱动低频（低频）",
    "产业链与行业史（低频）", "eltdx 冷门 F10（低频）", "运维与重复（低频）",
]

# lean80 = 二段（再禁 34：观察档 6 + 保留段低频 28）
LEAN80_EXTRA = [
    "get_dragon_tiger_seat_detail", "get_dragon_tiger_detail", "shortline_close_fetch",
    "eltdx_get_special_limits", "eltdx_get_security_codes", "eltdx_get_kline",
    "get_competitors", "get_industry_pe", "get_stock_list", "get_market_sentiment",
    "get_hot_keywords", "get_xueqiu_hot", "get_hot_search",
    "list_technical_indicators", "get_factor_catalog", "get_screening_conditions",
    "list_performance_metrics", "list_all_tools", "get_local_minute",
    "eltdx_get_auction_data", "eltdx_get_minute_history",
    "eltdx_get_stock_topics", "eltdx_get_topic_stocks",
    "analyze_industry_comparison", "analyze_stock_comprehensive",
    "run_tdx_formula", "get_l2_stats", "natural_lang_screener",
    "research_report", "get_per_share_data", "get_growth_rates", "calculate_atr",
    "analyze_market_overview", "get_industry_stocks",
]

ALL_TOOLS: list[str] = [t for _t, _d, _ts in GROUPS for t in _ts]
LEAN_DISABLE_GROUPS: tuple[str, ...] = (
    "宏观与全球（低频）", "可转债与ETF（低频）", "备源直取（不建议）",
    "财务三表原文（低频）", "基本面低频族（低频）", "事件驱动低频（低频）",
    "产业链与行业史（低频）", "eltdx 冷门 F10（低频）", "运维与重复（低频）",
)


def lean_hidden() -> list[str]:
    """lean 预设的隐藏名单（组名展开）。"""
    hidden: set[str] = set()
    for target in LEAN_DISABLE_GROUPS:
        for title, _desc, tools in GROUPS:
            if title == target:
                hidden.update(tools)
                break
    return sorted(hidden)


LEAN80_EXTRA: tuple[str, ...] = (
    "get_dragon_tiger_seat_detail", "get_dragon_tiger_detail", "shortline_close_fetch",
    "eltdx_get_special_limits", "eltdx_get_security_codes", "eltdx_get_kline",
    "get_competitors", "get_industry_pe", "get_stock_list", "get_market_sentiment",
    "get_hot_keywords", "get_xueqiu_hot", "get_hot_search",
    "list_technical_indicators", "get_factor_catalog", "get_screening_conditions",
    "list_performance_metrics", "list_all_tools", "get_local_minute",
    "eltdx_get_auction_data", "eltdx_get_minute_history",
    "eltdx_get_stock_topics", "eltdx_get_topic_stocks",
    "analyze_industry_comparison", "analyze_stock_comprehensive",
    "run_tdx_formula", "get_l2_stats", "natural_lang_screener",
    "research_report", "get_per_share_data", "get_growth_rates", "calculate_atr",
    "analyze_market_overview", "get_industry_stocks",
)


def lean80_hidden() -> list[str]:
    """lean80 预设 = lean ∪ 二段观察档。"""
    return sorted(set(lean_hidden()) | set(LEAN80_EXTRA))
