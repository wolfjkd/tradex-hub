"""
央视网新闻联播数据源 fetch_fn 包装器。

提供以下 fetcher：
  - fetch_cctv_news:     新闻联播条目 + 文字稿（当晚约 20:00 后更新）

设计原则：
  - 央视网官方一手，零鉴权
  - 失败时返回空 DataFrame，不抛异常

借鉴：simonlin1212/a-stock-data 的 §5.5 端点实现思路。
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any

import pandas as pd
from curl_cffi import requests as curl_requests

logger = logging.getLogger("tradex.cctv")

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
_TIMEOUT = 20


def fetch_cctv_news(
    date: str = "",
    with_content: bool = False,
    **kwargs,
) -> pd.DataFrame:
    """央视网新闻联播条目 + 文字稿。

    Args:
        date: 日期 YYYY-MM-DD，默认今天（当晚约 20:00 后才有当日条目）
        with_content: 是否获取正文内容（额外请求每条详情页）

    Returns:
        DataFrame with columns: 标题, 时间, 链接 [, 内容]
    """
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")

    try:
        # 央视网新闻联播列表接口
        url = "https://news.cctv.com/2019/07/ga49jm2p3kj4/index.shtml"
        # 改为对应日期的索引（央视网按日期归档）
        date_compact = date.replace("-", "")
        archive_url = f"https://cn.chinadaily.com.cn/a/{date.replace('-', '/')}/day.xml"

        # 直接走央视网新闻联播 API
        api_url = "https://news.cctv.com/list/"
        params = {
            "type": "xwlb",
            "date": date,
        }
        headers = {
            "User-Agent": _UA,
            "Referer": "https://news.cctv.com/",
            "Accept": "*/*",
        }
        resp = curl_requests.get(
            api_url, params=params, headers=headers, timeout=_TIMEOUT, impersonate="chrome120"
        )
        resp.raise_for_status()
        text = resp.text

        # 央视网返回 HTML，正则提取条目
        items = re.findall(
            r'<a[^>]+href="([^"]+)"[^>]*>([^<]+)</a>[^<]*?<span[^>]*>([^<]+)</span>',
            text,
        )
        if not items:
            # 尝试 JSON 接口
            try:
                data = resp.json()
                items = [(it.get("url", ""), it.get("title", ""), it.get("time", ""))
                         for it in (data.get("data") or [])]
            except Exception:
                return pd.DataFrame()

        rows = []
        for link, title, time_str in items:
            title = title.strip()
            if not title or "新闻联播" not in title and len(title) < 5:
                continue
            row = {
                "标题": title,
                "时间": (date + " " + time_str).strip(),
                "链接": link,
            }
            if with_content:
                # 抓详情页正文
                try:
                    detail_resp = curl_requests.get(
                        link, headers=headers, timeout=_TIMEOUT, impersonate="chrome120"
                    )
                    detail_text = detail_resp.text
                    # 提取正文（央视网常见正文容器）
                    content_match = re.search(
                        r'<div[^>]+class="[^"]*content[^"]*"[^>]*>([\s\S]+?)</div>',
                        detail_text,
                    )
                    if content_match:
                        content = re.sub(r"<[^>]+>", "", content_match.group(1)).strip()
                        row["内容"] = content[:3000]
                    else:
                        row["内容"] = ""
                except Exception:
                    row["内容"] = ""
            rows.append(row)

        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)

    except Exception as e:
        logger.warning("fetch_cctv_news(%s) failed: %s", date, e)
        return pd.DataFrame()
