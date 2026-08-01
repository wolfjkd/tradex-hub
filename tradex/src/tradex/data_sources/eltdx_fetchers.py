"""
eltdx 数据源 fetch_fn 包装器。

所有 eltdx (通达信行情协议) 的数据获取函数在此注册为 SmartRouter fetch_fn。
仅本文件（及 data_sources 包内其他 fetcher 文件）允许 `from eltdx import ...`。

复用原 eltdx_data.py 的 _get_client() 单例模式（TdxClient.from_hosts + connect）。
"""

from __future__ import annotations

import logging
import threading
import atexit
from typing import Any, Optional

logger = logging.getLogger("tradex.eltdx")


# ============================================================
# 客户端管理（单例）— 从 eltdx_data.py 迁移
# ============================================================

_client: Optional[Any] = None
_client_lock = False


def _get_client():
    """获取/创建 eltdx TdxClient 单例。

    关闭 probe_hosts（避免冷启动慢），使用默认 host 列表。
    第一次调用时建立连接，后续复用。
    """
    global _client, _client_lock
    if _client is not None:
        return _client
    if _client_lock:
        return None
    _client_lock = True
    try:
        from eltdx import TdxClient
        _client = TdxClient.from_hosts(timeout=8.0, pool_size=1)
        _client.connect()
        logger.info("eltdx TdxClient connected")
        return _client
    except Exception as e:
        logger.error(f"eltdx client init failed: {e}")
        _client = None
        return None
    finally:
        _client_lock = False


def _shutdown_client() -> None:
    global _client
    if _client is not None:
        try:
            _client.close()
        except Exception:
            pass
        _client = None


atexit.register(_shutdown_client)


def _normalize_code(code: str) -> str:
    """把 6 位代码或带前缀代码统一成 eltdx 期望的格式。

    eltdx 的 TdxClient 通常接受 'sz000001' / 'sh600000' 或 6 位纯代码。
    """
    code = code.strip().lower()
    if code.startswith(("sz", "sh", "bj")):
        return code
    if len(code) == 6 and code.isdigit():
        if code.startswith(("60", "68", "90", "11", "13")):
            return "sh" + code
        if code.startswith(("00", "30", "20")):
            return "sz" + code
        if code.startswith(("8", "43", "92")):
            return "bj" + code
    return code


def _strip_prefix(code: str) -> str:
    """去除 sh/sz/bj 前缀，返回 6 位纯代码。"""
    code = code.strip().lower()
    if code.startswith(("sh", "sz", "bj")):
        return code[2:]
    return code


# ============================================================
# fetch_fn 包装器
# ============================================================

def fetch_call_auction(code: str = "", **kwargs) -> Any:
    """集合竞价数据（eltdx 独占源）。返回 eltdx auctions.series 原始结果对象。"""
    client = _get_client()
    if client is None:
        raise RuntimeError("eltdx client not available")
    norm_code = _normalize_code(code)
    result = client.auctions.series(norm_code)
    if result is None:
        raise RuntimeError("auction series is empty")
    points = getattr(result, "points", None) or []
    if not points:
        raise RuntimeError("no auction points")
    return result


def fetch_tick_data(code: str = "", trading_date: str = "", count: int = 2000, **kwargs) -> Any:
    """逐笔成交数据（eltdx 独占源）。返回 eltdx trades.history 原始结果对象。"""
    client = _get_client()
    if client is None:
        raise RuntimeError("eltdx client not available")
    norm_code = _normalize_code(code)
    norm_date = (trading_date or "").replace("-", "").replace("/", "")
    result = client.trades.history(norm_code, norm_date, count=count)
    ticks = getattr(result, "ticks", None) or []
    if not ticks:
        raise RuntimeError(f"no ticks on {norm_date}")
    return result


def fetch_f10_profile(code: str = "", **kwargs) -> dict:
    """F10 资料（eltdx 独占源）。返回含 profile/topics/diagnosis 原始响应的 dict。"""
    client = _get_client()
    if client is None:
        raise RuntimeError("eltdx client not available")
    norm_code = code.strip()
    if norm_code.startswith(("sz", "sh", "bj")):
        norm_code = norm_code[2:]

    profile_resp = client.f10.company_profile(norm_code)
    topics_resp = client.f10.hot_topics(norm_code)
    diag_resp = client.f10.finance_diagnosis(norm_code)

    return {
        "profile_resp": profile_resp,
        "topics_resp": topics_resp,
        "diag_resp": diag_resp,
        "code": norm_code,
    }


def fetch_realtime_quote(code: str = "", **kwargs):
    """实时行情（eltdx 源）。返回单行 DataFrame，含'代码'列。

    eltdx 无全市场快照接口，使用 bars.get(count=1) 取最新一根 K 线作为快照。
    """
    import pandas as pd
    client = _get_client()
    if client is None:
        raise RuntimeError("eltdx client not available")
    norm_code = _normalize_code(code)
    result = client.bars.get(norm_code, period="day", count=1)
    bars = getattr(result, "bars", None) or []
    if not bars:
        raise RuntimeError("eltdx returned no bars")
    b = bars[-1]
    return pd.DataFrame([{
        "代码": _strip_prefix(norm_code),
        "最新价": getattr(b, "close", None),
        "今开": getattr(b, "open", None),
        "最高": getattr(b, "high", None),
        "最低": getattr(b, "low", None),
        "收盘": getattr(b, "close", None),
        "开盘": getattr(b, "open", None),
        "成交量": getattr(b, "volume", None),
        "成交额": getattr(b, "amount", None),
    }])


def fetch_historical_kline(code: str = "", period: str = "day", count: int = 100, **kwargs):
    """历史 K 线（eltdx 源）。返回中文列名 DataFrame（与 akshare 口径对齐）。"""
    import pandas as pd
    client = _get_client()
    if client is None:
        raise RuntimeError("eltdx client not available")
    norm_code = _normalize_code(code)
    result = client.bars.get(norm_code, period=period, count=count)
    bars = getattr(result, "bars", None) or []
    if not bars:
        raise RuntimeError(f"no kline bars for period={period}")
    rows = []
    for b in bars:
        rows.append({
            "日期": getattr(b, "date", None) or getattr(b, "datetime", None),
            "开盘": getattr(b, "open", None),
            "最高": getattr(b, "high", None),
            "最低": getattr(b, "low", None),
            "收盘": getattr(b, "close", None),
            "成交量": getattr(b, "volume", None),
            "成交额": getattr(b, "amount", None),
        })
    return pd.DataFrame(rows)


def fetch_minute_data(code: str = "", **kwargs):
    """分时数据（eltdx 源）。返回中文列名 DataFrame（时间/价格/均价/成交量）。"""
    import pandas as pd
    client = _get_client()
    if client is None:
        raise RuntimeError("eltdx client not available")
    norm_code = _normalize_code(code)
    result = client.minutes.today(norm_code)
    points = getattr(result, "points", None) or []
    if not points:
        raise RuntimeError("no minute points")
    rows = []
    for p in points:
        rows.append({
            "时间": getattr(p, "time_label", None) or getattr(p, "time", None),
            "价格": getattr(p, "price", None),
            "均价": getattr(p, "avg_price", None),
            "成交量": getattr(p, "volume", None),
        })
    return pd.DataFrame(rows)
