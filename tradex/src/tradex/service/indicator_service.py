"""indicator_service：技术指标计算业务逻辑层（工单 08 抽出）。

提供两种入口：
1) 直接计算（接收价格数组）：calc_macd / calc_kdj / calc_rsi / calc_boll
2) 按 symbol 自动取 K 线计算：calc_macd_by_symbol / calc_kdj_by_symbol / ...

设计：
- 直接计算函数复用 tools.technical_indicators 里已模块化的纯函数 _macd_values 等
  （这些函数本就在模块级而非 @mcp.tool 装饰器内，符合"业务逻辑抽离"原则）。
- by_symbol 函数调用 price_service.get_historical_price 取 K 线后调直接计算。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _extract_ohlcv(bars: list[dict]) -> tuple[list[float], list[float], list[float]]:
    """从 K 线 list of dict 提取 (closes, highs, lows)。

    Args:
        bars: K 线数据，每条含 收盘/开盘/最高/最低 字段（兼容中文/英文字段名）。

    Returns:
        tuple (closes, highs, lows)。
    """
    closes: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    for bar in bars:
        # 兼容多种字段名
        close = bar.get("收盘", bar.get("close", 0)) or 0
        high = bar.get("最高", bar.get("high", 0)) or 0
        low = bar.get("最低", bar.get("low", 0)) or 0
        closes.append(float(close))
        highs.append(float(high))
        lows.append(float(low))
    return closes, highs, lows


# ---------- 直接计算函数（接收价格数组） ----------


def calc_macd(
    closes: list[float],
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> dict[str, Any]:
    """MACD 计算（接收 closes 数组）。

    Returns:
        dict: 含 dif / dea / macd / data_points。
    """
    from ..tools.technical_indicators import _macd_values

    if not closes or len(closes) < slow_period:
        raise ValueError(
            f"数据不足: 需要至少 {slow_period} 个数据点，当前 {len(closes) if closes else 0}"
        )
    vals = _macd_values(closes, fast_period, slow_period, signal_period)
    return {
        "success": True,
        "dif": vals["dif"],
        "dea": vals["dea"],
        "macd": vals["macd"],
        "fast_period": fast_period,
        "slow_period": slow_period,
        "signal_period": signal_period,
        "data_points": len(closes),
    }


def calc_kdj(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 9,
    k_period: int = 3,
    d_period: int = 3,
) -> dict[str, Any]:
    """KDJ 计算。"""
    from ..tools.technical_indicators import _kdj_values

    if not (len(highs) == len(lows) == len(closes)):
        raise ValueError("参数错误: highs / lows / closes 长度必须相同")
    if len(closes) < period:
        raise ValueError(
            f"数据不足: 需要至少 {period} 个数据点，当前 {len(closes)}"
        )
    vals = _kdj_values(highs, lows, closes, period, k_period, d_period)
    return {
        "success": True,
        "k": vals["k"],
        "d": vals["d"],
        "j": vals["j"],
        "period": period,
        "k_period": k_period,
        "d_period": d_period,
        "data_points": len(closes),
    }


def calc_rsi(closes: list[float], period: int = 14) -> dict[str, Any]:
    """RSI 计算。"""
    from ..tools.technical_indicators import _rsi_values

    if len(closes) < period + 1:
        raise ValueError(
            f"数据不足: 需要至少 {period + 1} 个数据点，当前 {len(closes)}"
        )
    rsi_arr = _rsi_values(closes, period)
    return {
        "success": True,
        "rsi": rsi_arr,
        "period": period,
        "data_points": len(closes),
        "valid_points": sum(1 for x in rsi_arr if x is not None),
    }


def calc_boll(closes: list[float], period: int = 20, k: float = 2.0) -> dict[str, Any]:
    """BOLL 布林带计算。"""
    from ..tools.technical_indicators import _boll_values

    if len(closes) < period:
        raise ValueError(
            f"数据不足: 需要至少 {period} 个数据点，当前 {len(closes)}"
        )
    vals = _boll_values(closes, period, k)
    return {
        "success": True,
        "upper": vals["upper"],
        "middle": vals["middle"],
        "lower": vals["lower"],
        "bandwidth": vals["bandwidth"],
        "percent_b": vals["percent_b"],
        "period": period,
        "k": k,
        "data_points": len(closes),
    }


# ---------- 按 symbol 自动取 K 线 ----------


def _fetch_bars(symbol: str, period: str = "daily", num_bars: int = 120) -> list[dict]:
    """从 price_service 取 K 线并反转成升序（指标计算要求时间正序）。"""
    from . import price_service

    payload = price_service.get_historical_price(symbol=symbol, period=period)
    bars = payload.get("bars", [])
    # 数据源返回的是倒序（最新在前），指标计算需要正序
    return list(reversed(bars))[-num_bars:]


def calc_macd_by_symbol(
    symbol: str,
    period: str = "daily",
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> dict[str, Any]:
    """按 symbol 计算 MACD（自动取 K 线）。"""
    bars = _fetch_bars(symbol, period)
    closes, _, _ = _extract_ohlcv(bars)
    result = calc_macd(closes, fast_period, slow_period, signal_period)
    result["symbol"] = symbol
    result["period"] = period
    return result


def calc_kdj_by_symbol(
    symbol: str,
    period: str = "daily",
    kdj_period: int = 9,
    k_period: int = 3,
    d_period: int = 3,
) -> dict[str, Any]:
    """按 symbol 计算 KDJ（自动取 K 线）。"""
    bars = _fetch_bars(symbol, period)
    closes, highs, lows = _extract_ohlcv(bars)
    result = calc_kdj(highs, lows, closes, kdj_period, k_period, d_period)
    result["symbol"] = symbol
    result["kline_period"] = period
    return result


def calc_rsi_by_symbol(
    symbol: str, period: str = "daily", rsi_period: int = 14
) -> dict[str, Any]:
    """按 symbol 计算 RSI。"""
    bars = _fetch_bars(symbol, period)
    closes, _, _ = _extract_ohlcv(bars)
    result = calc_rsi(closes, rsi_period)
    result["symbol"] = symbol
    result["kline_period"] = period
    return result


def calc_boll_by_symbol(
    symbol: str, period: str = "daily", boll_period: int = 20, k: float = 2.0
) -> dict[str, Any]:
    """按 symbol 计算 BOLL。"""
    bars = _fetch_bars(symbol, period)
    closes, _, _ = _extract_ohlcv(bars)
    result = calc_boll(closes, boll_period, k)
    result["symbol"] = symbol
    result["kline_period"] = period
    return result
