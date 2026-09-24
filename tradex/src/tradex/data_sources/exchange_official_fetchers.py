"""
沪深交易所官方数据源 fetch_fn 包装器（零鉴权直连官方）。

提供以下 fetcher：
  - fetch_sse_dragon_tiger:        上交所官方龙虎榜（含营业部席位）
  - fetch_szse_dragon_tiger:       深交所官方龙虎榜（含营业部席位）
  - fetch_sse_margin_trading:      上交所两融明细
  - fetch_szse_margin_trading:     深交所两融明细
  - fetch_szse_trading_calendar:   深交所官方交易日历（整月）
  - fetch_szse_announcement:       深交所官方公告（深市备源）

设计原则：
  - 全部官方一手数据，与东财 datacenter 完全独立
  - 失败时返回空 DataFrame，不抛异常
  - 仅使用 curl_cffi（requests 兼容层），不引入其他第三方依赖

借鉴：simonlin1212/a-stock-data 的官方备胎扩展端点实现思路。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
from curl_cffi import requests as curl_requests

logger = logging.getLogger("tradex.exchange")

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
_TIMEOUT = 15


# ============================================================
# 上交所龙虎榜 — sse_dragon_tiger
# ============================================================

def fetch_sse_dragon_tiger(
    date: str = "",
    **kwargs,
) -> pd.DataFrame:
    """上交所官方龙虎榜（含营业部席位明细）。

    作为 dragon_tiger 的官方备源，与东财 datacenter 完全独立。
    含营业部买卖席位明细，比东财聚合数据更详细。

    Args:
        date: 交易日 YYYY-MM-DD，默认今天

    Returns:
        DataFrame with columns: 代码, 名称, 上榜原因, 净买入, 买入席位, 卖出席位
    """
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")

    try:
        # 上交所龙虎榜接口
        url = "http://query.sse.com.cn/infodisplay/queryLatestBargainRank.do"
        params = {
            "is_tbill": "false",
            "page_no": "1",
            "page_size": "50",
            "date": date.replace("-", ""),
        }
        headers = {
            "User-Agent": _UA,
            "Referer": "http://www.sse.com.cn/",
            "Accept": "*/*",
        }
        resp = curl_requests.get(
            url, params=params, headers=headers, timeout=_TIMEOUT, impersonate="chrome120"
        )
        resp.raise_for_status()
        data = resp.json()
        rows_raw = (data.get("bargainRank") or []).get("result", [])
        if not rows_raw:
            return pd.DataFrame()

        rows = []
        for it in rows_raw:
            rows.append({
                "代码": (it.get("STOCKCODE") or it.get("symbol") or "").strip(),
                "名称": (it.get("STOCKNAME") or it.get("name") or "").strip(),
                "上榜原因": (it.get("REASON") or "").strip(),
                "净买入": float(it.get("NETBUYAMT") or 0),
                "买入席位": (it.get("BUYSEAT") or "").strip(),
                "卖出席位": (it.get("SALESEAT") or "").strip(),
                "日期": date,
            })
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        return df[df["代码"] != ""].reset_index(drop=True)

    except Exception as e:
        logger.warning("fetch_sse_dragon_tiger(%s) failed: %s", date, e)
        return pd.DataFrame()


# ============================================================
# 深交所龙虎榜 — szse_dragon_tiger
# ============================================================

def fetch_szse_dragon_tiger(
    date: str = "",
    **kwargs,
) -> pd.DataFrame:
    """深交所官方龙虎榜（含营业部席位明细）。

    Args:
        date: 交易日 YYYY-MM-DD

    Returns:
        DataFrame with columns: 代码, 名称, 上榜原因, 净买入, 买入席位, 卖出席位
    """
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")

    try:
        # 深交所龙虎榜查询接口
        url = "http://www.szse.cn/api/disc/announcement/annList"
        params = {
            "random": "0.123",
            "channelCode": "fixed_disc",
            "pageSize": "50",
            "pageNum": "1",
            "bigCategoryId": "107",  # 龙虎榜
            "seDate": f"{date}~{date}",
        }
        headers = {
            "User-Agent": _UA,
            "Referer": "http://www.szse.cn/disclosure/listed/notice/",
            "Accept": "application/json",
        }
        resp = curl_requests.get(
            url, params=params, headers=headers, timeout=_TIMEOUT, impersonate="chrome120"
        )
        resp.raise_for_status()
        data = resp.json()
        anns = data.get("data", {}).get("result", [])
        if not anns:
            return pd.DataFrame()

        rows = []
        for it in anns:
            title = (it.get("title") or "").strip()
            code = (it.get("secCode") or "").strip()
            if not code:
                continue
            rows.append({
                "代码": code,
                "名称": title.split(" ")[0] if " " in title else title,
                "上榜原因": title,
                "公告时间": it.get("公告Time") or it.get("pubTime") or date,
                "附件链接": (it.get("relPath") or "").strip(),
                "日期": date,
            })
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)

    except Exception as e:
        logger.warning("fetch_szse_dragon_tiger(%s) failed: %s", date, e)
        return pd.DataFrame()


# ============================================================
# 两融明细 — sse_margin_trading / szse_margin_trading
# ============================================================

def fetch_sse_margin_trading(
    date: str = "",
    **kwargs,
) -> pd.DataFrame:
    """上交所两融交易明细（融资余额、融券余额）。"""
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    try:
        url = "http://query.sse.com.cn/infodisplay/queryLatestMarginTrade.do"
        params = {
            "is_tbill": "false",
            "page_no": "1",
            "page_size": "100",
            "date": date.replace("-", ""),
        }
        headers = {
            "User-Agent": _UA,
            "Referer": "http://www.sse.com.cn/",
            "Accept": "*/*",
        }
        resp = curl_requests.get(
            url, params=params, headers=headers, timeout=_TIMEOUT, impersonate="chrome120"
        )
        resp.raise_for_status()
        data = resp.json()
        rows_raw = (data.get("marginTrade") or []).get("result", [])
        if not rows_raw:
            return pd.DataFrame()

        rows = []
        for it in rows_raw:
            rows.append({
                "日期": date,
                "代码": (it.get("STOCKCODE") or "").strip(),
                "融资余额": float(it.get("FINANCE_BALANCE") or 0),
                "融资买入额": float(it.get("FINANCE_BUY") or 0),
                "融券余量": float(it.get("SECURITY_VOLUME") or 0),
                "融券卖出量": float(it.get("SECURITY_SELL") or 0),
            })
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)

    except Exception as e:
        logger.warning("fetch_sse_margin_trading(%s) failed: %s", date, e)
        return pd.DataFrame()


def fetch_szse_margin_trading(
    date: str = "",
    **kwargs,
) -> pd.DataFrame:
    """深交所两融交易明细。"""
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    try:
        url = "http://www.szse.cn/api/disc/announcement/annList"
        params = {
            "random": "0.123",
            "channelCode": "fixed_disc",
            "pageSize": "100",
            "pageNum": "1",
            "bigCategoryId": "108",  # 两融
            "seDate": f"{date}~{date}",
        }
        headers = {
            "User-Agent": _UA,
            "Referer": "http://www.szse.cn/disclosure/margin/",
            "Accept": "application/json",
        }
        resp = curl_requests.get(
            url, params=params, headers=headers, timeout=_TIMEOUT, impersonate="chrome120"
        )
        resp.raise_for_status()
        data = resp.json()
        anns = data.get("data", {}).get("result", [])
        if not anns:
            return pd.DataFrame()
        # 深交所两融是公告附件，需要单独下载解析
        rows = []
        for it in anns:
            rows.append({
                "日期": date,
                "代码": (it.get("secCode") or "").strip(),
                "标题": (it.get("title") or "").strip(),
                "附件链接": (it.get("relPath") or "").strip(),
            })
        return pd.DataFrame(rows) if rows else pd.DataFrame()

    except Exception as e:
        logger.warning("fetch_szse_margin_trading(%s) failed: %s", date, e)
        return pd.DataFrame()


# ============================================================
# 交易日历 — szse_trading_calendar
# ============================================================

def fetch_szse_trading_calendar(
    year: int = 0,
    month: int = 0,
    **kwargs,
) -> pd.DataFrame:
    """深交所官方交易日历（整月）。

    替代 eltdx 的 trading_day 兜底。深交所发布整月日历，节假日标注清晰。

    Args:
        year: 年份，默认当前年
        month: 月份，默认当前月

    Returns:
        DataFrame with columns: 日期, 是否交易日, 节假日
    """
    if not year:
        year = datetime.now().year
    if not month:
        month = datetime.now().month

    try:
        url = "http://www.szse.cn/api/report/ShowReport/commonQuery"
        params = {
            "random": "0.123",
            "tab1": "tab1",
            "TABLENAME": "lstv3_jyrl",
            "YEARMONTH": f"{year:04d}-{month:02d}",
        }
        headers = {
            "User-Agent": _UA,
            "Referer": "http://www.szse.cn/aboutus/exchangedate/",
            "Accept": "application/json",
        }
        resp = curl_requests.get(
            url, params=params, headers=headers, timeout=_TIMEOUT, impersonate="chrome120"
        )
        resp.raise_for_status()
        data = resp.json()
        rows_raw = data.get("data", [])
        if not rows_raw:
            return pd.DataFrame()

        rows = []
        for it in rows_raw:
            date_str = (it.get("JYRQ") or it.get("date") or "").strip()
            status = (it.get("JYBZ") or it.get("status") or "").strip()
            rows.append({
                "日期": date_str,
                "是否交易日": "是" if status == "1" else "否",
                "节假日": (it.get("MEMO") or it.get("memo") or "").strip(),
            })
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)

    except Exception as e:
        logger.warning("fetch_szse_trading_calendar(%d-%d) failed: %s", year, month, e)
        return pd.DataFrame()


# ============================================================
# 深交所官方公告 — szse_announcement（深市备源）
# ============================================================

def fetch_szse_announcement(
    symbol: str = "",
    code: str = "",
    page: int = 1,
    page_size: int = 20,
    **kwargs,
) -> pd.DataFrame:
    """深交所官方公告（深市股票的备胎源）。

    作为 cninfo_announcement 的官方备源，与巨潮信息网上游独立。

    Returns:
        DataFrame with columns: 公告标题, 公告时间, 公告类型, 附件链接, 股票代码
    """
    sym = (symbol or code or "").strip().lower()
    if not sym:
        raise ValueError("stock code is required")

    try:
        url = "http://www.szse.cn/api/disc/announcement/annList"
        params = {
            "random": "0.123",
            "channelCode": "fixed_disc",
            "pageSize": str(page_size),
            "pageNum": str(page),
            "stock": sym,
            "tabName": "fulltext",
        }
        headers = {
            "User-Agent": _UA,
            "Referer": "http://www.szse.cn/disclosure/listed/notice/",
            "Accept": "application/json",
        }
        resp = curl_requests.get(
            url, params=params, headers=headers, timeout=_TIMEOUT, impersonate="chrome120"
        )
        resp.raise_for_status()
        data = resp.json()
        anns = data.get("data", {}).get("result", [])
        if not anns:
            return pd.DataFrame()

        rows = []
        for it in anns:
            rows.append({
                "公告标题": (it.get("title") or "").strip(),
                "公告时间": (it.get("pubTime") or it.get("announcementTime") or "").strip(),
                "公告类型": (it.get("title") or "").strip(),
                "附件链接": (it.get("relPath") or "").strip(),
                "股票代码": sym,
            })
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)

    except Exception as e:
        logger.warning("fetch_szse_announcement(%s) failed: %s", sym, e)
        return pd.DataFrame()
