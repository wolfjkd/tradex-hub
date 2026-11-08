#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tradex-hub MCP 工具一键启停（中文 CLI，2026-11-08 老板需求）。

用法（在 tradex-hub 目录下，用任意本机 Python 跑均可）：
    python scripts/mcp_profile.py list            # 按中文分组查看 190 个工具现状
    python scripts/mcp_profile.py apply lean      # 一键精简（禁 73，剩 117）+ 重启网关
    python scripts/mcp_profile.py apply lean80    # 二段精简（再禁 34，剩 83）
    python scripts/mcp_profile.py apply full      # 恢复全部 190
    python scripts/mcp_profile.py show            # 看当前 profile

原理：写 config/mcp_tool_profile.json（隐藏名单）→ 杀 8000 网关进程 →
supervisor 约 5 秒自动拉起新进程加载新名单 → 脚本等待并验证 /health 工具数。
WorkBuddy/ZCode 界面在 MCP 重连后显示的数字即与实际一致。

铁律：只动 hub 自己的配置与网关进程，不碰 WorkBuddy 状态文件。
国内接口直连（/health 走 127.0.0.1，禁代理）。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILE = ROOT / "config" / "mcp_tool_profile.json"
GATEWAY = "http://127.0.0.1:8000/health"

# --------------------------------------------------------------- 中文分组全清单
# 结构：(中文名, 一句话说明, [工具名...])。顺序即 list 输出顺序。

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

ALL_TOOLS: list[str] = [t for _, _, ts in GROUPS for t in ts]


def _read_profile() -> dict:
    if PROFILE.exists():
        try:
            return json.loads(PROFILE.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"⚠️ profile 文件损坏（{e}），按 full 处理")
    return {"profile": "full", "hidden_tools": []}


def _write_profile(profile: str, hidden: list[str]) -> None:
    PROFILE.parent.mkdir(parents=True, exist_ok=True)
    PROFILE.write_text(
        json.dumps(
            {
                "profile": profile,
                "hidden_tools": hidden,
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _hidden_set(data: dict) -> set[str]:
    return set(data.get("hidden_tools") or [])


def cmd_list() -> int:
    hidden = _hidden_set(_read_profile())
    known = set(ALL_TOOLS)
    print(f"\n当前 profile：{_read_profile().get('profile', 'full')} ｜ "
          f"启用 {len(known - hidden)} / 全量 {len(known)}（另有名单外工具以网关为准）\n")
    print(f"{'状态':<4} {'工具':<34} 说明")
    print("-" * 88)
    for title, desc, tools in GROUPS:
        print(f"\n▎{title} —— {desc}")
        for t in tools:
            mark = "🚫" if t in hidden else "✅"
            print(f"  {mark} {t:<34}")
    extra = hidden - known
    if extra:
        print(f"\n▎名单内但未分组（仍处于隐藏状态）：{sorted(extra)}")
    print("\n提示：🚫=已隐藏（AI 不可见） ✅=启用。"
          "TradeX 看板/短线落库/数据源降级链不受本启停影响（进程内调用）。\n")
    return 0


def _resolve_preset(name: str) -> tuple[str, list[str]]:
    if name == "full":
        return "full", []
    if name == "lean":
        hidden: set[str] = set()
        for target in LEAN_DISABLE:
            for g_title, _desc, ts in GROUPS:
                if g_title == target:
                    hidden.update(ts)
                    break
        return "lean", sorted(hidden)
    if name == "lean80":
        _, lean_hidden = _resolve_preset("lean")
        return "lean80", sorted(set(lean_hidden) | set(LEAN80_EXTRA))
    raise SystemExit(f"未知预设：{name}（可选 lean / lean80 / full）")


def _gateway_tools() -> int | None:
    """读网关 /health 的 tools 数；国内回环直连（禁代理）。"""
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(GATEWAY, timeout=5) as r:
            return int(json.loads(r.read().decode("utf-8")).get("tools", -1))
    except Exception:  # noqa: BLE001
        return None


def _kill_gateway() -> int:
    """杀 8000 端口网关进程（supervisor 约 5 秒自动拉起新进程）。返回杀掉的 PID 数。"""
    try:
        out = subprocess.run(
            ["netstat", "-ano"], capture_output=True, timeout=15
        ).stdout.decode("utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ netstat 失败：{e}")
        return 0
    pids: set[str] = set()
    for line in out.splitlines():
        if ":8000" in line and "LISTENING" in line:
            parts = line.split()
            if len(parts) >= 5 and parts[1].endswith(":8000"):
                pids.add(parts[-1])
    for pid in pids:
        subprocess.run(
            ["taskkill", "/PID", pid, "/F"],
            capture_output=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        print(f"  已停网关进程 pid={pid}（supervisor 将自动拉起）")
    return len(pids)


def cmd_apply(name: str) -> int:
    profile, hidden = _resolve_preset(name)
    _write_profile(profile, hidden)
    print(f"\n✅ 已写入 {PROFILE.name}：profile={profile}，隐藏 {len(hidden)} 个"
          f"（暴露 {len(ALL_TOOLS) - len(hidden)}）")
    print("⏳ 重启网关使其生效……")
    killed = _kill_gateway()
    if not killed:
        print("  ⚠️ 未发现 8000 监听进程（网关可能没在跑），profile 已写入，下次启动生效")
    deadline = time.time() + 45
    while time.time() < deadline:
        time.sleep(3)
        n = _gateway_tools()
        if n is not None and n > 0:
            expect = len(ALL_TOOLS) - len(hidden)
            mark = "✅" if n == expect else "⚠️"
            print(f"{mark} 网关已就绪：/health 报告 tools={n}"
                  + (f"（预期 {expect}）" if n != expect else ""))
            break
        print("  等待网关拉起……")
    else:
        print("⚠️ 45 秒内未等到网关健康报告，请稍后手动确认：curl http://127.0.0.1:8000/health")
    print("\n📱 WorkBuddy/ZCode 在 MCP 重连后显示新数字（WorkBuddy 可关开一次 tradex 开关触发重连）")
    print("↩️  恢复全量：python scripts/mcp_profile.py apply full\n")
    return 0


def cmd_show() -> int:
    data = _read_profile()
    hidden = _hidden_set(data)
    print(f"\nprofile = {data.get('profile', 'full')} ｜ 隐藏 {len(hidden)} ｜ "
          f"启用 {len(ALL_TOOLS) - len(hidden)}（名单内口径）")
    gw = _gateway_tools()
    if gw is not None:
        print(f"网关 /health tools = {gw}")
    print(f"profile 文件：{PROFILE}\n")
    return 0


def main() -> int:
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd = argv[0]
    if cmd == "list":
        return cmd_list()
    if cmd == "show":
        return cmd_show()
    if cmd == "apply" and len(argv) > 1 and not argv[1].startswith("-"):
        return cmd_apply(argv[1].strip().lower())
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
