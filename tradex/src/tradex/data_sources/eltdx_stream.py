"""
eltdx 常驻推送连接管理器（交易看板 S 级底座）。

与 eltdx_fetchers.py 的短连接按需查询不同，本模块维护一个长期保持
连接的 TdxClient，用于准实时的五档盘口 / 行情增量刷新。

机制（基于 eltdx 2.0.2 实测结论）：
- eltdx 的 PooledSocketTransport 内部 Actor 线程已托管：读 socket、
  心跳保活（heartbeat_interval）、推送帧入队（PushBuffer）。
- 免费行情站**不主动推送**（drain_pushes 实测 0 帧）；「增量推送」
  实际通过 refresh_stream(0x0547) 的游标机制实现：
      首次 cursor=0 拿全量快照；
      之后用返回记录的 update_time_raw 作游标再次 refresh，
      服务端只返回有变化的记录（0 条 = 无变化）。
- 因此本管理器核心 = 常驻连接 + 订阅游标维护 + 增量轮询。

v3.3.7: 新增，交易看板 S 级底座。
"""

from __future__ import annotations

import logging
import os
import threading
import atexit
from typing import Any, Optional

logger = logging.getLogger("tradex.eltdx_stream")


_PROXY_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")


def _without_proxy_env() -> dict:
    """临时移除代理环境变量，返回 {key: 原值或 None} 供 _restore_env 恢复。

    仅用于连接建立窗口期（国内通达信行情必须直连）；连接完成后立即恢复，
    避免永久污染进程级代理配置（同进程其他走代理的源不受影响）。
    """
    saved: dict = {}
    for key in _PROXY_KEYS:
        saved[key] = os.environ.pop(key, None)
    return saved


def _restore_env(saved: dict) -> None:
    """恢复 _without_proxy_env 暂存的环境变量原值。"""
    for key, value in saved.items():
        if value is not None:
            os.environ[key] = value


class EltdxStreamManager:
    """常驻推送连接管理器（单例）。

    职责：
    1. 维护长期保持连接的 TdxClient（心跳自动保活）。
    2. 订阅管理：记录已订阅代码及其游标。
    3. 增量轮询：用游标 refresh_stream 拿准实时增量。
    4. 健康状态：连接状态、订阅数、推送缓冲快照。
    """

    def __init__(self, *, pool_size: int = 2, heartbeat_interval: float = 30.0, timeout: float = 8.0):
        self._pool_size = pool_size
        self._heartbeat_interval = heartbeat_interval
        self._timeout = timeout
        self._client: Optional[Any] = None
        self._cursors: dict[str, int] = {}
        self._lock = threading.RLock()
        self._started = False

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def start(self) -> bool:
        """创建并连接常驻 TdxClient。幂等：已启动则直接返回 True。

        连接期间临时清空代理环境变量（行情必须直连），
        连接完成后恢复原值——不永久污染进程级代理配置。
        """
        with self._lock:
            if self._started and self._client is not None:
                return True
            saved_proxy = _without_proxy_env()
            try:
                from eltdx import TdxClient
                self._client = TdxClient.from_hosts(
                    timeout=self._timeout,
                    pool_size=self._pool_size,
                    heartbeat_interval=self._heartbeat_interval,
                )
                self._client.connect()
                self._started = True
                logger.info("eltdx stream client connected (pool=%d)", self._pool_size)
                return True
            except Exception as exc:  # noqa: BLE001
                logger.error("eltdx stream client start failed: %s", exc)
                self._client = None
                self._started = False
                return False
            finally:
                _restore_env(saved_proxy)

    def stop(self) -> None:
        """关闭常驻连接并清空游标。"""
        with self._lock:
            client, self._client = self._client, None
            self._started = False
            self._cursors.clear()
        if client is not None:
            try:
                client.close()
            except Exception:  # noqa: BLE001
                pass
            logger.info("eltdx stream client closed")

    # ------------------------------------------------------------------
    # 订阅与增量轮询
    # ------------------------------------------------------------------
    def subscribe(self, codes: list[str], *, snapshot: bool = True) -> dict:
        """订阅一组代码。返回 {code: 快照记录 dict 或 None}。

        首次订阅会做一次全量快照（cursor=0），并把游标初始化为
        返回记录的 update_time_raw，供后续增量轮询使用。
        """
        with self._lock:
            if not self._ensure_started():
                raise RuntimeError("eltdx stream client not available")
            client = self._client
            norm_codes = [_normalize_code(c) for c in codes]
            # 初始化游标（已订阅的保留，新的从 0 开始）
            for code in norm_codes:
                self._cursors.setdefault(code, 0)
            cursors = {c: self._cursors[c] for c in norm_codes}

        result: dict = {}
        if snapshot:
            try:
                page = client.quotes.refresh(norm_codes, cursors={})
                records = _records_map(page)
                for code in norm_codes:
                    rec = records.get(code)
                    if rec is not None:
                        result[code] = _record_to_dict(rec)
                        self._update_cursor(code, rec)
                    else:
                        result[code] = None
            except Exception as exc:  # noqa: BLE001
                logger.error("eltdx stream subscribe snapshot failed: %s", exc)
                for code in norm_codes:
                    result[code] = None
        return result

    def poll(self, codes: Optional[list[str]] = None) -> dict:
        """增量轮询一次，返回 {code: 最新记录 dict}（仅含变化的代码）。

        codes 为 None 时轮询所有已订阅代码。返回空 dict = 无变化。
        """
        with self._lock:
            if not self._ensure_started():
                raise RuntimeError("eltdx stream client not available")
            client = self._client
            target = [_normalize_code(c) for c in codes] if codes else list(self._cursors.keys())
            if not target:
                return {}
            cursors = {c: self._cursors.get(c, 0) for c in target}

        try:
            page = client.quotes.refresh(target, cursors=cursors)
        except Exception as exc:  # noqa: BLE001
            logger.error("eltdx stream poll failed: %s", exc)
            return {}

        records = _records_map(page)
        changed: dict = {}
        for code in target:
            rec = records.get(code)
            if rec is not None:
                changed[code] = _record_to_dict(rec)
                self._update_cursor(code, rec)
        return changed

    def snapshot(self, codes: list[str]) -> dict:
        """全量五档快照（cursor=0），不更新游标。返回 {code: dict}。"""
        with self._lock:
            if not self._ensure_started():
                raise RuntimeError("eltdx stream client not available")
            client = self._client
            norm_codes = [_normalize_code(c) for c in codes]
        try:
            page = client.quotes.refresh(norm_codes, cursors={})
        except Exception as exc:  # noqa: BLE001
            logger.error("eltdx stream snapshot failed: %s", exc)
            return {}
        records = _records_map(page)
        return {c: _record_to_dict(records[c]) for c in norm_codes if c in records}

    def unsubscribe(self, codes: list[str]) -> None:
        """退订代码，清除游标。"""
        with self._lock:
            for code in codes:
                self._cursors.pop(_normalize_code(code), None)

    # ------------------------------------------------------------------
    # 健康状态
    # ------------------------------------------------------------------
    def health(self) -> dict:
        """返回连接状态、订阅数、推送缓冲快照。"""
        with self._lock:
            started = self._started and self._client is not None
            subscribed = len(self._cursors)
            client = self._client
            push = {}
            if client is not None:
                try:
                    snap = client.transport.push_snapshot()
                    if snap is not None:
                        push = {
                            "frame_count": snap.frame_count,
                            "byte_count": snap.byte_count,
                            "dropped_total": snap.dropped_total,
                            "closed": snap.closed,
                        }
                except Exception:  # noqa: BLE001
                    pass
            return {
                "started": started,
                "subscribed_count": subscribed,
                "push_buffer": push,
            }

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _ensure_started(self) -> bool:
        if self._started and self._client is not None:
            return True
        return self.start()

    def _update_cursor(self, code: str, rec: Any) -> None:
        new_cursor = getattr(rec, "update_time_raw", None)
        if new_cursor is not None:
            with self._lock:
                self._cursors[code] = int(new_cursor)


