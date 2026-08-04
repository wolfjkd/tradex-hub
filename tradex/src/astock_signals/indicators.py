"""
Technical indicator calculation for A-stocks.

Computes common technical indicators (MACD, RSI, Bollinger, etc.)
using stockstats on OHLCV data sourced from AKShare or mootdx.

TradingAgents-astock 移植模块。V0.1。
"""

from __future__ import annotations

from datetime import datetime, timedelta
import logging

import pandas as pd

logger = logging.getLogger(__name__)

# Supported indicators and their descriptions
_INDICATOR_DESCRIPTIONS: dict[str, str] = {
    "close_50_sma": "50-day Simple Moving Average (均线)",
    "close_200_sma": "200-day Simple Moving Average (均线)",
    "close_10_ema": "10-day Exponential Moving Average (均线)",
    "macd": "MACD line (指数平滑异同移动平均线)",
    "macds": "MACD Signal line (信号线)",
    "macdh": "MACD Histogram (柱状图)",
    "rsi": "Relative Strength Index (相对强弱指标, 14-day)",
    "boll": "Bollinger Band middle line (布林带中轨)",
    "boll_ub": "Bollinger Band upper boundary (布林带上轨)",
    "boll_lb": "Bollinger Band lower boundary (布林带下轨)",
    "atr": "Average True Range (平均真实波幅)",
    "vwma": "Volume-Weighted Moving Average (成交量加权移动平均)",
    "mfi": "Money Flow Index (资金流量指标)",
}

_SUPPORTED_INDICATORS = list(_INDICATOR_DESCRIPTIONS.keys())


def get_supported_indicators() -> list[str]:
    """Return list of all supported technical indicator names."""
    return _SUPPORTED_INDICATORS.copy()


def get_indicator_description(indicator: str) -> str:
    """Return human-readable description for an indicator."""
    return _INDICATOR_DESCRIPTIONS.get(indicator, "")


def calculate_indicators(
    df: pd.DataFrame,
    indicator: str,
    look_back_days: int = 30,
) -> pd.DataFrame:
    """Calculate technical indicators on OHLCV data using stockstats.

    Args:
        df: OHLCV DataFrame with columns Date, Open, High, Low, Close, Volume.
        indicator: Indicator name (e.g. 'rsi', 'macd').
        look_back_days: Number of recent days to return.

    Returns:
        DataFrame with Date and indicator value columns.
    """
    from stockstats import wrap

    wrapped = wrap(df.copy())
    # Trigger calculation
    wrapped[indicator]

    # Build result
    result_rows = []
    for _, row in wrapped.iterrows():
        d = row.get("Date")
        v = row.get(indicator)
        if pd.isna(v):
            continue
        result_rows.append({
            "Date": str(d)[:10] if hasattr(d, "strftime") else str(d),
            indicator: round(float(v), 4),
        })

    result_df = pd.DataFrame(result_rows)
    if look_back_days > 0 and not result_df.empty:
        result_df = result_df.tail(look_back_days)

    return result_df


def get_indicators_text(
    symbol: str,
    indicator: str,
    curr_date: str,
    look_back_days: int = 30,
    ohlcv_source: str = "akshare",
) -> str:
    """Get technical indicator values as formatted text.

    Args:
        symbol: 6-digit A-stock code.
        indicator: Indicator name (rsi, macd, boll, etc.).
        curr_date: Reference date YYYY-MM-DD.
        look_back_days: How many days to look back.
        ohlcv_source: 'akshare' (default) or 'mootdx'.

    Returns:
        Formatted markdown text.
    """
    code = symbol.strip()

    if indicator not in _INDICATOR_DESCRIPTIONS:
        return (
            f"Indicator '{indicator}' not supported. "
            f"Choose from: {_SUPPORTED_INDICATORS}"
        )

    try:
        df = _load_ohlcv(code, curr_date, source=ohlcv_source)
        result_df = calculate_indicators(df, indicator, look_back_days)

        if result_df.empty:
            return f"No data available for {indicator} on {code}"

        lines = [
            f"## {indicator} values for {code}",
            f"Period: last {len(result_df)} trading days up to {curr_date}",
            "",
        ]
        for _, row in result_df.iterrows():
            lines.append(f"  {row['Date']}: {row[indicator]}")

        desc = _INDICATOR_DESCRIPTIONS.get(indicator, "")
        if desc:
            lines.append(f"\n{desc}")

        return "\n".join(lines)

    except Exception as e:
        logger.error("Indicator calculation failed for %s/%s: %s", code, indicator, e)
        return f"Error calculating {indicator} for {code}: {str(e)}"


