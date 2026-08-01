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

import logging
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger("tradex.akshare")


def _ak():
    """延迟导入 akshare，避免模块加载时副作用。"""
    import akshare as ak
    return ak


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
    """
    ak = _ak()
    sym = symbol or code
    em_kwargs: dict = {"symbol": sym, "period": period, "adjust": adjust}
    if start_date:
        em_kwargs["start_date"] = start_date
    if end_date:
        em_kwargs["end_date"] = end_date
    return ak.stock_zh_a_hist(**em_kwargs)


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
        return ak.stock_sector_fund_flow_rank(indicator=indicator, sector_type=sector_type)
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
    """主要指数实时行情。返回 DataFrame。

    symbol 为空时返回新浪全量指数；指定时返回东方财富对应系列指数。
    """
    ak = _ak()
    if symbol:
        return ak.stock_zh_index_spot_em(symbol=symbol)
    try:
        df = ak.stock_zh_index_spot()
        if df is not None and not df.empty:
            return df
    except Exception as e:
        logger.debug("stock_zh_index_spot(sina) failed: %s", e)
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
        kw: dict = {}
        if date:
            kw["date"] = date
        return ak.stock_report_disclosure(**kw)
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
    """个股资金流向（akshare stock_individual_fund_flow）。

    返回与 em_push2 源相同的 dict 结构（realtime/history/signal）。
    """
    from ..utils.symbol import get_exchange
    ak = _ak()
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
    market = get_exchange(code)
    df = ak.stock_individual_fund_flow(stock=code, market=market)
    if df is None or df.empty:
        raise RuntimeError("AKShare 资金流数据为空")
    for _, row in df.iterrows():
        entry = {
            "date": str(row.get("日期", "")),
            "main_net": float(row.get("主力净流入-净额", 0) or 0),
            "small": float(row.get("小单净流入-净额", 0) or 0),
            "mid": float(row.get("中单净流入-净额", 0) or 0),
            "large": float(row.get("大单净流入-净额", 0) or 0),
            "super_large": float(row.get("超大单净流入-净额", 0) or 0),
        }
        result["history"].append(entry)
    if result["history"]:
        last = result["history"][-1]
        if last["main_net"] > 0:
            result["signal"] = "bullish_inflow"
        elif last["main_net"] < 0:
            result["signal"] = "bearish_outflow"
    return result


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
