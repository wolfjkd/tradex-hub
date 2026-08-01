"""
Multi-source fallback utility.

Tries multiple AKShare data source functions in order.
If the primary (eastmoney) fails, automatically falls back to
alternatives (sina, netease, ths, etc.).

Usage:
    df = await call_with_fallback(
        ("东方财富", ak.stock_zh_a_hist, {"symbol": "600519", "period": "daily"}),
        ("网易财经", ak.stock_zh_a_hist_163, {"symbol": "600519", "period": "daily"}),
    )
"""

from __future__ import annotations

import logging
from typing import Any, Callable

import pandas as pd

logger = logging.getLogger("tradex")


async def call_with_fallback(
    *sources: tuple[str, Callable, dict[str, Any]],
) -> pd.DataFrame:
    """
    Try multiple data source functions in order, return the first success.

    Each source is a tuple of (name, function, kwargs).
    If all sources fail, raises the last exception.

    Args:
        *sources: Tuples of (source_name, callable, kwargs_dict)

    Returns:
        DataFrame from the first successful call.

    Raises:
        Exception: The last exception if all sources fail.
    """
    last_error: Exception | None = None

    for name, func, kwargs in sources:
        try:
            df = func(**kwargs)
            if df is not None and not df.empty:
                logger.debug(f"[{name}] 成功, {len(df)} 行")
                return df
            # Got empty result, try next source
            logger.debug(f"[{name}] 返回空数据, 尝试下一个源")
            continue
        except Exception as e:
            last_error = e
            logger.debug(f"[{name}] 失败: {type(e).__name__}: {e}")
            continue

    # All sources failed
    if last_error:
        raise last_error
    return pd.DataFrame()


def try_sources_sync(
    *sources: tuple[str, Callable, dict[str, Any]],
) -> pd.DataFrame:
    """
    Synchronous version of call_with_fallback.

    Same interface but without async.
    """
    last_error: Exception | None = None

    for name, func, kwargs in sources:
        try:
            df = func(**kwargs)
            if df is not None and not df.empty:
                logger.debug(f"[{name}] 成功, {len(df)} 行")
                return df
            logger.debug(f"[{name}] 返回空数据, 尝试下一个源")
            continue
        except Exception as e:
            last_error = e
            logger.debug(f"[{name}] 失败: {type(e).__name__}: {e}")
            continue

    if last_error:
        raise last_error
    return pd.DataFrame()
