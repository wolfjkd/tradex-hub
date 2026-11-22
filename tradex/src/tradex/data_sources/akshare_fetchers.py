"""
AKShare 数据源 fetch_fn 包装器。

所有 akshare 的数据获取函数在此注册为 SmartRouter fetch_fn。
仅本文件（及 data_sources 包内其他 fetcher 文件）允许 `import akshare`。

设计原则：
  - 每个 fetch_fn 接受 **kwargs，返回原始数据（DataFrame/dict）
  - 多 endpoint 的数据类型（如 financial_stmt）通过 endpoint 参数分派
  - fetch_fn 只负责调用 akshare API 获取原始数据，不做过滤/格式化/缓存
  - 源内的 fallback（如 spot_em → spot）在 fetch_fn 内部处理
"""

from __future__ import annotations

import calendar
import logging
import time
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from ..utils.cache import cache

# —— QI-ARCH-09 六上游拆分（2026-11-19）：公共层独立 + EM/四池/备源三子模块；
# 本文件保留 akshare 主族 25 函数 + baidu 主族；下方 re-export 为兼容层
# （registry/_SOURCE_TABLE 等调用方 import 路径不变 = 行为零变化；渐进改引记录交接）。
from .akshare_common import (  # noqa: E402,F401 — 兼容 re-export
    _ak,
    _normalize_ak_period,
    _prev_quarter_end,
    _is_arrow_escape_invalid,
)
from .akshare_em import (  # noqa: E402,F401
    fetch_fund_hold_direct,
    fetch_dt_detail_em,
    fetch_dt_institution_em,
    fetch_dt_stock_stats_em,
    fetch_dt_branch_rank_em,
    fetch_margin_account_info_em,
    fetch_block_trade_market_stat_em,
    fetch_block_trade_detail_em,
    fetch_block_trade_daily_stat_em,
    fetch_bigcaps_em,
    fetch_global_index_spot,
)
from .akshare_pools import (  # noqa: E402,F401
    fetch_limit_up_board_em,
    _normalize_board_date,
    _latest_board_date,
    _trade_dates_recent,
    _latest_board_date_with_rows,
    _pick_field,
    _map_pool_rows,
    _fetch_pool_rows,
    _fetch_pool_with_fields,
    fetch_limit_up_board,
    fetch_board_sentiment,
)
from .akshare_backup import (  # noqa: E402,F401
    _fetch_sina_index_amount_today,
    _fetch_index_daily_from_push2his,
    _code6,
    _prefixed_code,
    fetch_company_info_cninfo,
    fetch_financial_stmt_sina,
    fetch_industry_data_ths,
    fetch_industry_comparison_ths,
    fetch_hot_rank_ths,
    fetch_baidu_economic_calendar_bak,
    fetch_market_sentiment_legu,
    fetch_baidu_trade_notify_tfp,
    fetch_bond_yield_cn_backup,
)

logger = logging.getLogger("tradex.akshare")

# v3.3.15 新增：季度末日期计算。
# 旧实现用 f"{year}{q*3:02d}31" 硬编码 31 日，Q2(6月)/Q3(9月) 会算出
# 20260631 / 20260931 这类**不存在的日期**，上游直接报错，而错误又被
# except 静默吞成空表 —— 结果是每年 4–9 月「机构持仓」默认调用恒返回空。



# 待发版：`_ssl_patch_lock` 已随 `fetch_index_news_sentiment` 一并删除。
# 原因：该锁只为串行化「临时篡改进程级 requests.sessions.Session.request 的
# verify 开关」而存在 —— 这是全局副作用，锁只能缩小窗口、不能消除风险。
# 而其唯一服务对象（chinascope 指数新闻情绪）上游**已永久失效**（端点 301 跳官网首页、
# 返回 text/html，akshare 内部 r.json() 必然 JSONDecodeError），源已退役，
# 这把拿全局副作用换来的锁自然失去存在理由。






# ============================================================
# K 线周期归一化（v3.3.14 新增）
# ============================================================
# SmartRouter 会把同一个 period 参数**原样转发**给主源(eltdx)与备源(akshare)，
# 但两源值域不同：eltdx 认 day/week/month，akshare 认 daily/weekly/monthly。
# eltdx 源内部有 _normalize_period() 归一化，akshare 源此前没有 ——
# 于是传 'day' 时主源正常、一旦降级到 akshare 就 KeyError('day')，降级链在该值下必断。
# 这里做反向归一化，使两个源的 period 语义对齐。




# ============================================================
# realtime_quote — 全量行情快照
# ============================================================

def fetch_realtime_quote(symbol: str = "", code: str = "", **kwargs):
    """A股实时行情快照（东方财富主，新浪备）。返回全量 DataFrame，含'代码'列。

    工具层负责按 symbol 过滤。
    兼容 symbol/code 两种参数名（SmartRouter 路由归一化）。
    """
    ak = _ak()
    try:
        df = ak.stock_zh_a_spot_em()
        if df is not None and not df.empty:
            return df
    except Exception as e:
        logger.debug("stock_zh_a_spot_em failed: %s", e)
    # 源内 fallback: 新浪
    df = ak.stock_zh_a_spot()
    if df is None or df.empty:
        raise RuntimeError("akshare realtime_quote returned empty (em+sina)")
    return df


# ============================================================
# historical_kline — 历史 K 线
# ============================================================

def fetch_historical_kline(
    symbol: str = "",
    code: str = "",
    period: str = "daily",
    start_date: str = "",
    end_date: str = "",
    adjust: str = "qfq",
    **kwargs,
):
    """历史 K 线（东方财富 stock_zh_a_hist）。返回中文列名 DataFrame。

    兼容 symbol/code 两种参数名（SmartRouter 路由归一化）。
    v3.3.14: period 先做归一化(day/week/month → daily/weekly/monthly)，
    使本备源与 eltdx 主源的周期语义对齐，避免路由原样透传时降级链断裂。
    """
    ak = _ak()
    sym = symbol or code
    em_kwargs: dict = {"symbol": sym, "period": _normalize_ak_period(period), "adjust": adjust}
    if start_date:
        em_kwargs["start_date"] = start_date
    if end_date:
        em_kwargs["end_date"] = end_date
    return ak.stock_zh_a_hist(**em_kwargs)


# ============================================================
# index_daily_amount — 指数历史日K成交额（量能对比数据源）
# ============================================================

