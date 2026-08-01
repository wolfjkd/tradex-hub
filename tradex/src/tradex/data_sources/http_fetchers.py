"""
HTTP 直连数据源 fetch_fn 包装器。

纯 HTTP 抓取的数据源（不依赖 akshare），主要是腾讯行情接口。
仅本文件允许直接发起 HTTP 请求获取行情数据。
"""

from __future__ import annotations

import logging
import urllib.request

logger = logging.getLogger("tradex.http")


def _tencent_quote_vals(code: str) -> list:
    """从腾讯 qt.gtimg.cn 获取个股行情，返回 ~ 分隔的值列表。"""
    prefix = "sh" if code.startswith("6") else "sz"
    url = f"https://qt.gtimg.cn/q={prefix}{code}"
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "Mozilla/5.0")
    resp = urllib.request.urlopen(req, timeout=5)
    raw = resp.read().decode("gbk")
    if '"' not in raw:
        raise RuntimeError("tencent quote: no data")
    return raw.split('"')[1].split("~")


def fetch_realtime_quote_tencent(symbol: str = "", code: str = "", **kwargs):
    """实时行情（腾讯 qt.gtimg.cn）。返回单行 DataFrame，含'代码'列。

    作为 realtime_quote 的 priority=200 兜底源。
    兼容 symbol/code 两种参数名（SmartRouter 路由归一化）。
    """
    import pandas as pd
    sym = symbol or code
    if not sym:
        raise RuntimeError("stock code is required (symbol or code)")
    vals = _tencent_quote_vals(sym)
    if len(vals) < 50:
        raise RuntimeError("tencent returned insufficient data")
    return pd.DataFrame([{
        "代码": sym,
        "名称": vals[1] if len(vals) > 1 else "",
        "最新价": float(vals[3]) if vals[3] else 0,
        "涨跌幅": float(vals[32]) if len(vals) > 32 and vals[32] else 0,
        "成交量": float(vals[36]) if len(vals) > 36 and vals[36] else 0,
        "成交额": float(vals[37]) if len(vals) > 37 and vals[37] else 0,
        "最高": float(vals[33]) if len(vals) > 33 and vals[33] else 0,
        "最低": float(vals[34]) if len(vals) > 34 and vals[34] else 0,
        "今开": float(vals[5]) if len(vals) > 5 and vals[5] else 0,
        "昨收": float(vals[4]) if len(vals) > 4 and vals[4] else 0,
        "总市值": float(vals[45]) if len(vals) > 45 and vals[45] else 0,
        "流通市值": float(vals[44]) if len(vals) > 44 and vals[44] else 0,
        "市盈率": float(vals[39]) if len(vals) > 39 and vals[39] else 0,
    }])


def fetch_profit_forecast_tencent(symbol: str = "", code: str = "", **kwargs) -> dict:
    """一致预期（腾讯行情兜底）。仅返回价格/PE，无 EPS 预测数据。

    作为 profit_forecast 的 priority=100 备源（当同花顺抓取失败时）。
    兼容 symbol/code 两种参数名（SmartRouter 路由归一化）。
    """
    sym = symbol or code
    if not sym:
        raise RuntimeError("stock code is required (symbol or code)")
    vals = _tencent_quote_vals(sym)
    if len(vals) < 50:
        raise RuntimeError("tencent returned insufficient data for profit_forecast")
    price = float(vals[3]) if vals[3] else 0
    pe_ttm = float(vals[39]) if len(vals) > 39 and vals[39] else 0
    return {
        "symbol": sym,
        "source": "tencent qt.gtimg.cn (price only)",
        "price": price,
        "pe_ttm": pe_ttm,
        "forecasts": [],
        "summary": "同花顺 EPS 抓取失败，仅返回腾讯实时价格/PE",
    }