# ============================================================
# 单例 + 生命周期
# ============================================================

_stream_manager: Optional[EltdxStreamManager] = None
_stream_lock = threading.Lock()


def get_stream_manager() -> EltdxStreamManager:
    """获取 EltdxStreamManager 单例（不自动连接，需显式 start）。"""
    global _stream_manager
    if _stream_manager is None:
        with _stream_lock:
            if _stream_manager is None:
                _stream_manager = EltdxStreamManager()
    return _stream_manager


def _shutdown_stream() -> None:
    global _stream_manager
    if _stream_manager is not None:
        try:
            _stream_manager.stop()
        except Exception:  # noqa: BLE001
            pass
        _stream_manager = None


atexit.register(_shutdown_stream)


# ============================================================
# 工具函数
# ============================================================

def _normalize_code(code: str) -> str:
    """6 位代码 → sh/sz/bj 前缀格式。"""
    code = code.strip().lower()
    if code.startswith(("sh", "sz", "bj")):
        return code
    if len(code) == 6 and code.isdigit():
        if code.startswith(("60", "68", "90", "11", "13")):
            return "sh" + code
        if code.startswith(("00", "30", "20")):
            return "sz" + code
        if code.startswith(("8", "43", "92")):
            return "bj" + code
    return code


def _records_map(page: Any) -> dict:
    """把 refresh 返回的 QuoteRefreshPage 转成 {full_code: record}。"""
    records = getattr(page, "records", None) or ()
    mapping: dict = {}
    for rec in records:
        code = getattr(rec, "full_code", None)
        if code is None:
            exchange = getattr(rec, "exchange", "")
            number = getattr(rec, "code", "")
            code = f"{exchange}{number}" if exchange and number else None
        if code is not None:
            mapping[code] = rec
    return mapping


def _record_to_dict(rec: Any) -> dict:
    """把 QuoteRefreshRecord 转成 dict（含五档盘口）。"""
    buy_levels = [
        {"price": lv.price, "volume": lv.volume}
        for lv in (getattr(rec, "buy_levels", None) or ())
    ]
    sell_levels = [
        {"price": lv.price, "volume": lv.volume}
        for lv in (getattr(rec, "sell_levels", None) or ())
    ]
    return {
        "code": getattr(rec, "full_code", None) or getattr(rec, "code", None),
        "last_price": getattr(rec, "last_price", None),
        "pre_close": getattr(rec, "last_close_price", None),
        "open": getattr(rec, "open_price", None),
        "high": getattr(rec, "high_price", None),
        "low": getattr(rec, "low_price", None),
        "total_hand": getattr(rec, "total_hand", None),
        "current_hand": getattr(rec, "current_hand", None),
        "amount": getattr(rec, "amount", None),
        "inside_dish": getattr(rec, "inside_dish", None),
        "outer_disc": getattr(rec, "outer_disc", None),
        "open_amount_yuan": getattr(rec, "open_amount_yuan", None),
        "update_time_raw": getattr(rec, "update_time_raw", None),
        "buy_levels": buy_levels,
        "sell_levels": sell_levels,
    }
