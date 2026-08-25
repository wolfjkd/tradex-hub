"""
数据源注册中心 — register_all_sources()。

注册全部 38 个数据类型到 SmartRouter，按数据源矩阵定义优先级与独占标记。

数据源矩阵（39 个数据类型，v3.3.1 新增 global_market_quote）：
  | data_type            | priority=1        | priority=100  | priority=200  | exclusive |
  |----------------------|-------------------|---------------|---------------|-----------|
  | realtime_quote       | eltdx             | akshare       | tencent_http  |           |
  | historical_kline     | eltdx             | akshare       |               |           |
  | minute_data          | eltdx             | akshare       |               |           |
  | call_auction         | eltdx             |               |               | 是        |
  | tick_data            | eltdx             |               |               | 是        |
  | f10_profile          | eltdx             |               |               | 是        |
  | company_info         | akshare           |               |               |           |
  | financial_stmt       | akshare           |               |               |           |
  | valuation            | akshare           |               |               |           |
  | industry_data        | akshare           |               |               |           |
  | market_overview      | akshare           |               |               |           |
  | news_data            | em_news_direct    | akshare       |               |           |
  | telegraph_news       | cls_telegraph     |               |               |           |
  | cninfo_announcement  | cninfo_direct     |               |               |           |
  | macro_data           | akshare           |               |               |           |
  | etf_data             | akshare           |               |               |           |
  | cb_data              | akshare           |               |               |           |
  | fund_flow            | em_push2          | akshare       |               |           |
  | dragon_tiger         | em_datacenter     | akshare       |               |           |
  | industry_comparison  | em_push2          | akshare       |               |           |
  | northbound           | ths_hsgt          | akshare       |               |           |
  | hot_money            | ths_editorial     |               |               | 是        |
  | lockup_expiry        | em_datacenter     |               |               | 是        |
  | limit_up_board       | em_push2_clist    |               |               | 是        |
  | hot_stocks           | akshare           |               |               |           |
  | profit_forecast      | akshare           | tencent_http  |               |           |
  | concept_attribution  | em_push2delay     |               |               |           |
  | baidu_economic_calendar | akshare_baidu_economic |           |               |           |
  | baidu_trade_notify   | akshare_baidu_notify |             |               |           |
  | index_news_sentiment | akshare_index_sentiment |           |               |           |
  | futures_news         | akshare_futures_news |             |               |           |
  | sina_finance_news    | sina_direct       |               |               |           |
  | hot_search           | akshare_hot_search |               |               |           |
  | hot_rank             | akshare_hot_rank   |               |               |           |
  | xueqiu_hot           | akshare_xueqiu_hot |               |               |           |
  | fund_hold            | akshare_fund_hold  |               |               |           |
  | wencai_query         | pywencai           |               |               |           |
  | wencai_news          | iwencai_openapi    |               |               |           |
"""

from __future__ import annotations

import logging

from astock_signals.smart_router import get_router

from . import akshare_fetchers as akf
from . import eltdx_fetchers as ef
from . import http_fetchers as hf
from . import news_fetchers as nf
from . import astock_signals_fetchers as asf
from . import wencai_fetchers as wf
from . import em_client as emc
from . import ths_fetchers as ths
from . import tdx_local as tdx

logger = logging.getLogger("tradex.data_sources")

_registered = False