def fetch_index_daily_amount(symbol: str = "", code: str = "", days: int = 6, **kwargs):
    """指数历史日K 量能序列（供盘后复盘「量能对比」柱状图）。

    主源：东方财富 push2his（历史K线域名，直连，curl_cffi 绕过系统代理）。
      返回字段 f51-f61 = [日期, 开, 收, 高, 低, 成交量(手), 成交额(元), 振幅, 涨跌幅, 涨跌额, 换手率]，
      其中 成交额 在第7位（index 6）。
    备源1：腾讯财经 stock_zh_index_daily_tx（直连可达，仅 成交量(手)，无成交额）。
    备源2：东方财富 stock_zh_index_daily_em（含 成交量+成交额；当前网络拓扑下 push2 直连常 RemoteDisconnected）。
    返回最近 days 个交易日的 [日期, 成交量(手), 成交额(元)]。
    兼容 symbol/code 两种参数名（symbol 用 sh000001 / sz399001 / sz399006 等格式）。
    """
    ak = _ak()
    sym = symbol or code
    if not sym:
        raise RuntimeError("index symbol required (e.g. sh000001)")

    # 主源：东财 push2his 历史K线（能返回成交额(元)）
    try:
        return _fetch_index_daily_from_push2his(sym, days)
    except Exception as e_push2his:
        logger.debug("push2his index daily(%s) failed: %s", sym, e_push2his)

    # 备源1：腾讯财经（amount 列实为成交量(手)，无成交额）
    try:
        df = ak.stock_zh_index_daily_tx(symbol=sym)
        src = "tx"
    except Exception as e_tx:
        logger.debug("stock_zh_index_daily_tx(%s) failed: %s", sym, e_tx)
        # 备源2：东方财富（含 成交量 + 成交额）
        try:
            df = ak.stock_zh_index_daily_em(symbol=sym)
            src = "em"
        except Exception as e_em:
            raise RuntimeError(
                f"index daily failed all (push2his, tx({e_tx}), em({e_em})) for {sym}"
            )

    if df is None or df.empty:
        raise RuntimeError(f"index daily empty for {sym} (src={src})")

    # 列名兼容：
    #  - 东财 stock_zh_index_daily_em：含 成交量 + 成交额 两列
    #  - 腾讯 stock_zh_index_daily_tx：仅 amount 列，且该列实为「成交量(手)」
    cols_lower = {str(c).lower(): c for c in df.columns}
    has_volume = any(k in cols_lower for k in ("volume", "vol", "成交量"))
    has_amount_name = any(k in cols_lower for k in ("amount", "amt", "成交额", "成交额(元)"))

    amt_col = None
    if has_volume and has_amount_name:
        # 东财：volume=成交量(手)，amount=成交额(元)
        vol_col = next(c for c in df.columns if str(c).lower() in ("volume", "vol", "成交量"))
        amt_col = next(c for c in df.columns if str(c).lower() in ("amount", "amt", "成交额", "成交额(元)"))
    elif has_amount_name and not has_volume:
        # 腾讯：仅 amount 列，实为成交量(手)
        vol_col = next(c for c in df.columns if str(c).lower() in ("amount", "amt", "成交额", "成交额(元)"))
    else:
        vol_col = df.columns[-1]

    df = df.tail(int(days))
    out = []
    for _, r in df.iterrows():
        vol = float(r.get(vol_col)) if vol_col and r.get(vol_col) is not None else 0.0
        amt = float(r.get(amt_col)) if amt_col and r.get(amt_col) is not None else None
        out.append({
            "date": str(r.get("date", "")),
            "volume": vol,          # 成交量(手)
            "amount": amt,         # 成交额(元)，东财源才有；腾讯源为 None
        })

    # 兜底：腾讯/东财备源仅返回成交量时，用新浪实时补齐「今日成交额(元)」，
    # 保证盘后复盘量能对比可用「亿元」口径而非仅成交量。
    if all(d.get("amount") is None for d in out):
        try:
            today_amt = _fetch_sina_index_amount_today(sym)
            if today_amt is not None and out:
                out[-1]["amount"] = today_amt
                out[-1]["_amount_source"] = "sina_realtime"
        except Exception as e_today:
            logger.debug("sina index amount(%s) backfill failed: %s", sym, e_today)

    return out






# ============================================================
# minute_data — 分时数据
# ============================================================

def fetch_minute_data(symbol: str = "", code: str = "", **kwargs):
    """当日分时数据（东方财富 stock_intraday_em）。返回原始 DataFrame。

    工具层负责列名标准化与格式化。
    兼容 symbol/code 两种参数名（SmartRouter 路由归一化）。
    """
    ak = _ak()
    sym = symbol or code
    df = ak.stock_intraday_em(symbol=sym)
    if df is None or df.empty:
        raise RuntimeError("akshare intraday empty")
    return df


# ============================================================
# company_info — 公司信息（多 endpoint）
# ============================================================

def fetch_company_info(
    endpoint: str = "individual_info",
    symbol: str = "",
    keyword: str = "",
    industry: str = "",
    **kwargs,
):
    """公司信息（多 endpoint 分派）。

    endpoint:
      - code_name:        股票代码名称列表（搜索）
      - individual_info:  个股基本信息
      - profile:          主营业务构成
      - industry_cons:    行业成分股
    """
    ak = _ak()
    if endpoint == "code_name":
        return ak.stock_info_a_code_name()
    if endpoint == "individual_info":
        return ak.stock_individual_info_em(symbol=symbol)
    if endpoint == "profile":
        return ak.stock_zyjs_ths(symbol=symbol)
    if endpoint == "industry_cons":
        return ak.stock_board_industry_cons_em(symbol=industry)
    raise ValueError(f"Unknown company_info endpoint: {endpoint}")


# ============================================================
# financial_stmt — 财务报表（多 endpoint）
# ============================================================

def fetch_financial_stmt(
    endpoint: str = "profit",
    symbol: str = "",
    **kwargs,
):
    """财务报表（多 endpoint 分派）。

    endpoint:
      - profit:     利润表（按季度）
      - balance:    资产负债表（按报告期）
      - cashflow:   现金流量表（按季度）
      - indicator:  财务分析指标
      - segments:   主营业务构成
    """
    ak = _ak()
    if endpoint == "profit":
        return ak.stock_profit_sheet_by_quarterly_em(symbol=symbol)
    if endpoint == "balance":
        return ak.stock_balance_sheet_by_report_em(symbol=symbol)
    if endpoint == "cashflow":
        return ak.stock_cash_flow_sheet_by_quarterly_em(symbol=symbol)
    if endpoint == "indicator":
        return ak.stock_financial_analysis_indicator(symbol=symbol)
    if endpoint == "segments":
        return ak.stock_zygc_em(symbol=symbol)
    raise ValueError(f"Unknown financial_stmt endpoint: {endpoint}")


# ============================================================
# valuation — 估值与分红（多 endpoint）
# ============================================================

def fetch_valuation(
    endpoint: str = "baidu",
    symbol: str = "",
    indicator: str = "",
    **kwargs,
):
    """估值数据（多 endpoint 分派）。

    endpoint:
      - baidu:            百度股市通估值指标（PE/PB/PS/总市值）
      - dividend_detail:  分红明细（stock_history_dividend_detail）
      - dividend_cninfo:  分红明细（巨潮，stock_dividend_cninfo）
      - circulate_holder: 流通股东（stock_circulate_stock_holder）
      - rank_forecast:    分析师评级（stock_rank_forecast_cninfo）
    """
    ak = _ak()
    if endpoint == "baidu":
        return ak.stock_zh_valuation_baidu(
            symbol=symbol, indicator=indicator, period="近一年"
        )
    if endpoint == "dividend_detail":
        return ak.stock_history_dividend_detail(symbol=symbol, indicator="分红")
    if endpoint == "dividend_cninfo":
        return ak.stock_dividend_cninfo(symbol=symbol)
    if endpoint == "circulate_holder":
        return ak.stock_circulate_stock_holder(symbol=symbol)
    if endpoint == "rank_forecast":
        return ak.stock_rank_forecast_cninfo()
    raise ValueError(f"Unknown valuation endpoint: {endpoint}")


# ============================================================
# industry_data — 行业与板块（多 endpoint）
# ============================================================

