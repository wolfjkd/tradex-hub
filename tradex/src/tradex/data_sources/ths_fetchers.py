"""同花顺数据源 —— 一致预期 / 热点归因 / 涨停揭秘 / 热榜（零鉴权）。

借鉴 a-stock-data 的同花顺实现，均为零鉴权直连接口。
同花顺是不封 IP 的低风险源，东财被封时的备选。
"""
from __future__ import annotations

import logging
from datetime import datetime
from io import StringIO

import pandas as pd
import requests

logger = logging.getLogger("tradex.ths")

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36")

_S = requests.Session()
_S.trust_env = False  # 直连，不读系统代理


def _get(url: str, params: dict | None = None, headers: dict | None = None, timeout: int = 10, **kw):
    h = {"User-Agent": _UA}
    if headers:
        h.update(headers)
    return _S.get(url, params=params, headers=h, timeout=timeout, **kw)


def fetch_ths_eps_forecast(code: str, **kwargs) -> pd.DataFrame:
    """同花顺机构一致预期 EPS（直连 basic.10jqka.com.cn，解析 HTML 表格）。

    Returns:
        DataFrame: 年度 / 预测机构数 / 最小值 / 均值 / 最大值（均值=一致预期 EPS）
    """
    code = str(code).split(".")[0].split("_")[0]  # 纯 6 位，带前缀会 404
    url = f"https://basic.10jqka.com.cn/new/{code}/worth.html"
    r = _get(url, headers={"Referer": "https://basic.10jqka.com.cn/"}, timeout=15)
    r.encoding = "gbk"
    dfs = pd.read_html(StringIO(r.text))
    for df in dfs:
        cols = [str(c) for c in df.columns]
        if any("每股收益" in c or "均值" in c for c in cols):
            return df
    return dfs[0] if dfs else pd.DataFrame()


def fetch_ths_hot_reason(date: str | None = None, **kwargs) -> pd.DataFrame:
    """同花顺当日强势股 + 题材归因（reason 人工运营标签，核心字段）。

    实测 73ms 拿到 ~125 只 + 完整字段。
    Returns columns: 名称 / 代码 / 题材归因 / 涨幅% / 换手率% / 成交额 / 大单净量 ...
    """
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    url = (f"http://zx.10jqka.com.cn/event/api/getharden/"
           f"date/{date}/orderby/date/orderway/desc/charset/GBK/")
    r = _get(url, timeout=10)
    data = r.json()
    if data.get("errocode", 0) != 0:
        raise RuntimeError(f"同花顺热点错误: {data.get('errormsg', '')}")
    rows = data.get("data") or []
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    rename = {
        "name": "名称", "code": "代码", "reason": "题材归因",
        "close": "收盘价", "zhangdie": "涨跌额", "zhangfu": "涨幅%",
        "huanshou": "换手率%", "chengjiaoe": "成交额",
        "chengjiaoliang": "成交量", "ddejingliang": "大单净量", "market": "市场",
    }
    return df.rename(columns=rename)


def fetch_ths_limit_up_pool(date: str, **kwargs) -> pd.DataFrame:
    """同花顺涨停揭秘：涨停原因 + 封板质量。date=YYYYMMDD。

    Returns columns: 代码 / 名称 / 涨停原因 / 板型 / 封板成功率 / 炸板次数 / 封单额 / 连板 / 首封时间
    """
    url = "https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool"
    params = {
        "page": 1, "limit": 200,
        "field": "199112,10,9001,330323,330324,330325,9002,330329,133971,133970,1968584,3475914,9003,9004",
        "filter": "HS,GEM2STAR", "order_field": "330324", "order_type": "0", "date": date,
    }
    r = _get(url, params=params, timeout=10)
    info = (r.json().get("data") or {}).get("info", [])
    rows = []
    for it in info:
        ft = it.get("first_limit_up_time")
        rows.append({
            "代码": it.get("code"), "名称": it.get("name"),
            "价格": it.get("latest"), "涨幅%": it.get("change_rate"),
            "涨停原因": it.get("reason_type", ""), "板型": it.get("limit_up_type", ""),
            "封板成功率": it.get("limit_up_suc_rate"), "炸板次数": it.get("open_num") or 0,
            "封单额": it.get("order_amount"), "连板": it.get("high_days", ""),
            "首封时间": datetime.fromtimestamp(int(ft)).strftime("%H:%M:%S") if ft else "",
            "是否回封": it.get("is_again_limit"),
        })
    return pd.DataFrame(rows)


