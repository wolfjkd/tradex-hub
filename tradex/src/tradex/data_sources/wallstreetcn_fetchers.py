"""
华尔街见闻数据源 fetch_fn 包装器。

提供以下 fetcher：
  - fetch_wallstreetcn_lives:    7×24 全球财经快讯（按频道 + 翻页游标）
  - fetch_macro_calendar:        全球宏观日历（公布值/预期/前值）

设计原则：
  - 华尔街见闻接口零鉴权、低风险
  - 失败时返回空 DataFrame，不抛异常
  - 与已有 tradex-hub 财经新闻源（财联社/新浪）上游完全独立

借鉴：simonlin1212/a-stock-data 的 §5.4 / §11.6 端点实现思路。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import pandas as pd
from curl_cffi import requests as curl_requests

logger = logging.getLogger("tradex.wallstreetcn")

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
_TIMEOUT = 15


# ============================================================
# 华尔街见闻 7×24 快讯 — wallstreetcn_lives
# ============================================================

def fetch_wallstreetcn_lives(
    channel: str = "global",  # global / important / a-stock / us-stock / forex / commodity
    limit: int = 30,
    cursor: str = "",
    **kwargs,
) -> pd.DataFrame:
    """华尔街见闻 7×24 全球财经快讯（按频道 + 翻页游标）。

    Args:
        channel: 频道过滤（默认全部）
        limit: 返回条数（最大 100）
        cursor: 翻页游标（首页留空，下一页传上一页最后一条的 score）

    Returns:
        DataFrame with columns: 标题, 内容, 发布时间, 频道
    """
    try:
        channel_map = {
            "global": "-820",
            "important": "-820",
            "a-stock": "-710",
            "us-stock": "-830",
            "forex": "-840",
            "commodity": "-880",
        }
        channel_id = channel_map.get(channel, "-820")
        url = "https://api-ddc-wallstreetcn.com/mapi/wapi/v2/live/list"
        params = {
            "channel_id": channel_id,
            "accept": "1,2,3",
            "limit": str(min(max(limit, 1), 100)),
        }
        if cursor:
            params["last_time"] = cursor
        else:
            params["last_time"] = str(int(time.time()))

        headers = {
            "User-Agent": _UA,
            "Referer": "https://wallstreetcn.com/live/global",
            "Accept": "application/json",
        }
        resp = curl_requests.get(
            url, params=params, headers=headers, timeout=_TIMEOUT, impersonate="chrome120"
        )
        resp.raise_for_status()
        data = resp.json()
        items = (data.get("data") or {}).get("items") or []
        if not items:
            return pd.DataFrame()

        rows = []
        from datetime import datetime, timezone
        for it in items:
            title = (it.get("title") or "").strip()
            content_html = it.get("content") or ""
            # 去 HTML 标签
            import re
            content = re.sub(r"<[^>]+>", "", content_html).strip()
            ctime = it.get("display_time") or it.get("created_at") or 0
            try:
                dt = datetime.fromtimestamp(int(ctime), tz=timezone.utc).astimezone()
                pub_time = dt.strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                pub_time = ""

            rows.append({
                "标题": title,
                "内容": content[:500],  # 截断长内容
                "发布时间": pub_time,
                "频道": channel,
                "原文链接": it.get("uri", ""),
            })
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)

    except Exception as e:
        logger.warning("fetch_wallstreetcn_lives(%s) failed: %s", channel, e)
        return pd.DataFrame()


# ============================================================
# 全球宏观日历 — macro_calendar
# ============================================================

def fetch_macro_calendar(
    start_date: str = "",
    end_date: str = "",
    country: str = "",  # "" 全部 / "中国" / "美国" / "欧元区" / "日本"
    min_importance: str = "",  # "" 全部 / "高" / "中" / "低"
    **kwargs,
) -> pd.DataFrame:
    """华尔街见闻全球宏观日历（公布值/预期/前值）。

    Args:
        start_date: YYYY-MM-DD
        end_date: YYYY-MM-DD
        country: 国家/地区过滤
        min_importance: 重要性过滤

    Returns:
        DataFrame with columns: 时间, 国家/地区, 指标, 重要性, 公布值, 预期值, 前值
    """
    try:
        from datetime import datetime, timedelta
        if not end_date:
            end_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        if not start_date:
            start_date = datetime.now().strftime("%Y-%m-%d")

        url = "https://api-ddc-wallstreetcn.com/mapi/wapi/v2/calendar/list"
        params = {
            "start_date": start_date,
            "end_date": end_date,
            "country": country,
        }
        headers = {
            "User-Agent": _UA,
            "Referer": "https://wallstreetcn.com/calendar",
            "Accept": "application/json",
        }
        resp = curl_requests.get(
            url, params=params, headers=headers, timeout=_TIMEOUT, impersonate="chrome120"
        )
        resp.raise_for_status()
        data = resp.json()
        items = (data.get("data") or {}).get("items") or []
        if not items:
            return pd.DataFrame()

        importance_map = {1: "低", 2: "中", 3: "高"}
        rows = []
        for it in items:
            importance = importance_map.get(it.get("importance") or 0, "中")
            if min_importance and importance != min_importance:
                continue
            rows.append({
                "时间": (it.get("pub_time") or it.get("date") or "").strip(),
                "国家/地区": (it.get("country") or it.get("region") or "").strip(),
                "指标": (it.get("title") or it.get("indicator") or "").strip(),
                "重要性": importance,
                "公布值": (it.get("actual") or "").strip(),
                "预期值": (it.get("forecast") or "").strip(),
                "前值": (it.get("previous") or "").strip(),
            })
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)

    except Exception as e:
        logger.warning("fetch_macro_calendar failed: %s", e)
        return pd.DataFrame()