def fetch_industry_data(
    endpoint: str = "board_industry_name_em",
    industry: str = "",
    sector_type: str = "行业资金流",
    indicator: str = "今日",
    period: str = "日k",
    start_date: str = "",
    end_date: str = "",
    **kwargs,
):
    """行业板块数据（多 endpoint 分派）。

    endpoint:
      - board_industry_name_em:  行业板块列表（东方财富）
      - board_industry_name_ths: 行业板块列表（同花顺）
      - board_industry_cons_em:  行业成分股
      - board_concept_name_em:   概念板块列表（东方财富）
      - board_concept_name_ths:  概念板块列表（同花顺）
      - sector_fund_flow_rank:   板块资金流向排名
      - board_industry_hist_em:  行业板块历史行情
    """
    ak = _ak()
    if endpoint == "board_industry_name_em":
        return ak.stock_board_industry_name_em()
    if endpoint == "board_industry_name_ths":
        return ak.stock_board_industry_name_ths()
    if endpoint == "board_industry_cons_em":
        return ak.stock_board_industry_cons_em(symbol=industry)
    if endpoint == "board_concept_name_em":
        return ak.stock_board_concept_name_em()
    if endpoint == "board_concept_name_ths":
        return ak.stock_board_concept_name_ths()
    if endpoint == "sector_fund_flow_rank":
        # 使用 curl_cffi 绕过系统代理（东财 push2 接口）
        from curl_cffi import requests as _rq
        _session = _rq.Session()
        _session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": "https://data.eastmoney.com/",
        })
        _st_map = {"行业资金流": "2", "概念资金流": "3", "地域资金流": "1"}
        _ind_map = {"今日": "0", "5日": "5", "10日": "10"}
        _fs = f"m:90+t:{_st_map.get(sector_type, '2')}"
        _url = "https://push2.eastmoney.com/api/qt/clist/get"
        _params = {
            "pn": "1", "pz": "100", "po": "1", "np": "1",
            "ut": "b2884a393a59ad64002292a3e90d46a5",
            "fltt": "2", "invt": "2",
            "fid0": "f62",
            "fs": _fs,
            "stat": "1",
            "fields": (
                "f12,f14,f2,f3,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,"
                "f204,f205,f124"
            ),
            "rt": "52975239",
        }
        resp = _session.get(_url, params=_params, timeout=15, impersonate="chrome120")
        resp.raise_for_status()
        _data = resp.json()
        _items = _data.get("data", {}).get("diff", [])
        _rows = []
        for item in _items:
            _rows.append({
                "板块": item.get("f14", ""),
                "代码": item.get("f12", ""),
                "最新价": item.get("f2", 0),
                "涨跌幅": item.get("f3", 0),
                "主力净流入": item.get("f62", 0),
                "主力净流入-占比": item.get("f184", 0),
                "超大单净流入": item.get("f66", 0),
                "超大单净流入-占比": item.get("f69", 0),
                "大单净流入": item.get("f72", 0),
                "大单净流入-占比": item.get("f75", 0),
                "中单净流入": item.get("f78", 0),
                "中单净流入-占比": item.get("f81", 0),
                "小单净流入": item.get("f84", 0),
                "小单净流入-占比": item.get("f87", 0),
                "主力净流入排名": item.get("f204", 0),
                "涨跌股数比": item.get("f205", 0),
            })
        if not _rows:
            # QI-STD-26（工单 17）：行业板块全量列表（feed 型）空 = push2 断源/结构
            # 变化（push2 域名族在封禁名单），不再折叠空表，抛出由 SmartRouter
            # 降级到 ths 备源。
            raise RuntimeError(
                f"东财行业板块列表返回空（push2 断源或结构变化）: endpoint={endpoint}"
            )
        return pd.DataFrame(_rows)
    if endpoint == "board_industry_hist_em":
        kw: dict = {"symbol": industry, "period": period}
        if start_date:
            kw["start_date"] = start_date
        if end_date:
            kw["end_date"] = end_date
        return ak.stock_board_industry_hist_em(**kw)
    raise ValueError(f"Unknown industry_data endpoint: {endpoint}")


# ============================================================
# market_overview — 指数行情
# ============================================================

def fetch_market_overview(symbol: str = "", **kwargs):
    """主要指数实时行情。返回 DataFrame（含 最新价/涨跌幅/成交量/成交额 等）。

    主源：新浪/腾讯 stock_zh_index_spot_sina（直连可达，成交额单位=元，数据正确）。
    备源：东方财富 stock_zh_index_spot_em（当前网络拓扑下 push2 直连常 RemoteDisconnected，
    失败时自动降级新浪源）。
    注意：旧版 akshare 的 stock_zh_index_spot 已改名 stock_zh_index_spot_sina，直接调用会
    AttributeError，故主源改用 _sina 后缀接口。
    """
    ak = _ak()
    if symbol:
        # 指定系列指数时走东财（带 symbol 参数过滤）
        try:
            return ak.stock_zh_index_spot_em(symbol=symbol)
        except Exception as e_em:
            logger.debug("stock_zh_index_spot_em(%s) failed: %s", symbol, e_em)
            return ak.stock_zh_index_spot_sina()
    try:
        df = ak.stock_zh_index_spot_sina()
        if df is not None and not df.empty:
            return df
    except Exception as e:
        logger.debug("stock_zh_index_spot_sina failed: %s", e)
    # 备源：东方财富
    return ak.stock_zh_index_spot_em()


# ============================================================
# news_data — 新闻与公告（多 endpoint）
# ============================================================



def fetch_news_data(
    endpoint: str = "stock_news_em",
    symbol: str = "",
    date: str = "",
    **kwargs,
):
    """新闻数据（多 endpoint 分派）。

    endpoint:
      - stock_news_em:       个股新闻（ArrowInvalid 库内 bug 时自动转调 em_news_direct）
      - stock_report_disclosure: 财报披露时间表
      - stock_notice_report: 公告
      - stock_news_main_cx:  财新网新闻
      - news_cctv:           CCTV 新闻
    """
    ak = _ak()
    if endpoint == "stock_news_em":
        try:
            return ak.stock_news_em(symbol=symbol)
        except Exception as e:
            if _is_arrow_escape_invalid(e):
                # 批次B①（2026-11-11）：akshare 库内 bug 与源健康无关，转调同
                # schema 的 em_news_direct（registry news_data 的 P999 备源）。
                from tradex.data_sources.news_fetchers import fetch_em_news_direct

                logger.warning(
                    "fetch_news_data(stock_news_em): akshare ArrowInvalid bug, "
                    "fallback to em_news_direct: %s",
                    e,
                )
                return fetch_em_news_direct(symbol=symbol)
            raise
    if endpoint == "stock_report_disclosure":
        # 尝试传递 period 参数（akshare 可能按报告期过滤）
        if date:
            return ak.stock_report_disclosure(period=date)
        return ak.stock_report_disclosure()
    if endpoint == "stock_notice_report":
        kw = {}
        if symbol:
            kw["symbol"] = symbol
        return ak.stock_notice_report(**kw)
    if endpoint == "stock_news_main_cx":
        return ak.stock_news_main_cx()
    if endpoint == "news_cctv":
        return ak.news_cctv(date=date)
    raise ValueError(f"Unknown news_data endpoint: {endpoint}")


# ============================================================
# macro_data — 宏观与外汇（多 endpoint）
# ============================================================

def fetch_macro_data(
    endpoint: str = "gdp",
    symbol: str = "",
    date: str = "",
    **kwargs,
):
    """宏观数据（多 endpoint 分派）。

    endpoint:
      - gdp / cpi / pmi / money_supply: 宏观指标
      - fx_spot:                        外汇汇率
      - bond_yield:                     国债收益率
      - margin_em:                      融资融券汇总（akshare 1.19 起 stock_margin_em 已移除，改用 stock_margin_sse 沪市汇总）
      - margin_sse:                     上交所融资融券明细
      - margin_szse:                    深交所融资融券明细
      - inner_trade:                    内部交易（股东增减持）
    """
    ak = _ak()
    if endpoint == "gdp":
        return ak.macro_china_gdp()
    if endpoint == "cpi":
        return ak.macro_china_cpi()
    if endpoint == "pmi":
        return ak.macro_china_pmi()
    if endpoint == "money_supply":
        return ak.macro_china_money_supply()
    if endpoint == "fx_spot":
        return ak.fx_spot_quote()
    if endpoint == "bond_yield":
        return ak.bond_china_yield(start_date="", end_date="")
    if endpoint == "margin_em":
        # akshare 1.19.1 移除了 stock_margin_em（东财融资融券汇总），
        # 改用 stock_margin_sse（上交所融资融券汇总）作为汇总级数据源，
        # 保持「汇总 > 沪明细 > 深明细」的 fallback 链语义不变。
        return ak.stock_margin_sse()
    if endpoint == "margin_sse":
        kw: dict = {}
        if date:
            kw["date"] = date
        return ak.stock_margin_detail_sse(**kw)
    if endpoint == "margin_szse":
        kw = {}
        if date:
            kw["date"] = date
        return ak.stock_margin_detail_szse(**kw)
    if endpoint == "inner_trade":
        return ak.stock_inner_trade_xq()
    raise ValueError(f"Unknown macro_data endpoint: {endpoint}")


