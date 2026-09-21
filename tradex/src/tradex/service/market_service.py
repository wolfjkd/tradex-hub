"""market_service：行情/资金类业务逻辑层（工单 02 抽出）。

从 tools/market.py 的 @mcp.tool() 装饰器内抽出核心业务逻辑为纯函数。
MCP 工具和 REST 路由各自薄包装，共享同一份代码（契约一致性）。

设计原则：
- 返回 Python dict（不是 JSON 字符串），让 MCP/REST 出口各自格式化
- 缓存逻辑保留在 service 层（MCP 和 REST 共享同一缓存，避免重复请求）
- 异常向上抛（由调用方决定怎么处理：MCP 转成 error_response，REST 转成 HTTPException）

参考先例：tools/diagnostics.py 的 build_dashboard_data() 已是纯函数先例。
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from ..data_sources import get_router
from ..data_sources.akshare_fetchers import fetch_index_daily_amount
from ..utils.cache import TTL_DAILY, TTL_REALTIME, cache
from ..utils.formatter import slim_df
from ..utils.symbol import normalize_symbol

logger = logging.getLogger(__name__)
_router = get_router()


def get_market_overview() -> dict[str, Any]:
    """A股主要指数实时行情快照。

    Returns:
        dict：包含指数名称、最新点位、涨跌幅、成交量、成交额等（max_rows=30）。

    Raises:
        Exception: 数据源不可达或返回异常时向上抛（由调用方处理）。
    """
    cache_key = "market_overview"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    df, _src = _router.route("market_overview")
    df = slim_df(df)
    rows = _df_to_records(df, max_rows=30)
    result = {"indices": rows, "source": _src}
    cache.set(cache_key, result, TTL_REALTIME)
    return result


def get_index_volume_compare(days: int = 6) -> dict[str, Any]:
    """三大指数（上证/深证/创业板）近 days 个交易日的量能序列。

    Args:
        days: 取近几个交易日，默认 6。

    Returns:
        dict：{sh000001: {name, series: [...]}, ...}，单指数失败项含 error 字段。
    """
    cache_key = f"index_vol_compare:{days}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    indices = [
        ("sh000001", "上证指数"),
        ("sz399001", "深证成指"),
        ("sz399006", "创业板指"),
    ]
    result: dict[str, Any] = {}
    for code, name in indices:
        try:
            data = fetch_index_daily_amount(symbol=code, days=days)
            series = []
            for d in (data or []):
                vol = float(d.get("volume", 0) or 0)
                amt = d.get("amount")
                amt = float(amt) if amt is not None else None
                series.append({
                    "date": str(d.get("date", "")),
                    "volume_hand": round(vol, 0),
                    "volume_yi_share": round(vol / 1e8, 2),
                    "amount_yuan": round(amt, 0) if amt is not None else None,
                    "amount_yi": round(amt / 1e8, 2) if amt is not None else None,
                })
            result[code] = {"name": name, "series": series}
        except Exception as e:
            logger.warning("index_daily_amount %s failed: %s", code, e)
            result[code] = {"name": name, "series": [], "error": str(e)}

    cache.set(cache_key, result, TTL_DAILY)
    return result


def get_money_flow(symbol: str) -> dict[str, Any]:
    """个股资金流向数据。

    Args:
        symbol: 6 位股票代码，如 "600519"。

    Returns:
        dict：含 rows（日期/主力净流入/超大单/大单/中单/小单净流入）。

    Raises:
        Exception: 数据源异常时向上抛。
    """
    symbol = normalize_symbol(symbol)
    cache_key = f"money_flow:{symbol}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    result_raw, _src = _router.route(
        "fund_flow", code=symbol, include_history=True
    )
    rows: list[dict] = []
    if isinstance(result_raw, dict):
        realtime = result_raw.get("realtime") or []
        history = result_raw.get("history") or []
        for item in realtime:
            rows.append({
                "时间": item.get("time", item.get("date", "")),
                "主力净流入": float(item.get("main_net", 0) or 0),
                "小单净流入": float(item.get("small", 0) or 0),
                "中单净流入": float(item.get("mid", 0) or 0),
                "大单净流入": float(item.get("large", 0) or 0),
                "超大单净流入": float(item.get("super_large", 0) or 0),
            })
        if not rows:
            for item in history:
                rows.append({
                    "日期": item.get("date", item.get("time", "")),
                    "主力净流入": float(item.get("main_net", 0) or 0),
                    "小单净流入": float(item.get("small", 0) or 0),
                    "中单净流入": float(item.get("mid", 0) or 0),
                    "大单净流入": float(item.get("large", 0) or 0),
                    "超大单净流入": float(item.get("super_large", 0) or 0),
                })
    if not rows:
        return {"symbol": symbol, "rows": [], "message": "该股票暂无资金流向数据"}

    result = {"symbol": symbol, "rows": rows[:30]}
    cache.set(cache_key, result, TTL_DAILY)
    return result


def get_north_bound_flow() -> dict[str, Any]:
    """北向资金（沪股通+深股通）净流入数据。

    Returns:
        dict：含 rows（日期/沪股通/深股通/合计净流入）。

    Raises:
        Exception: 数据源异常时向上抛。
    """
    cache_key = "north_bound_flow"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    result, _src = _router.route("northbound", include_history=True)
    rows: list[dict] = []
    discontinued_info: dict | None = None

    if isinstance(result, pd.DataFrame):
        df = result
        if df is None or df.empty:
            return {"rows": [], "message": "北向资金数据为空"}
        rows = _df_to_records(df, max_rows=30)
    elif isinstance(result, dict):
        if result.get("discontinued"):
            note = result.get("note", "北向资金已停更")
            realtime = result.get("realtime") or {}
            discontinued_info = {
                "status": "discontinued",
                "note": note,
                "last_total_yi": realtime.get("total"),
                "source": result.get("source"),
            }
        else:
            history = result.get("history") or []
            if not history:
                return {"rows": [], "message": "北向资金数据为空"}
            rows = history[:30]
    else:
        return {"rows": [], "message": "北向资金数据为空"}

    payload = {"rows": rows}
    if discontinued_info:
        payload["discontinued"] = discontinued_info
    cache.set(cache_key, payload, TTL_DAILY)
    return payload


def get_limit_up_down(direction: str = "涨停") -> dict[str, Any]:
    """当日涨停板或跌停板股票池。

    Args:
        direction: "涨停" 或 "跌停"。

    Returns:
        dict：含 rows（代码/名称/涨跌幅/封单额/连板天数等）。

    Raises:
        Exception: 数据源异常时向上抛。
    """
    cache_key = f"limit_pool:{direction}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    df, _src = _router.route("hot_stocks", direction=direction)
    rows = _df_to_records(df)
    result = {"direction": direction, "rows": rows}
    cache.set(cache_key, result, TTL_DAILY)
    return result


def get_dragon_tiger(num_days: int = 5) -> dict[str, Any]:
    """龙虎榜数据（机构和游资活跃买卖记录）。

    Args:
        num_days: 返回最近几个交易日的数据，默认 5。

    Returns:
        dict：含 rows（股票代码/名称/上榜原因/买入额/卖出额/净买入额等）。

    Raises:
        Exception: 数据源异常时向上抛。
    """
    cache_key = f"dragon_tiger:{num_days}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    result, _src = _router.route(
        "dragon_tiger", code="", look_back_days=num_days * 2
    )
    if not isinstance(result, pd.DataFrame):
        raise ValueError("龙虎榜数据格式异常")

    df = slim_df(result)
    rows = _df_to_records(df, max_rows=30)
    payload = {"rows": rows}
    cache.set(cache_key, payload, TTL_DAILY)
    return payload


def get_global_market_quote(category: str = "") -> dict[str, Any]:
    """全球市场行情快照。

    Args:
        category: 可选分类过滤（"美股指数"/"热门美股"/"亚太指数"/"韩股"/"外汇"），空返回全部。

    Returns:
        dict：含 rows（代码/名称/类别/最新价/涨跌额/涨跌幅等，max_rows=50）。

    Raises:
        Exception: 数据源异常时向上抛。
    """
    cache_key = f"global_market_quote:{category}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    df, _src = _router.route("global_market_quote")
    if df is None or df.empty:
        return {"rows": []}

    if category:
        df = df[df["类别"] == category]

    rows = _df_to_records(df, max_rows=50)
    result = {"rows": rows}
    cache.set(cache_key, result, TTL_REALTIME)
    return result


# ---------- 辅助函数 ----------


def _df_to_records(df: pd.DataFrame, max_rows: int | None = None) -> list[dict]:
    """DataFrame → list of dict（供 service 函数复用）。

    处理 NaN → None（JSON 友好），可选截断行数。
    此外把 datetime.date / datetime.datetime / pd.Timestamp 统一转 ISO 字符串，
    修复「Object of type date is not JSON serializable」序列化崩溃（曾导致 get_dragon_tiger 报错）。
    """
    if df is None or df.empty:
        return []
    if max_rows is not None:
        df = df.head(max_rows)
    # NaN → None；日期/时间对象 → ISO 字符串
    def _norm(v):
        if v is None or pd.isna(v):
            return None
        if isinstance(v, pd.Timestamp):
            return v.isoformat()
        if hasattr(v, "isoformat") and not isinstance(v, (str, int, float)):
            return v.isoformat()
        return v
    out = df.where(pd.notnull(df), None).to_dict(orient="records")
    for row in out:
        for k, v in list(row.items()):
            row[k] = _norm(v)
    return out
