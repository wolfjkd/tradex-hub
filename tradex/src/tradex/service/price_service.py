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
from typing import Any

import pandas as pd

from ..data_sources import get_router
from ..utils.cache import TTL_DAILY, TTL_REALTIME, cache
from ..utils.formatter import df_to_json, dict_to_json, slim_df
from ..utils.symbol import normalize_symbol

logger = logging.getLogger(__name__)
_router = get_router()


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
        records = row.where(pd.notnull(row), None).to_dict(orient="records")
        result = {"quote": records[0] if records else {}, "source": _src}
        # 缓存为 dict（统一 service 层契约）
        cache.set(cache_key, result, TTL_REALTIME)
        return result

    # A 股分支
    symbol = normalize_symbol(symbol)
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
        row = df[df[code_col].astype(str).str.strip() == symbol]
        if row.empty:
            raise ValueError(f"未找到股票 {symbol} 的实时行情")
    else:
        row = df
    records = row.where(pd.notnull(row), None).to_dict(orient="records")
    result = {"quote": records[0] if records else {}, "symbol": symbol, "source": _src}
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
        symbol: 6 位股票代码。
        period: "daily" / "weekly" / "monthly"。
        start_date: "YYYYMMDD" 格式，空返回所有。
        end_date: "YYYYMMDD" 格式，空返回至今。
        adjust: "qfq" / "hfq" / ""。

    Returns:
        dict：含 bars（list of dict，单条含 日期/开盘/收盘/最高/最低/成交量/成交额/振幅/涨跌幅/涨跌额/换手率）。

    Raises:
        Exception: 数据源异常时向上抛。
    """
    symbol = normalize_symbol(symbol)
    cache_key = f"hist_price:{symbol}:{period}:{start_date}:{end_date}:{adjust}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    df, _src = _router.route(
        "historical_kline",
        symbol=symbol,
        period=period,
        start_date=start_date,
        end_date=end_date,
        adjust=adjust,
    )
    if df is None or df.empty:
        result = {"symbol": symbol, "period": period, "bars": [], "source": _src}
    else:
        df_limited = df.head(500)
        bars = df_limited.where(pd.notnull(df_limited), None).to_dict(orient="records")
        result = {
            "symbol": symbol,
            "period": period,
            "adjust": adjust,
            "bar_count": len(bars),
            "bars": bars,
            "source": _src,
        }
    cache.set(cache_key, result, TTL_DAILY)
    return result


def get_intraday_data(symbol: str) -> dict[str, Any]:
    """当日分时数据（1 分钟 K 线）。

    Args:
        symbol: 6 位股票代码。

    Returns:
        dict：含 code/point_count/points（list of {time, price, avg_price, volume}）。

    Raises:
        ValueError: 无有效数据点。
        Exception: 数据源异常时向上抛。
    """
    symbol = normalize_symbol(symbol)
    cache_key = f"intraday:{symbol}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    df, _src = _router.route("minute_data", symbol=symbol)
    if df is None or df.empty:
        raise ValueError(f"获取分时数据失败 ({symbol}): 数据源返回空数据")

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
        raise ValueError(f"获取分时数据失败 ({symbol}): 无有效数据点")

    result = {
        "code": symbol,
        "point_count": len(points),
        "points": points,
        "source": _src,
    }
    cache.set(cache_key, result, TTL_REALTIME)
    return result
