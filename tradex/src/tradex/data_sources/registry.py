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

数据源矩阵（2026-11-11 批次C2 数据化）：本 docstring 不再手抄矩阵——
唯一知识源 = 模块级 ``_SOURCE_TABLE``（(data_type, source_name, fetcher,
priority, exclusive) 五元组声明表，历史裁决注释随行内联）；原 v0.1.0-DEV
手抄矩阵因与逐条 register 双份知识必漂移（实测已缺 shortline/KPL/index
全代新增）删除。注册/类型计数由 tests/test_v3314|test_v3315 计数断言护栏。


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
from . import kpl_fetchers as kpl  # 开盘啦 KPL（交接文档 07 T3，v3.8.8）
from . import em_client as emc
from . import ths_fetchers as ths
from . import tdx_local as tdx
from . import tdx_mcp_fetchers as tdxm  # 通达信官方 MCP（与 eltdx 平级互备，v0.1.0-DEV）
from . import tq_fetchers as tqf  # 通达信 TQ 本地源（HTTP 17709，SP-2026-10-13-001）
# ── 数据源大扩充（SP-2026-09-23-001）：新增 11 个 fetcher 模块 ──
from . import sina_fetchers as sina          # 新浪研报/资金流/期权
from . import baidu_fetchers as baidu        # 百度股市通 K 线
from . import baostock_fetchers as baostock  # baostock 估值/退市/ST
from . import exchange_official_fetchers as exchg  # 沪深交易所官方
from . import event_driven_fetchers as evtd  # 事件驱动 6 件套
from . import macro_official_fetchers as macro_off    # 人行/统计局/中债/货币网
from . import wallstreetcn_fetchers as wscn           # 华尔街见闻
from . import cctv_news_fetchers as cctv              # 央视新闻联播
from . import sw_industry_fetchers as swind           # 申万行业变迁
from . import industry_news_fetchers as indnews       # 产业链资讯 RSS
from . import tdx_package_fetchers as tdxpkg          # 通达信官网盘后包（H5）

