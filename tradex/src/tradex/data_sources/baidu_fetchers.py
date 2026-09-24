"""
百度股市通数据源 fetch_fn 包装器。

提供以下 fetcher：
  - fetch_baidu_kline_with_ma: 百度股市通带 MA 的日 K 线

作为 historical_kline 的第四备源（priority=200）。
与 eltdx(TCP)/akshare(抓东财)/tdx_mcp(官方 MCP) 上游完全独立。

借鉴：simonlin1212/a-stock-data 的 §1.5 baidu_kline_with_ma 实现思路。
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any

import pandas as pd
from curl_cffi import requests as curl_requests

logger = logging.getLogger("tradex.baidu")

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
_TIMEOUT = 15


def _baidu_market_prefix(code: str) -> str:
    """百度股市通的市场前缀：沪市 sh / 深市 sz / 北交所 bj。"""
    sym = code.strip().lower()
    if sym.startswith("6"):
        return "sh" + sym
    if sym.startswith(("0", "3")):
        return "sz" + sym
    if sym.startswith(("4", "8", "9")):
        return "bj" + sym
    return "sz" + sym


def fetch_baidu_kline_with_ma(
    symbol: str = "",
    code: str = "",
    period: str = "day",
    count: int = 120,
    **kwargs,
) -> pd.DataFrame:
    """百度股市通带 MA 的 K 线直连。

    作为 historical_kline 的第四备源。返回 OHLCV + MA5/MA10/MA20/MA30。
    百度接口响应快、零鉴权、自带均线，省去本地计算。

    Args:
        symbol: 6 位股票代码
        code: 6 位股票代码（别名）
        period: K 线周期，day / week / month
        count: 返回 K 线数量，默认 120

    Returns:
        DataFrame with columns: 日期, 开盘, 收盘, 最高, 最低, 成交量, 成交额,
                                MA5, MA10, MA20, MA30
    """
    sym = (symbol or code or "").strip().lower()
    if not sym:
        raise ValueError("stock code is required (symbol or code)")

    try:
        bd_code = _baidu_market_prefix(sym)
        # 百度股市通 K 线接口
        url = f"https://finance.pae.baidu.com/vapi/v1/getquotation"
        params = {
            "srcid": "5352",
            "pointType": "string",
            "code": bd_code,
            "market_type": "ab",
            "newFormat": "true",
            "is_498": "0",
            "finClientType": "pc",
            "ktype": period,
            "count": str(min(max(count, 1), 500)),
        }
        headers = {
            "User-Agent": _UA,
            "Referer": "https://gushitong.baidu.com/",
            "Accept": "*/*",
        }
        resp = curl_requests.get(
            url, params=params, headers=headers, timeout=_TIMEOUT, impersonate="chrome120"
        )
        resp.raise_for_status()
        data = resp.json()
        klines = (data.get("result") or {}).get("data", [])
        if not klines:
            return pd.DataFrame()

        rows = []
        for k in klines:
            try:
                # 百度返回格式：日期,开,收,高,低,量,额,振幅,涨跌幅,涨跌额,换手率
                # 或 dict 形式
                if isinstance(k, str):
                    parts = k.split(",")
                    if len(parts) < 7:
                        continue
                    row = {
                        "日期": parts[0],
                        "开盘": float(parts[1]) if parts[1] else 0,
                        "收盘": float(parts[2]) if parts[2] else 0,
                        "最高": float(parts[3]) if parts[3] else 0,
                        "最低": float(parts[4]) if parts[4] else 0,
                        "成交量": float(parts[5]) if parts[5] else 0,
                        "成交额": float(parts[6]) if parts[6] else 0,
                    }
                elif isinstance(k, dict):
                    row = {
                        "日期": k.get("date") or k.get("time") or "",
                        "开盘": float(k.get("open") or 0),
                        "收盘": float(k.get("close") or 0),
                        "最高": float(k.get("high") or 0),
                        "最低": float(k.get("low") or 0),
                        "成交量": float(k.get("volume") or 0),
                        "成交额": float(k.get("amount") or 0),
                    }
                else:
                    continue
                if row["日期"]:
                    rows.append(row)
            except (ValueError, IndexError):
                continue

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows).sort_values("日期").reset_index(drop=True)

        # 本地计算 MA（百度不带 MA 时兜底）
        for ma_n in (5, 10, 20, 30):
            df[f"MA{ma_n}"] = df["收盘"].rolling(window=ma_n, min_periods=1).mean()

        return df

    except Exception as e:
        logger.warning("fetch_baidu_kline_with_ma(%s) failed: %s", sym, e)
        return pd.DataFrame()