# ---------------------------------------------------------------------------
# Private: OHLCV data loading
# ---------------------------------------------------------------------------


def _load_ohlcv(
    code: str,
    curr_date: str,
    source: str = "akshare",
) -> pd.DataFrame:
    """Load OHLCV data for indicator calculation.

    Args:
        code: 6-digit stock code.
        curr_date: Reference date YYYY-MM-DD.
        source: 'akshare' or 'mootdx'.

    Returns:
        DataFrame with columns Date, Open, High, Low, Close, Volume.
    """
    if source == "mootdx":
        return _load_ohlcv_mootdx(code, curr_date)
    return _load_ohlcv_akshare(code, curr_date)


def _load_ohlcv_akshare(code: str, curr_date: str) -> pd.DataFrame:
    """Load OHLCV from AKShare (东方财富 + 腾讯备用)."""
    import akshare as ak

    start_date = (
        datetime.strptime(curr_date, "%Y-%m-%d") - timedelta(days=400)
    ).strftime("%Y%m%d")
    end_date = datetime.strptime(curr_date, "%Y-%m-%d").strftime("%Y%m%d")

    sources = [
        ("东方财富", ak.stock_zh_a_hist, {
            "symbol": code,
            "period": "daily",
            "start_date": start_date,
            "end_date": end_date,
            "adjust": "qfq",
        }),
    ]

    tx_prefix = "sh" if code.startswith("6") else "sz"
    sources.append(("腾讯", ak.stock_zh_a_hist_tx, {
        "symbol": f"{tx_prefix}{code}",
        "adjust": "qfq",
    }))

    df = None
    last_error = None
    for name, fn, kwargs in sources:
        try:
            df = fn(**kwargs)
            if df is not None and not df.empty:
                break
        except Exception as e:
            last_error = e
            logger.debug("OHLCV source %s failed for %s: %s", name, code, e)
            continue

    if df is None or df.empty:
        msg = f"No OHLCV data from any source for {code}"
        if last_error:
            msg += f": {last_error}"
        raise ValueError(msg)

    col_map = {
        "日期": "Date", "开盘": "Open", "最高": "High",
        "最低": "Low", "收盘": "Close", "成交量": "Volume",
        "date": "Date", "open": "Open", "high": "High",
        "low": "Low", "close": "Close", "volume": "Volume",
    }
    df = df.rename(columns=col_map)
    needed = ["Date", "Open", "High", "Low", "Close", "Volume"]
    df = df[[c for c in needed if c in df.columns]]

    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"])

    return df


def _load_ohlcv_mootdx(code: str, curr_date: str) -> pd.DataFrame:
    """Load OHLCV from mootdx (通达信 TCP)."""
    try:
        from mootdx.quotes import Quotes

        client = Quotes.factory(market="std")
        days = 400
        start = 0
        df = client.bars(symbol=code, frequency=9, start=start, offset=days)
        if df is None or df.empty:
            raise ValueError(f"No OHLCV data from mootdx for {code}")

        df = df.reset_index()
        col_map = {
            "date": "Date", "open": "Open", "high": "High",
            "low": "Low", "close": "Close", "volume": "Volume",
        }
        df = df.rename(columns=col_map)
        needed = ["Date", "Open", "High", "Low", "Close", "Volume"]
        df = df[[c for c in needed if c in df.columns]]

        if "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"])

        return df

    except Exception as e:
        logger.error("mootdx OHLCV failed for %s: %s", code, e)
        raise
