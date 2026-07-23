"""
Eastmoney push2 API client with rate limiting.

Extracted from src/astock_signals/anti_ban_client.py for MCP tools direct use.
Provides rate-limited HTTP requests to Eastmoney push2 APIs.
"""

from __future__ import annotations

import os
import random
import time
import threading

import requests as _requests

_EM_SESSION: _requests.Session | None = None
_EM_MIN_INTERVAL: float = float(os.environ.get("EM_MIN_INTERVAL", "1.0"))
_em_last_call: list[float] = [0.0]
_lock = threading.Lock()

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _ensure_session() -> _requests.Session:
    global _EM_SESSION
    if _EM_SESSION is None:
        with _lock:
            if _EM_SESSION is None:
                _EM_SESSION = _requests.Session()
                _EM_SESSION.headers.update({"User-Agent": _UA})
    return _EM_SESSION


def em_get(
    url: str,
    params: dict | None = None,
    headers: dict | None = None,
    timeout: int = 15,
    **kwargs,
) -> _requests.Response:
    with _lock:
        wait = _EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
        if wait > 0:
            time.sleep(wait + random.uniform(0.1, 0.5))
        _em_last_call[0] = time.time()
    return _ensure_session().get(url, params=params, headers=headers, timeout=timeout, **kwargs)


def em_push2(params: dict, timeout: int = 15) -> dict:
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    r = em_get(url, params=params, timeout=timeout)
    return r.json()


def em_push2_fund_flow(secid: str, timeout: int = 10) -> dict:
    url = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
    params = {
        "secid": secid,
        "klt": 1,
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
    }
    r = em_get(url, params=params, timeout=timeout)
    return r.json()


def em_push2his_fund_flow(secid: str, limit: int = 20, timeout: int = 10) -> dict:
    url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
    params = {
        "secid": secid,
        "lmt": limit,
        "klt": 101,
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
    }
    r = em_get(url, params=params, timeout=timeout)
    return r.json()