# ============================================================
# fund_flow — 个股资金流向（akshare 备源）
# ============================================================

def fetch_fund_flow(code: str = "", curr_date: str = "", include_history: bool = True, symbol: str = "", **kwargs) -> dict:
    """个股资金流向（直连东财 push2his API，curl_cffi 绕过系统代理）。

    返回与 em_push2 源相同的 dict 结构（realtime/history/signal）。
    使用 curl_cffi 替代 requests，避免系统代理导致的 RemoteDisconnected。

    参数归一化（v3.1.3 约定）：同时接受 symbol 和 code，全空语义化报错；
    归一与 secid 构造复用 sina_fetchers 同款 helper（同数据类型双源口径一致）。
    2026-11-14 修复：本函数是当年归一化的漏网者，route(symbol=...) 时
    code 留空 → secid="0." → 东财对空 secid 返回 {"data": null} →
    NoneType 模糊异常（此前靠 sina 备源兜底）。
    """
    from .sina_fetchers import (
        _em_secid,
        _require_symbol_code as _normalize_sym_code,  # QI-ARCH-13 显名随迁
    )
    from curl_cffi import requests as _rq

    sym = _normalize_sym_code(symbol, code)

    if not curr_date:
        curr_date = datetime.now().strftime("%Y-%m-%d")
    result: dict = {
        "symbol": sym,
        "source": "AKShare stock_individual_fund_flow",
        "date": curr_date,
        "realtime": [],
        "history": [],
        "signal": "neutral",
    }

    _session = _rq.Session()
    _session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://data.eastmoney.com/",
    })

    secid = _em_secid(sym)
    url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
    params = {
        "secid": secid,
        "lmt": 20,
        "klt": 101,
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
        "ut": "b2884a393a59ad64002292a3e90d46a5",
    }

    try:
        resp = _session.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        # "data" 键存在但值为 null（空 secid/风控/停牌）时 .get 默认值不生效，
        # 必须 or {} 防御，否则 None.get("klines") 泄漏 NoneType 模糊异常
        klines = (data.get("data") or {}).get("klines", [])
        if not klines:
            raise RuntimeError("资金流数据为空")
        for line in klines:
            parts = line.split(",")
            if len(parts) >= 6:
                result["history"].append({
                    "date": parts[0],
                    "main_net": float(parts[1]),
                    "small": float(parts[2]),
                    "mid": float(parts[3]),
                    "large": float(parts[4]),
                    "super_large": float(parts[5]),
                })
        if result["history"]:
            last = result["history"][-1]
            if last["main_net"] > 0:
                result["signal"] = "bullish_inflow"
            elif last["main_net"] < 0:
                result["signal"] = "bearish_outflow"
        return result
    except Exception as e:
        raise RuntimeError(f"AKShare 资金流数据获取失败: {e}")


# ============================================================
# dragon_tiger — 龙虎榜（akshare 备源）
# ============================================================

def fetch_dragon_tiger(code: str = "", trade_date: str = "", look_back_days: int = 30, **kwargs):
    """龙虎榜（akshare stock_lhb_detail_em）。

    code 非空: 返回与 em_datacenter 源相同的 dict 结构（单股上榜记录）。
    code 为空: 返回原始 DataFrame（全市场龙虎榜明细）。
    """
    ak = _ak()
    if not trade_date:
        trade_date = datetime.now().strftime("%Y-%m-%d")
    end_dt = datetime.strptime(trade_date, "%Y-%m-%d")
    start_dt = end_dt - timedelta(days=look_back_days)
    df = ak.stock_lhb_detail_em(
        start_date=start_dt.strftime("%Y%m%d"),
        end_date=end_dt.strftime("%Y%m%d"),
    )
    if df is None or df.empty:
        raise RuntimeError("AKShare 龙虎榜数据为空")
    if not code:
        # 全市场龙虎榜明细：返回原始 DataFrame
        return df
    code_col = "代码" if "代码" in df.columns else df.columns[1]
    filtered = df[df[code_col].astype(str).str.zfill(6) == code]
    if filtered.empty:
        raise RuntimeError(f"AKShare 龙虎榜无 {code} 上榜记录")
    result: dict = {
        "symbol": code,
        "source": "AKShare stock_lhb_detail_em",
        "trade_date": trade_date,
        "look_back_days": look_back_days,
        "appearances": [],
        "latest_seats": {"buy": [], "sell": []},
        "institutional": None,
    }
    for _, row in filtered.iterrows():
        result["appearances"].append({
            "date": str(row.get("上榜日", "")),
            "reason": str(row.get("解读", "")),
            "net_buy_wan": round(float(row.get("龙虎榜净买额", 0) or 0) / 10000, 1),
            "turnover_pct": round(float(row.get("换手率", 0) or 0), 2),
        })
    return result


# ============================================================
# industry_comparison — 行业对比（akshare 备源）
# ============================================================

def fetch_industry_comparison(code: str = "", trade_date: str = "", top_n: int = 20, **kwargs) -> dict:
    """行业对比（akshare stock_sector_fund_flow_rank）。返回与 em_push2 源相同的 dict 结构。"""
    ak = _ak()
    if not trade_date:
        trade_date = datetime.now().strftime("%Y-%m-%d")
    result: dict = {
        "source": "AKShare stock_sector_fund_flow_rank",
        "date": trade_date,
        "code": code or None,
        "industries": [],
    }
    df = ak.stock_sector_fund_flow_rank(indicator="今日", sector_type="行业资金流")
    if df is None or df.empty:
        raise RuntimeError("AKShare 行业资金流数据为空")

    # 2026-11-06 实测：akshare 1.20.21 把列名改成了
    #   「板块/涨跌幅/领涨股票」→「名称/今日涨跌幅/今日主力净流入最大股」。
    # 旧映射取不到值会把所有行业读成 "" / 0.0（假 0），故按别名兜底，
    # 别名全不匹配时直接抛错，交给 SmartRouter 降级到 ths_flow / sina_industry。
    def _pick(*names: str) -> str | None:
        for name in names:
            if name in df.columns:
                return name
        return None

    name_col = _pick("板块", "名称")
    change_col = _pick("涨跌幅", "今日涨跌幅")
    leader_col = _pick("领涨股票", "今日主力净流入最大股")
    if not name_col or not change_col:
        raise RuntimeError(
            f"AKShare 行业资金流列名漂移（缺少板块/涨跌幅列）：{list(df.columns)}"
        )

    for i, (_, row) in enumerate(df.iterrows()):
        if i >= top_n:
            break
        result["industries"].append({
            "rank": i + 1,
            "name": str(row.get(name_col, "")),
            "change_pct": float(row.get(change_col, 0) or 0),
            "up_count": 0,
            "down_count": 0,
            "leader": str(row.get(leader_col, "")) if leader_col else "",
        })
    return result