def fetch_ths_hot_list(period: str = "hour", **kwargs) -> pd.DataFrame:
    """同花顺热榜：人气值 + 概念标签 + 排名变化。period: hour/day。

    Returns columns: 排名 / 代码 / 名称 / 人气值 / 涨幅% / 排名变化 / 概念标签 / 热度标签
    """
    r = _get("https://dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1/stock",
             params={"stock_type": "a", "type": period, "list_type": "normal"}, timeout=10)
    lst = (r.json().get("data") or {}).get("stock_list") or []
    rows = []
    for it in lst:
        tag = it.get("tag") or {}
        rows.append({
            "排名": it.get("order"), "代码": it.get("code"), "名称": it.get("name"),
            "人气值": it.get("rate"), "涨幅%": it.get("rise_and_fall"),
            "排名变化": it.get("hot_rank_chg"),
            "概念标签": tag.get("concept_tag") or [],
            "热度标签": tag.get("popularity_tag", ""),
        })
    return pd.DataFrame(rows)


# ── 市场盘口分析（同花顺 eq.10jqka.com.cn 盘面分析页，零鉴权直连）──
# 三个接口：涨跌分布 / 涨跌趋势分时 / 市场成交额分时。
# 关键：limit_up_minute 接口的 header 返回「准确全市场涨跌家数/涨跌停（含北交所）」，
# 比东财 getTopicZDFenBu（仅沪深A股、涨停口径含新股虚增）更准确。

_THS_REFERER = "https://eq.10jqka.com.cn/"


def fetch_ths_up_down_distribution(**kwargs) -> pd.DataFrame:
    """同花顺涨跌分布（11 档区间，含北交所）。

    Returns columns: 区间 / 家数 / 方向（跌/平/涨）
    """
    url = "https://dq.10jqka.com.cn/fuyao/up_down_distribution/distribution/v2/realtime"
    r = _get(url, headers={"Referer": _THS_REFERER}, timeout=15)
    r.raise_for_status()
    table = (r.json().get("data") or {}).get("table", [])
    n = len(table)
    rows = []
    for i, it in enumerate(table):
        key = str(it.get("key", ""))
        val = int(it.get("value", 0) or 0)
        # key 有重复（">10%" 跌/涨各一次），靠顺序判方向：前半跌、中间平、后半涨
        if i < n // 2:
            direction = "跌"
        elif i == n // 2:
            direction = "平"
        else:
            direction = "涨"
        rows.append({"区间": key, "家数": val, "方向": direction})
    return pd.DataFrame(rows)


def fetch_ths_market_chart(chart_key: str, **kwargs) -> dict:
    """同花顺市场分析图表数据（盘面分析页的涨跌趋势/成交额分时）。

    chart_key: limit_up_minute（涨跌趋势）/ turnover_minute（市场成交额）/ market_score_day（评分）。

    Returns dict: {name, header:[{name,key,val}], point_key_list, point_list, ...}
    """
    url = f"https://dq.10jqka.com.cn/fuyao/market_analysis_api/chart/v1/get_chart_data?chart_key={chart_key}"
    r = _get(url, headers={"Referer": _THS_REFERER}, timeout=15)
    r.raise_for_status()
    return (r.json().get("data") or {}).get("charts") or {}


def fetch_ths_limit_up_minute(**kwargs) -> dict:
    """涨跌趋势分时（含 header 准确全市场涨跌家数/涨跌停，含北交所）。"""
    return fetch_ths_market_chart("limit_up_minute")


def fetch_ths_turnover_minute(**kwargs) -> dict:
    """市场成交额分时（当日 vs 昨日同时刻）。"""
    return fetch_ths_market_chart("turnover_minute")


def fetch_ths_market_breadth(**kwargs) -> dict:
    """准确全市场涨跌家数/涨跌停/平盘（含北交所）。

    涨/跌/涨停/跌停从 limit_up_minute 接口的 header 提取；平盘数从涨跌分布接口 "0" 档拿。
    返回 {"up","down","flat","limit_up","limit_down"}。
    实测：上涨2121/下跌3292/涨停80/跌停5（与通达信/同花顺全市场口径一致）。
    """
    data = fetch_ths_market_chart("limit_up_minute")
    header = data.get("header") or []
    out = {}
    for h in header:
        out[str(h.get("key"))] = h.get("val")
    flat = 0
    try:
        dist = fetch_ths_up_down_distribution()
        zero = dist[dist["方向"] == "平"]
        flat = int(zero["家数"].sum()) if not zero.empty else 0
    except Exception:  # noqa: BLE001
        flat = 0
    return {
        "up": int(out.get("rise", 0) or 0),
        "down": int(out.get("fall", 0) or 0),
        "flat": flat,
        "limit_up": int(out.get("limit_up", 0) or 0),
        "limit_down": int(out.get("limit_down", 0) or 0),
    }
