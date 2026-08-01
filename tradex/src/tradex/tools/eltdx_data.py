"""
eltdx_data.py - eltdx 通达信协议独有数据源
============================================
基于 eltdx 1.2.0 包封装的 5 个 MCP 工具。

独有数据（AKShare 没有）：
  - 集合竞价（auction_series）
  - 逐笔成交（history / today）
  - F10 资料（company_profile / hot_topics / finance_diagnosis）
  - 分时数据（today / history）
  - K线数据（get / all）

v3.1.0 起：所有数据获取通过 SmartRouter.route() 路由，不再直接 import eltdx。
eltdx 客户端管理已迁移至 data_sources/eltdx_fetchers.py。

代码归属说明：
  eltdx 是 https://github.com/electrkismet/eltdx/ 的开源项目（pip 包）。
  本文件只通过 SmartRouter 调用其公开 API，不复制/修改其源码。
  eltdx 版权声明保留在 pip 安装包的 LICENSE 中。
"""

from __future__ import annotations

import json
import logging
import os
import time
import threading
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from ..data_sources import get_router

logger = logging.getLogger("tradex.eltdx")

_router = get_router()


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


def _ok(payload: Any) -> str:
    return json.dumps({"status": "success", "data": payload}, ensure_ascii=False, default=str)


def _err(message: str) -> str:
    return json.dumps({"status": "error", "error": message}, ensure_ascii=False)


def _no_data(reason: str = "no data") -> str:
    return json.dumps({"status": "no_data", "message": reason}, ensure_ascii=False)


def _strip_prefix(code: str) -> str:
    """去除 sh/sz/bj 前缀，返回 6 位纯代码。"""
    code = code.strip().lower()
    if code.startswith(("sh", "sz", "bj")):
        return code[2:]
    return code


# ============================================================
# MCP 工具注册
# ============================================================

def register(mcp: FastMCP):
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
        try:
            start = time.time()
            result, _src = _router.route("call_auction", code=code)
            latency_ms = round((time.time() - start) * 1000, 1)

            points = getattr(result, "points", None) or []
            if not points:
                return _no_data("no auction points")

            return _ok({
                "code": _strip_prefix(code),
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
        try:
            start = time.time()
            tick_code = _strip_prefix(code)
            norm_date = trading_date.replace("-", "").replace("/", "")

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
                            "code": tick_code,
                            "date": norm_date,
                            "latency_ms": latency_ms,
                            "tick_count": len(ticks_out),
                            "ticks": ticks_out,
                        })
                except Exception as cache_err:
                    logger.debug("TickStore cache read failed: %s", cache_err)

            # SmartRouter 路由获取逐笔数据（eltdx 独占源）
            result, _src = _router.route(
                "tick_data", code=code, trading_date=trading_date, count=count
            )
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
                "code": tick_code,
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
        try:
            start = time.time()
            result, _src = _router.route("f10_profile", code=code)
            latency_ms = round((time.time() - start) * 1000, 1)

            profile_resp = result.get("profile_resp")
            topics_resp = result.get("topics_resp")
            diag_resp = result.get("diag_resp")
            norm_code = result.get("code", _strip_prefix(code))

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
        获取股票当日分时数据（SmartRouter 路由，优先 eltdx 数据源）。

        1 分钟一根 K 线的价量数据。

        Args:
            code: 股票代码，如 "000001"
        """
        try:
            start = time.time()
            df, _src = _router.route("minute_data", code=code)
            latency_ms = round((time.time() - start) * 1000, 1)

            if df is None or df.empty:
                return _no_data("no minute points")

            points = []
            for _, row in df.iterrows():
                time_val = str(row.get("时间", row.get("time", "")))
                price_val = float(row.get("价格", row.get("收盘", row.get("close", 0))) or 0)
                avg_val = float(row.get("均价", row.get("avg_price", 0)) or 0)
                vol_val = float(row.get("成交量", row.get("volume", 0)) or 0)
                if time_val:
                    points.append({
                        "time": time_val,
                        "price": price_val,
                        "avg_price": avg_val,
                        "volume": vol_val,
                    })

            if not points:
                return _no_data("no minute points")

            return _ok({
                "code": _strip_prefix(code),
                "latency_ms": latency_ms,
                "point_count": len(points),
                "points": points,
            })
        except Exception as e:
            logger.exception("eltdx_get_minutes failed")
            return _err(f"minutes query failed: {e}")

    @mcp.tool()
    async def eltdx_get_kline(code: str, period: str = "day", count: int = 100) -> str:
        """
        获取股票 K 线数据（SmartRouter 路由，优先 eltdx 数据源）。

        支持日/周/月/分钟等多种周期。

        Args:
            code: 股票代码，如 "000001"
            period: 周期，"day" / "week" / "month" / "5m" / "15m" / "30m" / "60m"
            count: 返回 K 线根数（默认 100）
        """
        try:
            start = time.time()
            df, _src = _router.route(
                "historical_kline", code=code, period=period, count=count
            )
            latency_ms = round((time.time() - start) * 1000, 1)

            if df is None or df.empty:
                return _no_data(f"no kline bars for period={period}")

            bars = []
            for _, row in df.iterrows():
                bars.append({
                    "date": str(row.get("日期", row.get("date", ""))),
                    "open": float(row.get("开盘", row.get("open", 0)) or 0),
                    "high": float(row.get("最高", row.get("high", 0)) or 0),
                    "low": float(row.get("最低", row.get("low", 0)) or 0),
                    "close": float(row.get("收盘", row.get("close", 0)) or 0),
                    "volume": float(row.get("成交量", row.get("volume", 0)) or 0),
                    "amount": float(row.get("成交额", row.get("amount", 0)) or 0),
                })

            if not bars:
                return _no_data(f"no kline bars for period={period}")

            return _ok({
                "code": _strip_prefix(code),
                "period": period,
                "latency_ms": latency_ms,
                "bar_count": len(bars),
                "bars": bars,
            })
        except Exception as e:
            logger.exception("eltdx_get_kline failed")
            return _err(f"kline query failed: {e}")