# ============================================================
# northbound — 北向资金（akshare 备源）
# ============================================================

def fetch_northbound(curr_date: str = "", include_history: bool = False, **kwargs):
    """北向资金（akshare stock_hsgt_hist_em）。返回 DataFrame。"""
    ak = _ak()
    df = ak.stock_hsgt_hist_em(symbol="北向资金")
    if df is None or df.empty:
        raise RuntimeError("AKShare 北向资金数据为空")
    return df


# ============================================================
# hot_stocks — 涨跌停股票池
# ============================================================

def fetch_hot_stocks(direction: str = "涨停", date: str = "", **kwargs):
    """涨跌停股票池（akshare）。

    direction: "涨停" → stock_zt_pool_em; "跌停" → stock_zt_pool_dtgc_em
    返回 DataFrame。
    """
    ak = _ak()
    if not date:
        date = datetime.now().strftime("%Y%m%d")
    if direction == "涨停":
        return ak.stock_zt_pool_em(date=date)
    return ak.stock_zt_pool_dtgc_em(date=date)


# ============================================================
# profit_forecast — 一致预期（同花顺 HTTP 抓取）
# ============================================================

def fetch_profit_forecast(symbol: str = "", **kwargs) -> dict:
    """分析师一致预期 EPS（同花顺 basic.10jqka 抓取 + 腾讯实时价格）。

    返回包含 forecasts/price/forward_pe/peg 等字段的 dict。
    抓取逻辑从 signal_data_base.get_profit_forecast 迁移而来。
    """
    import math
    import re
    import requests as _rq

    code = symbol
    url = f"https://basic.10jqka.com.cn/new/{code}/worth.html"
    _headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36"
        ),
        "Referer": "https://basic.10jqka.com.cn/",
    }
    # 铁律：国内接口直连。requests 默认 trust_env=True 会读 HTTP(S)_PROXY。
    _s = _rq.Session()
    _s.trust_env = False
    resp = _s.get(url, headers=_headers, timeout=15)
    resp.encoding = "gbk"
    html = resp.text

    thead_pat = re.compile(
        r"<thead[^>]*>\s*<tr>\s*<th>\s*年度\s*</th>\s*"
        r"<th>\s*预测机构数\s*</th>.*?</thead>",
        re.DOTALL,
    )
    thead_m = thead_pat.search(html)
    if not thead_m:
        raise RuntimeError(f"{symbol} 无分析师一致预期数据（找不到EPS预测表头）")

    tbody_pat = re.compile(r"<tbody[^>]*>(.*?)</tbody>", re.DOTALL)
    tbody_m = tbody_pat.search(html, thead_m.end())
    if not tbody_m:
        raise RuntimeError(f"{symbol} 无分析师一致预期数据（找不到EPS预测表体）")

    tbody_html = tbody_m.group(1)
    row_pat = re.compile(
        r"<tr[^>]*>\s*<th[^>]*>\s*(\d{4})\s*</th>\s*"
        r"<td[^>]*>\s*(\d+)\s*</td>\s*"
        r"<td[^>]*>\s*([\d.]+)\s*</td>\s*"
        r"<td[^>]*>\s*([\d.]+)\s*</td>\s*"
        r"<td[^>]*>\s*([\d.]+)\s*</td>\s*"
        r"<td[^>]*>\s*([\d.]+)\s*</td>"
        r".*?</tr>",
        re.DOTALL,
    )

    eps_by_year: dict[str, float] = {}
    forecast_rows: list[dict] = []
    for rm in row_pat.finditer(tbody_html):
        fy = rm.group(1)
        analysts = int(rm.group(2))
        eps_min = rm.group(3)
        eps_mean = float(rm.group(4))
        eps_max = rm.group(5)
        industry_avg = rm.group(6)
        entry = {
            "year": fy,
            "analysts": analysts,
            "eps_min": eps_min,
            "eps_mean": eps_mean,
            "eps_max": eps_max,
            "industry_average": industry_avg,
            "low_coverage_warning": analysts < 3,
        }
        forecast_rows.append(entry)
        if analysts > 0:
            eps_by_year[fy] = eps_mean

    if not forecast_rows:
        raise RuntimeError(f"{symbol} 无分析师一致预期数据")

    tip_pat = re.compile(r'<p[^>]*class="tip[^"]*"[^>]*>(.*?)</p>', re.DOTALL)
    tip_m = tip_pat.search(html, max(0, thead_m.start() - 2000), thead_m.start())
    summary_text = ""
    if tip_m:
        summary_text = re.sub(r"<[^>]+>", "", tip_m.group(1)).strip()

    result: dict = {
        "symbol": symbol,
        "source": "同花顺 analyst consensus",
        "summary": summary_text,
        "forecasts": forecast_rows,
    }

    try:
        import urllib.request as _ur
        # 铁律：国内接口直连。默认 opener 会读 HTTP(S)_PROXY 环境变量，必须绕过。
        _opener = _ur.build_opener(_ur.ProxyHandler({}))
        # QI-BUG-01 修复：原代码引用未定义名 prefix → NameError 被尾部 except
        # 吞成 valuation_note → 六字段静默失效 + 备源永不接管。
        # 语义：A 股代码补交易所前缀拼腾讯行情 URL（同 http_fetchers._tencent_quote_vals）。
        quote_url = f"https://qt.gtimg.cn/q={_prefixed_code(code)}"
        req = _ur.Request(quote_url)
        req.add_header("User-Agent", "Mozilla/5.0")
        quote_resp = _opener.open(req, timeout=5)
        raw = quote_resp.read().decode("gbk")
        vals = raw.split('"')[1].split("~") if '"' in raw else []
        if len(vals) >= 53:
            price = float(vals[3]) if vals[3] else 0
            pe_ttm = float(vals[39]) if vals[39] else 0
            result["price"] = price
            result["pe_ttm"] = pe_ttm
            years_sorted = sorted(eps_by_year.keys())
            if years_sorted and eps_by_year.get(years_sorted[0], 0) > 0:
                eps_cur = eps_by_year[years_sorted[0]]
                fwd_pe = round(price / eps_cur, 1)
                result["forward_pe"] = fwd_pe
                result["forward_pe_year"] = years_sorted[0]
                if len(years_sorted) >= 2 and eps_by_year.get(years_sorted[1], 0) > 0:
                    eps_next = eps_by_year[years_sorted[1]]
                    cagr = eps_next / eps_cur - 1
                    if cagr > 0:
                        peg = round(fwd_pe / (cagr * 100), 2)
                        result["peg"] = peg
                        result["eps_cagr"] = round(cagr * 100, 1)
                        if fwd_pe > 30:
                            digest = round(
                                math.log(fwd_pe / 30) / math.log(1 + cagr), 1
                            )
                            result["pe_digestion_years"] = digest
                    else:
                        result["peg"] = None
                        result["eps_cagr"] = round(cagr * 100, 1)
                        result["peg_note"] = "EPS declining, PEG not applicable"
    except Exception as e:
        result["valuation_note"] = f"Forward valuation unavailable: {e}"

    return result


# ============================================================
# baidu_economic_calendar — 百度经济数据日历
# ============================================================

