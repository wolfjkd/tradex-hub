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
  | company_info         | akshare           | cninfo        |               |           |
  | financial_stmt       | akshare           | sina          |               |           |
  | valuation            | akshare           | eltdx         |               |           |
  | industry_data        | akshare           | ths           |               |           |
  | market_overview      | akshare           |               |               |           |
  | news_data            | em_news_direct    | akshare       |               |           |
  | telegraph_news       | cls_telegraph     |               |               |           |
  | cninfo_announcement  | cninfo_direct     |               |               |           |
  | macro_data           | akshare           |               |               |           |
  | etf_data             | akshare           |               |               |           |
  | cb_data              | akshare           |               |               |           |
  | fund_flow            | em_push2          | akshare       |               |           |
  | dragon_tiger         | em_datacenter     | akshare       |               |           |
  | industry_comparison  | em_push2          | akshare       | ths_flow      |           |
  | northbound           | ths_hsgt          | akshare       |               |           |
  | hot_money            | ths_editorial     |               |               | 是        |
  | lockup_expiry        | em_datacenter     |               |               | 是        |
  | limit_up_board       | em_push2_clist    |               |               | 是        |
  | hot_stocks           | akshare           |               |               |           |
  | profit_forecast      | akshare           | tencent_http  |               |           |
  | concept_attribution  | em_push2delay     |               |               |           |
  | baidu_economic_calendar | akshare_baidu_economic | akshare_report_time |         |           |
  | baidu_trade_notify   | akshare_baidu_notify | akshare_tfp   |               |           |
  | index_news_sentiment | legu_activity | ths_distribution |         |           |
  | futures_news         | akshare_futures_news |             |               |           |
  | sina_finance_news    | sina_direct       |               |               |           |
  | hot_search           | akshare_hot_search | ths_hot       |               |           |
  | hot_rank             | akshare_hot_rank   | ths_hot       |               |           |
  | xueqiu_hot           | akshare_xueqiu_hot | ths_hot       |               |           |
  | fund_hold            | em_zlsj_direct     | akshare_fund_hold |           |           |
  | wencai_query         | pywencai           |               |               |           |
  | wencai_news          | iwencai_openapi    |               |               |           |
