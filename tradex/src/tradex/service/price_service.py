"""price_service：价格/K线类业务逻辑层（工单 04 抽出）。

从 tools/price_data.py 的 @mcp.tool() 装饰器内抽出核心业务逻辑为纯函数。
MCP 工具和 REST 路由各自薄包装，共享同一份代码（契约一致性）。

设计原则：
- 返回 Python dict（不是 JSON 字符串），让 MCP/REST 出口各自格式化
- 缓存逻辑保留在 service 层（MCP 和 REST 共享同一缓存，避免重复请求）
- 异常向上抛（由调用方决定怎么处理）
- eltdx Rust 内核 panic 防护由 data_sources/eltdx_fetchers.py 的 _NativePanicShield
  统一负责（所有通过 SmartRouter.route() 的调用都自动经过），service 层无需重复实现。

参考先例：tools/diagnostics.py 的 build_dashboard_data() 已是纯函数先例。
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from ..data_sources import get_router
from ..utils.cache import TTL_DAILY, TTL_REALTIME, cache
from ..utils.formatter import df_to_json, df_to_records, dict_to_json, slim_df
from ..utils.symbol import (
    format_with_exchange,
    is_index_code,
    normalize_symbol,
)

logger = logging.getLogger(__name__)
_router = get_router()

# 单次 K 线最多取多少根（各数据源 count 上限已在此收敛）
_MAX_BARS = 1000
# 返回给调用方的最大根数（防止长区间把响应撑爆）
_RESPONSE_BAR_CAP = 500


def _is_global_code(symbol: str) -> bool:
    """检测是否为全球行情代码（非A股6位数字代码）。

    与原 tools/price_data.py 的 _is_global_code 完全一致（契约保持）。
    """
    return symbol.startswith(("us", "hk", "kr", "wh", "int_", "hf_"))


def _find_code_col(df) -> str:
    """Find the stock code column in a DataFrame (varies by data source).

    与原 tools/price_data.py 的 _find_code_col 完全一致。
    """
    for c in df.columns:
        if c in ("代码", "code", "symbol"):
            return c
        if "代码" in c or "code" in c.lower() or "symbol" in c.lower():
            return c
    return df.columns[0]


def _resolve_symbol(symbol: str) -> tuple[str, bool]:
    """解析出路由用代码，并标记是否为指数。

    指数代码**必须保留交易所前缀**：eltdx 的 ``_normalize_code`` 见到 sh/sz/bj
    前缀会原样使用，而剥成 6 位裸码后 ``000001`` 会被判成深市个股（平安银行）——
    与 ``sh000001``（上证指数）撞号。这正是 2026-10-25 那次「传指数、静默拿到
    11 元档个股数据」的根因。

    个股仍归一为 6 位纯代码，保持既有行为不变。

    Returns:
        (路由用代码, 是否指数)
    """
    raw = str(symbol or "").strip()
    if is_index_code(raw):
        return format_with_exchange(raw), True
    return normalize_symbol(raw), False


def _parse_date(value: str, field: str) -> date | None:
    """解析 YYYYMMDD / YYYY-MM-DD；空值返回 None，非法格式抛 ValueError。"""
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"{field} 格式非法：{value!r}（应为 YYYYMMDD 或 YYYY-MM-DD）")


def _estimate_bar_count(
    period: str,
    start: date | None,
    end: date | None,
) -> int | None:
    """按日期区间估算需要向数据源索取多少根 K 线。

    主源（eltdx/tdx_mcp）的语义是「最近 N 根」，不是「区间内全部」——所以要覆盖
    到区间起点，必须**从今天往回**数够根数，再靠 _filter_by_date 精确裁剪。
    用 end_date 当锚点会算出一个只覆盖最近若干根的窗口，历史区间永远筛不到数据。

    Returns:
        需要的根数；无需调整时返回 None。
    """
    if start is None and end is None:
        return None

    if start is not None and end is not None and start > end:
        raise ValueError(
            f"start_date 不能晚于 end_date（{start} > {end}）"
        )

    # 覆盖到区间起点所需的最早边界
    anchor_start = start or end
    span_days = max((date.today() - anchor_start).days, 1)
    period_key = str(period or "").strip().lower()

    if period_key in ("weekly", "week", "w", "1w"):
        bars = span_days / 7 + 5
    elif period_key in ("monthly", "month", "m", "1m"):
        bars = span_days / 30 + 3
    else:
        bars = span_days * 0.75 + 10  # 交易日约占自然日 75%
    return max(1, min(int(bars) + 1, _MAX_BARS))


def _find_date_col(df: pd.DataFrame) -> str | None:
    """定位 K 线日期列（各源列名不一致）。

    只认明确的日期语义列名——不做「列数==2 就改名」这类猜测，猜错会把不相关
    结构当成 K 线塞给调用方（2026-10-25 估值 bug 的同类教训）。
    """
    for col in df.columns:
        name = str(col).strip().lower()
        if name in ("日期", "date", "时间", "time", "day", "trade_date"):
            return col
    for col in df.columns:
        if "日期" in str(col) or "date" in str(col).lower():
            return col
    return None


def _filter_by_date(
    df: pd.DataFrame,
    start: date | None,
    end: date | None,
) -> pd.DataFrame:
    """按日期区间裁剪并按日期升序排列。

    区间为空时原样返回（仅做升序归一），确保未传日期时行为不变。
    """
    if df is None or df.empty:
        return df

    date_col = _find_date_col(df)
    if date_col is None:
        if start is not None or end is not None:
            raise ValueError(
                f"数据源未返回可识别的日期列，无法按区间裁剪：{list(df.columns)}"
            )
        return df

    df = df.copy()
    parsed = pd.to_datetime(df[date_col], errors="coerce")
    df = df.assign(**{date_col: parsed})
    df = df.dropna(subset=[date_col])
    if df.empty:
        return df

    if start is not None:
        df = df[df[date_col].dt.date >= start]
    if end is not None:
        df = df[df[date_col].dt.date <= end]
    return df.sort_values(date_col, ascending=True)


def _fetch_valuation_snapshot(symbol: str) -> dict[str, float | None]:
    """补取市盈率/市净率（实时行情主源 eltdx 不带估值字段）。

    为什么单独走腾讯：一次 HTTP 就能同时拿到 PE(val[39]) 与 PB(val[46])，
    比连打百度估值两次便宜得多；且按日缓存，同一标的当天只补一次。

    取不到就留 None —— 绝不填 0，0 会被当成「PE=0 极度低估」这种假信号。
    """
    cache_key = f"valuation_snapshot:{symbol}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    snapshot: dict[str, float | None] = {"市盈率": None, "市净率": None}
    try:
        df, _src = _router.route(
            "realtime_quote", source_name="tencent_http", symbol=symbol
        )
        if df is not None and not df.empty:
            row = df.iloc[0]
            for field in ("市盈率", "市净率"):
                value = row.get(field)
                if value is None or pd.isna(value):
                    continue
                numeric = float(value)
                # 上游空字段在该适配器里被写成 0，0 视为缺失而非真实估值
                snapshot[field] = numeric if numeric != 0 else None
    except Exception as exc:  # noqa: BLE001 - 估值补取失败不影响行情主流程
        logger.debug("估值补取失败(%s): %s", symbol, exc)

    cache.set(cache_key, snapshot, TTL_DAILY)
    return snapshot


def get_realtime_quote(symbol: str) -> dict[str, Any]:
    """实时报价（A 股 6 位代码或全球行情代码 usDJI/hkHSI 等）。

    Args:
        symbol: A 股 6 位数字代码（如 "600519"）或全球行情代码（如 "usDJI"）。

    Returns:
        dict：实时报价字段（最新价/涨跌幅/成交量/成交额/最高/最低/开盘/昨收/换手率/市盈率/市净率）。

    Raises:
        ValueError: 全球代码未找到 / A 股代码未找到。
        Exception: 数据源异常时向上抛。
    """
    # 全球代码分支
    if _is_global_code(symbol):
        cache_key = f"global_quote:{symbol}"
        cached = cache.get(cache_key)
        if cached is not None:
            # tools 原返回 JSON 字符串；service 层统一返回 dict（此处 cached 是 JSON 串需解析）
            import json
            return json.loads(cached) if isinstance(cached, str) else cached

        df, _src = _router.route("global_market_quote")
        if df is None or df.empty:
            raise ValueError(f"获取全球行情失败 ({symbol}): 数据源返回空数据")
        row = df[df["代码"] == symbol]
        if row.empty:
            raise ValueError(f"未找到代码 {symbol} 的全球行情")
        # 取首条记录（兼容 df_to_json 行为）
        records = df_to_records(row)
        result = {"quote": records[0] if records else {}, "source": _src}
        # 缓存为 dict（统一 service 层契约）
        cache.set(cache_key, result, TTL_REALTIME)
        return result

    # A 股分支
    symbol, is_index = _resolve_symbol(symbol)
    cache_key = f"realtime_quote:{symbol}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    df, _src = _router.route("realtime_quote", symbol=symbol)
    if df is None or df.empty:
        raise ValueError(f"获取实时行情失败 ({symbol}): 数据源返回空数据")
    code_col = _find_code_col(df)
    if len(df) > 1:
        # 数据源回填的代码可能不带交易所前缀，两种形态都要认
        wanted = {symbol, normalize_symbol(symbol)}
        row = df[df[code_col].astype(str).str.strip().isin(wanted)]
        if row.empty:
            raise ValueError(f"未找到股票 {symbol} 的实时行情")
    else:
        row = df
    records = df_to_records(row)
    quote = records[0] if records else {}
    # 主源不带估值字段 → 补一层（按日缓存，失败留 None）
    missing = [field for field in ("市盈率", "市净率") if quote.get(field) in (None, "")]
    if missing:
        snapshot = _fetch_valuation_snapshot(symbol)
        for field in missing:
            quote[field] = snapshot.get(field)
    result = {
        "quote": quote,
        "symbol": symbol,
        "is_index": is_index,
        "source": _src,
    }
    if any(quote.get(field) is None for field in ("市盈率", "市净率")):
        result["valuation_note"] = (
            "市盈率/市净率缺失：实时行情主源不带估值字段，估值备源当日亦未取到；"
            "需要时改用 get_valuation_metrics"
        )
    cache.set(cache_key, result, TTL_REALTIME)
    return result


def get_historical_price(
    symbol: str,
    period: str = "daily",
    start_date: str = "",
    end_date: str = "",
    adjust: str = "qfq",
) -> dict[str, Any]:
    """历史 K 线数据（OHLCV）。

    Args:
        symbol: 6 位股票代码，或带交易所前缀的指数代码（sh000001 / sz399001 等）。
        period: "daily" / "weekly" / "monthly"。
        start_date: "YYYYMMDD" 格式，空表示不设下界。
        end_date: "YYYYMMDD" 格式，空表示到最新。
        adjust: "qfq" / "hfq" / ""。

    Returns:
        dict：含 bars（list of dict）、bar_count、is_index、source。

    Raises:
        ValueError: 日期格式非法 / 区间颠倒 / 数据源未返回可识别日期列。
        Exception: 数据源异常时向上抛。
    """
    code, is_index = _resolve_symbol(symbol)
    start = _parse_date(start_date, "start_date")
    end = _parse_date(end_date, "end_date")
    if start is not None and end is not None and start > end:
        raise ValueError(f"start_date 不能晚于 end_date（{start_date} > {end_date}）")

    cache_key = f"hist_price:{code}:{period}:{start_date}:{end_date}:{adjust}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    route_kwargs: dict[str, Any] = {
        "symbol": code,
        "period": period,
        "start_date": start_date,
        "end_date": end_date,
        "adjust": adjust,
    }
    # 只认 count 不认日期区间的主源（eltdx/tdx_mcp）靠估算根数覆盖目标区间
    estimate = _estimate_bar_count(period, start, end)
    if estimate is not None:
        route_kwargs["count"] = estimate

    df, _src = _router.route("historical_kline", **route_kwargs)
    if df is None or df.empty:
        result = {
            "symbol": code,
            "period": period,
            "is_index": is_index,
            "bars": [],
            "source": _src,
        }
    else:
        df = _filter_by_date(df, start, end)
        if df.empty:
            raise ValueError(
                f"区间内无 K 线数据（{code}，{start_date or '不限'}~{end_date or '最新'}）；"
                f"若区间距今过远，可能超出单次可取根数上限 {_MAX_BARS}"
            )
        # 升序后取尾部：长区间下保留最近的一段，而不是最早的一段
        bars = df_to_records(df.tail(_RESPONSE_BAR_CAP))
        # 日期列统一截到 YYYY-MM-DD，避免把 15:00 的收盘时刻当成日线日期
        for bar in bars:
            for k, v in list(bar.items()):
                if isinstance(v, str) and "T" in v and len(v) >= 10:
                    bar[k] = v[:10]
        result = {
            "symbol": code,
            "period": period,
            "adjust": adjust,
            "is_index": is_index,
            "bar_count": len(bars),
            "bars": bars,
            "source": _src,
        }
    cache.set(cache_key, result, TTL_DAILY)
    return result


def get_intraday_data(symbol: str) -> dict[str, Any]:
    """当日分时数据（1 分钟 K 线）。

    Args:
        symbol: 6 位股票代码，或带交易所前缀的指数代码。

    Returns:
        dict：含 code/point_count/points/is_index/source。

    Raises:
        ValueError: 无有效数据点。
        Exception: 数据源异常时向上抛。
    """
    code, is_index = _resolve_symbol(symbol)
    cache_key = f"intraday:{code}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    df, _src = _router.route("minute_data", symbol=code)
    if df is None or df.empty:
        raise ValueError(f"获取分时数据失败 ({code}): 数据源返回空数据")

    # 兼容 akshare(时间/开盘/收盘/均价/成交量) 与 eltdx(时间/价格/均价/成交量) 列名
    col_map = {
        "时间": "time", "time": "time",
        "开盘": "open", "open": "open",
        "收盘": "close", "close": "close", "价格": "close", "price": "close",
        "最高": "high", "high": "high",
        "最低": "low", "low": "low",
        "均价": "avg_price", "avg_price": "avg_price",
        "成交量": "volume", "volume": "volume",
        "成交额": "amount", "amount": "amount",
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

    points = []
    for _, row in df.iterrows():
        time_val = str(row.get("time", ""))
        price_val = float(row.get("close", row.get("price", 0)) or 0)
        avg_val = float(row.get("avg_price", 0) or 0)
        vol_val = int(row.get("volume", 0) or 0)

        if time_val and price_val > 0:
            points.append({
                "time": time_val,
                "price": price_val,
                "avg_price": avg_val,
                "volume": vol_val,
            })

    if not points:
        raise ValueError(f"获取分时数据失败 ({code}): 无有效数据点")

    result = {
        "code": code,
        "is_index": is_index,
        "point_count": len(points),
        "points": points,
        "source": _src,
    }
    cache.set(cache_key, result, TTL_REALTIME)
    return result
