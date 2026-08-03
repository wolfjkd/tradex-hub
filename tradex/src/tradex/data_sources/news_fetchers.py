"""
新闻资讯类数据源直连 fetch_fn 包装器。

3 个直连数据源（不依赖 akshare）：
  - em_news_direct:    东财 search-api-web JSONP 个股新闻
  - cls_telegraph:     财联社 cls.cn 实时电报
  - cninfo_direct:     巨潮 cninfo.com.cn 官方公告

设计原则：
  - 每个 fetch_fn 接受 **kwargs，返回 DataFrame（统一格式）
  - 失败时返回空 DataFrame，不抛异常（容错设计）
  - 仅使用 curl_cffi（requests 兼容层），不引入其他第三方依赖
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import pandas as pd
from curl_cffi import requests as curl_requests

logger = logging.getLogger("tradex.news")

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
_TIMEOUT = 15  # 秒


# ============================================================
# 东财个股新闻直连 — em_news_direct
# ============================================================

def fetch_em_news_direct(symbol: str = "", code: str = "", **kwargs) -> pd.DataFrame:
    """东财个股新闻直连（search-api-web JSONP，参照 akshare 实现）。

    替代 akshare stock_news_em，直连底层 JSONP 接口更稳定。
    兼容 symbol/code 两种参数名（SmartRouter 路由归一化）。

    Args:
        symbol: 6位股票代码，如 "600519"
        code: 6位股票代码（别名）

    Returns:
        DataFrame with columns: 新闻标题, 新闻内容, 发布时间, 文章来源, 新闻链接, 股票代码
    """
    sym = symbol or code
    if not sym:
        raise ValueError("fetch_em_news_direct: symbol/code is required")

    try:
        url = "https://search-api-web.eastmoney.com/search/jsonp"
        inner_param = {
            "uid": "",
            "keyword": sym,
            "type": ["cmsArticleWebOld"],
            "client": "web",
            "clientVersion": "curr",
            "param": {
                "cmsArticleWebOld": {
                    "searchScope": "default",
                    "sort": "default",
                    "pageIndex": 1,
                    "pageSize": 30,
                    "preTag": "<em>",
                    "postTag": "</em>",
                }
            },
        }
        params = {
            "cb": "jQuery35101792940631092459_1764599530165",
            "param": json.dumps(inner_param, ensure_ascii=False),
            "_": "1764599530176",
        }
        headers = {
            "User-Agent": _UA,
            "Referer": "https://so.eastmoney.com/news/s?keyword=" + sym,
            "Accept": "*/*",
        }
        resp = curl_requests.get(url, params=params, headers=headers, timeout=_TIMEOUT, impersonate="chrome120")
        resp.raise_for_status()

        # 解析 JSONP 响应：去掉 callback 包裹
        text = resp.text.strip()
        # 格式: jQueryXXXXXXXXXX({...})
        paren_idx = text.find("(")
        if paren_idx > 0 and text.endswith(")"):
            text = text[paren_idx + 1 : -1]
        data = json.loads(text)

        articles_raw = data.get("result", {}).get("cmsArticleWebOld", [])
        if not articles_raw:
            return pd.DataFrame()

        articles = []
        for item in articles_raw:
            title = (item.get("title") or "").strip()
            if not title:
                continue
            pub_time = _parse_em_time(item.get("date") or "")
            code_str = item.get("code") or ""
            link = f"http://finance.eastmoney.com/a/{code_str}.html" if code_str else ""
            articles.append({
                "新闻标题": title,
                "新闻内容": (item.get("content") or "").strip(),
                "发布时间": pub_time,
                "文章来源": item.get("mediaName") or "",
                "新闻链接": link,
                "股票代码": sym,
            })

        if not articles:
            return pd.DataFrame()

        return pd.DataFrame(articles)

    except Exception as e:
        logger.warning("fetch_em_news_direct(%s) failed: %s", sym, e)
        return pd.DataFrame()


def _parse_em_time(raw: str) -> str:
    """解析东财新闻时间格式为 YYYY-MM-DD HH:MM:SS。"""
    if not raw:
        return ""
    try:
        if len(raw) == 10:  # timestamp seconds
            return datetime.fromtimestamp(int(raw)).strftime("%Y-%m-%d %H:%M:%S")
        if len(raw) == 13:  # timestamp ms
            return datetime.fromtimestamp(int(raw) / 1000).strftime("%Y-%m-%d %H:%M:%S")
        return raw
    except Exception:
        return raw


# ============================================================
# 财联社快讯直连 — cls_telegraph
# ============================================================

def fetch_cls_telegraph(num_results: int = 20, **kwargs) -> pd.DataFrame:
    """财联社实时电报直连（cls.cn get_roll_list，含签名计算）。

    获取全市场 7×24 小时财经快讯，分钟级更新。
    签名算法参照 akshare 实现：sign = md5(sha1(urlencode(params)))。

    Args:
        num_results: 返回条数，默认 20，最大 50

    Returns:
        DataFrame with columns: 标题, 内容, 发布日期, 发布时间
    """
    try:
        url = "https://www.cls.cn/v1/roll/get_roll_list"
        rn = min(max(num_results, 1), 50)
        params = {
            "app": "CailianpressWeb",
            "category": "",
            "last_time": str(int(time.time())),
            "os": "web",
            "refresh_type": "1",
            "rn": str(rn),
            "sv": "8.4.6",
        }
        # 签名计算：md5(sha1(urlencode(params)))
        sign = hashlib.md5(
            hashlib.sha1(urlencode(params).encode("utf-8")).hexdigest().encode("utf-8")
        ).hexdigest()
        params["sign"] = sign

        headers = {
            "User-Agent": _UA,
            "Referer": "https://www.cls.cn/telegraph",
        }
        resp = curl_requests.get(url, params=params, headers=headers, timeout=_TIMEOUT, impersonate="chrome120")
        resp.raise_for_status()

        data = resp.json()
        roll_data = (data.get("data") or {}).get("roll_data") or []
        if not roll_data:
            return pd.DataFrame()

        items = []
        for item in roll_data:
            title = (item.get("title") or "").strip()
            content = (item.get("content") or "").strip()
            if not title and not content:
                continue
            ctime = item.get("ctime") or 0
            dt = datetime.fromtimestamp(ctime, tz=timezone.utc).astimezone() if ctime else None
            items.append({
                "标题": title,
                "内容": content,
                "发布日期": dt.strftime("%Y-%m-%d") if dt else "",
                "发布时间": dt.strftime("%H:%M:%S") if dt else "",
            })

        if not items:
            return pd.DataFrame()

        df = pd.DataFrame(items)
        return df.head(rn)

    except Exception as e:
        logger.warning("fetch_cls_telegraph failed: %s", e)
        return pd.DataFrame()


# ============================================================
# 巨潮公告直连 — cninfo_direct
# ============================================================

def fetch_cninfo_direct(
    symbol: str = "",
    code: str = "",
    keyword: str = "",
    page_size: int = 30,
    **kwargs,
) -> pd.DataFrame:
    """巨潮资讯网公告直连（cninfo.com.cn）。

    替代 akshare stock_notice_report，直连官方 POST 接口更稳定。
    支持 symbol 为空时查询全市场最新公告。

    Args:
        symbol: 6位股票代码，如 "600519"。为空则查全市场
        code: 6位股票代码（别名）
        keyword: 搜索关键词，如 "年报"、"业绩预告"
        page_size: 每页条数，默认 30

    Returns:
        DataFrame with columns: 标题, 发布日期, 公告类型, PDF链接, 股票代码, 股票名称
    """
    sym = symbol or code

    try:
        url = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
        headers = {
            "User-Agent": _UA,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": "http://www.cninfo.com.cn",
            "Referer": "http://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "*/*",
        }

        # 构建 POST 数据
        post_data: dict[str, Any] = {
            "pageNum": 1,
            "pageSize": str(page_size),
            "column": "szse",
            "tabName": "fulltext",
            "plate": "",
            "stock": "",
            "searchkey": keyword,
            "secid": "",
            "category": "",
            "trade": "",
            "seDate": "",
            "sortName": "",
            "sortType": "",
            "isHLtitle": "true",
        }

        # 如果指定了股票代码，解析 orgId
        if sym:
            org_id = _resolve_org_id(sym)
            if org_id:
                post_data["stock"] = f"{sym},{org_id}"
                post_data["column"] = "szse"

        resp = curl_requests.post(url, data=post_data, headers=headers, timeout=_TIMEOUT)
        resp.raise_for_status()

        result = resp.json()
        announcements = result.get("announcements") or []
        if not announcements:
            return pd.DataFrame()

        items = []
        for ann in announcements:
            title = (ann.get("announcementTitle") or "").strip()
            if not title:
                continue
            ann_time = ann.get("announcementTime") or 0
            date_str = datetime.fromtimestamp(ann_time / 1000).strftime("%Y-%m-%d") if ann_time else ""
            adj_url = ann.get("adjunctUrl") or ""
            pdf_url = f"http://static.cninfo.com.cn/{adj_url}" if adj_url else ""
            items.append({
                "标题": title,
                "发布日期": date_str,
                "公告类型": ann.get("announcementTypeName") or "",
                "PDF链接": pdf_url,
                "股票代码": ann.get("secCode") or "",
                "股票名称": ann.get("secName") or "",
            })

        if not items:
            return pd.DataFrame()

        df = pd.DataFrame(items)

        # 在 Python 端按 symbol 过滤（巨潮 API 的 stock 参数过滤不稳定）
        if sym:
            df = df[df["股票代码"] == sym]

        if df.empty:
            return pd.DataFrame()

        return df

    except Exception as e:
        logger.warning("fetch_cninfo_direct(%s) failed: %s", sym or "all", e)
        return pd.DataFrame()


def _resolve_org_id(symbol: str) -> str:
    """通过巨潮搜索接口解析股票代码对应的 orgId。

    API 返回格式：list[dict]，每个 dict 包含 code/orgId/zwjc 等字段。

    Args:
        symbol: 6位股票代码

    Returns:
        orgId 字符串，失败返回空字符串
    """
    try:
        url = "http://www.cninfo.com.cn/new/information/topSearch/query"
        headers = {
            "User-Agent": _UA,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer": "http://www.cninfo.com.cn/",
            "X-Requested-With": "XMLHttpRequest",
        }
        data = {"keyWord": symbol, "maxNum": 5}
        resp = curl_requests.post(url, data=data, headers=headers, timeout=_TIMEOUT)
        resp.raise_for_status()
        result = resp.json()

        # API 返回 list[dict] 或 dict{stockList: [...]}
        if isinstance(result, list):
            stock_list = result
        else:
            stock_list = result.get("stockList") or []

        for stock in stock_list:
            if isinstance(stock, dict) and stock.get("code") == symbol:
                return stock.get("orgId") or ""
        if stock_list and isinstance(stock_list[0], dict):
            return stock_list[0].get("orgId") or ""
        return ""
    except Exception as e:
        logger.warning("_resolve_org_id(%s) failed: %s", symbol, e)
        return ""


# ============================================================
# 新浪财经新闻直连 — sina_finance_news
# ============================================================

def fetch_sina_finance_news(num_results: int = 20, **kwargs) -> pd.DataFrame:
    """新浪财经新闻直连（滚动新闻 API）。

    获取全市场最新财经新闻，覆盖宏观、公司、行业等。

    Args:
        num_results: 返回条数，默认 20，最大 50

    Returns:
        DataFrame with columns: 新闻标题, 发布时间, 文章来源, 新闻链接
    """
    try:
        num = min(max(num_results, 1), 50)
        url = "https://feed.mix.sina.com.cn/api/roll/get"
        params = {
            "pageid": "153",
            "lid": "2509",
            "k": "",
            "num": str(num),
        }
        headers = {
            "User-Agent": _UA,
            "Referer": "https://finance.sina.com.cn/",
            "Accept": "application/json",
        }
        resp = curl_requests.get(url, params=params, headers=headers, timeout=_TIMEOUT)
        resp.raise_for_status()

        data = resp.json()
        result = data.get("result", {})
        items_data = result.get("data", []) or []
        if not items_data:
            return pd.DataFrame()

        articles = []
        for item in items_data:
            title = (item.get("title") or "").strip()
            if not title:
                continue
            ctime = item.get("ctime") or ""
            pub_time = ""
            if ctime:
                try:
                    pub_time = datetime.fromtimestamp(int(ctime)).strftime("%Y-%m-%d %H:%M")
                except Exception:
                    pub_time = ctime
            articles.append({
                "新闻标题": title,
                "发布时间": pub_time,
                "文章来源": item.get("source") or "",
                "新闻链接": item.get("url") or "",
            })

        if not articles:
            return pd.DataFrame()

        df = pd.DataFrame(articles)
        return df.head(num)

    except Exception as e:
        logger.warning("fetch_sina_finance_news failed: %s", e)
        return pd.DataFrame()