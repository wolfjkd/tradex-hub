"""备源族（QI-ARCH-09 拆分，2026-11-19）：新浪/巨潮/同花顺/乐咕/中债等独立上游备源函数——备源不得与主源打同一上游域名族（选源原则）。"""
from __future__ import annotations
import logging
from datetime import datetime

import pandas as pd

from .akshare_common import _ak

logger = logging.getLogger("tradex.akshare")

_SINA_STMT_MAP = {
    "profit": "利润表",
    "balance": "资产负债表",
    "cashflow": "现金流量表",
}

def _fetch_sina_index_amount_today(sym: str):
    """新浪实时行情（hq.sinajs.cn）取指数当日成交额(元)。

    sym: sh000001 / sz399001 / sz399006 等。
    新浪指数行情字段：…, 成交量(手), 成交额(元), …（上证/深证的额在第10位）。返回整数成交额(元)或 None。
    """
    import urllib.request
    # 铁律：国内接口直连。默认 opener 会读 HTTP(S)_PROXY 环境变量，必须绕过。
    _opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    url = f"https://hq.sinajs.cn/list={sym}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120",
        "Referer": "https://finance.sina.com.cn",
    })
    resp = _opener.open(req, timeout=8)
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


def fetch_bond_yield_cn_backup(curve: str = "国债", **kwargs) -> pd.DataFrame:
    """中国国债收益率曲线备源（东财 datacenter，2/5/10/30 年）。

    Returns:
        DataFrame with columns: 期限, 收益率(%)——取最新有值交易日
    """
    if curve != "国债":
        raise ValueError(f"备源仅支持国债曲线，收到 curve={curve}")
    # 2026-11-10 审计修复：改走模块统一 _ak()（含 set_timeout getattr 防御，
    # akshare<1.20.4 不再炸源），不再裸 import 绕过防御。
    ak = _ak()

    df = ak.bond_zh_us_rate()
    if df is None or df.empty:
        raise ValueError("bond_zh_us_rate 返回空")
    terms = [
        ("中国国债收益率2年", "2年"),
        ("中国国债收益率5年", "5年"),
        ("中国国债收益率10年", "10年"),
        ("中国国债收益率30年", "30年"),
    ]
    cols_present = [c for c, _ in terms if c in df.columns]
    valid = df.dropna(how="all", subset=cols_present)
    if valid.empty:
        raise ValueError("bond_zh_us_rate 全列 NaN（疑似上游改版）")
    latest = valid.iloc[-1]  # 最新有值行；行内个别期限 NaN 则该期限不进结果
    rows = [
        {"期限": label, "收益率(%)": float(latest[col])}
        for col, label in terms
        if col in df.columns and pd.notna(latest[col])
    ]
    if not rows:
        raise ValueError("bond_zh_us_rate 最新行无有效收益率")
    return pd.DataFrame(rows)