def fetch_baidu_economic_calendar(date: str = "", **kwargs) -> pd.DataFrame:
    """百度股市通经济数据日历。

    调用 ak.news_economic_baidu(date=date) 获取每日经济数据发布日程。

    Args:
        date: 查询日期，格式 "YYYYMMDD"。默认为当日

    Returns:
        DataFrame with columns: 日期, 时间, 事件, 重要性, 前值, 预期, 公布值, 地区, 国家, 统计周期
    """
    ak = _ak()
    if not date:
        date = datetime.now().strftime("%Y%m%d")
    try:
        df = ak.news_economic_baidu(date=date)
        if df is None or df.empty:
            # QI-STD-26（工单 17）：akshare 空表主因是上游风控/断源，不再折叠空表
            # （与下方 except 的 v3.3.15 不吞异常纪律同向）。
            raise RuntimeError(
                f"百度财报日历返回空表（akshare 上游可能风控/断源）: {date or 'default'}"
            )
        return df
    except Exception as e:
        logger.warning("fetch_baidu_economic_calendar(%s) failed: %s", date, e)
        # v3.3.15：不吞异常。吞掉会让 SmartRouter 把失败当成功（不降级、不计健康度），
        # 调用方也分不清「当天确实无数据」与「上游挂了」。
        raise


# ============================================================
# baidu_trade_notify — 百度交易提醒（多 endpoint）
# ============================================================

def fetch_baidu_trade_notify(endpoint: str = "suspend", date: str = "", **kwargs) -> pd.DataFrame:
    """百度股市通交易提醒（多 endpoint 分派）。

    endpoint:
      - suspend:     停复牌提醒（ak.news_trade_notify_suspend_baidu）
      - dividend:    分红派息提醒（ak.news_trade_notify_dividend_baidu）
      - report_time: 财报发行时间（ak.news_report_time_baidu）

    Args:
        endpoint: 提醒类型
        date: 查询日期，格式 "YYYYMMDD"

    Returns:
        DataFrame
    """
    ak = _ak()
    if not date:
        date = datetime.now().strftime("%Y%m%d")
    try:
        if endpoint == "suspend":
            df = ak.news_trade_notify_suspend_baidu(date=date)
        elif endpoint == "dividend":
            df = ak.news_trade_notify_dividend_baidu(date=date)
        elif endpoint == "report_time":
            df = ak.news_report_time_baidu(date=date)
        else:
            raise ValueError(f"Unknown baidu_trade_notify endpoint: {endpoint}")
        if df is None or df.empty:
            # QI-STD-26（工单 17）：空表不再折叠（交易提示 feed 型，主因=上游断源）。
            raise RuntimeError(
                f"百度交易提示返回空表（akshare 上游可能风控/断源）: {endpoint}/{date or 'default'}"
            )
        return df
    except Exception as e:
        logger.warning("fetch_baidu_trade_notify(%s, %s) failed: %s", endpoint, date, e)
        # v3.3.15：不吞异常，交由 SmartRouter 降级并计健康度
        raise


# ============================================================
# index_news_sentiment — 指数新闻情绪（主源已退役，见下）
# ============================================================
# 【已退役】原 `fetch_index_news_sentiment`（走 ak.index_news_sentiment_scope →
# www.chinascope.com/inews/senti/index）**上游永久失效，函数已删除**。
#
# 实测铁证（非猜测，可复现）：
#   curl -kL "https://www.chinascope.com/inews/senti/index?period=YEAR"
#     → 301 跳转到 https://www.chinascope.com.cn/ （公司官网首页）
#     → HTTP 200 + content_type: text/html（22,833 字节的官网 HTML）
#   ⇒ 该 JSON API 端点已被数库科技撤下/搬迁；akshare 内部 r.json() 必然
#     JSONDecodeError。与 SSL 无关（-k 绕过证书照样拿到 HTML）。
#
# 为什么删而不是留着当"备胎"：它的上游是死的，留着只会有害 ——
#   ① 每次调用先白失败一次（浪费一次 HTTP 往返 + 超时窗口）；
#   ② 把该源健康分压低，污染健康度看板；
#   ③ 为了它必须保留「在锁里篡改进程级 requests.sessions.Session.request」
#      这种全局副作用 hack（见本文件顶部已删的 _ssl_patch_lock 说明），
#      用一个全局副作用去维持一个永远失败的源，收益为负。
#
# 现装配：主源 legu_activity（乐咕乐股赚钱效应，实测 12 项），
#         备源 ths_distribution（同花顺涨跌分布，实测 11 行，跨上游）。
# 详见 registry.py 的 index_news_sentiment 注册块。


# ============================================================
# futures_news — 期货新闻（上海有色网）
# ============================================================

def fetch_futures_news(symbol: str = "全部", **kwargs) -> pd.DataFrame:
    """期货新闻（上海有色网）。

    调用 ak.futures_news_shmet(symbol=symbol) 获取期货/大宗商品相关新闻。

    Args:
        symbol: 品种，默认 "全部"

    Returns:
        DataFrame with columns: 标题, 发布时间, 内容
    """
    ak = _ak()
    try:
        df = ak.futures_news_shmet(symbol=symbol)
        if df is None or df.empty:
            # QI-STD-26（工单 17）：上海有色新闻 feed 空表 = 断源，不再折叠。
            raise RuntimeError(
                f"期货新闻(上海有色)返回空表（akshare 上游可能风控/断源）: {symbol}"
            )
        return df
    except Exception as e:
        logger.warning("fetch_futures_news(%s) failed: %s", symbol, e)
        # v3.3.15：不吞异常，交由 SmartRouter 降级并计健康度
        raise


# ============================================================
# hot_search_baidu — 百度热搜股票
# ============================================================

def fetch_hot_search_baidu(symbol: str = "A股", date: str = "", time: str = "今日", **kwargs) -> pd.DataFrame:
    """百度股市通热搜股票。

    调用 ak.stock_hot_search_baidu(symbol=symbol, date=date, time=time) 获取热搜排行。

    Args:
        symbol: {"全部", "A股", "港股", "美股"}
        date: 日期，格式 "YYYYMMDD"
        time: {"今日", "1小时"}

    Returns:
        DataFrame with columns: 股票代码, 股票名称, 热搜排名, 热度值等
    """
    ak = _ak()
    if not date:
        date = datetime.now().strftime("%Y%m%d")
    try:
        df = ak.stock_hot_search_baidu(symbol=symbol, date=date, time=time)
        if df is None or df.empty:
            # QI-STD-26（工单 17）：热搜 feed 空表 = 断源（同下方 except 注：
            # 吞掉会伪装成"无热搜"），不再折叠，让位备源 ths_hot 并计健康度。
            raise RuntimeError(
                f"百度热搜返回空表（akshare 上游可能风控/断源）: {symbol or 'all'}"
            )
        return df
    except Exception as e:
        logger.warning("fetch_hot_search_baidu(%s) failed: %s", symbol, e)
        # v3.3.15：不吞异常（百度该接口常间歇性返回 KeyError 'list'，吞掉会伪装成"无热搜"）
        raise


# ============================================================
# hot_rank_data — 东方财富人气榜（多 endpoint）
# ============================================================

