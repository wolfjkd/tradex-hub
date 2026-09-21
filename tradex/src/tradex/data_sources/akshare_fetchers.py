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
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

logger = logging.getLogger("tradex.akshare")

# v3.3.15 新增：季度末日期计算。
# 旧实现用 f"{year}{q*3:02d}31" 硬编码 31 日，Q2(6月)/Q3(9月) 会算出
# 20260631 / 20260931 这类**不存在的日期**，上游直接报错，而错误又被
# except 静默吞成空表 —— 结果是每年 4–9 月「机构持仓」默认调用恒返回空。
_QUARTER_END_MONTH = {1: 3, 2: 6, 3: 9, 4: 12}


def _prev_quarter_end(today: "datetime | None" = None) -> str:
    """返回「上一季度末」的真实日期，格式 YYYYMMDD。

    以真实月末为准（6→30、9→30、12→31），不再硬编码 31 日。
    今天 2026-09-14 → 所属 Q3 → 上一季度末 = 20260630。
    """
    d = (today or datetime.now()).date()
    q = (d.month - 1) // 3 + 1          # 当前季度 1-4
    py, pq = (d.year, q - 1) if q > 1 else (d.year - 1, 4)   # 上一季度
    m = _QUARTER_END_MONTH[pq]
    last_day = calendar.monthrange(py, m)[1]                  # 真实月末，不假设 31
    return f"{py}{m:02d}{last_day:02d}"

# 待发版：`_ssl_patch_lock` 已随 `fetch_index_news_sentiment` 一并删除。
# 原因：该锁只为串行化「临时篡改进程级 requests.sessions.Session.request 的
# verify 开关」而存在 —— 这是全局副作用，锁只能缩小窗口、不能消除风险。
# 而其唯一服务对象（chinascope 指数新闻情绪）上游**已永久失效**（端点 301 跳官网首页、
# 返回 text/html，akshare 内部 r.json() 必然 JSONDecodeError），源已退役，
# 这把拿全局副作用换来的锁自然失去存在理由。


def _ak():
    """延迟导入 akshare，避免模块加载时副作用。"""
    import akshare as ak
    return ak


# ============================================================
# K 线周期归一化（v3.3.14 新增）
# ============================================================
# SmartRouter 会把同一个 period 参数**原样转发**给主源(eltdx)与备源(akshare)，
# 但两源值域不同：eltdx 认 day/week/month，akshare 认 daily/weekly/monthly。
# eltdx 源内部有 _normalize_period() 归一化，akshare 源此前没有 ——
# 于是传 'day' 时主源正常、一旦降级到 akshare 就 KeyError('day')，降级链在该值下必断。
# 这里做反向归一化，使两个源的 period 语义对齐。
_AK_PERIOD_ALIASES = {
    "day": "daily", "daily": "daily", "d": "daily", "1d": "daily",
    "week": "weekly", "weekly": "weekly", "w": "weekly", "1w": "weekly",
    "month": "monthly", "monthly": "monthly", "m": "monthly", "1m": "monthly",
}


def _normalize_ak_period(period: str) -> str:
    """把 eltdx 风格周期名(day/week/month)转成 akshare 期望的(daily/weekly/monthly)。

    已是 akshare 风格的值保持不变；未识别的值原样透传，交由 akshare 自行报错。
    """
    key = str(period or "").strip().lower()
    return _AK_PERIOD_ALIASES.get(key, period)


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


def _fetch_sina_index_amount_today(sym: str):
    """新浪实时行情（hq.sinajs.cn）取指数当日成交额(元)。

    sym: sh000001 / sz399001 / sz399006 等。
    新浪指数行情字段：…, 成交量(手), 成交额(元), …（上证/深证的额在第10位）。返回整数成交额(元)或 None。
    """
    import urllib.request
    url = f"https://hq.sinajs.cn/list={sym}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120",
        "Referer": "https://finance.sina.com.cn",
    })
    resp = urllib.request.urlopen(req, timeout=8)
    raw = resp.read().decode("gbk", "ignore")
    quotes = raw.split("=", 1)[-1].strip(";").strip('"')
    if not quotes:
        return None
    parts = quotes.split(",")
    # 指数格式: 名称,今开,昨收,现价,最高,最低,买一?,卖一?,成交量(手),成交额(元),...
    # 兼容两侧字段偏移——成交额在成交量之后。
    try:
        vol_idx = 8
        amt_idx = 9
        amount = float(parts[amt_idx]) if len(parts) > amt_idx else None
        return amount
    except (ValueError, IndexError):
        return None