# ============================================================
# 数据源注册表（唯一直接知识源）— 批次C2 数据化（2026-11-11）
# ============================================================
# 每行 = (data_type, source_name, fetcher, priority, exclusive)。
# 原「逐条 register 调用体 + 顶部手抄矩阵 docstring」双份知识合一于此：
#   - 顶部手抄矩阵因与 register 调用必漂移（实测已缺 shortline/KPL/index
#     全代新增）而删除，本表为唯一事实；
#   - 历史裁决注释（死源剥离/降级 P999/备源选型理由）随行内联，改动新类型
#     时在本表加行即可，计数护栏见 tests/test_v3314|v3315 计数断言。
_SOURCE_TABLE: tuple[tuple[str, str, object, int, bool], ...] = (
# ── 行情类 ──
    ("realtime_quote", "eltdx", ef.fetch_realtime_quote, 1, False),
    ("realtime_quote", "akshare", akf.fetch_realtime_quote, 100, False),
    ("realtime_quote", "tencent_http", hf.fetch_realtime_quote_tencent, 200, False),
    ("historical_kline", "eltdx", ef.fetch_historical_kline, 1, False),
    ("historical_kline", "akshare", akf.fetch_historical_kline, 100, False),
    ("minute_data", "eltdx", ef.fetch_minute_data, 1, False),
    ("minute_data", "akshare", akf.fetch_minute_data, 100, False),
# ── eltdx 独占源 ──
    ("call_auction", "eltdx", ef.fetch_call_auction, 1, True),
    ("tick_data", "eltdx", ef.fetch_tick_data, 1, True),
    ("f10_profile", "eltdx", ef.fetch_f10_profile, 1, True),
    ("security_codes", "eltdx", ef.fetch_security_codes, 1, True),
    ("all_a_shares", "eltdx", ef.fetch_all_a_shares, 1, True),
    ("minute_history", "eltdx", ef.fetch_minute_history, 1, True),
    ("minute_aux", "eltdx", ef.fetch_minute_aux, 1, True),
    ("today_ticks", "eltdx", ef.fetch_today_ticks, 1, True),
    ("opening_match", "eltdx", ef.fetch_opening_match, 1, True),
    ("full_kline", "eltdx", ef.fetch_full_kline, 1, True),
    ("adjusted_kline", "eltdx", ef.fetch_adjusted_kline, 1, True),
    ("stock_profile", "eltdx", ef.fetch_stock_profile, 1, True),
    ("shortline_indicators", "eltdx", ef.fetch_shortline_indicators, 1, True),
    ("finance_batch", "eltdx", ef.fetch_finance_batch, 1, True),
    ("special_limits", "eltdx", ef.fetch_special_limits, 1, True),
    ("finance_report", "eltdx", ef.fetch_finance_report, 1, True),
    ("dividend_financing", "eltdx", ef.fetch_dividend_financing, 1, True),
    ("company_news", "eltdx", ef.fetch_company_news, 1, True),
    ("northbound_holding", "eltdx", ef.fetch_northbound_holding, 1, True),
    ("stock_topics", "eltdx", ef.fetch_stock_topics, 1, True),
    ("topic_stocks", "eltdx", ef.fetch_topic_stocks, 1, True),
    ("auction_data", "eltdx", ef.fetch_auction_data, 1, True),
    ("category_quotes", "eltdx", ef.fetch_category_quotes, 1, False),
    ("category_quotes", "tencent", hf.fetch_category_quotes_tencent, 100, False),
    ("trading_day", "eltdx", ef.fetch_trading_day, 1, True),
    ("opening_match_history", "eltdx", ef.fetch_opening_match_history, 1, True),
    ("capital_changes", "eltdx", ef.fetch_capital_changes, 1, True),
    ("special_limits_scan", "eltdx", ef.fetch_special_limits_scan, 1, True),
    ("f10_extra", "eltdx", ef.fetch_f10_extra, 1, True),
# ── 通达信官方 MCP（tdx_mcp，v0.1.0-DEV，SP-2026-09-21-001） ──
# 与 eltdx 同属 priority=1 第一梯队，互为备份、互为兜底。
# SmartRouter 机制：同 priority=1 时健康分高者优先 → 日常 eltdx 胜出；
# eltdx 连续失败健康分归零后自动切到本源，恢复后自动切回（非独占 + 自动降级）。
# token 走独立 env TDX_MCP_TOKEN，缺失时空闲（fetch_fn 抛 TDXSourceUnavailable），
# 不影响注册，也不影响 eltdx 正常服务。
    ("realtime_quote", "tdx_mcp", tdxm.fetch_realtime_quote, 1, False),
    ("historical_kline", "tdx_mcp", tdxm.fetch_historical_kline, 1, False),
# ── 通达信 TQ 本地源（tq，SP-2026-10-13-001）──
# 走本地 HTTP 17709（JSON-RPC），依赖通达信客户端运行中；未运行 → TQSourceUnavailable
# → 标准失败降级（DEBUG 日志，客户端没开是常态）。与 eltdx/tdx_mcp 平级互备。
    ("realtime_quote", "tq", tqf.fetch_realtime_quote_tq, 1, False),
# tq 独占增量类型（eltdx/tdx_mcp/akshare 均无）：L2 统计 + 通达信公式生态桥
    ("l2_stats", "tq", tqf.fetch_l2_stats, 1, False),
    ("tdx_formula", "tq", tqf.fetch_tdx_formula, 1, False),
# ── 通达信官方 MCP 纯增量类型（eltdx 无法提供的增量能力，独立 data_type）──
# 这些不属于"与 eltdx 互备"，而是官方 MCP 的额外能力，经 registry 统一暴露：
#   - screener：自然语言条件选股（L3 独立工具 natural_lang_screener 消费）
#   - research_report：券商研报（wenda_report_query）
#   - macro_data：宏观数据增强（wenda_macro_query，与 akshare 版互为交叉验证）
    ("screener", "tdx_mcp", tdxm.fetch_screener, 1, False),
    ("research_report", "tdx_mcp", tdxm.fetch_research_report, 1, False),
    ("macro_data", "tdx_mcp", tdxm.fetch_macro_data, 100, False),
# ── akshare 单源（备 tencent_http） ──
    ("company_info", "akshare", akf.fetch_company_info, 1, False),
# v3.3.14: 补独立备源（非东财）——原先这四类均为 akshare 单源，东财异常时无兜底
    ("company_info", "cninfo", akf.fetch_company_info_cninfo, 100, False),
    ("financial_stmt", "akshare", akf.fetch_financial_stmt, 1, False),
    ("financial_stmt", "sina", akf.fetch_financial_stmt_sina, 100, False),
    ("valuation", "akshare", akf.fetch_valuation, 1, False),
    ("valuation", "eltdx", ef.fetch_valuation_eltdx, 100, False),
    ("industry_data", "akshare", akf.fetch_industry_data, 1, False),
    ("industry_data", "ths", akf.fetch_industry_data_ths, 100, False),
    ("market_overview", "akshare", akf.fetch_market_overview, 1, False),
    ("market_overview", "tencent_http", hf.fetch_market_overview_tencent, 100, False),
    ("index_daily_amount", "akshare", akf.fetch_index_daily_amount, 1, False),
    ("news_data", "akshare", akf.fetch_news_data, 1, False),
# 2026-09-23：em_news_direct 降级 P999（search-api-web 不在封禁名单，
# 但东财整体「非必要不调用」，akshare 版本主源已足够）
    ("news_data", "em_news_direct", nf.fetch_em_news_direct, 999, False),
    ("telegraph_news", "cls_telegraph", nf.fetch_cls_telegraph, 1, False),
    ("cninfo_announcement", "cninfo_direct", nf.fetch_cninfo_direct, 1, False),
    ("macro_data", "akshare", akf.fetch_macro_data, 1, False),
    ("etf_data", "astock_signals", asf.fetch_etf_data, 1, False),
    ("cb_data", "astock_signals", asf.fetch_cb_data, 1, False),
    ("hot_stocks", "akshare", akf.fetch_hot_stocks, 1, False),
# ── 东财主 + akshare 备 —— 2026-09-23 东财 push2 族被风控移除 ──
# fund_flow：原 em_push2 主源已删（push2 域名被封），akshare 自身底层抓
# push2his 也在封禁名单，所以 fund_flow 实际也成裸类型（akshare 备源也挂）。
# 但保留 akshare 注册 —— push2his 不在被封列表时它会恢复服务。
    ("fund_flow", "akshare", akf.fetch_fund_flow, 100, False),
# dragon_tiger：datacenter-web 不在封禁列表，仍可用 —— 但按老板指示降级 P999
    ("dragon_tiger", "em_datacenter", asf.fetch_dragon_tiger_em, 999, False),
    ("dragon_tiger", "akshare", akf.fetch_dragon_tiger, 100, False),
# industry_comparison：em_push2 主源已删，保留 akshare + ths_flow 双备源
    ("industry_comparison", "akshare", akf.fetch_industry_comparison, 100, False),
# v3.3.15：上面两源**同属东财 push2 族**，本机会一起被 RST（实测两源同时
# RemoteDisconnected），名义双源、实际无兜底。补同花顺行业资金流作为
# 跨上游兜底，主源同族失效时它是实际可用的一环。
    ("industry_comparison", "ths_flow", akf.fetch_industry_comparison_ths, 200, False),
# 工单 H7：再补新浪行业页（第三独立上游）。口径不同——新浪只有涨跌幅+成交额、
# 没有主力净额，输出 metric=amount_change 并写明口径，绝不伪造净流入。
    ("industry_comparison", "sina_industry", sina.fetch_industry_comparison_sina, 300, False),
# ── 同花顺主 + akshare 备 ──
    ("northbound", "ths_hsgt", asf.fetch_northbound_ths, 1, False),
    ("northbound", "akshare", akf.fetch_northbound, 100, False),
# ── 独占源 —— 2026-09-23 东财 push2 族被风控移除 ──
    ("hot_money", "ths_editorial", asf.fetch_hot_money, 1, True),
# lockup_expiry：datacenter-web 不在封禁列表 —— 按老板指示独占也降级 P999
    ("lockup_expiry", "em_datacenter", asf.fetch_lockup_expiry, 999, True),
# limit_up_board：原 em_push2_clist 主源已删（push2 域名被封）→ 整类型失效
# 2026-09-26 修复：补 akshare_em 主源（stock_zt_pool_em），独立于 push2 域名族
    ("limit_up_board", "akshare_em", akf.fetch_limit_up_board, 1, False),
# ── 大市值名单（工单 H4，2026-11-06）──
# 主源新浪 bigcaps（按总市值降序翻页，东财 2026-09-22 起成片失败后的替代）；
# 备源东财全市场快照（stock_zh_a_spot_em），与主源不同接口，失败才降级。
    ("bigcaps", "sina_bigcaps", sina.fetch_sina_bigcaps, 1, False),
    ("bigcaps", "akshare_em", akf.fetch_bigcaps_em, 100, False),
# ── 通达信盘后包（工单 H5，2026-11-06）──
# 官方每日增量包 g4day（约 2.7MB，17:00 后发布），全市场日线含成交额。
# 只挂一个源：packet 下载/解析失败时由 service 层降级到实时成交额榜。
    ("tdx_daily_package", "tdx_official", tdxpkg.fetch_tdx_daily_package, 1, False),
# ── akshare 主 + tencent_http 备 ──
    ("profit_forecast", "akshare", akf.fetch_profit_forecast, 1, False),
    ("profit_forecast", "tencent_http", hf.fetch_profit_forecast_tencent, 100, False),
# ── 单源 —— 2026-09-23 东财 push2delay 被风控移除 ──
# concept_attribution：原 em_push2delay 主源已删 → 整类型失效（裸类型，
# 老板拍板「能用就保留，不能用就接受失效」，待补同花顺备源；
# 2026-09-28 审计已删旧 push2 fetcher 代码）
# ── v3.3.1 新增：全局行情（腾讯直连，美股/大宗/亚太/外汇） ──
    ("global_market_quote", "tencent_http", hf.fetch_global_quote_tencent, 1, False),
# ── 市场级统计（实时涨跌家数 / 行业板块涨幅）为裸类型 ──
# 2026-09-23 移除东财 push2ex / push2 主源（push2 域名族被持续风控，
# curl: (56) 连接被服务端主动断开，且 akshare _em 后缀接口连锁失效）。
# market_breadth / industry_quotes 暂成裸类型 —— 老板拍板「能用就保留，
# 不能用就接受失效」，等需要时再补同花顺备源。
# ── v3.3.8/3.3.9 曾新增的市场级统计源（market_breadth / industry_quotes /
# stock_boards）已于 2026-09-23 随东财 push2 族退役删除；push2 时代的死
# fetcher 函数已于 2026-09-28 审计清理。裸类型待补同花顺备源（老板拍板）：
# market_breadth / industry_quotes / stock_boards / concept_attribution。
# 同花顺备源（全部走 ths 独立上游，与 push2 无关）：
    ("ths_eps_forecast", "ths", ths.fetch_ths_eps_forecast, 1, False),
    ("ths_hot_reason", "ths", ths.fetch_ths_hot_reason, 1, False),
    ("ths_limit_up_pool", "ths", ths.fetch_ths_limit_up_pool, 1, False),
    ("ths_hot_list", "ths", ths.fetch_ths_hot_list, 1, False),
    ("ths_up_down_distribution", "ths", ths.fetch_ths_up_down_distribution, 1, False),
    ("ths_limit_up_minute", "ths", ths.fetch_ths_limit_up_minute, 1, False),
    ("ths_turnover_minute", "ths", ths.fetch_ths_turnover_minute, 1, False),
    ("ths_market_breadth", "ths", ths.fetch_ths_market_breadth, 1, False),
    ("local_kline", "tdx_local", tdx.fetch_local_kline, 1, False),
    ("local_minute", "tdx_local", tdx.fetch_local_minute, 1, False),
# ── v3.3.0 新增：新闻/资讯类数据源 ──
    ("baidu_economic_calendar", "akshare_baidu_economic", akf.fetch_baidu_economic_calendar, 1, False),
    ("baidu_trade_notify", "akshare_baidu_notify", akf.fetch_baidu_trade_notify, 1, False),
# index_news_sentiment 的旧主源 akshare_index_sentiment 已退役（上游 chinascope
# 永久失效），改由下方 v3.3.15 区块统一装配主源+备源，故此处不再注册。
    ("futures_news", "akshare_futures_news", akf.fetch_futures_news, 1, False),
    ("sina_finance_news", "sina_direct", nf.fetch_sina_finance_news, 1, False),
    ("hot_search", "akshare_hot_search", akf.fetch_hot_search_baidu, 1, False),
    ("hot_rank", "akshare_hot_rank", akf.fetch_hot_rank_data, 1, False),
    ("xueqiu_hot", "akshare_xueqiu_hot", akf.fetch_xueqiu_hot, 1, False),
# 机构持仓汇总：2026-09-23 按老板指示降级 P999（datacenter-zlsj 不在封禁
# 列表，但东财整体策略就是「非必要不调用」）。akshare 版按字段名映射，
# 上游改字段顺序也不会错位；akshare 版服务 endpoint="detail"，
# hold 会直接 raise —— hold 场景只有 em_zlsj 这一路。
    ("fund_hold", "em_zlsj_direct", akf.fetch_fund_hold_direct, 999, False),
    ("fund_hold", "akshare_fund_hold", akf.fetch_fund_hold_data, 100, False),
# ── v3.3.15：补「单源无兜底」类型的备源（一律选**非同一上游**，避免同生共死） ──
# 盘点结论：下列 8 类此前均为单源注册，源失效即整类型失效，且部分源还把异常
# 静默吞成空表，失败完全不可见。补齐后每类至少有 2 个不同上游的源。
#
# 财报日历：补百度财报披露时间表（主源同属百度但接口不同，属降级备源）
    ("baidu_economic_calendar", "akshare_report_time", akf.fetch_baidu_economic_calendar_bak, 100, False),
# 交易提示：补全市场停复牌表（百度主源 → akshare 停复牌，语义精确对应）
    ("baidu_trade_notify", "akshare_tfp", akf.fetch_baidu_trade_notify_tfp, 100, False),
# 热度三兄弟（东财人气榜 / 百度热搜 / 雪球热度）→ 统一以同花顺热榜兜底
    ("hot_rank", "ths_hot", akf.fetch_hot_rank_ths, 100, False),
    ("hot_search", "ths_hot", akf.fetch_hot_rank_ths, 100, False),
    ("xueqiu_hot", "ths_hot", akf.fetch_hot_rank_ths, 100, False),
# 指数情绪：**主源整体重装**（旧主源 akshare_index_sentiment 已退役）。
# 旧主源上游 chinascope 永久失效（端点 301 跳官网首页、返 text/html，
# akshare 内部 r.json() 必然 JSONDecodeError，与 SSL 无关），源与配套的
# 全局 SSL hack 一并删除。现把实测可用的乐咕乐股「赚钱效应」提为主源，
# 并补同花顺涨跌分布作跨上游备源（两者上游不同，非同生共死）。
# 注意：备源必须返回 DataFrame —— 工具层 get_market_sentiment 写的是
# `df is None or df.empty`，若给 dict（如 ths_market_breadth）会 AttributeError。
    ("index_news_sentiment", "legu_activity", akf.fetch_market_sentiment_legu, 1, False),
    ("index_news_sentiment", "ths_distribution", ths.fetch_ths_up_down_distribution, 100, False),
# futures_news 保持单源，理由见 CHANGELOG：
#   - futures_news：上游为上海有色网，akshare 无等价第二源
# （fund_hold 已从单源升为双源：em_zlsj_direct 主 + akshare_fund_hold 备）
# ── v3.3.0 新增：同花顺问财数据源（可选依赖） ──
    ("wencai_query", "pywencai", wf.fetch_wencai_query, 1, False),
    ("wencai_news", "iwencai_openapi", wf.fetch_wencai_news, 1, False),
# ── v3.8.8 新增：开盘啦 KPL 数据源（交接文档 07 T3；KPL 短线特色口径独有） ──
# 免鉴权直连（实测 2026-11-07）；KPL 系列在各自类型内为唯一源（exclusive）
    ("kpl_limit_up", "kpl", kpl.fetch_kpl_limit_up, 1, True),
    ("kpl_sentiment", "kpl", kpl.fetch_kpl_sentiment, 1, True),
    ("kpl_boards", "kpl", kpl.fetch_kpl_boards, 1, True),
    ("kpl_bidding", "kpl", kpl.fetch_kpl_bidding, 1, True),
# ════════════════════════════════════════════════════════════════════
# SP-2026-09-23-001 数据源大扩充：一次性注册全部新类型 + 备源
# 设计原则：
#   - 全新类型：主源 priority=1，备源 priority=100/200
#   - 已有类型加备源：作为 priority=100/200 加入（不打乱原有梯队）
#   - 上游独立性验证：每条备源都与主源不同上游（避免假双源）
# ════════════════════════════════════════════════════════════════════
# ── P0 三件套：ETF 期权 + 业绩预告 + 机构调研 ──
# 2026-09-28 死源剥离（老板拍板）：ETF 期权双源（sina_option）上游 OptionService
# 已下线（Service not found），类型与 fetcher 一并移除，待寻新源再接。
    ("earnings_forecast", "em_datacenter", evtd.fetch_earnings_forecast, 999, False),
    ("institution_survey", "em_datacenter", evtd.fetch_institution_survey, 999, False),
# ── 事件驱动其余 4 件套 ──
    ("holder_trades", "em_datacenter", evtd.fetch_holder_trades, 999, False),
    ("share_buyback", "em_datacenter", evtd.fetch_share_buyback, 999, False),
    ("equity_pledge", "em_datacenter", evtd.fetch_equity_pledge, 999, False),
    ("ipo_calendar", "em_datacenter", evtd.fetch_ipo_calendar, 999, False),
# ── 指数追踪：2026-09-28 死源剥离（老板拍板）──
# 中证 zealink 域名（csi-web.cn.zealink.com）全球 DNS 失效、国证 API 404，
# index_constituents / index_weights / index_valuation 三类型双源齐挂，
# fetcher 模块一并移除；复启需改走 csindex.com.cn 官网抓取。
# （2026-11-11 现状：index_valuation / index_constituents 已按此路径复活，
# index_weights 仍死无源。）
# ── 宏观 5 件套 → 2 件套：2026-09-28 死源剥离（老板拍板）──
# 移除 social_financing（人行 404）/ repo_fixing_rate + lpr_history
# （货币网静态 json 404，AGS 接口语义不符）；保留实测可用的 PMI + 中债曲线。
    ("pmi_data", "nbs_official", macro_off.fetch_nbs_pmi, 1, False),
    ("bond_yield_curve", "chinabond_official", macro_off.fetch_chinabond_yield_curve, 1, False),
# 2026-11-08：中债 yield_main 改版（JSON→JS 页面）主源解析空壳已按纪律抛出，
# 东财 datacenter（akshare bond_zh_us_rate）挂第二源兜底国债曲线。
    ("bond_yield_curve", "em_bond_backup", akf.fetch_bond_yield_cn_backup, 100, False),
# 2026-11-08 复活：v3.6.0 曾以 zealink 实现指数估值（后 DNS 死亡被剥离），
# 现换中证官网 OSS 自动估值文件（oss-ch.csindex.com.cn，一手，xls）。
    ("index_valuation", "csindex_official", macro_off.fetch_index_valuation, 1, False),
# 2026-11-11 批次B② 复活：成分股同走中证官网 OSS cons 文件（一手，xls）。
# 覆盖范围仅中证系（国证 399 开头无 cons 文件，实测 404）；index_weights
# 仍死无源不救（2026-11-10 审计确认）。
    ("index_constituents", "csindex_official", macro_off.fetch_index_constituents, 1, False),
# ── 投资者互动 2 件套：2026-09-28 死源剥离（老板拍板）──
# 巨潮互动易上游 500、上交所 e互动 404（主站存活、接口层死亡），
# 类型与 fetcher 模块一并移除。
# ── 全球新闻 3 件套 ──
    ("wallstreetcn_lives", "wscn_api", wscn.fetch_wallstreetcn_lives, 1, False),
    ("macro_calendar", "wscn_api", wscn.fetch_macro_calendar, 1, False),
    ("cctv_news_main", "cctv_official", cctv.fetch_cctv_news, 1, False),
# ── 申万行业历史 2 件套 ──
    ("sw_industry_history", "sw_official", swind.fetch_sw_industry_history, 1, False),
    ("sw_industry_as_of", "sw_official", swind.fetch_sw_industry_as_of, 1, False),
# ── 产业链资讯：1 类型聚合 12 赛道 ──
    ("industry_news", "rss_direct", indnews.fetch_industry_news, 1, False),
# ── 监管异动（交易所股票交易异常波动预警） ──
# 借鉴 chengzuopeng/stock-sdk 的 getUnusualFluctuation 实现（ISC license）
# 数据源：datacenter-web RPT_WATCH_UNUSUAL_FLUCTUATE
# 实测约 4038 条历史，自带两个月滚动窗口；IS_HAPPEN=1 已触发 / =0 逼近未达
# 2026-09-25 30 连续调用压测零封禁零限流，从 P999 提到 P1 主源（老板拍板）
    ("regulatory_anomaly", "em_datacenter", emc.fetch_unusual_fluctuation, 1, False),
# ── 龙虎榜扩展族（借鉴 stock-sdk dragonTiger.ts，ISC license）──
# 全部走 datacenter-web 子域。补全 tradex-hub 龙虎榜缺失维度：
#   - dt_detail：上榜个股详情（含 D1/D2/D5/D10 上榜后股价跟踪）
#   - dt_stock_stats：个股上榜次数统计（按周期聚合）
#   - dt_institution：机构席位买卖统计
#   - dt_seat_detail：个股某日买卖营业部席位明细（注意上游不接受组合 filter，只按 SECURITY_CODE 过滤再按 TRADE_DATE 倒序取最新）
#   - dt_branch_rank：营业部排行（**akshare 独占源** —— 上游 datacenter-web 无对应 report，
#     走 akshare 包装的 stock_lhb_yybph_em，2026-09-25 老板拍板战略转向后唯一接入路径）
# 2026-09-25 30 连续调用压测零封禁零限流，em_datacenter 主源从 P999 提到 P1
# 2026-09-25 老板拍板新增 akshare 包装层作 priority=100 备源（字段对齐主源）
    ("dt_detail", "em_datacenter", emc.fetch_dragon_tiger_detail, 1, False),
    ("dt_detail", "akshare_em", akf.fetch_dt_detail_em, 100, False),
    ("dt_stock_stats", "em_datacenter", emc.fetch_dragon_tiger_stock_stats, 1, False),
    ("dt_stock_stats", "akshare_em", akf.fetch_dt_stock_stats_em, 100, False),
    ("dt_institution", "em_datacenter", emc.fetch_dragon_tiger_institution, 1, False),
    ("dt_institution", "akshare_em", akf.fetch_dt_institution_em, 100, False),
    ("dt_seat_detail", "em_datacenter", emc.fetch_dragon_tiger_seat_detail, 1, False),
# dt_seat_detail 不加 akshare 备源：akshare 的 stock_lhb_stock_detail_date_em
# 只给上榜日期列表，不提供买卖席位明细；席位明细主源只有 datacenter-web 一路
# dt_branch_rank：akshare 独占主源（上游 datacenter-web 无对应 report）
    ("dt_branch_rank", "akshare_em", akf.fetch_dt_branch_rank_em, 1, False),
# ── 融资融券扩展族（借鉴 stock-sdk margin.ts，ISC license）──
# tradex-hub 已有交易所官方两融明细（sse/szse_official），
# 补「账户统计 + 标的列表」两个新维度，走 datacenter-web。
# 2026-09-25 30 连续调用压测零封禁零限流，em_datacenter 主源从 P999 提到 P1
# 2026-09-25 老板拍板新增 akshare 包装层作 priority=100 备源
    ("margin_account_info", "em_datacenter", emc.fetch_margin_account_info, 1, False),
    ("margin_account_info", "akshare_em", akf.fetch_margin_account_info_em, 100, False),
    ("margin_target_list", "em_datacenter", emc.fetch_margin_target_list, 1, False),
# margin_target_list 不加 akshare 备源：akshare 无等价单函数包装
# （东财 RPTA_WEB_RZRQ_GGMX 数据由 stock_margin_account_info 汇总层级提供，
# 个股明细层级需要单独接口，akshare 当前未集成）
# ── 大宗交易族（借鉴 stock-sdk blockTrade.ts，ISC license）──
# tradex-hub 之前完全没有大宗交易能力，本次一次性补齐 3 个维度。
# 2026-09-25 30 连续调用压测零封禁零限流，em_datacenter 主源从 P999 提到 P1
# 2026-09-25 老板拍板新增 akshare 包装层作 priority=100 备源
    ("block_trade_market_stat", "em_datacenter", emc.fetch_block_trade_market_stat, 1, False),
    ("block_trade_market_stat", "akshare_em", akf.fetch_block_trade_market_stat_em, 100, False),
    ("block_trade_detail", "em_datacenter", emc.fetch_block_trade_detail, 1, False),
    ("block_trade_detail", "akshare_em", akf.fetch_block_trade_detail_em, 100, False),
    ("block_trade_daily_stat", "em_datacenter", emc.fetch_block_trade_daily_stat, 1, False),
    ("block_trade_daily_stat", "akshare_em", akf.fetch_block_trade_daily_stat_em, 100, False),
# ── 给已有类型加独立备源（一主一备 / 一主二备） ──
# historical_kline 第四备源：百度股市通（与 eltdx/akshare/tdx_mcp 完全独立）
    ("historical_kline", "baidu_http", baidu.fetch_baidu_kline_with_ma, 200, False),
# research_report 第二备源：新浪研报（与 tdx_mcp 独立）
    ("research_report", "sina_research", sina.fetch_sina_research_reports, 100, False),
# fund_flow 解决裸源：新浪日度资金流（与 akshare 独立）
    ("fund_flow", "sina_fund_flow", sina.fetch_sina_fund_flow, 100, False),
# valuation 第三备源：baostock TCP（独立通道）
    ("valuation", "baostock_tcp", baostock.fetch_baostock_valuation_history, 200, False),
# dragon_tiger 官方备源：沪深交易所一手（含营业部席位）
    ("dragon_tiger", "sse_official", exchg.fetch_sse_dragon_tiger, 50, False),
    ("dragon_tiger", "szse_official", exchg.fetch_szse_dragon_tiger, 60, False),
# 退市日 + ST 名单：baostock 兜底
    ("delisting_date", "baostock_tcp", baostock.fetch_baostock_delisting_date, 100, False),
    ("st_stock_list", "baostock_tcp", baostock.fetch_baostock_st_list, 100, False),
# 交易日历：深交所官方替换 eltdx 兜底
    ("trading_calendar", "szse_official", exchg.fetch_szse_trading_calendar, 50, False),
# 交易日历备源：sina 交易日清单（与深交所接口完全独立，覆盖 1990→当年年末）
    ("trading_calendar", "akshare_sina", akf.fetch_trading_calendar, 100, False),
# 深市公告：官方备源（与巨潮独立）
    ("cninfo_announcement", "szse_official", exchg.fetch_szse_announcement, 100, False),
# 两融明细：交易所官方一手
    ("margin_trading", "sse_official", exchg.fetch_sse_margin_trading, 50, False),
    ("margin_trading", "szse_official", exchg.fetch_szse_margin_trading, 60, False),
)


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
    """实际注册逻辑（调用方须持有 _register_lock）。

    批次C2（2026-11-11）数据化：注册明细唯一直接知识源 = 模块级
    ``_SOURCE_TABLE``，本函数只负责把表按原顺序灌进 SmartRouter
    全局单例（行为与逐条 register 等价，改前/改后 _sources 快照比对实证）。
    """
    router = get_router()
    for data_type, source, fetch_fn, priority, exclusive in _SOURCE_TABLE:
        router.register(data_type, source, fetch_fn, priority=priority, exclusive=exclusive)

    report = router.get_registry_report()
    data_types = sorted({x["data_type"] for x in report})
    logger.info(
        "register_all_sources: 已注册 %d 个数据类型, %d 个数据源",
        len(data_types), len(report),
    )