def fetch_hot_rank_data(endpoint: str = "rank", symbol: str = "", **kwargs) -> pd.DataFrame:
    """东方财富个股人气榜（多 endpoint 分派）。

    endpoint:
      - rank:     全市场人气榜（ak.stock_hot_rank_em）
      - up:       飙升榜（ak.stock_hot_up_em）
      - detail:   个股历史趋势及粉丝特征（ak.stock_hot_rank_detail_em）
      - realtime: 个股实时变动（ak.stock_hot_rank_detail_realtime_em）
      - keyword:  个股热门关键词（ak.stock_hot_keyword_em）
      - latest:   个股最新排名（ak.stock_hot_rank_latest_em）
      - relate:   相关股票（ak.stock_hot_rank_relate_em）

    Args:
        endpoint: 榜单类型
        symbol: 带市场表示的证券代码，如 "SZ000665"

    Returns:
        DataFrame
    """
    ak = _ak()
    try:
        if endpoint == "rank":
            df = ak.stock_hot_rank_em()
        elif endpoint == "up":
            df = ak.stock_hot_up_em()
        elif endpoint == "detail":
            df = ak.stock_hot_rank_detail_em(symbol=symbol)
        elif endpoint == "realtime":
            df = ak.stock_hot_rank_detail_realtime_em(symbol=symbol)
        elif endpoint == "keyword":
            df = ak.stock_hot_keyword_em(symbol=symbol)
        elif endpoint == "latest":
            df = ak.stock_hot_rank_latest_em(symbol=symbol)
        elif endpoint == "relate":
            df = ak.stock_hot_rank_relate_em(symbol=symbol)
        else:
            raise ValueError(f"Unknown hot_rank_data endpoint: {endpoint}")
        if df is None or df.empty:
            # QI-STD-26（工单 17）：人气榜走 push2 族空表多因 RST（同 except 注：
            # 伪装成"人气榜为空"既不让位备源也让健康度虚高），不再折叠。
            raise RuntimeError(
                f"东财人气榜返回空表（akshare 上游可能风控/断源）: {endpoint}"
            )
        return df
    except Exception as e:
        logger.warning("fetch_hot_rank_data(%s) failed: %s", endpoint, e)
        # v3.3.15：不吞异常。东财人气榜走 push2 族，本机会间歇性被 RST，
        # 旧实现把它伪装成"人气榜为空"，既不让位给备源也让健康度虚高。
        raise


# ============================================================
# xueqiu_hot — 雪球热度（多 endpoint）
# ============================================================

def fetch_xueqiu_hot(endpoint: str = "follow", symbol: str = "最热门", **kwargs) -> pd.DataFrame:
    """雪球沪深股市热度排行榜（多 endpoint 分派）。

    endpoint:
      - follow: 关注排行榜（ak.stock_hot_follow_xq）
      - tweet:  讨论排行榜（ak.stock_hot_tweet_xq）
      - deal:   交易排行榜（ak.stock_hot_deal_xq）

    Args:
        endpoint: 排行榜类型
        symbol: {"最热门", "沪深股市", "创业板", "科创板"}

    Returns:
        DataFrame
    """
    ak = _ak()
    try:
        if endpoint == "follow":
            df = ak.stock_hot_follow_xq(symbol=symbol)
        elif endpoint == "tweet":
            df = ak.stock_hot_tweet_xq(symbol=symbol)
        elif endpoint == "deal":
            df = ak.stock_hot_deal_xq(symbol=symbol)
        else:
            raise ValueError(f"Unknown xueqiu_hot endpoint: {endpoint}")
        if df is None or df.empty:
            # QI-STD-26（工单 17）：雪球热度 feed 空表 = 断源，不再折叠。
            raise RuntimeError(
                f"雪球热度返回空表（akshare 上游可能风控/断源）: {endpoint}"
            )
        return df
    except Exception as e:
        logger.warning("fetch_xueqiu_hot(%s) failed: %s", endpoint, e)
        # v3.3.15：不吞异常，交由 SmartRouter 降级并计健康度
        raise


# ============================================================
# fund_hold_data — 机构持仓（多 endpoint）
# ============================================================

def fetch_fund_hold_data(endpoint: str = "hold", symbol: str = "基金持仓", date: str = "", **kwargs) -> pd.DataFrame:
    """机构持仓数据（仅服务 endpoint="detail"，hold 已移交直取实现）。

    ⚠️ endpoint="hold" **已故意停用**（v3.3.15 之后发现的问题）：
    本函数原先调用 `ak.stock_report_fund_hold`，但该 akshare 接口用
      `big_df.columns = ["序号","_","股票简称","_","_","持有基金家数",...]`
    **按位置**硬编码中文列名，而上游东财 `/dataapi/zlsj/list` 的字段顺序
    已经改版 → **整行列错位**。实测（直接调 akshare，绕开本项目全部代码）：
      股票代码 列拿到 HOLDCHA_VALUE = -415345718.82（一个市值，不是代码）
      股票简称 列拿到 SECURITY_CODE  = 000680（代码跑到了简称列）
      持股变动数值 列拿到 HOLDCHA     = '减仓'（文本跑进了数值列）
    且 1.18.91 与 1.18.94 **同样错位** → 属上游字段漂移 + akshare 位置映射，
    **不是本项目升级引入**。此前每年 4–9 月因默认日期非法而返回空表，所以看不出来。

    关键：真正需要的 `SECURITY_NAME_ABBR`（股票简称）落在 akshare 标为 "_" 的
    位置，最终 `big_df[[...]]` 选择时被**丢弃** → 无法在其输出上补救列名，
    只能绕开 akshare 直取上游。故 hold 改由 `fetch_fund_hold_direct` 承担。
    此处 hold 直接 raise，而**不作为备源兜底** —— 否则 direct 失败时它会
    静默返回错标数据，比直接失败更糟。

    Args:
        endpoint: 仅支持 "detail"（单只基金持仓明细，走 ak.stock_report_fund_hold_detail）
        symbol: detail 时为基金代码
        date: 财报日期 "YYYYMMDD"

    Returns:
        DataFrame
    """
    ak = _ak()
    if endpoint == "hold":
        raise RuntimeError(
            "akshare 的 stock_report_fund_hold 列已错位（上游字段顺序改版 + akshare "
            "按位置硬编码列名），hold 已改由 fetch_fund_hold_direct 直取东财；"
            "此处不再作为兜底，以免返回错标数据"
        )
    if not date:
        date = _prev_quarter_end()
    try:
        if endpoint == "detail":
            df = ak.stock_report_fund_hold_detail(symbol=symbol, date=date)
        else:
            raise ValueError(f"Unknown fund_hold_data endpoint: {endpoint}")
        if df is None or df.empty:
            # QI-STD-26（工单 17）：本源（detail 分支）空表多因上游断源；无持仓股票
            # 的合法空由 em_zlsj 直取源兜底给出（抛出后降级可达），不再折叠。
            raise RuntimeError(
                f"基金持仓返回空表（akshare 上游可能风控/断源）: {endpoint}/{symbol or 'all'}"
            )
        return df
    except Exception as e:
        logger.warning("fetch_fund_hold_data(%s, %s) failed: %s", endpoint, symbol, e)
        # v3.3.15：不吞异常，交由 SmartRouter 降级并计健康度
        raise


# ============================================================
# 机构持仓汇总 —— 直取东财（修复 akshare 列错位）
# ============================================================
# 上游：东方财富 datacenter /dataapi/zlsj/list
# 与 akshare 的唯一区别：**按上游字段名映射中文列名**，而不是按位置。
# 上游字段顺序再变也不会错位。

# 机构类型 -> 东财 type 参数

# (上游字段名, 输出中文列名) —— 顺序即输出列顺序
#
# ⚠️ 列名**刻意沿用 akshare 原有的 9 个列名**（不新增/不改名），只把「哪个字段
# 填进哪个列」改对。原因：下游（如周末复盘报告模板）按列名取值，改名会静默
# 打断它们。最后额外追加一列 持股占流通股比（纯新增，不改动既有列，风险低）。





# ============================================================
# v3.3.14 新增：单源类型的独立备源（避免东财一挂全挂）
# ============================================================
# 背景：company_info / financial_stmt / industry_data 此前均为 akshare 单源，
# 且都走东方财富。东财不可用（限流 / 反爬 / 代理误路由）时这些数据类型
# **完全没有兜底**，违反「一主一备」原则。
# 以下备源刻意选用**非东财**厂商：巨潮资讯 / 新浪财经 / 同花顺。