"""

from __future__ import annotations

import logging
import threading

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

# v3.3.9+：注册过程加锁，避免多线程并发进入时重复注册。
# SmartRouter.register 自身也已做同 key 幂等，此处锁用于兜底"注册中途异常重试"场景。
_registered = False
_register_lock = threading.Lock()


def register_all_sources() -> None:
    """注册全部 38 个数据类型到 SmartRouter 全局单例。

    幂等：重复调用不会重复注册。
    """
    global _registered
    if _registered:
        logger.debug("register_all_sources: already registered, skip")
        return
    with _register_lock:
        if _registered:  # 双检锁：等待锁期间可能已被其他线程注册
            return
        _do_register()
        _registered = True


def _do_register() -> None:
    """实际注册逻辑（调用方须持有 _register_lock）。"""
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
    # v3.3.14: 补独立备源（非东财）——原先这四类均为 akshare 单源，东财异常时无兜底
    router.register("company_info", "cninfo", akf.fetch_company_info_cninfo, priority=100)
    router.register("financial_stmt", "akshare", akf.fetch_financial_stmt, priority=1)
    router.register("financial_stmt", "sina", akf.fetch_financial_stmt_sina, priority=100)
    router.register("valuation", "akshare", akf.fetch_valuation, priority=1)
    router.register("valuation", "eltdx", ef.fetch_valuation_eltdx, priority=100)
    router.register("industry_data", "akshare", akf.fetch_industry_data, priority=1)
    router.register("industry_data", "ths", akf.fetch_industry_data_ths, priority=100)
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
    # v3.3.15：上面两源**同属东财 push2 族**，本机会一起被 RST（实测两源同时
    # RemoteDisconnected），名义双源、实际无兜底。补同花顺行业资金流作为
    # 跨上游兜底，主源同族失效时它是实际可用的一环。
    router.register("industry_comparison", "ths_flow",
                    akf.fetch_industry_comparison_ths, priority=200)

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
    # index_news_sentiment 的旧主源 akshare_index_sentiment 已退役（上游 chinascope
    # 永久失效），改由下方 v3.3.15 区块统一装配主源+备源，故此处不再注册。
    router.register("futures_news", "akshare_futures_news", akf.fetch_futures_news, priority=1)
    router.register("sina_finance_news", "sina_direct", nf.fetch_sina_finance_news, priority=1)
    router.register("hot_search", "akshare_hot_search", akf.fetch_hot_search_baidu, priority=1)
    router.register("hot_rank", "akshare_hot_rank", akf.fetch_hot_rank_data, priority=1)
    router.register("xueqiu_hot", "akshare_xueqiu_hot", akf.fetch_xueqiu_hot, priority=1)
    # 机构持仓汇总：**主源改为直取东财**（akshare 版列错位，见 akshare_fetchers 说明）。
    # 直取版按上游字段名映射列，上游再改字段顺序也不会错位。
    # akshare 版降为备源，但它只服务 endpoint="detail"（hold 会直接 raise）。
    router.register("fund_hold", "em_zlsj_direct", akf.fetch_fund_hold_direct, priority=1)
    router.register("fund_hold", "akshare_fund_hold", akf.fetch_fund_hold_data, priority=100)

    # ── v3.3.15：补「单源无兜底」类型的备源（一律选**非同一上游**，避免同生共死） ──
    # 盘点结论：下列 8 类此前均为单源注册，源失效即整类型失效，且部分源还把异常
    # 静默吞成空表，失败完全不可见。补齐后每类至少有 2 个不同上游的源。
    #
    # 财报日历：补百度财报披露时间表（主源同属百度但接口不同，属降级备源）
    router.register("baidu_economic_calendar", "akshare_report_time",
                    akf.fetch_baidu_economic_calendar_bak, priority=100)
    # 交易提示：补全市场停复牌表（百度主源 → akshare 停复牌，语义精确对应）
    router.register("baidu_trade_notify", "akshare_tfp",
                    akf.fetch_baidu_trade_notify_tfp, priority=100)
    # 热度三兄弟（东财人气榜 / 百度热搜 / 雪球热度）→ 统一以同花顺热榜兜底
    router.register("hot_rank", "ths_hot", akf.fetch_hot_rank_ths, priority=100)
    router.register("hot_search", "ths_hot", akf.fetch_hot_rank_ths, priority=100)
    router.register("xueqiu_hot", "ths_hot", akf.fetch_hot_rank_ths, priority=100)
    # 指数情绪：**主源整体重装**（旧主源 akshare_index_sentiment 已退役）。
    # 旧主源上游 chinascope 永久失效（端点 301 跳官网首页、返 text/html，
    # akshare 内部 r.json() 必然 JSONDecodeError，与 SSL 无关），源与配套的
    # 全局 SSL hack 一并删除。现把实测可用的乐咕乐股「赚钱效应」提为主源，
    # 并补同花顺涨跌分布作跨上游备源（两者上游不同，非同生共死）。
    # 注意：备源必须返回 DataFrame —— 工具层 get_market_sentiment 写的是
    # `df is None or df.empty`，若给 dict（如 ths_market_breadth）会 AttributeError。
    router.register("index_news_sentiment", "legu_activity",
                    akf.fetch_market_sentiment_legu, priority=1)
    router.register("index_news_sentiment", "ths_distribution",
                    ths.fetch_ths_up_down_distribution, priority=100)
    # futures_news 保持单源，理由见 CHANGELOG：
    #   - futures_news：上游为上海有色网，akshare 无等价第二源
    # （fund_hold 已从单源升为双源：em_zlsj_direct 主 + akshare_fund_hold 备）

    # ── v3.3.0 新增：同花顺问财数据源（可选依赖） ──
    router.register("wencai_query", "pywencai", wf.fetch_wencai_query, priority=1)
    router.register("wencai_news", "iwencai_openapi", wf.fetch_wencai_news, priority=1)

    report = router.get_registry_report()
    data_types = sorted({x["data_type"] for x in report})
    logger.info(
        "register_all_sources: 已注册 %d 个数据类型, %d 个数据源",
        len(data_types), len(report),
    )
