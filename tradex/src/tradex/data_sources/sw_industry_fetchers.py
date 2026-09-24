"""
申万行业分类历史变迁 fetch_fn 包装器。

提供以下 fetcher：
  - fetch_sw_industry_history:   申万行业分类变迁史（一次性下载 .xls 缓存）
  - fetch_sw_industry_as_of:     按 (code, date) 查询股票在指定日期所属的申万行业

设计原则：
  - 申万行业分类官网一手数据（.xls 文件）
  - 首次加载后内存缓存，避免重复请求
  - 失败时返回空 DataFrame，不抛异常

借鉴：simonlin1212/a-stock-data 的 §6.7 端点实现思路。
"""

from __future__ import annotations

import io
import logging
import threading
from datetime import datetime
from typing import Any

import pandas as pd
from curl_cffi import requests as curl_requests

logger = logging.getLogger("tradex.sw_industry")

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
_TIMEOUT = 30

# 模块级缓存：变迁史 DataFrame
_history_df: pd.DataFrame | None = None
_history_lock = threading.Lock()


def _load_history() -> pd.DataFrame:
    """下载并缓存申万行业分类变迁史（一次性）。"""
    global _history_df
    with _history_lock:
        if _history_df is not None:
            return _history_df
        try:
            # 申万行业分类变迁史下载链接（可能需要更新）
            url = "http://www.swsindex.com/downfile/branchhistory.xls"
            headers = {
                "User-Agent": _UA,
                "Referer": "http://www.swsindex.com/",
                "Accept": "*/*",
            }
            resp = curl_requests.get(
                url, headers=headers, timeout=_TIMEOUT, impersonate="chrome120"
            )
            resp.raise_for_status()
            df = pd.read_excel(io.BytesIO(resp.content))
            _history_df = df
            logger.info("sw_industry_history loaded: %d rows", len(df))
            return df
        except Exception as e:
            logger.warning("load sw_industry_history failed: %s", e)
            _history_df = pd.DataFrame()
            return _history_df


def fetch_sw_industry_history(
    force_refresh: bool = False,
    **kwargs,
) -> pd.DataFrame:
    """申万行业分类变迁史（含所有股票在不同时期的行业归属）。

    Args:
        force_refresh: 强制重新下载（绕过缓存）

    Returns:
        DataFrame with columns: 股票代码, 股票名称, 行业代码, 行业名称, 开始日期, 结束日期
    """
    global _history_df
    if force_refresh:
        with _history_lock:
            _history_df = None
    return _load_history()


def fetch_sw_industry_as_of(
    symbol: str = "",
    code: str = "",
    date: str = "",
    **kwargs,
) -> pd.DataFrame:
    """按 (code, date) 查询股票在指定日期所属的申万行业。

    用于历史回测时还原当时行业归属（避免使用今日行业造成未来函数）。

    Args:
        symbol: 6 位股票代码
        code: 6 位股票代码（别名）
        date: 查询日期 YYYY-MM-DD（默认今天）

    Returns:
        DataFrame with columns: 股票代码, 行业代码, 行业名称, 生效日期
    """
    sym = (symbol or code or "").strip().lower()
    if not sym:
        raise ValueError("stock code is required")
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")

    try:
        history = _load_history()
        if history.empty:
            return pd.DataFrame()

        # 假设 history 含列：股票代码, 开始日期, 结束日期, 行业代码, 行业名称
        # 列名按实际 .xls 调整
        col_code = "股票代码" if "股票代码" in history.columns else history.columns[0]
        col_start = "开始日期" if "开始日期" in history.columns else history.columns[3]
        col_end = "结束日期" if "结束日期" in history.columns else history.columns[4]

        # 过滤：代码匹配 + 日期落在 [开始, 结束) 区间
        mask = (history[col_code].astype(str).str.lower() == sym) & \
               (history[col_start].astype(str) <= date) & \
               ((history[col_end].isna()) | (history[col_end].astype(str) >= date))
        subset = history[mask].copy()
        if subset.empty:
            return pd.DataFrame()

        # 返回标准列
        result = pd.DataFrame({
            "股票代码": sym,
            "行业代码": subset.get("行业代码", pd.Series(dtype=str)).values,
            "行业名称": subset.get("行业名称", pd.Series(dtype=str)).values,
            "生效日期": subset[col_start].values,
        })
        return result.reset_index(drop=True)

    except Exception as e:
        logger.warning("fetch_sw_industry_as_of(%s, %s) failed: %s", sym, date, e)
        return pd.DataFrame()