# ============================================================
# v3.3.15 新增备源 —— 补「单源无兜底」的 8 个数据类型
# ============================================================
# 背景：hot_rank / hot_search / xueqiu_hot / fund_hold / futures_news /
#      baidu_economic_calendar / baidu_trade_notify / index_news_sentiment
#      原为单源注册，源失效即整类型失效；且部分源此前还把异常静默吞成空表，
#      失败完全不可见。本节补齐「非同一上游」的备源，避免与主源同生共死。
#
# 选源原则（与 P2-2 的教训一致）：
#   备源不得与主源打同一个上游域名族 —— 否则主源被限流时备源一起死。
#   东财 push2 族在本机会间歇性被 RST，故首选同花顺 / 百度 / 巨潮等独立上游。












# ============================================================
# 东财 datacenter-web 数据源 —— akshare 包装层（2026-09-25 老板拍板）
# ============================================================
# 老板原话："AKshare 更新过后，可能东财源有改善。我们就用 akshare 中集成的
# 东财源，不自己独立开发东财源的接口了。"
#
# 策略：
#   - em_datacenter（em_client.py 手写直连）保持 priority=1 主源
#   - 本节 akshare 包装函数注册为 priority=100 备源
#   - 两者**字段对齐**（akshare 包装层把中文列名映射成主源的英文 snake_case），
#     SmartRouter 降级时上层 MCP 工具无需感知差异
#   - 签名对齐主源（start_date/end_date 等 kwargs），SmartRouter 透传无障碍
#
# 为什么不直接用主源？老板拍板战略转向："未来不再自己开发东财接口"，
# akshare 已封装好同一上游（datacenter-web），由 akshare 维护列名映射，
# 上游 schema 漂移时改 akshare 即可，本项目不用每次踩字段名变更的坑。
#
# 已实测字段对照（2026-09-25）：数据量与主源完全一致
#   - stock_lhb_detail_em     299行 × 21列 ↔ dt_detail
#   - stock_lhb_jgmmtj_em     734行 × 16列 ↔ dt_institution
#   - stock_lhb_jgstatistic_em 416行 × 16列 ↔ dt_stock_stats
#   - stock_lhb_yybph_em      901行 × 17列 ↔ dt_branch_rank（补回主源删除的维度）
#   - stock_margin_account_info 3397行×13列 ↔ margin_account_info
#   - stock_dzjy_sctj         4648行 × 9列 ↔ block_trade_market_stat
#   - stock_dzjy_mrmx         15行 × 9列   ↔ block_trade_detail
#   - stock_dzjy_mrtj         117行 × 12列 ↔ block_trade_daily_stat
# ============================================================




















# ============================================================
# 涨停板池 —— akshare stock_zt_pool_em（2026-09-26 新增，修复 limit_up_board 整类型失效）
# 原 em_push2_clist 主源在 push2 IP 风控中已删除（registry.py:235），整类型失效。
# akshare 包装东财涨停板池接口，由 akshare 维护字段映射，独立于 push2 域名族。
# 实测返回字段包含「连板数」（原 SPEC 假设无该字段，实测纠正）。
# ============================================================


# ============================================================
# 涨停四池 + 打板情绪（2026-10-30 专项重构）
#
# 修复背景（KNOWN-ISSUES #5）：schema 不许传 date、底层又强校验 date 必填，
# 调用方无解；且路由层只挂了一个只返回涨停池 list 的 fetcher，
# 而工具期望 {"data": [...]} 信封 —— 整条链路上层也拿不到数据。
# 现在改为：date 缺省自动回退到最近有数据的交易日，四池统一映射，
# 情绪指标由四池现算（公式见 fetch_board_sentiment 文档）。
# ============================================================

# 四池原始列名不完全一致，按语义归一到统一字段

_POOL_AK_FUNCS: dict[str, str] = {
    "zt": "stock_zt_pool_em",
    "zb": "stock_zt_pool_zbgc_em",
    "dt": "stock_zt_pool_dtgc_em",
    "prev_zt": "stock_zt_pool_previous_em",
}























# ============================================================
# trading_calendar 备源 —— sina 交易日清单（2026-10-30 专项重构 #1）
#
# 背景：深交所官方接口 2026-10 起返 404，而全仓只有它一个源、没有兜底，
# 交易日判定整条能力直接失效，只能靠提示词层的降级链硬撑。
# 备源走 akshare 的 sina 交易日清单（1990→当年年末），与深交所完全独立。
# ============================================================

def fetch_trading_calendar(year: int = 0, month: int = 0, **kwargs) -> pd.DataFrame:
    """交易日历（sina 交易日清单备源，整月口径与深交所主源对齐）。

    Args:
        year: 年份，默认当前年
        month: 月份，默认当前月

    Returns:
        DataFrame with columns: 日期(YYYY-MM-DD)、是否交易日(是/否)、节假日

    Raises:
        RuntimeError: sina 清单尚未覆盖该月份（不猜、不伪造交易日）
    """
    if not year:
        year = datetime.now().year
    if not month:
        month = datetime.now().month

    ak = _ak()
    df = ak.tool_trade_date_hist_sina()
    if df is None or df.empty:
        raise RuntimeError("sina 交易日清单返回空")
    if "trade_date" not in df.columns:
        raise RuntimeError(
            f"sina 交易日清单结构变化，缺少 trade_date 列：{list(df.columns)}"
        )

    trade_days = pd.to_datetime(df["trade_date"], errors="coerce").dropna()
    if trade_days.empty:
        raise RuntimeError("sina 交易日清单无有效日期")

    max_day = trade_days.max().date()
    last_day_of_month = calendar.monthrange(year, month)[1]
    # 覆盖性按「月份」判定，不按最后一天：清单只含交易日，
    # 若月末恰是周末/节假日，用「月末 > 最后交易日」会误判成未覆盖。
    if (year, month) > (max_day.year, max_day.month):
        raise RuntimeError(
            f"sina 交易日清单仅覆盖到 {max_day}，无法判定 {year}-{month:02d}；"
            "请改用其他来源或等待清单更新"
        )

    trade_set = set(trade_days.dt.date)
    rows = []
    for day_num in range(1, last_day_of_month + 1):
        cur = datetime(year, month, day_num).date()
        is_trade = cur in trade_set
        if is_trade:
            memo = ""
        elif cur.weekday() >= 5:
            memo = "周末"
        else:
            memo = "休市"
        rows.append({
            "日期": cur.strftime("%Y-%m-%d"),
            "是否交易日": "是" if is_trade else "否",
            "节假日": memo,
        })

    if not any(r["是否交易日"] == "是" for r in rows):
        raise RuntimeError(f"{year}-{month:02d} 无任何交易日，sina 清单可能滞后")
    return pd.DataFrame(rows)


# ============================================================
# 大市值名单备源 — bigcaps（工单 H4）
#
# 主源走新浪 bigcaps；东财全市场快照只在主源失败时兜底。
# 口径：总市值 ≥ 门槛（亿元），缺市值不丢票、写 reason。
# ============================================================







# ============================================================
# 国债收益率备源 — bond_yield_curve 第二源（2026-11-08）
# ============================================================
# 中债 yield_main 接口改版（JSON→JS 填充页面），主源 chinabond_official 解析
# 出空壳已按纪律抛出；本 fetcher 走东财 datacenter（akshare bond_zh_us_rate）
# 兜底国债曲线。仅支持 curve=国债（信用债曲线无对应上游，抛出走记账）。




# QI-STD-95：fetch_global_index_spot 频控契约代码化（原仅 docstring「调用方必须
# 做 ≥60s 级缓存」）——push2 clist 对高频有 IP 风控，模块级最小间隔兜底


