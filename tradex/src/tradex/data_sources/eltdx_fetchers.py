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
_client_lock = threading.Lock()
_client_initializing = False


def _get_client():
    """获取/创建 eltdx TdxClient 单例。

    关闭 probe_hosts（避免冷启动慢），使用默认 host 列表。
    第一次调用时建立连接，后续复用。
    v3.1.4 起：使用 threading.Lock 替代布尔值标志，修复多线程竞态。
    """
    global _client, _client_initializing
    if _client is not None:
        return _client
    with _client_lock:
        # 双重检查：拿到锁后再次确认（其他线程可能已初始化）
        if _client is not None:
            return _client
        if _client_initializing:
            return None
        _client_initializing = True
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
        with _client_lock:
            _client_initializing = False


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

def _normalize_symbol_code(symbol: str = "", code: str = "") -> str:
    """归一化股票代码参数：同时接受 symbol 和 code，返回非空者。

    解决 SmartRouter.route(**kwargs) 原样转发参数时，
    不同 fetcher 参数名不一致（symbol vs code）导致主源失败的 P0 bug。
    """
    raw = code or symbol
    if not raw:
        raise RuntimeError("stock code is required (symbol or code)")
    return _normalize_code(raw)


def fetch_call_auction(code: str = "", symbol: str = "", **kwargs) -> Any:
    """集合竞价数据（eltdx 独占源）。返回 eltdx auctions.series 原始结果对象。

    兼容 symbol/code 两种参数名（SmartRouter 路由归一化）。
    """
    client = _get_client()
    if client is None:
        raise RuntimeError("eltdx client not available")
    norm_code = _normalize_symbol_code(symbol, code)
    result = client.auctions.series(norm_code)
    if result is None:
        raise RuntimeError("auction series is empty")
    points = getattr(result, "points", None) or []
    if not points:
        raise RuntimeError("no auction points")
    return result


def fetch_tick_data(code: str = "", symbol: str = "", trading_date: str = "", count: int = 2000, **kwargs) -> Any:
    """逐笔成交数据（eltdx 独占源）。返回 eltdx trades.history 原始结果对象。

    兼容 symbol/code 两种参数名（SmartRouter 路由归一化）。
    """
    client = _get_client()
    if client is None:
        raise RuntimeError("eltdx client not available")
    norm_code = _normalize_symbol_code(symbol, code)
    norm_date = (trading_date or "").replace("-", "").replace("/", "")
    result = client.trades.history(norm_code, norm_date, count=count)
    ticks = getattr(result, "ticks", None) or []
    if not ticks:
        raise RuntimeError(f"no ticks on {norm_date}")
    return result


def fetch_f10_profile(code: str = "", symbol: str = "", **kwargs) -> dict:
    """F10 资料（eltdx 独占源）。返回含 profile/topics/diagnosis 原始响应的 dict。

    兼容 symbol/code 两种参数名（SmartRouter 路由归一化）。
    """
    client = _get_client()
    if client is None:
        raise RuntimeError("eltdx client not available")
    raw = code or symbol
    if not raw:
        raise RuntimeError("stock code is required (symbol or code)")
    norm_code = raw.strip()
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


def fetch_realtime_quote(code: str = "", symbol: str = "", **kwargs):
    """实时行情（eltdx 源）。返回单行 DataFrame，含'代码'列。

    使用 client.get_quote() 获取真正的实时报价（QuoteSnapshot），
    字段比 K 线最后一根完整：含涨跌额/涨跌幅/昨收/内外盘/现手等。
    兼容 symbol/code 两种参数名（SmartRouter 路由归一化）。
    """
    import pandas as pd
    client = _get_client()
    if client is None:
        raise RuntimeError("eltdx client not available")
    norm_code = _normalize_symbol_code(symbol, code)
    quotes = client.get_quote(norm_code)
    if not quotes:
        raise RuntimeError("eltdx returned no quote")
    q = quotes[0]
    return pd.DataFrame([{
        "代码": getattr(q, "code", _strip_prefix(norm_code)),
        "最新价": getattr(q, "last_price", None),
        "昨收": getattr(q, "pre_close_price", None),
        "今开": getattr(q, "open_price", None),
        "最高": getattr(q, "high_price", None),
        "最低": getattr(q, "low_price", None),
        "涨跌额": getattr(q, "change", None),
        "涨跌幅": getattr(q, "change_pct", None),
        "成交量": getattr(q, "total_hand", None),  # 单位：手
        "成交额": getattr(q, "amount", None),
        "内盘": getattr(q, "inside_dish", None),
        "外盘": getattr(q, "outer_disc", None),
        "现手": getattr(q, "current_hand", None),
    }])


def fetch_historical_kline(code: str = "", symbol: str = "", period: str = "day", count: int = 100, **kwargs):
    """历史 K 线（eltdx 源）。返回中文列名 DataFrame（与 akshare 口径对齐）。

    兼容 symbol/code 两种参数名（SmartRouter 路由归一化）。
    KlineBar 字段映射（v3.1.3 修复）：date→time, volume→volume_lots。
    """
    import pandas as pd
    client = _get_client()
    if client is None:
        raise RuntimeError("eltdx client not available")
    norm_code = _normalize_symbol_code(symbol, code)
    result = client.bars.get(norm_code, period=period, count=count)
    bars = getattr(result, "bars", None) or []
    if not bars:
        raise RuntimeError(f"no kline bars for period={period}")
    rows = []
    for b in bars:
        rows.append({
            "日期": getattr(b, "time", None),
            "开盘": getattr(b, "open", None),
            "最高": getattr(b, "high", None),
            "最低": getattr(b, "low", None),
            "收盘": getattr(b, "close", None),
            "成交量": getattr(b, "volume_lots", None),
            "成交额": getattr(b, "amount", None),
        })
    return pd.DataFrame(rows)


def fetch_minute_data(code: str = "", symbol: str = "", **kwargs):
    """分时数据（eltdx 源）。返回中文列名 DataFrame（时间/价格/均价/成交量）。

    兼容 symbol/code 两种参数名（SmartRouter 路由归一化）。
    """
    import pandas as pd
    client = _get_client()
    if client is None:
        raise RuntimeError("eltdx client not available")
    norm_code = _normalize_symbol_code(symbol, code)
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