def register_all_sources() -> None:
    """注册全部 38 个数据类型到 SmartRouter 全局单例。

    幂等：重复调用不会重复注册。
    """
    global _registered
    if _registered:
        logger.debug("register_all_sources: already registered, skip")
        return
    router = get_router()

    # ── 行情类 ──
    router.register("realtime_quote", "eltdx", ef.fetch_realtime_quote, priority=1)
    router.register("realtime_quote", "akshare", akf.fetch_realtime_quote, priority=100)
    router.register("realtime_quote", "tencent_http", hf.fetch_realtime_quote_tencent, priority=200)

    router.register("historical_kline", "eltdx", ef.fetch_historical_kline, priority=1)
    router.register("historical_kline", "akshare", akf.fetch_historical_kline, priority=100)

    router.register("minute_data", "eltdx", ef.fetch_minute_data, priority=1)
    router.register("minute_data", "akshare", akf.fetch_minute_data, priority=100)

    # ── eltdx 独占源 ──
    router.register("call_auction", "eltdx", ef.fetch_call_auction, priority=1, exclusive=True)
    router.register("tick_data", "eltdx", ef.fetch_tick_data, priority=1, exclusive=True)
    router.register("f10_profile", "eltdx", ef.fetch_f10_profile, priority=1, exclusive=True)
    router.register("security_codes", "eltdx", ef.fetch_security_codes, priority=1, exclusive=True)
    router.register("all_a_shares", "eltdx", ef.fetch_all_a_shares, priority=1, exclusive=True)
    router.register("minute_history", "eltdx", ef.fetch_minute_history, priority=1, exclusive=True)
    router.register("minute_aux", "eltdx", ef.fetch_minute_aux, priority=1, exclusive=True)
    router.register("today_ticks", "eltdx", ef.fetch_today_ticks, priority=1, exclusive=True)
    router.register("opening_match", "eltdx", ef.fetch_opening_match, priority=1, exclusive=True)
    router.register("full_kline", "eltdx", ef.fetch_full_kline, priority=1, exclusive=True)
    router.register("adjusted_kline", "eltdx", ef.fetch_adjusted_kline, priority=1, exclusive=True)
    router.register("stock_profile", "eltdx", ef.fetch_stock_profile, priority=1, exclusive=True)
    router.register("shortline_indicators", "eltdx", ef.fetch_shortline_indicators, priority=1, exclusive=True)
    router.register("finance_batch", "eltdx", ef.fetch_finance_batch, priority=1, exclusive=True)
    router.register("special_limits", "eltdx", ef.fetch_special_limits, priority=1, exclusive=True)
    router.register("finance_report", "eltdx", ef.fetch_finance_report, priority=1, exclusive=True)
    router.register("dividend_financing", "eltdx", ef.fetch_dividend_financing, priority=1, exclusive=True)
    router.register("company_news", "eltdx", ef.fetch_company_news, priority=1, exclusive=True)
    router.register("northbound_holding", "eltdx", ef.fetch_northbound_holding, priority=1, exclusive=True)
    router.register("stock_topics", "eltdx", ef.fetch_stock_topics, priority=1, exclusive=True)
    router.register("topic_stocks", "eltdx", ef.fetch_topic_stocks, priority=1, exclusive=True)
    router.register("auction_data", "eltdx", ef.fetch_auction_data, priority=1, exclusive=True)
    router.register("category_quotes", "eltdx", ef.fetch_category_quotes, priority=1)
    router.register("category_quotes", "tencent", hf.fetch_category_quotes_tencent, priority=100)  # eltdx 榜失败降级全市场排序
    router.register("trading_day", "eltdx", ef.fetch_trading_day, priority=1, exclusive=True)
    router.register("opening_match_history", "eltdx", ef.fetch_opening_match_history, priority=1, exclusive=True)
    router.register("capital_changes", "eltdx", ef.fetch_capital_changes, priority=1, exclusive=True)
    router.register("special_limits_scan", "eltdx", ef.fetch_special_limits_scan, priority=1, exclusive=True)
    router.register("f10_extra", "eltdx", ef.fetch_f10_extra, priority=1, exclusive=True)

    # ── akshare 单源（备 tencent_http） ──
    router.register("company_info", "akshare", akf.fetch_company_info, priority=1)
    router.register("financial_stmt", "akshare", akf.fetch_financial_stmt, priority=1)
    router.register("valuation", "akshare", akf.fetch_valuation, priority=1)
    router.register("industry_data", "akshare", akf.fetch_industry_data, priority=1)
    router.register("market_overview", "akshare", akf.fetch_market_overview, priority=1)
    router.register("market_overview", "tencent_http", hf.fetch_market_overview_tencent, priority=100)
    router.register("index_daily_amount", "akshare", akf.fetch_index_daily_amount, priority=1)
    router.register("news_data", "em_news_direct", nf.fetch_em_news_direct, priority=1)
    router.register("news_data", "akshare", akf.fetch_news_data, priority=100)
    router.register("telegraph_news", "cls_telegraph", nf.fetch_cls_telegraph, priority=1)
    router.register("cninfo_announcement", "cninfo_direct", nf.fetch_cninfo_direct, priority=1)
    router.register("macro_data", "akshare", akf.fetch_macro_data, priority=1)
    router.register("etf_data", "astock_signals", asf.fetch_etf_data, priority=1)
    router.register("cb_data", "astock_signals", asf.fetch_cb_data, priority=1)
    router.register("hot_stocks", "akshare", akf.fetch_hot_stocks, priority=1)

    # ── 东财主 + akshare 备 ──
    router.register("fund_flow", "em_push2", asf.fetch_fund_flow_em, priority=1)
    router.register("fund_flow", "akshare", akf.fetch_fund_flow, priority=100)

    router.register("dragon_tiger", "em_datacenter", asf.fetch_dragon_tiger_em, priority=1)
    router.register("dragon_tiger", "akshare", akf.fetch_dragon_tiger, priority=100)

    router.register("industry_comparison", "em_push2", asf.fetch_industry_comparison_em, priority=1)
    router.register("industry_comparison", "akshare", akf.fetch_industry_comparison, priority=100)

    # ── 同花顺主 + akshare 备 ──
    router.register("northbound", "ths_hsgt", asf.fetch_northbound_ths, priority=1)
    router.register("northbound", "akshare", akf.fetch_northbound, priority=100)

    # ── 独占源 ──
    router.register("hot_money", "ths_editorial", asf.fetch_hot_money, priority=1, exclusive=True)
    router.register("lockup_expiry", "em_datacenter", asf.fetch_lockup_expiry, priority=1, exclusive=True)
    router.register("limit_up_board", "em_push2_clist", asf.fetch_limit_up_board, priority=1, exclusive=True)

    # ── akshare 主 + tencent_http 备 ──
    router.register("profit_forecast", "akshare", akf.fetch_profit_forecast, priority=1)
    router.register("profit_forecast", "tencent_http", hf.fetch_profit_forecast_tencent, priority=100)

    # ── 单源 ──
    router.register("concept_attribution", "em_push2delay", asf.fetch_concept_attribution, priority=1)

    # ── v3.3.1 新增：全局行情（腾讯直连，美股/大宗/亚太/外汇） ──
    router.register("global_market_quote", "tencent_http", hf.fetch_global_quote_tencent, priority=1)

    # ── v3.3.8 新增：市场级统计（实时涨跌家数 / 行业板块涨幅） ──
    # market_breadth：东财 push2ex 涨跌分布（实时）
    # industry_quotes：东财 push2 行业板块（内部自动降级 push2delay 镜像）
    router.register("market_breadth", "em_push2ex", hf.fetch_market_breadth, priority=1)
    router.register("industry_quotes", "em_push2", hf.fetch_industry_quotes, priority=1)

    # ── v3.3.9 新增：同花顺备源 + 东财 slist + 通达信本地数据 ──
    router.register("stock_boards", "em_slist", emc.fetch_stock_boards, priority=1)
    router.register("ths_eps_forecast", "ths", ths.fetch_ths_eps_forecast, priority=1)
    router.register("ths_hot_reason", "ths", ths.fetch_ths_hot_reason, priority=1)
    router.register("ths_limit_up_pool", "ths", ths.fetch_ths_limit_up_pool, priority=1)
    router.register("ths_hot_list", "ths", ths.fetch_ths_hot_list, priority=1)
    router.register("ths_up_down_distribution", "ths", ths.fetch_ths_up_down_distribution, priority=1)
    router.register("ths_limit_up_minute", "ths", ths.fetch_ths_limit_up_minute, priority=1)
    router.register("ths_turnover_minute", "ths", ths.fetch_ths_turnover_minute, priority=1)
    router.register("ths_market_breadth", "ths", ths.fetch_ths_market_breadth, priority=1)
    router.register("local_kline", "tdx_local", tdx.fetch_local_kline, priority=1)
    router.register("local_minute", "tdx_local", tdx.fetch_local_minute, priority=1)

    # ── v3.3.0 新增：新闻/资讯类数据源 ──
    router.register("baidu_economic_calendar", "akshare_baidu_economic", akf.fetch_baidu_economic_calendar, priority=1)
    router.register("baidu_trade_notify", "akshare_baidu_notify", akf.fetch_baidu_trade_notify, priority=1)
    router.register("index_news_sentiment", "akshare_index_sentiment", akf.fetch_index_news_sentiment, priority=1)
    router.register("futures_news", "akshare_futures_news", akf.fetch_futures_news, priority=1)
    router.register("sina_finance_news", "sina_direct", nf.fetch_sina_finance_news, priority=1)
    router.register("hot_search", "akshare_hot_search", akf.fetch_hot_search_baidu, priority=1)
    router.register("hot_rank", "akshare_hot_rank", akf.fetch_hot_rank_data, priority=1)
    router.register("xueqiu_hot", "akshare_xueqiu_hot", akf.fetch_xueqiu_hot, priority=1)
    router.register("fund_hold", "akshare_fund_hold", akf.fetch_fund_hold_data, priority=1)

    # ── v3.3.0 新增：同花顺问财数据源（可选依赖） ──
    router.register("wencai_query", "pywencai", wf.fetch_wencai_query, priority=1)
    router.register("wencai_news", "iwencai_openapi", wf.fetch_wencai_news, priority=1)

    _registered = True
    report = router.get_registry_report()
    data_types = sorted({x["data_type"] for x in report})
    logger.info(
        "register_all_sources: 已注册 %d 个数据类型, %d 个数据源",
        len(data_types), len(report),
    )
