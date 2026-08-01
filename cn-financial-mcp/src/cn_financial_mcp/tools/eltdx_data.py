"""
eltdx_data.py - eltdx 通达信协议独有数据源
============================================
基于 eltdx 1.0.2 包封装的 5 个 MCP 工具。

独有数据（AKShare 没有）：
  - 集合竞价（auction_series）
  - 逐笔成交（history / today）
  - F10 资料（company_profile / hot_topics / finance_diagnosis）
  - 分时数据（today / history）
  - K线数据（get / all）

代码归属说明：
  eltdx 是 https://github.com/electkismet/eltdx/ 的开源项目（pip 包）。
  本文件只通过 import 调用其公开 API，不复制/修改其源码。
  eltdx 版权声明保留在 pip 安装包的 LICENSE 中。
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import threading
from typing import Any, Optional

logger = logging.getLogger("cn-financial-mcp.eltdx")

# Hub src path for astock_signals imports (TickStore)
_HUB_SRC = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "src")
)
if _HUB_SRC not in sys.path:
    sys.path.insert(0, _HUB_SRC)

# TickStore SQLite DB path: <project_root>/data/tick_store.db
_PROJECT_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
)
_TICK_DB_PATH = os.path.join(_PROJECT_ROOT, "data", "tick_store.db")

_tick_store_instance: Optional[Any] = None
_tick_store_lock = threading.Lock()


def _get_tick_store():
    """获取 TickStore 单例（DB 路径: <project_root>/data/tick_store.db）。

    不可用时返回 None（不影响工具主流程）。
    """
    global _tick_store_instance
    if _tick_store_instance is not None:
        return _tick_store_instance
    with _tick_store_lock:
        if _tick_store_instance is None:
            try:
                from astock_signals.tick_store import TickStore
                os.makedirs(os.path.dirname(_TICK_DB_PATH), exist_ok=True)
                _tick_store_instance = TickStore(_TICK_DB_PATH)
                logger.info("TickStore initialized at %s", _TICK_DB_PATH)
            except Exception as e:
                logger.warning("TickStore init failed: %s", e)
                return None
    return _tick_store_instance


# ============================================================
# 客户端管理
# ============================================================

_client: Optional[Any] = None
_client_lock = False


def _get_client():
    """
    获取/创建 eltdx TdxClient 单例。

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


# 进程退出时清理连接
import atexit
atexit.register(_shutdown_client)


def _ok(payload: Any) -> str:
    return json.dumps({"status": "success", "data": payload}, ensure_ascii=False, default=str)


def _err(message: str) -> str:
    return json.dumps({"status": "error", "error": message}, ensure_ascii=False)


def _no_data(reason: str = "no data") -> str:
    return json.dumps({"status": "no_data", "message": reason}, ensure_ascii=False)


def _normalize_code(code: str) -> str:
    """
    把 6 位代码或带前缀代码统一成 eltdx 期望的格式。
    eltdx 的 TdxClient 通常接受 'sz000001' / 'sh600000' 或 6 位纯代码，
    这里的 tools 接受 6 位代码即可。
    """
    code = code.strip().lower()
    if code.startswith(("sz", "sh", "bj")):
        return code
    if len(code) == 6 and code.isdigit():
        # 默认按代码首位分配市场（6=沪，0/3=深，8/4=北）
        if code.startswith(("60", "68", "90", "11", "13")):
            return "sh" + code
        if code.startswith(("00", "30", "20")):
            return "sz" + code
        if code.startswith(("8", "43", "92")):
            return "bj" + code
    return code


# ============================================================
# MCP 工具注册
# ============================================================

