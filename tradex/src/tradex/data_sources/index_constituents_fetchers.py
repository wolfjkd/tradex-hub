"""
中证指数 + 国证指数官网数据源 fetch_fn 包装器。

提供以下 fetcher：
  - fetch_csi_index_constituents: 中证指数成分股
  - fetch_csi_index_weights:      中证指数权重
  - fetch_csi_index_valuation:    中证指数 PE 与股息率
  - fetch_cnindex_constituents:   国证指数成分股
  - fetch_cnindex_weights:        国证指数权重

设计原则：
  - 全部官方一手数据（中证指数官网、国证指数官网）
  - 与 akshare(抓东财聚合) 上游独立
  - 中证作为 priority=1（一手），国证作为 priority=100（备）

借鉴：simonlin1212/a-stock-data 的 §12 指数与交易日历层实现思路。
"""

from __future__ import annotations

import io
import logging
from datetime import datetime
from typing import Any

import pandas as pd
from curl_cffi import requests as curl_requests

logger = logging.getLogger("tradex.index_constituents")

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
_TIMEOUT = 20


# ============================================================
# 中证指数 — 成分股
# ============================================================

def fetch_csi_index_constituents(
    index_code: str = "000300",  # 沪深300
    **kwargs,
) -> pd.DataFrame:
    """中证指数官网成分股查询（一手数据，零鉴权）。

    Args:
        index_code: 指数代码，如 000300（沪深300）/ 000905（中证500）/ 000852（中证1000）

    Returns:
        DataFrame with columns: 代码, 名称, 上市交易所
    """
    try:
        url = f"https://csi-web.cn.zealink.com/zh_CN/close-info/detail/{index_code}/Constituent"
        headers = {
            "User-Agent": _UA,
            "Referer": "https://www.csindex.com.cn/",
            "Accept": "application/json",
        }
        resp = curl_requests.get(
            url, headers=headers, timeout=_TIMEOUT, impersonate="chrome120"
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("data") or []
        if not items:
            return pd.DataFrame()

        rows = []
        for it in items:
            rows.append({
                "代码": (it.get("stockCode") or it.get("code") or "").strip(),
                "名称": (it.get("stockName") or it.get("name") or "").strip(),
                "上市交易所": (it.get("exchange") or "").strip(),
            })
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)

    except Exception as e:
        logger.warning("fetch_csi_index_constituents(%s) failed: %s", index_code, e)
        return pd.DataFrame()


# ============================================================
# 中证指数 — 权重
# ============================================================

def fetch_csi_index_weights(
    index_code: str = "000300",
    **kwargs,
) -> pd.DataFrame:
    """中证指数官网权重查询（最近公布的指数权重，月末快照）。

    Returns:
        DataFrame with columns: 代码, 名称, 权重(%)
    """
    try:
        url = f"https://csi-web.cn.zealink.com/zh_CN/close-info/detail/{index_code}/Weight"
        headers = {
            "User-Agent": _UA,
            "Referer": "https://www.csindex.com.cn/",
            "Accept": "application/json",
        }
        resp = curl_requests.get(
            url, headers=headers, timeout=_TIMEOUT, impersonate="chrome120"
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("data") or []
        if not items:
            return pd.DataFrame()

        rows = []
        for it in items:
            rows.append({
                "代码": (it.get("stockCode") or "").strip(),
                "名称": (it.get("stockName") or "").strip(),
                "权重(%)": float(it.get("weight") or 0) * 100,
            })
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)

    except Exception as e:
        logger.warning("fetch_csi_index_weights(%s) failed: %s", index_code, e)
        return pd.DataFrame()


# ============================================================
# 中证指数 — PE 与股息率
# ============================================================

def fetch_csi_index_valuation(
    index_code: str = "000300",
    **kwargs,
) -> pd.DataFrame:
    """中证指数官网 PE 与股息率（不含 PB）。

    Returns:
        DataFrame with columns: 日期, PE, 股息率(%)
    """
    try:
        url = f"https://csi-web.cn.zealink.com/zh_CN/close-info/detail/{index_code}/PE"
        headers = {
            "User-Agent": _UA,
            "Referer": "https://www.csindex.com.cn/",
            "Accept": "application/json",
        }
        resp = curl_requests.get(
            url, headers=headers, timeout=_TIMEOUT, impersonate="chrome120"
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("data") or []
        if not items:
            return pd.DataFrame()

        rows = []
        for it in items:
            rows.append({
                "日期": (it.get("date") or "").strip(),
                "PE": float(it.get("pe") or 0),
                "股息率(%)": float(it.get("dividendYield") or 0) * 100,
            })
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)

    except Exception as e:
        logger.warning("fetch_csi_index_valuation(%s) failed: %s", index_code, e)
        return pd.DataFrame()


# ============================================================
# 国证指数 — 成分股
# ============================================================

def fetch_cnindex_constituents(
    index_code: str = "399001",  # 深证成指
    **kwargs,
) -> pd.DataFrame:
    """国证指数官网成分股（作为中证的备源）。

    Returns:
        DataFrame with columns: 代码, 名称, 上市交易所
    """
    try:
        url = f"http://www.cnindex.com.cn/index/details/constituents/{index_code}"
        headers = {
            "User-Agent": _UA,
            "Referer": "http://www.cnindex.com.cn/",
            "Accept": "application/json",
        }
        resp = curl_requests.get(
            url, headers=headers, timeout=_TIMEOUT, impersonate="chrome120"
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("data") or []
        if not items:
            return pd.DataFrame()

        rows = []
        for it in items:
            rows.append({
                "代码": (it.get("code") or "").strip(),
                "名称": (it.get("name") or "").strip(),
                "上市交易所": (it.get("exchange") or "").strip(),
            })
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)

    except Exception as e:
        logger.warning("fetch_cnindex_constituents(%s) failed: %s", index_code, e)
        return pd.DataFrame()


# ============================================================
# 国证指数 — 权重
# ============================================================

def fetch_cnindex_weights(
    index_code: str = "399001",
    **kwargs,
) -> pd.DataFrame:
    """国证指数官网权重查询。

    Returns:
        DataFrame with columns: 代码, 名称, 权重(%)
    """
    try:
        url = f"http://www.cnindex.com.cn/index/details/weights/{index_code}"
        headers = {
            "User-Agent": _UA,
            "Referer": "http://www.cnindex.com.cn/",
            "Accept": "application/json",
        }
        resp = curl_requests.get(
            url, headers=headers, timeout=_TIMEOUT, impersonate="chrome120"
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("data") or []
        if not items:
            return pd.DataFrame()

        rows = []
        for it in items:
            rows.append({
                "代码": (it.get("code") or "").strip(),
                "名称": (it.get("name") or "").strip(),
                "权重(%)": float(it.get("weight") or 0),
            })
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)

    except Exception as e:
        logger.warning("fetch_cnindex_weights(%s) failed: %s", index_code, e)
        return pd.DataFrame()
