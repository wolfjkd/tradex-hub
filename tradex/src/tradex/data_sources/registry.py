"""
数据源注册中心 — register_all_sources()。

注册全部数据类型到 SmartRouter，按数据源矩阵定义优先级与独占标记。

⚠️ 2026-09-23（老板拍板）：东财 push2 域名族被持续风控（curl: (56) 连接被
服务端主动断开，且 akshare 所有 `_em` 后缀函数连锁失效）。整体策略：
  - 删除 push2 族所有注册点（em_push2 / em_push2delay / em_push2ex /
    em_push2_clist / em_slist 共 8 个）
  - 剩余东财源全部降级到 priority=999（datacenter-web / search-api-web /
    datacenter-zlsj 三个子域名当前仍可用，但「非必要不调用」）
  - 5 个数据类型因此成裸类型（无源）：industry_quotes / concept_attribution /
    market_breadth / limit_up_board / stock_boards —— 老板拍板「能用就保留，
    不能用就接受失效」，等需要时再补同花顺备源

数据源矩阵（v0.1.0-DEV + tdx_mcp 平级互备 + 东财 push2 族退役）：
  | data_type            | priority=1          | priority=100  | priority=200  | exclusive | P999 (东财兜底) |
  |----------------------|---------------------|---------------|---------------|-----------|----------------|
  | realtime_quote       | eltdx, tdx_mcp      | akshare       | tencent_http  |           |                |
  | historical_kline     | eltdx, tdx_mcp      | akshare       |               |           |                |
  | screener (增量)      | tdx_mcp             |               |               |           |                |
  | research_report(增量)| tdx_mcp             |               |               |           |                |
  | macro_data           | akshare             | tdx_mcp       |               |           |                |
  | minute_data          | eltdx               | akshare       |               |           |                |
  | call_auction         | eltdx             |               |               | 是        |                |
  | tick_data            | eltdx             |               |               | 是        |                |
  | f10_profile          | eltdx             |               |               | 是        |                |
  | company_info         | akshare           | cninfo        |               |           |                |
  | financial_stmt       | akshare           | sina          |               |           |                |
  | valuation            | akshare           | eltdx         |               |           |                |
  | industry_data        | akshare           | ths           |               |           |                |
  | market_overview      | akshare           | tencent_http  |               |           |                |
  | news_data            | akshare           |               |               |           | em_news_direct |
  | telegraph_news       | cls_telegraph     |               |               |           |                |
  | cninfo_announcement  | cninfo_direct     |               |               |           |                |
  | etf_data             | akshare           |               |               |           |                |
  | cb_data              | akshare           |               |               |           |                |
  | fund_flow            | (无主源)          | akshare       |               |           | (push2 已删)   |
  | dragon_tiger         | (无主源)          | akshare       |               |           | em_datacenter  |
  | industry_comparison  | (无主源)          | akshare       | ths_flow      |           | (push2 已删)   |
  | northbound           | ths_hsgt          | akshare       |               |           |                |
  | hot_money            | ths_editorial     |               |               | 是        |                |
  | lockup_expiry        | (无主源)          |               |               |           | em_datacenter (独占兜底) |
  | hot_stocks           | akshare           |               |               |           |                |
  | profit_forecast      | akshare           | tencent_http  |               |           |                |
  | concept_attribution  | (裸类型)          |               |               |           | (push2delay 已删) |
  | baidu_economic_calendar | akshare_baidu_economic | akshare_report_time |         |           |                |
  | baidu_trade_notify   | akshare_baidu_notify | akshare_tfp   |               |           |                |
  | index_news_sentiment | legu_activity | ths_distribution |         |           |                |
  | futures_news         | akshare_futures_news |             |               |           |                |
  | sina_finance_news    | sina_direct       |               |               |           |                |
  | hot_search           | akshare_hot_search | ths_hot       |               |           |                |
  | hot_rank             | akshare_hot_rank   | ths_hot       |               |           |                |
  | xueqiu_hot           | akshare_xueqiu_hot | ths_hot       |               |           |                |
  | fund_hold            | (无主源)          | akshare_fund_hold |           |           | em_zlsj_direct |
  | wencai_query         | pywencai           |               |               |           |                |
  | wencai_news          | iwencai_openapi    |               |               |           |                |
  | market_breadth       | (裸类型)          |               |               |           | (push2ex 已删) |
  | industry_quotes      | (裸类型)          |               |               |           | (push2 已删)   |
  | limit_up_board       | (裸类型)          |               |               |           | (push2_clist 已删) |
  | stock_boards         | (裸类型)          |               |               |           | (slist 已删)   |
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
from . import tdx_mcp_fetchers as tdxm  # 通达信官方 MCP（与 eltdx 平级互备，v0.1.0-DEV）
# ── 数据源大扩充（SP-2026-09-23-001）：新增 11 个 fetcher 模块 ──
from . import sina_fetchers as sina          # 新浪研报/资金流/期权
from . import baidu_fetchers as baidu        # 百度股市通 K 线
from . import baostock_fetchers as baostock  # baostock 估值/退市/ST
from . import exchange_official_fetchers as exchg  # 沪深交易所官方
from . import event_driven_fetchers as evtd  # 事件驱动 6 件套
from . import index_constituents_fetchers as idxcons  # 中证/国证指数
from . import macro_official_fetchers as macro_off    # 人行/统计局/中债/货币网
from . import interaction_fetchers as interact        # 互动易/e互动
from . import wallstreetcn_fetchers as wscn           # 华尔街见闻
from . import cctv_news_fetchers as cctv              # 央视新闻联播
from . import sw_industry_fetchers as swind           # 申万行业变迁
from . import industry_news_fetchers as indnews       # 产业链资讯 RSS

logger = logging.getLogger("tradex.data_sources")

# v3.3.9+：注册过程加锁，避免多线程并发进入时重复注册。
# SmartRouter.register 自身也已做同 key 幂等，此处锁用于兜底"注册中途异常重试"场景。
_registered = False
_register_lock = threading.Lock()


def register_all_sources() -> None:
    """注册全部数据类型到 SmartRouter 全局单例（v0.1.0-DEV：东财 push2 族已退役）。

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

    # ── 通达信官方 MCP（tdx_mcp，v0.1.0-DEV，SP-2026-09-21-001） ──
    # 与 eltdx 同属 priority=1 第一梯队，互为备份、互为兜底。
    # SmartRouter 机制：同 priority=1 时健康分高者优先 → 日常 eltdx 胜出；
    # eltdx 连续失败健康分归零后自动切到本源，恢复后自动切回（非独占 + 自动降级）。
    # token 走独立 env TDX_MCP_TOKEN，缺失时空闲（fetch_fn 抛 TDXSourceUnavailable），
    # 不影响注册，也不影响 eltdx 正常服务。
    router.register("realtime_quote", "tdx_mcp", tdxm.fetch_realtime_quote, priority=1)
    router.register("historical_kline", "tdx_mcp", tdxm.fetch_historical_kline, priority=1)

    # ── 通达信官方 MCP 纯增量类型（eltdx 无法提供的增量能力，独立 data_type）──
    # 这些不属于"与 eltdx 互备"，而是官方 MCP 的额外能力，经 registry 统一暴露：
    #   - screener：自然语言条件选股（L3 独立工具 natural_lang_screener 消费）
    #   - research_report：券商研报（wenda_report_query）
    #   - macro_data：宏观数据增强（wenda_macro_query，与 akshare 版互为交叉验证）
    router.register("screener", "tdx_mcp", tdxm.fetch_screener, priority=1)
    router.register("research_report", "tdx_mcp", tdxm.fetch_research_report, priority=1)
    router.register("macro_data", "tdx_mcp", tdxm.fetch_macro_data, priority=100)

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
    router.register("news_data", "akshare", akf.fetch_news_data, priority=1)
    # 2026-09-23：em_news_direct 降级 P999（search-api-web 不在封禁名单，
    # 但东财整体「非必要不调用」，akshare 版本主源已足够）
    router.register("news_data", "em_news_direct", nf.fetch_em_news_direct, priority=999)
    router.register("telegraph_news", "cls_telegraph", nf.fetch_cls_telegraph, priority=1)
    router.register("cninfo_announcement", "cninfo_direct", nf.fetch_cninfo_direct, priority=1)
    router.register("macro_data", "akshare", akf.fetch_macro_data, priority=1)
    router.register("etf_data", "astock_signals", asf.fetch_etf_data, priority=1)
    router.register("cb_data", "astock_signals", asf.fetch_cb_data, priority=1)
    router.register("hot_stocks", "akshare", akf.fetch_hot_stocks, priority=1)

    # ── 东财主 + akshare 备 —— 2026-09-23 东财 push2 族被风控移除 ──
    # fund_flow：原 em_push2 主源已删（push2 域名被封），akshare 自身底层抓
    # push2his 也在封禁名单，所以 fund_flow 实际也成裸类型（akshare 备源也挂）。
    # 但保留 akshare 注册 —— push2his 不在被封列表时它会恢复服务。
    router.register("fund_flow", "akshare", akf.fetch_fund_flow, priority=100)

    # dragon_tiger：datacenter-web 不在封禁列表，仍可用 —— 但按老板指示降级 P999
    router.register("dragon_tiger", "em_datacenter", asf.fetch_dragon_tiger_em, priority=999)
    router.register("dragon_tiger", "akshare", akf.fetch_dragon_tiger, priority=100)

    # industry_comparison：em_push2 主源已删，保留 akshare + ths_flow 双备源
    router.register("industry_comparison", "akshare", akf.fetch_industry_comparison, priority=100)
    # v3.3.15：上面两源**同属东财 push2 族**，本机会一起被 RST（实测两源同时
    # RemoteDisconnected），名义双源、实际无兜底。补同花顺行业资金流作为
    # 跨上游兜底，主源同族失效时它是实际可用的一环。
    router.register("industry_comparison", "ths_flow",
                    akf.fetch_industry_comparison_ths, priority=200)

    # ── 同花顺主 + akshare 备 ──
    router.register("northbound", "ths_hsgt", asf.fetch_northbound_ths, priority=1)
    router.register("northbound", "akshare", akf.fetch_northbound, priority=100)

    # ── 独占源 —— 2026-09-23 东财 push2 族被风控移除 ──
    router.register("hot_money", "ths_editorial", asf.fetch_hot_money, priority=1, exclusive=True)
    # lockup_expiry：datacenter-web 不在封禁列表 —— 按老板指示独占也降级 P999
    router.register("lockup_expiry", "em_datacenter", asf.fetch_lockup_expiry, priority=999, exclusive=True)
    # limit_up_board：原 em_push2_clist 主源已删（push2 域名被封）→ 整类型失效
    # 老板拍板「能用就保留，不能用就接受失效」
    # router.register("limit_up_board", "em_push2_clist", asf.fetch_limit_up_board, priority=1, exclusive=True)

    # ── akshare 主 + tencent_http 备 ──
    router.register("profit_forecast", "akshare", akf.fetch_profit_forecast, priority=1)
    router.register("profit_forecast", "tencent_http", hf.fetch_profit_forecast_tencent, priority=100)

    # ── 单源 —— 2026-09-23 东财 push2delay 被风控移除 ──
    # concept_attribution：原 em_push2delay 主源已删 → 整类型失效
    # 老板拍板「能用就保留，不能用就接受失效」
    # router.register("concept_attribution", "em_push2delay", asf.fetch_concept_attribution, priority=1)

    # ── v3.3.1 新增：全局行情（腾讯直连，美股/大宗/亚太/外汇） ──
    router.register("global_market_quote", "tencent_http", hf.fetch_global_quote_tencent, priority=1)

    # ── v3.3.8 新增：市场级统计（实时涨跌家数 / 行业板块涨幅） ──
    # market_breadth：东财 push2ex 涨跌分布（实时）
    # industry_quotes：东财 push2 行业板块（内部自动降级 push2delay 镜像）
    # ── v3.3.8 曾新增：市场级统计（涨跌家数 / 行业板块涨幅） ──
    # 2026-09-23 移除东财 push2ex / push2 主源（push2 域名族被持续风控，
    # curl: (56) 连接被服务端主动断开，且 akshare _em 后缀接口连锁失效）。
    # market_breadth / industry_quotes 暂成裸类型 —— 老板拍板「能用就保留，
    # 不能用就接受失效」，等需要时再补同花顺备源。
    # router.register("market_breadth", "em_push2ex", hf.fetch_market_breadth, priority=1)
    # router.register("industry_quotes", "em_push2", hf.fetch_industry_quotes, priority=1)

    # ── v3.3.9 新增：同花顺备源 + 东财 slist + 通达信本地数据 ──
    # ── v3.3.9 曾新增：同花顺备源 + 东财 slist + 通达信本地数据 ──
    # 2026-09-23 移除东财 slist（push2 域名族被封，stock_boards 暂成裸类型，
    # 老板拍板「能用就保留，不能用就接受失效」）。
    # router.register("stock_boards", "em_slist", emc.fetch_stock_boards, priority=1)
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
    # 机构持仓汇总：2026-09-23 按老板指示降级 P999（datacenter-zlsj 不在封禁
    # 列表，但东财整体策略就是「非必要不调用」）。akshare 版按字段名映射，
    # 上游改字段顺序也不会错位；akshare 版服务 endpoint="detail"，
    # hold 会直接 raise —— hold 场景只有 em_zlsj 这一路。
    router.register("fund_hold", "em_zlsj_direct", akf.fetch_fund_hold_direct, priority=999)
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

    # ════════════════════════════════════════════════════════════════════
    # SP-2026-09-23-001 数据源大扩充：一次性注册全部新类型 + 备源
    # 设计原则：
    #   - 全新类型：主源 priority=1，备源 priority=100/200
    #   - 已有类型加备源：作为 priority=100/200 加入（不打乱原有梯队）
    #   - 上游独立性验证：每条备源都与主源不同上游（避免假双源）
    # ════════════════════════════════════════════════════════════════════

    # ── P0 三件套：ETF 期权 + 业绩预告 + 机构调研（全新类型） ──
    router.register("etf_option_tquote", "sina_option", sina.fetch_sina_option_tquote, priority=1)
    router.register("etf_option_greeks", "sina_option", sina.fetch_sina_option_greeks, priority=1)
    router.register("earnings_forecast", "em_datacenter", evtd.fetch_earnings_forecast, priority=999)
    router.register("institution_survey", "em_datacenter", evtd.fetch_institution_survey, priority=999)

    # ── 事件驱动其余 4 件套 ──
    router.register("holder_trades", "em_datacenter", evtd.fetch_holder_trades, priority=999)
    router.register("share_buyback", "em_datacenter", evtd.fetch_share_buyback, priority=999)
    router.register("equity_pledge", "em_datacenter", evtd.fetch_equity_pledge, priority=999)
    router.register("ipo_calendar", "em_datacenter", evtd.fetch_ipo_calendar, priority=999)

    # ── 指数追踪 3 件套（中证一手 + 国证备） ──
    router.register("index_constituents", "csi_official", idxcons.fetch_csi_index_constituents, priority=1)
    router.register("index_constituents", "cnindex_official", idxcons.fetch_cnindex_constituents, priority=100)
    router.register("index_weights", "csi_official", idxcons.fetch_csi_index_weights, priority=1)
    router.register("index_weights", "cnindex_official", idxcons.fetch_cnindex_weights, priority=100)
    router.register("index_valuation", "csi_official", idxcons.fetch_csi_index_valuation, priority=1)

    # ── 宏观 5 件套（官方一手 + akshare 备） ──
    router.register("social_financing", "pboc_official", macro_off.fetch_pboc_social_financing, priority=1)
    router.register("pmi_data", "nbs_official", macro_off.fetch_nbs_pmi, priority=1)
    router.register("bond_yield_curve", "chinabond_official", macro_off.fetch_chinabond_yield_curve, priority=1)
    router.register("repo_fixing_rate", "chinamoney_official", macro_off.fetch_repo_fixing_rates, priority=1)
    router.register("lpr_history", "chinamoney_official", macro_off.fetch_lpr_history, priority=1)

    # ── 投资者互动 2 件套 ──
    router.register("cninfo_irm", "cninfo_irm_official", interact.fetch_cninfo_irm, priority=1)
    router.register("sse_e_interaction", "sse_einteract_official", interact.fetch_sse_e_interaction, priority=1)

    # ── 全球新闻 3 件套 ──
    router.register("wallstreetcn_lives", "wscn_api", wscn.fetch_wallstreetcn_lives, priority=1)
    router.register("macro_calendar", "wscn_api", wscn.fetch_macro_calendar, priority=1)
    router.register("cctv_news_main", "cctv_official", cctv.fetch_cctv_news, priority=1)

    # ── 申万行业历史 2 件套 ──
    router.register("sw_industry_history", "sw_official", swind.fetch_sw_industry_history, priority=1)
    router.register("sw_industry_as_of", "sw_official", swind.fetch_sw_industry_as_of, priority=1)

    # ── 产业链资讯：1 类型聚合 12 赛道 ──
    router.register("industry_news", "rss_direct", indnews.fetch_industry_news, priority=1)

    # ── 监管异动（交易所股票交易异常波动预警） ──
    # 借鉴 chengzuopeng/stock-sdk 的 getUnusualFluctuation 实现（ISC license）
    # 数据源：datacenter-web RPT_WATCH_UNUSUAL_FLUCTUATE（P999 降级源，老板批准）
    # 实测约 4038 条历史，自带两个月滚动窗口；IS_HAPPEN=1 已触发 / =0 逼近未达
    router.register("regulatory_anomaly", "em_datacenter",
                    emc.fetch_unusual_fluctuation, priority=999)

    # ── 龙虎榜扩展族（借鉴 stock-sdk dragonTiger.ts，ISC license）──
    # 全部走 datacenter-web 子域，P999 降级源。补全 tradex-hub 龙虎榜缺失维度：
    #   - dt_detail：上榜个股详情（含 D1/D2/D5/D10 上榜后股价跟踪）
    #   - dt_stock_stats：个股上榜次数统计（按周期聚合）
    #   - dt_institution：机构席位买卖统计
    #   - dt_seat_detail：个股某日买卖营业部席位明细
    # 注：dt_branch_rank 营业部排行未接入——上游 datacenter-web 没有对应 report，
    #     该数据走 datapc.eastmoney.com/emdatacenter/ranking/department 页面，不在 P999 降级源范围内。
    router.register("dt_detail", "em_datacenter",
                    emc.fetch_dragon_tiger_detail, priority=999)
    router.register("dt_stock_stats", "em_datacenter",
                    emc.fetch_dragon_tiger_stock_stats, priority=999)
    router.register("dt_institution", "em_datacenter",
                    emc.fetch_dragon_tiger_institution, priority=999)
    router.register("dt_seat_detail", "em_datacenter",
                    emc.fetch_dragon_tiger_seat_detail, priority=999)

    # ── 融资融券扩展族（借鉴 stock-sdk margin.ts，ISC license）──
    # tradex-hub 已有交易所官方两融明细（sse/szse_official），
    # 补「账户统计 + 标的列表」两个新维度，走 datacenter-web P999 降级源。
    router.register("margin_account_info", "em_datacenter",
                    emc.fetch_margin_account_info, priority=999)
    router.register("margin_target_list", "em_datacenter",
                    emc.fetch_margin_target_list, priority=999)

    # ── 大宗交易族（借鉴 stock-sdk blockTrade.ts，ISC license）──
    # tradex-hub 之前完全没有大宗交易能力，本次一次性补齐 3 个维度。
    router.register("block_trade_market_stat", "em_datacenter",
                    emc.fetch_block_trade_market_stat, priority=999)
    router.register("block_trade_detail", "em_datacenter",
                    emc.fetch_block_trade_detail, priority=999)
    router.register("block_trade_daily_stat", "em_datacenter",
                    emc.fetch_block_trade_daily_stat, priority=999)

    # ── 给已有类型加独立备源（一主一备 / 一主二备） ──
    # historical_kline 第四备源：百度股市通（与 eltdx/akshare/tdx_mcp 完全独立）
    router.register("historical_kline", "baidu_http", baidu.fetch_baidu_kline_with_ma, priority=200)
    # research_report 第二备源：新浪研报（与 tdx_mcp 独立）
    router.register("research_report", "sina_research", sina.fetch_sina_research_reports, priority=100)
    # fund_flow 解决裸源：新浪日度资金流（与 akshare 独立）
    router.register("fund_flow", "sina_fund_flow", sina.fetch_sina_fund_flow, priority=100)
    # valuation 第三备源：baostock TCP（独立通道）
    router.register("valuation", "baostock_tcp", baostock.fetch_baostock_valuation_history, priority=200)
    # dragon_tiger 官方备源：沪深交易所一手（含营业部席位）
    router.register("dragon_tiger", "sse_official", exchg.fetch_sse_dragon_tiger, priority=50)
    router.register("dragon_tiger", "szse_official", exchg.fetch_szse_dragon_tiger, priority=60)
    # 退市日 + ST 名单：baostock 兜底
    router.register("delisting_date", "baostock_tcp", baostock.fetch_baostock_delisting_date, priority=100)
    router.register("st_stock_list", "baostock_tcp", baostock.fetch_baostock_st_list, priority=100)
    # 交易日历：深交所官方替换 eltdx 兜底
    router.register("trading_calendar", "szse_official", exchg.fetch_szse_trading_calendar, priority=50)
    # 深市公告：官方备源（与巨潮独立）
    router.register("cninfo_announcement", "szse_official", exchg.fetch_szse_announcement, priority=100)
    # 两融明细：交易所官方一手
    router.register("margin_trading", "sse_official", exchg.fetch_sse_margin_trading, priority=50)
    router.register("margin_trading", "szse_official", exchg.fetch_szse_margin_trading, priority=60)

    report = router.get_registry_report()
    data_types = sorted({x["data_type"] for x in report})
    logger.info(
        "register_all_sources: 已注册 %d 个数据类型, %d 个数据源",
        len(data_types), len(report),
    )
