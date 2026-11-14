"""大智慧365 本地 WS 行情 fetcher（本机 127.0.0.1 回环，零外网依赖）。

协议来源：dzh-queue 项目破译的 DZH365 本地 WS（2026-10-08 首破，2026-10-09/11
盘中复核；2026-11-14 新增全球指数 obj 格式破译——IX*.index，来源：客户端
httproot/stock/365complex 前端代码表）。

  - WS ws://127.0.0.1:30718/ 由 DZH365 主进程 dzh2.exe 提供：
    **客户端必须运行且已登录**，未运行时连接失败（调用方拿诚实空态）
  - 握手必须带 Origin: http://127.0.0.1:30719，否则服务端静默丢弃
  - 全球指数 obj = IX*.index：IXKS11.index=韩国KOSPI、IXDJIA.index=道琼斯、
    IXNDX.index=纳斯达克综合、IXFTSE.index=英国富时、IXGDAXI.index=德国等
    （恒生/恒生科技不在 IX 市场，走腾讯 hk 前缀源）

设计（本机回环，无外网、无代理、无东财限流问题）：
  - 连接复用：dzh-queue 实测新连接首次 ~3s、复用 ~1ms；30s 防半开重建
  - 失败负缓存 60s：DZH365 未运行时避免调用方高频空转
  - dyna 通道对 A 股指数与全球指数均可用（SH000001/IXKS11 双对照实测）

数据口径（IXKS11 实测 2026-11-14）：
  new=5290.529785 与东财全球指数表交叉验证一致；amount=0（全球指数无成交额）；
  pct 由 new/lastclose 计算（-0.98% 与东财一致）。
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

logger = logging.getLogger("tradex.dzh")

WS_URL = "ws://127.0.0.1:30718/"
# 实测：握手不带 Origin 会被服务端静默丢弃
ORIGIN = "http://127.0.0.1:30719"

_CONN_REUSE = 30.0   # 连接最长复用秒数（防半开连接）
_FAIL_TTL = 60.0     # 失败负缓存（DZH365 未运行时静默期）

_lock = threading.Lock()
_ws: Any = None
_ws_deadline = 0.0
_fail_until = 0.0


def _get_ws():
    """取复用连接；过期/半开时重建。失败抛异常（由调用方负缓存兜底）。"""
    global _ws, _ws_deadline
    with _lock:
        now = time.time()
        if _ws is not None and now < _ws_deadline:
            return _ws
        try:
            if _ws is not None:
                try:
                    _ws.close()
                except Exception:  # noqa: BLE001
                    pass
                _ws = None
            # 懒导入：websocket-client（pyproject 主依赖已声明）
            from websocket import create_connection

            _ws = create_connection(WS_URL, origin=ORIGIN, timeout=5)
            _ws_deadline = now + _CONN_REUSE
            return _ws
        except Exception:
            _ws = None
            raise


def _send_recv(ws: Any, query: str, to: float = 8.0) -> dict[str, Any]:
    """一问一答（服务端对单次 subscribe 回一帧 JSON）。"""
    ws.send(query)
    deadline = time.time() + to
    while True:
        remain = deadline - time.time()
        if remain <= 0:
            raise TimeoutError("接收超时")
        ws.settimeout(remain)
        msg = ws.recv()
        if not msg:
            continue
        return json.loads(msg)


def _parse_dyna(head: list, row: list) -> dict[str, Any]:
    """dyna 行（head/row 按位 zip）→ 标准行情 dict。纯函数，便于单测。

    字段位置（IXKS11/SH000001 实测）：3=现价(new)前是 4=昨收/5=开/6=高/7=低
    ——准确序：head.index('new')/'lastclose'/'amount'/'time'，不做硬编码位次。
    """
    d = dict(zip(head, row))

    def _f(key: str) -> float | None:
        v = d.get(key)
        try:
            return float(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None

    point = _f("new")
    lastclose = _f("lastclose")
    pct = None
    if point is not None and lastclose:
        pct = round((point - lastclose) / lastclose * 100, 2)
    return {
        "obj": d.get("obj"),
        "time": d.get("time"),
        "point": point,
        "lastclose": lastclose,
        "pct": pct,
        "open": _f("open"),
        "high": _f("high"),
        "low": _f("low"),
        "amount": _f("amount") or 0.0,  # 全球指数该字段为 0（东财表亦无）
    }


def fetch_dzh_index_quote(obj: str, **kwargs) -> dict[str, Any]:
    """大智慧365 本地行情（dyna 通道）。

    Args:
        obj: 带市场前缀的 obj，如 `SH000001`（A 股指数）、
             `IXKS11.index`（韩国KOSPI）——全球指数市场为 IX*.index。

    Returns:
        {obj, time, point, lastclose, pct, open, high, low, amount}；
        DZH365 未运行/连接失败时返回 {}（诚实空态，调用方负缓存兜底）。
    """
    global _fail_until
    now = time.time()
    if now < _fail_until:
        return {}  # 失败冷却期内不打本地 WS（DZH365 未运行场景）
    query = f"service=quote&type=dyna&where=obj={obj}&response_times=1&response_mode=0"
    for attempt in (1, 2):  # 一次重试：半开连接重建后再试
        try:
            resp = _send_recv(_get_ws(), query, 8.0)
            head = resp.get("head") or []
            datas = resp.get("datas") or []
            if not head or not datas:
                logger.debug("dzh dyna 空响应: obj=%s", obj)
                return {}
            row = datas[0][0] if isinstance(datas[0], list) and datas[0] else None
            if row is None:
                return {}
            return _parse_dyna(head, row)
        except Exception as e:  # noqa: BLE001 - 连接类失败：重建重试一次
            logger.debug("dzh dyna 尝试 %s 失败: %s", attempt, e)
            global _ws, _ws_deadline
            with _lock:
                try:
                    if _ws is not None:
                        _ws.close()
                except Exception:  # noqa: BLE001
                    pass
                _ws = None
                _ws_deadline = 0.0
    # 连续失败：进入冷却（DZH365 未运行时的静默期）
    _fail_until = time.time() + _FAIL_TTL
    return {}
