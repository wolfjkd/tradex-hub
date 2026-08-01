"""
Anti-ban rate-limited HTTP client for Eastmoney APIs.

东财系 HTTP 接口（push2 / push2his / datacenter-web / search-api / np-weblist）
有风控：每秒 >5 次 / 单 IP 并发 ≥10 / 1 分钟 ≥200 次 / 5 分钟 ≥300 次 → 临时封 IP。

所有 eastmoney.com 请求一律走此入口：串行限流（最小间隔 + 随机抖动）+ 复用 Keep-Alive 会话。

TradingAgents-astock 移植模块。V0.1。
"""

from __future__ import annotations

import os
import re
import random
import time
import logging
import threading

import requests as _requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_EM_SESSION: _requests.Session | None = None
_EM_MIN_INTERVAL: float = float(os.environ.get("EM_MIN_INTERVAL", "1.0"))
_em_last_call: list[float] = [0.0]  # mutable for inner func access
_lock = threading.Lock()  # 保护 session 初始化和限流逻辑

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

# 6 位纯数字股票代码正则（用于 SQL filter 注入防护）
_CODE_RE = re.compile(r"^\d{6}$")


def _ensure_session() -> _requests.Session:
    """Get or create the shared Eastmoney session (lazy init, thread-safe)."""
    global _EM_SESSION
    if _EM_SESSION is None:
        with _lock:
            if _EM_SESSION is None:  # double-check
                _EM_SESSION = _requests.Session()
                _EM_SESSION.headers.update({"User-Agent": _UA})
    return _EM_SESSION


# ---------------------------------------------------------------------------
# Public API: rate-limited request
# ---------------------------------------------------------------------------


def em_get(
    url: str,
    params: dict | None = None,
    headers: dict | None = None,
    timeout: int = 15,
    **kwargs,
) -> _requests.Response:
    """东财统一请求入口：自动节流 + 复用 session + 默认 UA。

    所有 eastmoney.com 接口都应通过它请求，避免多 Agent 高频拉数据被封 IP。
    串行限流：与上次东财请求间隔 < EM_MIN_INTERVAL 时 sleep 补足 + 0.1~0.5s 随机抖动。
    线程安全：使用锁确保限流计算和时间戳更新是原子操作。

    并发优化：锁内仅计算等待时间并预定时间戳（让后续线程据此排队），
    sleep 在锁外执行，避免高并发时所有线程在锁内排队退化为串行。

    Args:
        url: Full URL to request.
        params: Query parameters dict.
        headers: Optional per-request headers (e.g. Referer/Origin).
        timeout: Request timeout in seconds.
        **kwargs: Passed to session.get().

    Returns:
        requests.Response object.
    """
    # 第一阶段：锁内计算等待时间并预定时间戳（让后续线程据此排队）
    with _lock:
        now = time.time()
        wait = _EM_MIN_INTERVAL - (now - _em_last_call[0])
        if wait < 0:
            wait = 0
        jitter = random.uniform(0.1, 0.5)
        sleep_time = wait + jitter
        # 预定本次请求时刻，后续线程据此排队
        _em_last_call[0] = now + sleep_time

    # 第二阶段：锁外 sleep，不阻塞其他线程计算等待时间
    if sleep_time > 0:
        time.sleep(sleep_time)

    # 第三阶段：执行请求（不持锁，允许并发请求的等待阶段重叠）
    return _ensure_session().get(
        url, params=params, headers=headers, timeout=timeout, **kwargs
    )


def set_min_interval(seconds: float) -> None:
    """Adjust the minimum interval between Eastmoney requests.

    Args:
        seconds: Minimum seconds between requests (default 1.0).
    """
    global _EM_MIN_INTERVAL
    with _lock:
        _EM_MIN_INTERVAL = float(seconds)


def em_reset_session() -> None:
    """Close and recreate the Eastmoney session (e.g. after IP change)."""
    global _EM_SESSION
    with _lock:
        if _EM_SESSION is not None:
            try:
                _EM_SESSION.close()
            except Exception as e:
                logger.debug("em_reset_session close error: %s", e)
            _EM_SESSION = None


# ---------------------------------------------------------------------------
# Input validation helper
# ---------------------------------------------------------------------------


def validate_code(code: str) -> str:
    """校验股票代码格式（纯 6 位数字），防止 SQL 注入。

    Args:
        code: 股票代码

    Returns:
        校验通过的代码

    Raises:
        ValueError: 代码格式不合法
    """
    if not _CODE_RE.match(code):
        raise ValueError(f"Invalid stock code: {code!r} (must be 6 digits)")
    return code


# ---------------------------------------------------------------------------
# Eastmoney Datacenter unified query helper
# ---------------------------------------------------------------------------


def em_datacenter(
    report_name: str,
    columns: str = "ALL",
    filter_str: str = "",
    page_size: int = 50,
    sort_columns: str = "",
    sort_types: str = "-1",
) -> list[dict]:
    """东财数据中心统一查询 — 龙虎榜/解禁 等共用入口。

    Args:
        report_name: Report name, e.g. "RPT_LIFT_STAGE", "RPT_DAILYBILLBOARD_DETAILSNEW".
        columns: Column selection, "ALL" for everything.
        filter_str: Filter expression, e.g. '(SECURITY_CODE="000858")'.
        page_size: Results per page (max 200).
        sort_columns: Column name to sort by.
        sort_types: Sort direction (-1=desc, 1=asc).

    Returns:
        List of dicts, each representing one row.
    """
    params = {
        "reportName": report_name,
        "columns": columns,
        "filter": filter_str,
        "pageNumber": "1",
        "pageSize": str(page_size),
        "sortColumns": sort_columns,
        "sortTypes": sort_types,
        "source": "WEB",
        "client": "WEB",
    }
    r = em_get(_DATACENTER_URL, params=params, timeout=15)

    # 检查 HTTP 状态码，403 时自动 reset session 并重试一次
    if r.status_code == 403:
        logger.warning("em_datacenter got 403, resetting session and retrying...")
        em_reset_session()
        r = em_get(_DATACENTER_URL, params=params, timeout=15)

    r.raise_for_status()

    try:
        d = r.json()
    except ValueError:
        logger.error("em_datacenter: response is not valid JSON (status=%d)", r.status_code)
        return []

    if d.get("result") and d["result"].get("data"):
        return d["result"]["data"]
    return []


# ---------------------------------------------------------------------------
# Convenience: push2 / push2his direct request helpers
# ---------------------------------------------------------------------------


def em_push2(params: dict, timeout: int = 15) -> dict:
    """Query Eastmoney push2 API (realtime market data).

    Args:
        params: Query parameters dict.
        timeout: Request timeout.

    Returns:
        Parsed JSON dict.
    """
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    r = em_get(url, params=params, timeout=timeout)
    return r.json()


def em_push2_fund_flow(secid: str, timeout: int = 10) -> dict:
    """Query Eastmoney push2 fund flow API (minute-level).

    Args:
        secid: Security ID, e.g. "1.600519" or "0.000858".
        timeout: Request timeout.

    Returns:
        Parsed JSON dict with klines data.
    """
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
    """Query Eastmoney push2his fund flow API (daily historical).

    Args:
        secid: Security ID.
        limit: Number of trading days.
        timeout: Request timeout.

    Returns:
        Parsed JSON dict with daily klines.
    """
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