def register(mcp):
    """Register eltdx-specific tools with the MCP server."""

    @mcp.tool()
    async def eltdx_get_auction(code: str) -> str:
        """
        获取股票集合竞价数据（eltdx 独有，AKShare 无此功能）。

        集合竞价发生在开盘前 9:15-9:25，用于确定开盘价。
        返回每 3 秒一个价格点的撮合量、未匹配量。

        Args:
            code: 股票代码，如 "000001"（平安银行）、"600519"（贵州茅台）
        """
        client = _get_client()
        if client is None:
            return _err("eltdx client not available")
        try:
            start = time.time()
            norm_code = _normalize_code(code)
            result = client.auctions.series(norm_code)
            latency_ms = round((time.time() - start) * 1000, 1)

            if result is None:
                return _no_data("auction series is empty")

            points = getattr(result, "points", None) or []
            if not points:
                return _no_data("no auction points")

            return _ok({
                "code": norm_code,
                "latency_ms": latency_ms,
                "point_count": len(points),
                "points": [
                    {
                        "time": getattr(p, "time_label", None) or getattr(p, "time", None),
                        "price": getattr(p, "price", None),
                        "matched_volume": getattr(p, "matched_volume", None),
                        "unmatched_volume": getattr(p, "unmatched_volume", None),
                    }
                    for p in points
                ],
            })
        except Exception as e:
            logger.exception("eltdx_get_auction failed")
            return _err(f"auction query failed: {e}")

    @mcp.tool()
    async def eltdx_get_ticks(code: str, trading_date: str, count: int = 2000) -> str:
        """
        获取股票逐笔成交数据（eltdx 独有，AKShare 无此功能）。

        包含每笔成交的时间、价格、数量、买卖方向。

        Args:
            code: 股票代码，如 "000001"
            trading_date: 交易日期，格式 "20260617" 或 "2026-06-17"
            count: 返回笔数（默认 2000）
        """
        client = _get_client()
        if client is None:
            return _err("eltdx client not available")
        try:
            start = time.time()
            norm_code = _normalize_code(code)
            norm_date = trading_date.replace("-", "").replace("/", "")

            # 6位纯代码用于 TickStore 存储
            tick_code = norm_code
            if tick_code.startswith(("sh", "sz", "bj")):
                tick_code = tick_code[2:]

            # 缓存优先：同一天同一股票从 TickStore 读取
            store = _get_tick_store()
            if store is not None:
                try:
                    cached_df = store.load_tick(tick_code, norm_date)
                    if cached_df is not None and not cached_df.empty:
                        cached = cached_df.tail(count) if len(cached_df) > count else cached_df
                        ticks_out = [
                            {
                                "time": row.get("time"),
                                "price": row.get("price"),
                                "volume": row.get("volume"),
                                "amount": row.get("amount"),
                                "bs": row.get("direction") if row.get("direction") in ("buy", "sell") else "buy",
                            }
                            for _, row in cached.iterrows()
                        ]
                        latency_ms = round((time.time() - start) * 1000, 1)
                        return _ok({
                            "code": norm_code,
                            "date": norm_date,
                            "latency_ms": latency_ms,
                            "tick_count": len(ticks_out),
                            "ticks": ticks_out,
                        })
                except Exception as cache_err:
                    logger.debug("TickStore cache read failed: %s", cache_err)

            result = client.trades.history(norm_code, norm_date, count=count)
            latency_ms = round((time.time() - start) * 1000, 1)

            ticks = getattr(result, "ticks", None) or []
            if not ticks:
                return _no_data(f"no ticks on {norm_date}")

            ticks_out = [
                {
                    "time": getattr(t, "time", None),
                    "price": getattr(t, "price", None),
                    "volume": getattr(t, "volume", None),
                    "amount": getattr(t, "amount", None),
                    "bs": "buy" if getattr(t, "buy_or_sell", None) in (0, "0", "buy") else "sell",
                }
                for t in ticks
            ]

            # 异步写入 TickStore（不阻塞返回，失败仅记录日志）
            if store is not None:
                _rows = [
                    {
                        "time": t_obj.get("time", ""),
                        "price": t_obj.get("price"),
                        "volume": t_obj.get("volume"),
                        "amount": t_obj.get("amount"),
                        "direction": t_obj.get("bs", ""),
                    }
                    for t_obj in ticks_out
                ]
                _store = store
                _tc = tick_code
                _nd = norm_date

                def _save_to_store():
                    try:
                        _store.save_tick(_tc, _nd, _rows)
                    except Exception as save_err:
                        logger.warning("TickStore async save failed: %s", save_err)

                threading.Thread(target=_save_to_store, daemon=True).start()

            return _ok({
                "code": norm_code,
                "date": norm_date,
                "latency_ms": latency_ms,
                "tick_count": len(ticks_out),
                "ticks": ticks_out,
            })
        except Exception as e:
            logger.exception("eltdx_get_ticks failed")
            return _err(f"ticks query failed: {e}")

    @mcp.tool()
    async def eltdx_get_f10(code: str) -> str:
        """
        获取股票 F10 资料（eltdx 独有，AKShare 无此功能）。

        包含公司概况、热点题材、财务诊断评分。

        Args:
            code: 股票代码，如 "000001"（6 位）
        """
        client = _get_client()
        if client is None:
            return _err("eltdx client not available")
        try:
            start = time.time()
            norm_code = code.strip()
            if norm_code.startswith(("sz", "sh", "bj")):
                norm_code = norm_code[2:]

            profile_resp = client.f10.company_profile(norm_code)
            topics_resp = client.f10.hot_topics(norm_code)
            diag_resp = client.f10.finance_diagnosis(norm_code)
            latency_ms = round((time.time() - start) * 1000, 1)

            def _rows(resp):
                if resp is None or not getattr(resp, "ok", False):
                    return []
                table = resp.first_table
                return list(table.rows) if table else []

            profile_rows = _rows(profile_resp)
            topics_rows = _rows(topics_resp)
            diag_rows = _rows(diag_resp)

            profile = profile_rows[0] if profile_rows else {}
            topics = topics_rows[:5]
            diagnosis = diag_rows[0] if diag_rows else {}

            return _ok({
                "code": norm_code,
                "latency_ms": latency_ms,
                "profile": profile,
                "hot_topics": topics,
                "finance_diagnosis": diagnosis,
            })
        except Exception as e:
            logger.exception("eltdx_get_f10 failed")
            return _err(f"f10 query failed: {e}")

    @mcp.tool()
    async def eltdx_get_minutes(code: str) -> str:
        """
        获取股票当日分时数据（eltdx 数据源，与 AKShare 互补）。

        1 分钟一根 K 线的价量数据。

        Args:
            code: 股票代码，如 "000001"
        """
        client = _get_client()
        if client is None:
            return _err("eltdx client not available")
        try:
            start = time.time()
            norm_code = _normalize_code(code)
            result = client.minutes.today(norm_code)
            latency_ms = round((time.time() - start) * 1000, 1)

            points = getattr(result, "points", None) or []
            if not points:
                return _no_data("no minute points")

            return _ok({
                "code": norm_code,
                "latency_ms": latency_ms,
                "point_count": len(points),
                "points": [
                    {
                        "time": getattr(p, "time_label", None) or getattr(p, "time", None),
                        "price": getattr(p, "price", None),
                        "avg_price": getattr(p, "avg_price", None),
                        "volume": getattr(p, "volume", None),
                    }
                    for p in points
                ],
            })
        except Exception as e:
            logger.exception("eltdx_get_minutes failed")
            return _err(f"minutes query failed: {e}")

    @mcp.tool()
    async def eltdx_get_kline(code: str, period: str = "day", count: int = 100) -> str:
        """
        获取股票 K 线数据（eltdx 数据源，与 AKShare 互补）。

        支持日/周/月/分钟等多种周期。

        Args:
            code: 股票代码，如 "000001"
            period: 周期，"day" / "week" / "month" / "5m" / "15m" / "30m" / "60m"
            count: 返回 K 线根数（默认 100）
        """
        client = _get_client()
        if client is None:
            return _err("eltdx client not available")
        try:
            start = time.time()
            norm_code = _normalize_code(code)
            result = client.bars.get(norm_code, period=period, count=count)
            latency_ms = round((time.time() - start) * 1000, 1)

            bars = getattr(result, "bars", None) or []
            if not bars:
                return _no_data(f"no kline bars for period={period}")

            return _ok({
                "code": norm_code,
                "period": period,
                "latency_ms": latency_ms,
                "bar_count": len(bars),
                "bars": [
                    {
                        "date": getattr(b, "date", None) or getattr(b, "datetime", None),
                        "open": getattr(b, "open", None),
                        "high": getattr(b, "high", None),
                        "low": getattr(b, "low", None),
                        "close": getattr(b, "close", None),
                        "volume": getattr(b, "volume", None),
                        "amount": getattr(b, "amount", None),
                    }
                    for b in bars
                ],
            })
        except Exception as e:
            logger.exception("eltdx_get_kline failed")
            return _err(f"kline query failed: {e}")
