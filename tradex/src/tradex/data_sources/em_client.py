"""东财统一请求客户端 —— 限流防封 + slist 板块归属。

借鉴 a-stock-data 的 em_get 防封机制：
  - 串行限流：最小间隔 ≥1s + 随机抖动（东财风控：>5次/秒触发封禁）
  - 会话复用 + 默认浏览器 UA + Referer
  - 所有 eastmoney.com 接口都应走 em_get，避免高频被封 IP。

东财风控阈值（社区实测）：
  - 每秒 >5 次 / 并发 ≥10 / 5分钟 ≥300 次 → 触发封禁
"""
from __future__ import annotations

import random
import threading
import time

import pandas as pd
from curl_cffi import requests as _rq

logger = __import__("logging").getLogger("tradex.em")

# 东财风控：最小请求间隔（秒）
EM_MIN_INTERVAL = 1.0

# v3.3.9+：限流时间戳加锁保护——多线程同时穿透间隔会导致并发请求数超风控阈值封 IP。
_em_last_call = [0.0]
_em_throttle_lock = threading.Lock()
_EM_SESSION = _rq.Session()

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36")
_REFERER = "https://quote.eastmoney.com/"


def em_get(url: str, params: dict | None = None, headers: dict | None = None,
           timeout: int = 15, **kwargs):
    """东财统一请求入口：自动节流 + 复用 session + 默认 UA。

    节流检查与时间戳更新在同一把锁内完成（含 sleep），
    保证任意时刻只有一个请求在"检查-等待-发出"临界区，
    多线程并发调用时严格维持 ≥EM_MIN_INTERVAL 的实际间隔。
    """
    with _em_throttle_lock:
        wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
        if wait > 0:
            time.sleep(wait + random.uniform(0.1, 0.5))
        h = {"User-Agent": _UA, "Referer": _REFERER}
        if headers:
            h.update(headers)
        try:
            resp = _EM_SESSION.get(url, params=params, headers=h, timeout=timeout,
                                   impersonate="chrome120", **kwargs)
        finally:
            _em_last_call[0] = time.time()
    return resp


def fetch_stock_boards(code: str, **kwargs) -> pd.DataFrame:
    """个股所属板块/概念归属（东财 slist，一次请求拿全行业/概念/地域 + 龙头股）。

    Returns:
        DataFrame columns: 板块名称 / 板块代码(BK) / 涨跌幅 / 领涨股票
    """
    code = str(code).split(".")[0].split("_")[0]  # 归一纯 6 位
    market_code = 1 if code.startswith("6") else 0
    params = {
        "fltt": "2", "invt": "2",
        "secid": f"{market_code}.{code}",
        "spt": "3", "pi": "0", "pz": "200", "po": "1",
        "fields": "f12,f14,f3,f128",
    }
    r = em_get("https://push2.eastmoney.com/api/qt/slist/get", params=params, timeout=15)
    r.raise_for_status()
    diff = (r.json().get("data") or {}).get("diff") or {}
    items = diff.values() if isinstance(diff, dict) else diff
    rows = []
    for it in items:
        rows.append({
            "板块名称": it.get("f14", ""),
            "板块代码": it.get("f12", ""),
            "涨跌幅": it.get("f3", ""),
            "领涨股票": it.get("f128", ""),
        })
    return pd.DataFrame(rows)