def _fetch_index_daily_from_push2his(sym: str, days: int) -> list:
    """直连东财 push2his 历史K线接口取指数量能序列（含成交额）。

    返回 [{"date","volume","amount"}, ...]；成交额/成交量为 None 时表示该源未提供。
    """
    from curl_cffi import requests as _rq

    # symbol 格式 sh000001 / sz399001 / sz399006 → secid
    if sym.lower().startswith("sh") or sym.lower().startswith("1."):
        secid = "1." + sym[2:].zfill(6) if "." not in sym else sym
    elif sym.lower().startswith("sz") or sym.lower().startswith("0."):
        secid = "0." + sym[2:].zfill(6) if "." not in sym else sym
    else:
        # 纯数字：上证≈1.，深证≈0.
        secid = f"1.{sym.zfill(6)}" if sym.startswith(("000001", "999999")) else f"0.{sym.zfill(6)}"

    _session = _rq.Session()
    _session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://quote.eastmoney.com/",
    })
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": secid,
        "ut": "fa5fd1943c7b386f172d6893dbfba10b",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": 101,
        "fqt": 0,
        "end": "20500101",
        "lmt": max(int(days), 10),
    }

    resp = _session.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    klines = (data.get("data") or {}).get("klines") or []
    if not klines:
        raise RuntimeError(f"push2his kline empty for {sym}")

    out = []
    for line in klines[-int(days):]:
        p = line.split(",")
        # f51..f61: 0日期 1开 2收 3高 4低 5成交量(手) 6成交额(元)
        vol = float(p[5]) if len(p) > 5 and p[5] not in (None, "", "-") else 0.0
        amt = float(p[6]) if len(p) > 6 and p[6] not in (None, "", "-") else None
        out.append({
            "date": p[0],
            "volume": vol,
            "amount": amt,
        })
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
            return pd.DataFrame()
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
      - stock_news_em:       个股新闻
      - stock_report_disclosure: 财报披露时间表
      - stock_notice_report: 公告
      - stock_news_main_cx:  财新网新闻
      - news_cctv:           CCTV 新闻
    """
    ak = _ak()
    if endpoint == "stock_news_em":
        return ak.stock_news_em(symbol=symbol)
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
      - margin_em:                      融资融券汇总
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
        return ak.stock_margin_em()
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

def fetch_fund_flow(code: str = "", curr_date: str = "", include_history: bool = True, **kwargs) -> dict:
    """个股资金流向（直连东财 push2his API，curl_cffi 绕过系统代理）。

    返回与 em_push2 源相同的 dict 结构（realtime/history/signal）。
    使用 curl_cffi 替代 requests，避免系统代理导致的 RemoteDisconnected。
    """
    from curl_cffi import requests as _rq

    if not curr_date:
        curr_date = datetime.now().strftime("%Y-%m-%d")
    result: dict = {
        "symbol": code,
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

    secid = f"1.{code}" if code.startswith("6") else f"0.{code}"
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
        klines = data.get("data", {}).get("klines", [])
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
    for i, (_, row) in enumerate(df.iterrows()):
        if i >= top_n:
            break
        result["industries"].append({
            "rank": i + 1,
            "name": str(row.get("板块", "")),
            "change_pct": float(row.get("涨跌幅", 0) or 0),
            "up_count": 0,
            "down_count": 0,
            "leader": str(row.get("领涨股票", "")),
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
    resp = _rq.get(url, headers=_headers, timeout=15)
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
        prefix = "sh" if code.startswith("6") else "sz"
        quote_url = f"https://qt.gtimg.cn/q={prefix}{code}"
        req = _ur.Request(quote_url)
        req.add_header("User-Agent", "Mozilla/5.0")
        quote_resp = _ur.urlopen(req, timeout=5)
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
            logger.debug("fetch_baidu_economic_calendar(%s): empty", date)
            return pd.DataFrame()
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
            logger.debug("fetch_baidu_trade_notify(%s, %s): empty", endpoint, date)
            return pd.DataFrame()
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
            logger.debug("fetch_futures_news(%s): empty", symbol)
            return pd.DataFrame()
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
            logger.debug("fetch_hot_search_baidu(%s): empty", symbol)
            return pd.DataFrame()
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
            logger.debug("fetch_hot_rank_data(%s): empty", endpoint)
            return pd.DataFrame()
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
            logger.debug("fetch_xueqiu_hot(%s): empty", endpoint)
            return pd.DataFrame()
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
            logger.debug("fetch_fund_hold_data(%s, %s): empty", endpoint, symbol)
            return pd.DataFrame()
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
_EM_ZLSJ_URL = "http://data.eastmoney.com/dataapi/zlsj/list"

# 机构类型 -> 东财 type 参数
_FUND_HOLD_SYMBOL_MAP = {
    "基金持仓": "1",
    "QFII持仓": "2",
    "社保持仓": "3",
    "券商持仓": "4",
    "保险持仓": "5",
    "信托持仓": "6",
}

# (上游字段名, 输出中文列名) —— 顺序即输出列顺序
#
# ⚠️ 列名**刻意沿用 akshare 原有的 9 个列名**（不新增/不改名），只把「哪个字段
# 填进哪个列」改对。原因：下游（如周末复盘报告模板）按列名取值，改名会静默
# 打断它们。最后额外追加一列 持股占流通股比（纯新增，不改动既有列，风险低）。
_FUND_HOLD_FIELDS = [
    ("SECURITY_CODE", "股票代码"),
    ("SECURITY_NAME_ABBR", "股票简称"),
    ("HOULD_NUM", "持有基金家数"),
    ("TOTAL_SHARES", "持股总数"),
    ("HOLD_VALUE", "持股市值"),
    ("HOLDCHA", "持股变化"),          # 增仓 / 减仓（方向）
    ("HOLDCHA_NUM", "持股变动数值"),   # 股数增减
    ("HOLDCHA_RATIO", "持股变动比例"), # 百分比
    ("FREESHARES_RATIO", "持股占流通股比"),  # 新增列（akshare 原 schema 无此列）
]

_FUND_HOLD_NUM_COLS = (
    "持有基金家数", "持股总数", "持股市值", "持股变动数值",
    "持股变动比例", "持股占流通股比",
)


def fetch_fund_hold_direct(
    endpoint: str = "hold", symbol: str = "基金持仓", date: str = "", **kwargs
) -> pd.DataFrame:
    """机构持仓汇总 —— 直取东财 datacenter，按字段名映射列（修复列错位）。

    仅支持 endpoint="hold"；其余 endpoint 抛 ValueError，交由 SmartRouter
    降级到 akshare 源（后者负责 detail）。

    Args:
        endpoint: 仅 "hold"
        symbol: {"基金持仓","QFII持仓","社保持仓","券商持仓","保险持仓","信托持仓"}
        date: 财报日期 "YYYYMMDD"，默认上一季度末

    Returns:
        DataFrame，列沿用 akshare 原有命名以保证下游不被打断：
        序号 / 股票代码 / 股票简称 / 持有基金家数 / 持股总数 / 持股市值 /
        持股变化 / 持股变动数值 / 持股变动比例，并追加 持股占流通股比。
        其中「持股变化」为方向文本（增仓/减仓），「持股变动数值」为股数，
        「持股变动比例」为百分比。
    """
    if endpoint != "hold":
        raise ValueError(
            f"fetch_fund_hold_direct 仅支持 endpoint='hold'，收到 {endpoint!r}"
            "（detail 请走 akshare 源）"
        )
    t = str(symbol or "基金持仓").strip()
    if t not in _FUND_HOLD_SYMBOL_MAP:
        raise ValueError(
            f"未知机构类型 {symbol!r}（支持: {list(_FUND_HOLD_SYMBOL_MAP)}）"
        )
    if not date:
        date = _prev_quarter_end()
    em_date = (
        f"{date[:4]}-{date[4:6]}-{date[6:]}"
        if (len(date) == 8 and date.isdigit())
        else date
    )

    from .em_client import em_get

    rows: list = []
    page = 1
    total_pages = 1
    while page <= total_pages:
        params = {
            "date": em_date,
            "type": _FUND_HOLD_SYMBOL_MAP[t],
            "zjc": "0",
            "sortField": "HOULD_NUM",
            "sortDirec": "1",
            "pageNum": str(page),
            "pageSize": "500",
            "p": str(page),
            "pageNo": str(page),
        }
        resp = em_get(_EM_ZLSJ_URL, params=params, timeout=25)
        payload = resp.json()
        if not payload or not payload.get("data"):
            break
        rows.extend(payload["data"])
        try:
            total_pages = int(payload.get("pages") or 1)
        except (TypeError, ValueError):
            total_pages = 1
        page += 1
        if page > 60:  # 安全阀：最多 60 页（3 万条），防上游 pages 异常导致死循环
            logger.warning("fetch_fund_hold_direct(%s): 分页超过 60 页，提前截断", t)
            break

    if not rows:
        raise RuntimeError(f"东财机构持仓({t}, {date}) 返回空数据")

    out = pd.DataFrame(
        [{cn: r.get(en) for en, cn in _FUND_HOLD_FIELDS} for r in rows]
    )
    out.insert(0, "序号", range(1, len(out) + 1))
    for c in _FUND_HOLD_NUM_COLS:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    # 护栏：列错位会立刻暴露 —— 股票代码必须是 6 位数字，否则宁可失败也不给错标数据
    codes = out["股票代码"].astype(str).str.strip()
    if not codes.str.fullmatch(r"\d{6}").all():
        bad = codes[~codes.str.fullmatch(r"\d{6}")].head(3).tolist()
        raise RuntimeError(
            f"东财机构持仓({t}) 股票代码列异常（疑似上游字段再变）：{bad}"
        )
    return out


# ============================================================
# v3.3.14 新增：单源类型的独立备源（避免东财一挂全挂）
# ============================================================
# 背景：company_info / financial_stmt / industry_data 此前均为 akshare 单源，
# 且都走东方财富。东财不可用（限流 / 反爬 / 代理误路由）时这些数据类型
# **完全没有兜底**，违反「一主一备」原则。
# 以下备源刻意选用**非东财**厂商：巨潮资讯 / 新浪财经 / 同花顺。


def _code6(code: str) -> str:
    """提取 6 位纯代码（去掉 sh/sz/bj 前缀）。"""
    c = str(code or "").strip().lower()
    return c[2:] if c.startswith(("sh", "sz", "bj")) else c


def _prefixed_code(code: str) -> str:
    """补全为 sh/sz/bj 前缀形式（新浪等接口需要）。"""
    c = str(code or "").strip().lower()
    if c.startswith(("sh", "sz", "bj")):
        return c
    if len(c) == 6 and c.isdigit():
        if c.startswith(("60", "68", "90", "11", "13")):
            return "sh" + c
        if c.startswith(("00", "30", "20")):
            return "sz" + c
        if c.startswith(("8", "43", "92")):
            return "bj" + c
    return c


def fetch_company_info_cninfo(
    endpoint: str = "individual_info",
    symbol: str = "",
    code: str = "",
    **kwargs,
) -> pd.DataFrame:
    """公司信息备源（巨潮资讯 stock_profile_cninfo，非东财）。

    v3.3.14 新增：company_info 此前只有 akshare 东财单源。
    仅覆盖 individual_info 语义；其它 endpoint 直接报错，交由路由汇总失败原因。
    """
    if endpoint != "individual_info":
        raise ValueError(
            f"cninfo 备源不支持 company_info endpoint={endpoint!r}（仅 individual_info）"
        )
    sym = _code6(code or symbol)
    if not sym:
        raise RuntimeError("stock code is required")
    return _ak().stock_profile_cninfo(symbol=sym)


_SINA_STMT_MAP = {
    "profit": "利润表",
    "balance": "资产负债表",
    "cashflow": "现金流量表",
}


def fetch_financial_stmt_sina(
    endpoint: str = "profit",
    symbol: str = "",
    code: str = "",
    **kwargs,
) -> pd.DataFrame:
    """财务报表备源（新浪财经 stock_financial_report_sina，非东财）。

    v3.3.14 新增：financial_stmt 此前只有 akshare 东财单源。
    覆盖 profit / balance / cashflow 三个主 endpoint。
    """
    if endpoint not in _SINA_STMT_MAP:
        raise ValueError(
            f"sina 备源不支持 financial_stmt endpoint={endpoint!r}"
            f"（支持: {list(_SINA_STMT_MAP)}）"
        )
    sym = _prefixed_code(code or symbol)
    if not sym:
        raise RuntimeError("stock code is required")
    return _ak().stock_financial_report_sina(stock=sym, symbol=_SINA_STMT_MAP[endpoint])


def fetch_industry_data_ths(endpoint: str = "board_industry_name_em", **kwargs):
    """行业 / 概念板块备源（同花顺，非东财）。

    v3.3.14 新增：industry_data 此前只有 akshare 东财单源。
    接受主源的 endpoint 名并映射到对应的同花顺接口。
    """
    ak = _ak()
    if endpoint in ("board_industry_name_em", "board_industry_name_ths"):
        return ak.stock_board_industry_name_ths()
    if endpoint in ("board_concept_name_em", "board_concept_name_ths"):
        return ak.stock_board_concept_name_ths()
    raise ValueError(
        f"ths 备源不支持 industry_data endpoint={endpoint!r}"
        "（支持: board_industry_name_em/ths, board_concept_name_em/ths）"
    )


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


def fetch_industry_comparison_ths(
    endpoint: str = "即时", code: str = "", symbol: str = "",
    trade_date: str = "", top_n: int = 20, **kwargs,
) -> dict:
    """行业横向对比备源（同花顺行业资金流，非东财）。

    v3.3.15 新增：industry_comparison 原先主备两源（em_push2 / akshare
    stock_sector_fund_flow_rank）**都打东财 push2 族**，主源被限流时备源一同失败，
    整类型失效。本源改走同花顺 10jqka，与主源完全解耦。

    返回与 em_push2 / akshare 源完全相同的 dict 结构，工具层无需改动。
    """
    ak = _ak()
    if not trade_date:
        trade_date = datetime.now().strftime("%Y-%m-%d")

    # 同花顺行业资金流：即时 / 3日排行 / 5日排行 / 10日排行 / 20日排行
    indicator = endpoint if endpoint in (
        "即时", "3日排行", "5日排行", "10日排行", "20日排行"
    ) else "即时"

    df = ak.stock_fund_flow_industry(symbol=indicator)
    if df is None or df.empty:
        raise RuntimeError("同花顺行业资金流数据为空")

    chg_col = next(
        (c for c in ("行业-涨跌幅", "阶段涨跌幅", "涨跌幅") if c in df.columns), None
    )

    result: dict = {
        "source": f"THS stock_fund_flow_industry({indicator})",
        "date": trade_date,
        "code": code or symbol or None,
        "industries": [],
    }
    for i, (_, row) in enumerate(df.iterrows()):
        if i >= top_n:
            break
        try:
            chg = float(row.get(chg_col, 0) or 0) if chg_col else 0.0
        except (TypeError, ValueError):
            chg = 0.0
        result["industries"].append({
            "rank": i + 1,
            "name": str(row.get("行业", "") or ""),
            "change_pct": chg,
            "up_count": 0,
            "down_count": 0,
            "leader": str(row.get("领涨股", "") or ""),
        })
    if not result["industries"]:
        raise RuntimeError("同花顺行业资金流解析后为空")
    return result


def fetch_hot_rank_ths(
    endpoint: str = "rank", symbol: str = "", period: str = "", **kwargs,
) -> pd.DataFrame:
    """热度榜备源（同花顺人气榜，非东财）。

    v3.3.15 新增，同时服务 hot_rank / hot_search / xueqiu_hot 三个类型的降级兜底。
    这三类主源分别是东财人气榜(push2，本机会间歇性 RST)、百度股市通、雪球热度，
    都属"个股热度排行"语义，同花顺人气榜可作为结构相近的降级备源。

    返回列：排名 / 代码 / 名称 / 人气值 / 涨幅% / 排名变化 / 概念标签 / 热度标签

    个股维度的 endpoint（detail/realtime/keyword/latest/relate）无法用全市场榜
    替代，遇到时直接抛错 —— 宁可如实记为失败，也不返回语义不符的数据。
    """
    from . import ths_fetchers as _ths   # 局部导入，避免模块级循环依赖

    if endpoint in ("detail", "realtime", "keyword", "latest", "relate"):
        raise ValueError(
            f"ths 备源不支持个股维度 endpoint={endpoint!r}（同花顺热榜仅提供全市场榜）"
        )
    p = period or ("day" if endpoint in ("up", "3日排行") else "hour")
    df = _ths.fetch_ths_hot_list(period=p)
    if df is None or df.empty:
        raise RuntimeError("同花顺热榜返回空")
    return df


def fetch_baidu_economic_calendar_bak(date: str = "", **kwargs) -> pd.DataFrame:
    """财报披露日历备源（百度股市通，非东财）。

    v3.3.15 新增，服务 baidu_economic_calendar 的兜底。
    主源是百度理财日历（宏观事件），本备源给的是 A股财报披露时间表，
    语义偏"财报日历"一侧，属**降级备源**（字段不同，工具层泛化输出）。
    """
    ak = _ak()
    # 注意：ak.news_report_time_baidu 的 date 默认值是**写死的过期日期**，
    # 不传就用 2025 年的旧值。这里显式补当天，避免备源返回陈旧数据。
    d = date or datetime.now().strftime("%Y%m%d")
    df = ak.news_report_time_baidu(date=d)
    if df is None or df.empty:
        raise RuntimeError(f"百度财报披露时间表返回空（date={d}）")
    return df


def fetch_market_sentiment_legu(**kwargs) -> pd.DataFrame:
    """A股市场情绪备源（乐咕乐股「赚钱效应分析」，非东财、非 chinascope）。

    v3.3.15 新增，服务 index_news_sentiment 的兜底。

    背景（实测结论）：主源 akshare index_news_sentiment_scope 的上游
    www.chinascope.com 已**不再提供 JSON 接口**，现在返回 HTML 页面
    （content-type: text/html，正文是 <!DOCTYPE html>），任何客户端都拿不到数据 ——
    属上游永久失效，非本机网络/证书问题。

    本备源给出标准 A股市场情绪口径（上涨/下跌/涨停/跌停家数、真实涨跌幅、
    活跃度等），来自 legulegu.com，与主源完全独立。
    """
    ak = _ak()
    df = ak.stock_market_activity_legu()
    if df is None or df.empty:
        raise RuntimeError("乐咕乐股市场活跃度返回空")
    return df


def fetch_baidu_trade_notify_tfp(
    endpoint: str = "suspend", symbol: str = "", date: str = "", **kwargs,
) -> pd.DataFrame:
    """交易提示/停复牌备源（akshare stock_tfp_em 全市场停复牌表，非百度）。

    v3.3.15 新增，服务 baidu_trade_notify 的兜底。
    主源是百度交易提示（停复牌口径）。本备源给出全市场停复牌明细
    （序号/代码/名称/停牌时间/停牌截止时间/停牌期限/停牌原因），语义精确对应，
    且**不需要股票代码**，与工具层"市场级调用"的方式一致。
    """
    ak = _ak()
    df = ak.stock_tfp_em()
    if df is None or df.empty:
        raise RuntimeError("全市场停复牌表返回空")
    return df

