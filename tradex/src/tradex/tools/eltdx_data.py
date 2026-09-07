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
from ..data_sources.eltdx_stream import get_stream_manager

logger = logging.getLogger("tradex.eltdx")

_router = get_router()


# TickStore SQLite DB path: <project_root>/data/tick_store.db
_PROJECT_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
)
_TICK_DB_PATH = os.path.join(_PROJECT_ROOT, "data", "tick_store.db")

_tick_store_instance: Optional[Any] = None
_tick_store_lock = threading.Lock()


def _normalize_tick_side(side: Any) -> str:
    """归一 eltdx 逐笔方向到统一口径。

    eltdx TradeTick.side 取值: "buy"/"sell"/"neutral"(另 status_N 兜底)。
    统一透传合法值, 其余(缺失/未知/status_N)标 "unknown",
    不再默认 buy/sell 以免污染买卖统计。
    """
    if side in ("buy", "sell", "neutral"):
        return side
    return "unknown"


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


def _normalize_stream_code(code: str) -> str:
    """6 位代码 → sh/sz/bj 前缀格式（与 eltdx_stream 归一化一致）。"""
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
                                # v3.3.9+: 未知/缺失方向不再默认 "buy"(避免卖单误标),
                                # 显式标 "unknown";与实时路径 _normalize_tick_side 口径一致
                                "bs": _normalize_tick_side(row.get("direction")),
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
                    # v3.3.9+ 修复: 此前读不存在的 buy_or_sell 字段(getattr 恒 None)
                    # → 所有逐笔被误标 "sell"。eltdx TradeTick 真实字段是 side:
                    #   "buy" / "sell" / "neutral", 兜底 status_N。此处透传并标 unknown。
                    "bs": _normalize_tick_side(getattr(t, "side", None)),
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

    @mcp.tool()
    async def eltdx_get_depth(code: str) -> str:
        """
        获取股票五档盘口快照（买1-5 / 卖1-5，eltdx 常驻连接）。

        通过 eltdx refresh_stream(0x0547) 拿实时五档盘口，含最新价、
        涨跌、内外盘、买卖五档价量。免费行情站不主动推送，本接口为
        一次性快照（调用即拉取最新）。

        Args:
            code: 股票代码，如 "000001" 或 "sh600170"
        """
        try:
            start = time.time()
            manager = get_stream_manager()
            if not manager.start():
                return _err("eltdx stream client not available")
            snap = manager.snapshot([code])
            latency_ms = round((time.time() - start) * 1000, 1)

            record = snap.get(_normalize_stream_code(code))
            if record is None:
                return _no_data(f"no depth data for {code}")

            return _ok({
                "code": _strip_prefix(code),
                "latency_ms": latency_ms,
                "last_price": record.get("last_price"),
                "pre_close": record.get("pre_close"),
                "open": record.get("open"),
                "high": record.get("high"),
                "low": record.get("low"),
                "total_hand": record.get("total_hand"),
                "amount": record.get("amount"),
                "inside_dish": record.get("inside_dish"),
                "outer_disc": record.get("outer_disc"),
                "buy_levels": record.get("buy_levels"),
                "sell_levels": record.get("sell_levels"),
            })
        except Exception as e:
            logger.exception("eltdx_get_depth failed")
            return _err(f"depth query failed: {e}")

    @mcp.tool()
    async def eltdx_stream_health() -> str:
        """
        查询 eltdx 常驻连接管理器健康状态。

        返回连接是否启动、已订阅代码数、推送缓冲快照（帧数/字节数/丢弃数）。
        用于诊断交易看板推送链路的健康情况。

        Args:
            无参数
        """
        try:
            manager = get_stream_manager()
            health = manager.health()
            return _ok(health)
        except Exception as e:
            logger.exception("eltdx_stream_health failed")
            return _err(f"stream health query failed: {e}")

    @mcp.tool()
    async def eltdx_get_security_codes(market: str = "all", category: str = "") -> str:
        """
        获取全市场证券代码表（eltdx 精确分类，v3.3.7 新增）。

        返回权威证券代码清单，含代码、名称、类别（a_share/etf/index/bond 等）、
        板块（主板/创业板/科创板）。相比行情快照更权威：含停牌股、精确分类。

        Args:
            market: 市场，'sh' / 'sz' / 'bj' / 'all'（默认 all，沪深京三市场）
            category: 类别过滤，如 'a_share'（A股）、'etf'、'index'，空则不过滤
        """
        try:
            start = time.time()
            df, _src = _router.route("security_codes", market=market)
            latency_ms = round((time.time() - start) * 1000, 1)

            if df is None or df.empty:
                return _no_data(f"no securities for market={market}")

            if category:
                df = df[df["类别"] == category]

            items = []
            for _, row in df.iterrows():
                items.append({
                    "code": str(row.get("代码", "")),
                    "name": str(row.get("名称", "")),
                    "category": str(row.get("类别", "")),
                    "board": str(row.get("板块", "")),
                })

            return _ok({
                "market": market,
                "category": category,
                "latency_ms": latency_ms,
                "count": len(items),
                "items": items,
            })
        except Exception as e:
            logger.exception("eltdx_get_security_codes failed")
            return _err(f"security codes query failed: {e}")

    @mcp.tool()
    async def eltdx_get_minute_history(code: str, trading_date: str) -> str:
        """
        获取股票历史分时数据（eltdx 独有，v3.3.7 新增）。

        返回指定交易日的历史分时（约 240 点/日），用于盘后复盘。
        这是 eltdx 独有能力（历史分时 AKShare 需付费）。

        Args:
            code: 股票代码，如 "600170"
            trading_date: 交易日，格式 "20260813" 或 "2026-08-13"
        """
        try:
            start = time.time()
            df, _src = _router.route("minute_history", code=code, trading_date=trading_date)
            latency_ms = round((time.time() - start) * 1000, 1)

            if df is None or df.empty:
                return _no_data(f"no minute history for {code} on {trading_date}")

            points = []
            for _, row in df.iterrows():
                points.append({
                    "time": str(row.get("时间", "")),
                    "price": float(row.get("价格", 0) or 0),
                    "avg_price": float(row.get("均价", 0) or 0),
                    "volume": float(row.get("成交量", 0) or 0),
                })

            return _ok({
                "code": _strip_prefix(code),
                "trading_date": trading_date,
                "latency_ms": latency_ms,
                "point_count": len(points),
                "points": points,
            })
        except Exception as e:
            logger.exception("eltdx_get_minute_history failed")
            return _err(f"minute history query failed: {e}")

    @mcp.tool()
    async def eltdx_get_buy_sell_strength(code: str) -> str:
        """
        获取股票日内买卖强度数据（eltdx 独有，v3.3.7 新增）。

        返回日内逐分钟的买卖盘力量对比（买盘/卖盘委比量），
        用于 T0 盘口强弱判断。这是 eltdx 独有能力。

        Args:
            code: 股票代码，如 "600170"
        """
        try:
            start = time.time()
            df, _src = _router.route("minute_aux", code=code, kind="buy_sell_strength")
            latency_ms = round((time.time() - start) * 1000, 1)

            if df is None or df.empty:
                return _no_data(f"no buy/sell strength for {code}")

            points = []
            for _, row in df.iterrows():
                points.append({
                    "time": str(row.get("时间", "")),
                    "buy": float(row.get("买盘", 0) or 0),
                    "sell": float(row.get("卖盘", 0) or 0),
                })

            return _ok({
                "code": _strip_prefix(code),
                "latency_ms": latency_ms,
                "point_count": len(points),
                "points": points,
            })
        except Exception as e:
            logger.exception("eltdx_get_buy_sell_strength failed")
            return _err(f"buy/sell strength query failed: {e}")

    @mcp.tool()
    async def eltdx_get_today_ticks(code: str, count: int = 1000) -> str:
        """
        获取股票当日逐笔成交明细（eltdx 独有，v3.3.7 新增）。

        返回当日逐笔成交（时间/价格/成交量/成交额/方向/是否开盘撮合）。
        与历史逐笔互补，用于盘中实时逐笔监控。

        Args:
            code: 股票代码，如 "600170"
            count: 返回条数，默认 1000，上限 1800
        """
        try:
            start = time.time()
            df, _src = _router.route("today_ticks", code=code, count=count)
            latency_ms = round((time.time() - start) * 1000, 1)

            if df is None or df.empty:
                return _no_data(f"no today ticks for {code}")

            ticks = []
            for _, row in df.iterrows():
                ticks.append({
                    "time": str(row.get("时间", "")),
                    "price": float(row.get("价格", 0) or 0),
                    "volume": float(row.get("成交量", 0) or 0),
                    "amount": float(row.get("成交额", 0) or 0),
                    "side": str(row.get("方向", "")),
                    "is_opening_match": bool(row.get("是否开盘撮合", False)),
                })

            return _ok({
                "code": _strip_prefix(code),
                "latency_ms": latency_ms,
                "tick_count": len(ticks),
                "ticks": ticks,
            })
        except Exception as e:
            logger.exception("eltdx_get_today_ticks failed")
            return _err(f"today ticks query failed: {e}")

    @mcp.tool()
    async def eltdx_get_opening_match(code: str) -> str:
        """
        获取股票当日 9:25 开盘撮合（eltdx 独有，v3.3.7 新增）。

        返回开盘集合竞价形成的正式撮合那一笔（开盘价/开盘量/开盘额），
        是 T0 竞价策略判断开盘强弱的核心数据。

        Args:
            code: 股票代码，如 "600170"
        """
        try:
            start = time.time()
            df, _src = _router.route("opening_match", code=code)
            latency_ms = round((time.time() - start) * 1000, 1)

            if df is None or df.empty:
                return _no_data(f"no opening match for {code}")

            row = df.iloc[0]
            return _ok({
                "code": _strip_prefix(code),
                "latency_ms": latency_ms,
                "time": str(row.get("时间", "")),
                "open_price": float(row.get("价格", 0) or 0),
                "open_volume": float(row.get("成交量", 0) or 0),
                "open_amount": float(row.get("成交额", 0) or 0),
                "side": str(row.get("方向", "")),
            })
        except Exception as e:
            logger.exception("eltdx_get_opening_match failed")
            return _err(f"opening match query failed: {e}")

    @mcp.tool()
    async def eltdx_get_full_kline(code: str, period: str = "day") -> str:
        """
        获取股票全量历史 K 线（eltdx，v3.3.7 新增）。

        自动分页拉取全量 K 线（如日线约 6000+ 根），适合回测。
        与 eltdx_get_kline（单页）互补。

        Args:
            code: 股票代码，如 "600170"
            period: 周期，"day" / "week" / "month"
        """
        try:
            start = time.time()
            df, _src = _router.route("full_kline", code=code, period=period)
            latency_ms = round((time.time() - start) * 1000, 1)

            if df is None or df.empty:
                return _no_data(f"no full kline for {code}")

            bars = []
            for _, row in df.iterrows():
                bars.append({
                    "date": str(row.get("日期", "")),
                    "open": float(row.get("开盘", 0) or 0),
                    "high": float(row.get("最高", 0) or 0),
                    "low": float(row.get("最低", 0) or 0),
                    "close": float(row.get("收盘", 0) or 0),
                    "volume": float(row.get("成交量", 0) or 0),
                    "amount": float(row.get("成交额", 0) or 0),
                })

            return _ok({
                "code": _strip_prefix(code),
                "period": period,
                "latency_ms": latency_ms,
                "bar_count": len(bars),
                "bars": bars,
            })
        except Exception as e:
            logger.exception("eltdx_get_full_kline failed")
            return _err(f"full kline query failed: {e}")

    @mcp.tool()
    async def eltdx_get_adjusted_kline(code: str, period: str = "day", adjust: str = "qfq", count: int = 800) -> str:
        """
        获取股票复权 K 线（eltdx，v3.3.7 新增）。

        返回前复权(qfq)/后复权(hfq) K 线，复权因子由 eltdx 本地计算。

        Args:
            code: 股票代码，如 "600170"
            period: 周期，"day" / "week" / "month"
            adjust: 复权方式，"qfq"（前复权，默认）/ "hfq"（后复权）
            count: 返回根数，默认 800
        """
        try:
            start = time.time()
            df, _src = _router.route("adjusted_kline", code=code, period=period, adjust=adjust, count=count)
            latency_ms = round((time.time() - start) * 1000, 1)

            if df is None or df.empty:
                return _no_data(f"no adjusted kline for {code}")

            bars = []
            for _, row in df.iterrows():
                bars.append({
                    "date": str(row.get("日期", "")),
                    "open": float(row.get("开盘", 0) or 0),
                    "high": float(row.get("最高", 0) or 0),
                    "low": float(row.get("最低", 0) or 0),
                    "close": float(row.get("收盘", 0) or 0),
                    "volume": float(row.get("成交量", 0) or 0),
                    "amount": float(row.get("成交额", 0) or 0),
                })

            return _ok({
                "code": _strip_prefix(code),
                "period": period,
                "adjust": adjust,
                "latency_ms": latency_ms,
                "bar_count": len(bars),
                "bars": bars,
            })
        except Exception as e:
            logger.exception("eltdx_get_adjusted_kline failed")
            return _err(f"adjusted kline query failed: {e}")

    @mcp.tool()
    async def eltdx_get_stock_profile(codes: str) -> str:
        """
        获取股票全景档案（eltdx 独有，v3.3.7 新增）。

        返回「行情 + 证券信息 + 财务」一张表：最新价、涨跌幅、换手率、
        总市值、流通市值、总股本、EPS、板块等。量化选股核心工具。

        Args:
            codes: 股票代码，支持逗号分隔多只，如 "600170,000001"
        """
        try:
            start = time.time()
            df, _src = _router.route("stock_profile", codes=codes)
            latency_ms = round((time.time() - start) * 1000, 1)

            if df is None or df.empty:
                return _no_data(f"no stock profile for {codes}")

            profiles = []
            for _, row in df.iterrows():
                profiles.append({
                    "code": str(row.get("代码", "")),
                    "name": str(row.get("名称", "")),
                    "last_price": row.get("最新价"),
                    "change_pct": row.get("涨跌幅"),
                    "turnover_rate": row.get("换手率"),
                    "total_market_value": row.get("总市值"),
                    "circulating_market_value": row.get("流通市值"),
                    "total_shares": row.get("总股本"),
                    "circulating_shares": row.get("流通股本"),
                    "eps": row.get("EPS"),
                    "board": str(row.get("板块", "")),
                })

            return _ok({
                "latency_ms": latency_ms,
                "count": len(profiles),
                "profiles": profiles,
            })
        except Exception as e:
            logger.exception("eltdx_get_stock_profile failed")
            return _err(f"stock profile query failed: {e}")

    @mcp.tool()
    async def eltdx_get_shortline_indicators(codes: str) -> str:
        """
        获取股票短线打板指标（eltdx 独有，v3.3.7 新增）。

        返回 21 项短线指标：涨停状态、连板天数、涨停次数、封单流通比、
        市盈率TTM、60日贝塔、自由流通市值等。短线打板分析核心。

        Args:
            codes: 股票代码，支持逗号分隔多只，如 "600170,000001"
        """
        try:
            start = time.time()
            df, _src = _router.route("shortline_indicators", codes=codes)
            latency_ms = round((time.time() - start) * 1000, 1)

            if df is None or df.empty:
                return _no_data(f"no shortline indicators for {codes}")

            indicators = []
            for _, row in df.iterrows():
                indicators.append({str(k): row.get(k) for k in df.columns})

            return _ok({
                "latency_ms": latency_ms,
                "count": len(indicators),
                "indicators": indicators,
            })
        except Exception as e:
            logger.exception("eltdx_get_shortline_indicators failed")
            return _err(f"shortline indicators query failed: {e}")

    @mcp.tool()
    async def eltdx_get_finance_batch(codes: str) -> str:
        """
        获取股票批量财务字段（eltdx 独有，v3.3.7 新增）。

        一次拉取多只股票的财务字段：总股本、流通股本、总资产、净利润、
        每股收益、行业、上市日期等。量化选股估值利器。

        Args:
            codes: 股票代码，支持逗号分隔多只，如 "600170,000001"
        """
        try:
            start = time.time()
            df, _src = _router.route("finance_batch", codes=codes)
            latency_ms = round((time.time() - start) * 1000, 1)

            if df is None or df.empty:
                return _no_data(f"no finance data for {codes}")

            finances = []
            for _, row in df.iterrows():
                finances.append({
                    "code": str(row.get("代码", "")),
                    "total_shares": row.get("总股本"),
                    "circulating_shares": row.get("流通股本"),
                    "total_assets": row.get("总资产"),
                    "net_profit": row.get("净利润"),
                    "eps": row.get("每股收益"),
                    "industry": str(row.get("行业", "")),
                    "ipo_date": str(row.get("上市日期", "")),
                })

            return _ok({
                "latency_ms": latency_ms,
                "count": len(finances),
                "finances": finances,
            })
        except Exception as e:
            logger.exception("eltdx_get_finance_batch failed")
            return _err(f"finance batch query failed: {e}")

    @mcp.tool()
    async def eltdx_get_special_limits() -> str:
        """
        获取特殊品种涨跌停参考价（eltdx 独有，v3.3.7 新增）。

        返回特殊品种（ST/新股/复牌等）的涨跌停参考价。
        用于判断特殊品种的涨跌幅限制。

        Args:
            无参数
        """
        try:
            start = time.time()
            df, _src = _router.route("special_limits")
            latency_ms = round((time.time() - start) * 1000, 1)

            if df is None or df.empty:
                return _no_data("no special limits")

            limits = []
            for _, row in df.iterrows():
                limits.append({
                    "code": str(row.get("代码", "")),
                    "limit_up_price": row.get("涨停价"),
                    "limit_down_price": row.get("跌停价"),
                })

            return _ok({
                "latency_ms": latency_ms,
                "count": len(limits),
                "limits": limits,
            })
        except Exception as e:
            logger.exception("eltdx_get_special_limits failed")
            return _err(f"special limits query failed: {e}")

    @mcp.tool()
    async def eltdx_get_finance_report(code: str, report_type: str = "zcfzb") -> str:
        """
        获取通达信财务报表（eltdx F10，v3.3.7 新增）。

        返回通达信原始财务报表，report_type：zcfzb=资产负债表 / lrb=利润表 /
        xjllb=现金流量表。字段为通达信内部编码（T007/T008 等），
        作为 akshare 中文财报的降级补充源。

        Args:
            code: 股票代码，如 "600170"
            report_type: 报表类型，默认 zcfzb（资产负债表）
        """
        try:
            start = time.time()
            df, _src = _router.route("finance_report", code=code, report_type=report_type)
            latency_ms = round((time.time() - start) * 1000, 1)

            if df is None or df.empty:
                return _no_data(f"no finance report for {code}")

            return _ok({
                "code": _strip_prefix(code),
                "report_type": report_type,
                "latency_ms": latency_ms,
                "columns": list(df.columns),
                "row_count": len(df),
                "rows": df.head(20).to_dict(orient="records"),
            })
        except Exception as e:
            logger.exception("eltdx_get_finance_report failed")
            return _err(f"finance report query failed: {e}")

    @mcp.tool()
    async def eltdx_get_dividend_financing(code: str) -> str:
        """
        获取股票分红融资历史（eltdx F10，v3.3.7 新增）。

        返回分红方案历史。字段为通达信内部编码，作为 akshare 分红的降级补充源。

        Args:
            code: 股票代码，如 "600170"
        """
        try:
            start = time.time()
            df, _src = _router.route("dividend_financing", code=code)
            latency_ms = round((time.time() - start) * 1000, 1)

            if df is None or df.empty:
                return _no_data(f"no dividend financing for {code}")

            return _ok({
                "code": _strip_prefix(code),
                "latency_ms": latency_ms,
                "columns": list(df.columns),
                "row_count": len(df),
                "rows": df.head(20).to_dict(orient="records"),
            })
        except Exception as e:
            logger.exception("eltdx_get_dividend_financing failed")
            return _err(f"dividend financing query failed: {e}")

    @mcp.tool()
    async def eltdx_get_company_news(code: str) -> str:
        """
        获取公司资讯/研报（eltdx F10，v3.3.7 新增）。

        返回公司研报/监管措施资讯。字段为通达信内部编码，作为 akshare 资讯的降级补充源。

        Args:
            code: 股票代码，如 "600170"
        """
        try:
            start = time.time()
            df, _src = _router.route("company_news", code=code)
            latency_ms = round((time.time() - start) * 1000, 1)

            if df is None or df.empty:
                return _no_data(f"no company news for {code}")

            return _ok({
                "code": _strip_prefix(code),
                "latency_ms": latency_ms,
                "columns": list(df.columns),
                "row_count": len(df),
                "rows": df.head(20).to_dict(orient="records"),
            })
        except Exception as e:
            logger.exception("eltdx_get_company_news failed")
            return _err(f"company news query failed: {e}")

    @mcp.tool()
    async def eltdx_get_northbound_holding(code: str) -> str:
        """
        获取沪深股通持股变化（eltdx F10，v3.3.7 新增）。

        返回北向资金持股变化。字段为通达信内部编码，作为 akshare 北向的降级补充源。

        Args:
            code: 股票代码，如 "600170"
        """
        try:
            start = time.time()
            df, _src = _router.route("northbound_holding", code=code)
            latency_ms = round((time.time() - start) * 1000, 1)

            if df is None or df.empty:
                return _no_data(f"no northbound holding for {code}")

            return _ok({
                "code": _strip_prefix(code),
                "latency_ms": latency_ms,
                "columns": list(df.columns),
                "row_count": len(df),
                "rows": df.head(20).to_dict(orient="records"),
            })
        except Exception as e:
            logger.exception("eltdx_get_northbound_holding failed")
            return _err(f"northbound holding query failed: {e}")

    @mcp.tool()
    async def eltdx_get_stock_topics(code: str) -> str:
        """
        获取个股关联全部题材（eltdx helpers，v3.3.7 新增）。

        返回个股关联的题材列表（题材名/关联度/入选理由），题材挖掘核心。

        Args:
            code: 股票代码，如 "600170"
        """
        try:
            start = time.time()
            df, _src = _router.route("stock_topics", code=code)
            latency_ms = round((time.time() - start) * 1000, 1)

            if df is None or df.empty:
                return _no_data(f"no topics for {code}")

            topics = []
            for _, row in df.iterrows():
                topics.append({
                    "topic_name": str(row.get("题材名", "")),
                    "relation_level": row.get("关联度"),
                    "reason": str(row.get("入选理由", "")),
                })

            return _ok({
                "code": _strip_prefix(code),
                "latency_ms": latency_ms,
                "count": len(topics),
                "topics": topics,
            })
        except Exception as e:
            logger.exception("eltdx_get_stock_topics failed")
            return _err(f"stock topics query failed: {e}")

    @mcp.tool()
    async def eltdx_get_topic_stocks(code: str, topic_name: str = "") -> str:
        """
        获取题材成分股排名（eltdx helpers，v3.3.7 新增）。

        返回某题材下的成分股（排名/涨跌幅/3日/5日/20日/60日涨跌幅）。
        topic_name 为空时用种子股首个题材。

        Args:
            code: 种子股票代码，如 "600170"
            topic_name: 题材名，如 "节能环保"，空则用首个题材
        """
        try:
            start = time.time()
            df, _src = _router.route("topic_stocks", code=code, topic_name=topic_name)
            latency_ms = round((time.time() - start) * 1000, 1)

            if df is None or df.empty:
                return _no_data(f"no topic stocks for {code}")

            stocks = []
            for _, row in df.iterrows():
                stocks.append({
                    "code": str(row.get("代码", "")),
                    "name": str(row.get("名称", "")),
                    "rank": row.get("排名"),
                    "change_pct": row.get("涨跌幅"),
                    "change_pct_3d": row.get("3日涨跌幅"),
                    "change_pct_5d": row.get("5日涨跌幅"),
                    "change_pct_20d": row.get("20日涨跌幅"),
                    "change_pct_60d": row.get("60日涨跌幅"),
                })

            return _ok({
                "seed_code": _strip_prefix(code),
                "topic_name": topic_name,
                "latency_ms": latency_ms,
                "count": len(stocks),
                "stocks": stocks,
            })
        except Exception as e:
            logger.exception("eltdx_get_topic_stocks failed")
            return _err(f"topic stocks query failed: {e}")

    @mcp.tool()
    async def eltdx_get_auction_data(code: str) -> str:
        """
        获取股票竞价汇总（eltdx helpers，v3.3.7 新增）。

        返回开盘集合竞价汇总：开盘价/开盘量/开盘额/开盘涨跌幅/昨收。
        聚合竞价序列 + 9:25 快照 + 行情。

        Args:
            code: 股票代码，如 "600170"
        """
        try:
            start = time.time()
            df, _src = _router.route("auction_data", code=code)
            latency_ms = round((time.time() - start) * 1000, 1)

            if df is None or df.empty:
                return _no_data(f"no auction data for {code}")

            row = df.iloc[0]
            return _ok({
                "code": str(row.get("代码", "")),
                "latency_ms": latency_ms,
                "open_price": row.get("开盘价"),
                "open_volume": row.get("开盘量"),
                "open_amount": row.get("开盘额"),
                "open_change_pct": row.get("开盘涨跌幅"),
                "pre_close": row.get("昨收"),
            })
        except Exception as e:
            logger.exception("eltdx_get_auction_data failed")
            return _err(f"auction data query failed: {e}")

    @mcp.tool()
    async def eltdx_get_category_quotes(category: str = "沪深a股", sort_by: str = "涨幅", count: int = 80) -> str:
        """
        获取分类行情列表（eltdx，v3.3.7 新增，B 级）。

        返回分类行情（A股涨幅榜/成交额榜/封单榜等），实时性强于 akshare。

        Args:
            category: 分类，"沪深a股" / "a股"
            sort_by: 排序字段，"涨幅" / "成交额" / "现价" / "封单额" 等
            count: 返回条数，默认 80
        """
        try:
            start = time.time()
            df, _src = _router.route("category_quotes", category=category, sort_by=sort_by, count=count)
            latency_ms = round((time.time() - start) * 1000, 1)

            if df is None or df.empty:
                return _no_data(f"no category quotes for {category}")

            quotes = []
            for _, row in df.iterrows():
                quotes.append({
                    "code": str(row.get("代码", "")),
                    "last_price": row.get("现价"),
                    "change_pct": row.get("涨跌幅"),
                    "amount": row.get("成交额"),
                    "bid1": row.get("买一"),
                    "ask1": row.get("卖一"),
                    "rise_speed": row.get("涨速"),
                })

            return _ok({
                "category": category,
                "sort_by": sort_by,
                "latency_ms": latency_ms,
                "count": len(quotes),
                "quotes": quotes,
            })
        except Exception as e:
            logger.exception("eltdx_get_category_quotes failed")
            return _err(f"category quotes query failed: {e}")

    @mcp.tool()
    async def eltdx_get_trading_day() -> str:
        """
        获取当前交易日（eltdx，v3.3.7 新增，B 级）。

        通过服务器握手返回当前交易日日期，用于判断是否交易日。

        Args:
            无参数
        """
        try:
            df, _src = _router.route("trading_day")
            if df is None or df.empty:
                return _no_data("no trading day")
            row = df.iloc[0]
            return _ok({
                "server_date": str(row.get("服务器日期", "")),
                "server_datetime": str(row.get("服务器时间", "")),
            })
        except Exception as e:
            logger.exception("eltdx_get_trading_day failed")
            return _err(f"trading day query failed: {e}")

    @mcp.tool()
    async def eltdx_get_opening_match_history(code: str, trading_date: str) -> str:
        """
        获取历史开盘撮合（eltdx，v3.3.7 新增，B 级）。

        返回历史某日 9:25 开盘撮合（开盘价/量/额），盘后复盘用。

        Args:
            code: 股票代码，如 "600170"
            trading_date: 交易日，格式 "20260813" 或 "2026-08-13"
        """
        try:
            start = time.time()
            df, _src = _router.route("opening_match_history", code=code, trading_date=trading_date)
            latency_ms = round((time.time() - start) * 1000, 1)

            if df is None or df.empty:
                return _no_data(f"no opening match for {code} on {trading_date}")

            row = df.iloc[0]
            return _ok({
                "code": _strip_prefix(code),
                "trading_date": trading_date,
                "latency_ms": latency_ms,
                "open_price": float(row.get("价格", 0) or 0),
                "open_volume": float(row.get("成交量", 0) or 0),
                "open_amount": float(row.get("成交额", 0) or 0),
            })
        except Exception as e:
            logger.exception("eltdx_get_opening_match_history failed")
            return _err(f"opening match history query failed: {e}")

    @mcp.tool()
    async def eltdx_get_capital_changes(code: str) -> str:
        """
        获取股本变动历史（eltdx，v3.3.7 新增，B 级）。

        返回股本变动（分红/送股/增发等）历史，复权计算基础。

        Args:
            code: 股票代码，如 "600170"
        """
        try:
            start = time.time()
            df, _src = _router.route("capital_changes", code=code)
            latency_ms = round((time.time() - start) * 1000, 1)

            if df is None or df.empty:
                return _no_data(f"no capital changes for {code}")

            changes = []
            for _, row in df.iterrows():
                changes.append({
                    "date": str(row.get("日期", "")),
                    "type": str(row.get("变动类型", "")),
                    "shares_before": row.get("变动前股本"),
                    "shares_after": row.get("变动后股本"),
                })

            return _ok({
                "code": _strip_prefix(code),
                "latency_ms": latency_ms,
                "count": len(changes),
                "changes": changes,
            })
        except Exception as e:
            logger.exception("eltdx_get_capital_changes failed")
            return _err(f"capital changes query failed: {e}")

    @mcp.tool()
    async def eltdx_get_special_limits_scan() -> str:
        """
        扫描全市场特殊涨跌停参考价（eltdx，v3.3.7 新增，B 级）。

        扫描全部特殊品种（ST/新股/复牌）的涨跌停参考价。

        Args:
            无参数
        """
        try:
            start = time.time()
            df, _src = _router.route("special_limits_scan")
            latency_ms = round((time.time() - start) * 1000, 1)

            if df is None or df.empty:
                return _no_data("no special limits scan")

            limits = []
            for _, row in df.iterrows():
                limits.append({
                    "code": str(row.get("代码", "")),
                    "limit_up_price": row.get("涨停价"),
                    "limit_down_price": row.get("跌停价"),
                })

            return _ok({
                "latency_ms": latency_ms,
                "count": len(limits),
                "limits": limits,
            })
        except Exception as e:
            logger.exception("eltdx_get_special_limits_scan failed")
            return _err(f"special limits scan query failed: {e}")

    @mcp.tool()
    async def eltdx_get_f10_extra(entry: str, code: str) -> str:
        """
        获取 F10 额外资料（eltdx 通用入口，v3.3.7 新增，B 级）。

        覆盖 F10 B 级接口，字段为通达信内部编码（T007 等），
        作为 akshare 中文源的降级补充源。

        Args:
            entry: 接口名，可选：valuation(估值)/theme_market(题材行情)/
                   stock_score(个股总评)/profit_forecast(盈利预测)/
                   ranking_detail(排名)/governance(治理)/
                   shareholder_change_plans(增减持)/business_composition(主营构成)/
                   announcements(公告)/news(新闻)/stock_info(基础信息)
            code: 股票代码，如 "600170"
        """
        try:
            start = time.time()
            df, _src = _router.route("f10_extra", entry=entry, code=code)
            latency_ms = round((time.time() - start) * 1000, 1)

            if df is None or df.empty:
                return _no_data(f"no f10 data for {entry} {code}")

            return _ok({
                "entry": entry,
                "code": _strip_prefix(code),
                "latency_ms": latency_ms,
                "columns": list(df.columns),
                "row_count": len(df),
                "rows": df.head(20).to_dict(orient="records"),
            })
        except Exception as e:
            logger.exception("eltdx_get_f10_extra failed")
            return _err(f"f10 extra query failed: {e}")
