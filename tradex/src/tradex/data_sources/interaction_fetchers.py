"""
投资者互动数据源 fetch_fn 包装器。

提供以下 fetcher：
  - fetch_cninfo_irm:           互动易（深市投资者问答）
  - fetch_sse_e_interaction:    上证 e 互动（沪市投资者问答）
  - fetch_ths_hot_list:         同花顺热榜（已存在的备用名）

设计原则：
  - 上交所与深交所分别独立接口
  - 失败时返回空 DataFrame，不抛异常

借鉴：simonlin1212/a-stock-data 的 §10 舆情互动层实现思路。
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
from curl_cffi import requests as curl_requests

logger = logging.getLogger("tradex.interaction")

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
_TIMEOUT = 15


# ============================================================
# 互动易（深市） — cninfo_irm
# ============================================================

def fetch_cninfo_irm(
    symbol: str = "",
    code: str = "",
    page: int = 1,
    page_size: int = 20,
    **kwargs,
) -> pd.DataFrame:
    """互动易（深市投资者互动问答，巨潮信息网）。

    Args:
        symbol: 6 位股票代码（深市）
        page: 页码
        page_size: 每页条数

    Returns:
        DataFrame with columns: 提问, 答复, 提问时间, 答复时间
    """
    sym = (symbol or code or "").strip().lower()
    if not sym:
        raise ValueError("stock code is required")

    try:
        url = "http://www.cninfo.com.cn/new/disclosure/stock irm_query"
        params = {
            "stock": sym,
            "page": str(page),
            "pageSize": str(page_size),
        }
        headers = {
            "User-Agent": _UA,
            "Referer": "http://www.cninfo.com.cn/new/disclosure/stock",
            "Accept": "application/json",
        }
        resp = curl_requests.post(
            url, data=params, headers=headers, timeout=_TIMEOUT, impersonate="chrome120"
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("recordList") or data.get("data") or []
        if not items:
            return pd.DataFrame()

        rows = []
        for it in items:
            rows.append({
                "提问": (it.get("questionContent") or it.get("question") or "").strip(),
                "答复": (it.get("answerContent") or it.get("answer") or "").strip(),
                "提问时间": (it.get("questionTime") or it.get("qTime") or "").strip(),
                "答复时间": (it.get("answerTime") or it.get("aTime") or "").strip(),
                "股票代码": sym,
            })
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)

    except Exception as e:
        logger.warning("fetch_cninfo_irm(%s) failed: %s", sym, e)
        return pd.DataFrame()


# ============================================================
# 上证 e 互动（沪市） — sse_e_interaction
# ============================================================

def fetch_sse_e_interaction(
    symbol: str = "",
    code: str = "",
    page: int = 1,
    page_size: int = 20,
    kind: str = "",  # "" 全部 / "问答" / "建议"
    **kwargs,
) -> pd.DataFrame:
    """上证 e 互动（沪市投资者问答平台）。

    上交所运营的独立平台，与巨潮完全独立。

    Returns:
        DataFrame with columns: 提问, 答复, 提问时间, 答复时间
    """
    sym = (symbol or code or "").strip().lower()
    if not sym:
        raise ValueError("stock code is required")

    try:
        url = "http://sns.sseinfo.com/api/query/questionAndAnswer"
        params = {
            "stockcode": sym,
            "page": str(page),
            "pageSize": str(page_size),
            "type": kind,
        }
        headers = {
            "User-Agent": _UA,
            "Referer": "http://sns.sseinfo.com/",
            "Accept": "application/json",
        }
        resp = curl_requests.get(
            url, params=params, headers=headers, timeout=_TIMEOUT, impersonate="chrome120"
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("data") or data.get("results") or []
        if not items:
            return pd.DataFrame()

        rows = []
        for it in items:
            rows.append({
                "提问": (it.get("content") or it.get("question") or "").strip(),
                "答复": (it.get("answerContent") or it.get("answer") or "").strip(),
                "提问时间": (it.get("questionDate") or it.get("qDate") or "").strip(),
                "答复时间": (it.get("answerDate") or it.get("aDate") or "").strip(),
                "股票代码": sym,
            })
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)

    except Exception as e:
        logger.warning("fetch_sse_e_interaction(%s) failed: %s", sym, e)
        return pd.DataFrame()
