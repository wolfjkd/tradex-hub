"""financial_service：财务报表/指标业务逻辑层（工单 05 抽出）。

从 tools/financial_stmt.py 的 @mcp.tool() 装饰器内抽出 8 个核心业务函数：
- get_income_statement / get_balance_sheet / get_cash_flow_statement（三大报表）
- get_financial_line_item（特定科目提取）
- get_financial_indicators / get_growth_rates / get_per_share_data（指标类）
- get_segments_revenue（主营构成）

MCP 工具和 REST 路由各自薄包装，共享同一份代码（契约一致性）。
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from ..data_sources import get_router
from ..utils.cache import TTL_FINANCIAL, cache
from ..utils.formatter import (
    BALANCE_SHEET_COLS,
    CASHFLOW_STATEMENT_COLS,
    INCOME_STATEMENT_COLS,
    df_to_json,
    slim_df,
    slim_financial_df,
)
from ..utils.symbol import format_em_symbol, normalize_symbol

logger = logging.getLogger(__name__)
_router = get_router()


def _df_to_records(df: pd.DataFrame, max_rows: int | None = None) -> list[dict]:
    """DataFrame → list of dict（NaN → None）。"""
    if df is None or df.empty:
        return []
    if max_rows is not None:
        df = df.head(max_rows)
    return df.where(pd.notnull(df), None).to_dict(orient="records")


def get_income_statement(symbol: str, num_quarters: int = 8) -> dict[str, Any]:
    """利润表（按季度）。"""
    symbol = normalize_symbol(symbol)
    em_symbol = format_em_symbol(symbol)
    cache_key = f"income_stmt:{symbol}:{num_quarters}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    df, _src = _router.route("financial_stmt", endpoint="profit", symbol=em_symbol)
    if df is None or df.empty:
        raise ValueError(f"利润表数据为空 ({symbol})")
    if num_quarters > 0:
        df = df.head(num_quarters)
    df = slim_financial_df(df, INCOME_STATEMENT_COLS)
    records = _df_to_records(df)
    result = {"symbol": symbol, "statement": "income", "periods": records, "source": _src}
    cache.set(cache_key, result, TTL_FINANCIAL)
    return result


def get_balance_sheet(symbol: str, num_quarters: int = 8) -> dict[str, Any]:
    """资产负债表（按季度）。"""
    symbol = normalize_symbol(symbol)
    em_symbol = format_em_symbol(symbol)
    cache_key = f"balance_sheet:{symbol}:{num_quarters}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    df, _src = _router.route("financial_stmt", endpoint="balance", symbol=em_symbol)
    if df is None or df.empty:
        raise ValueError(f"资产负债表数据为空 ({symbol})")
    if num_quarters > 0:
        df = df.head(num_quarters)
    df = slim_financial_df(df, BALANCE_SHEET_COLS)
    records = _df_to_records(df)
    result = {"symbol": symbol, "statement": "balance", "periods": records, "source": _src}
    cache.set(cache_key, result, TTL_FINANCIAL)
    return result


def get_cash_flow_statement(symbol: str, num_quarters: int = 8) -> dict[str, Any]:
    """现金流量表（按季度）。"""
    symbol = normalize_symbol(symbol)
    em_symbol = format_em_symbol(symbol)
    cache_key = f"cash_flow:{symbol}:{num_quarters}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    df, _src = _router.route("financial_stmt", endpoint="cashflow", symbol=em_symbol)
    if df is None or df.empty:
        raise ValueError(f"现金流量表数据为空 ({symbol})")
    if num_quarters > 0:
        df = df.head(num_quarters)
    df = slim_financial_df(df, CASHFLOW_STATEMENT_COLS)
    records = _df_to_records(df)
    result = {"symbol": symbol, "statement": "cashflow", "periods": records, "source": _src}
    cache.set(cache_key, result, TTL_FINANCIAL)
    return result


def get_financial_line_item(
    symbol: str, item: str, num_quarters: int = 8
) -> dict[str, Any]:
    """从三大财务报表中提取特定科目的时间序列。

    Args:
        symbol: 6 位股票代码。
        item: 科目名称（支持模糊匹配，如"营业总收入"/"净利润"/"总资产"）。
        num_quarters: 返回最近几个季度。

    Returns:
        dict：含 item / periods（时间序列）。

    Raises:
        ValueError: 三大报表中均未找到该科目。
    """
    symbol = normalize_symbol(symbol)
    em_symbol = format_em_symbol(symbol)
    cache_key = f"line_item:{symbol}:{item}:{num_quarters}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    statements = [
        ("利润表", "profit", INCOME_STATEMENT_COLS, em_symbol),
        ("资产负债表", "balance", BALANCE_SHEET_COLS, em_symbol),
        ("现金流量表", "cashflow", CASHFLOW_STATEMENT_COLS, em_symbol),
    ]

    for stmt_name, endpoint, whitelist, sym in statements:
        try:
            df, _src = _router.route("financial_stmt", endpoint=endpoint, symbol=sym)
        except Exception:
            continue
        if df is None or df.empty:
            continue

        slim = slim_financial_df(df, whitelist)
        matching_cols = [c for c in slim.columns if item in c]
        if not matching_cols:
            raw_match = [c for c in df.columns if item.upper() in c.upper()]
            if raw_match:
                date_cols = [c for c in df.columns if "REPORT_DATE_NAME" in c.upper()]
                keep = date_cols + raw_match
                avail = [c for c in keep if c in df.columns]
                sub = df[avail] if avail else df[raw_match]
                if num_quarters > 0:
                    sub = sub.head(num_quarters)
                slim2 = slim_df(sub)
                records = _df_to_records(slim2)
                result = {
                    "symbol": symbol, "item": item, "source_statement": stmt_name,
                    "periods": records, "source": _src,
                }
                cache.set(cache_key, result, TTL_FINANCIAL)
                return result
            continue

        date_cols = [c for c in slim.columns if "报告期" in c]
        keep = date_cols + matching_cols
        avail = [c for c in keep if c in slim.columns]
        sub = slim[avail] if avail else slim[matching_cols]
        if num_quarters > 0:
            sub = sub.head(num_quarters)
        records = _df_to_records(sub)
        result = {
            "symbol": symbol, "item": item, "source_statement": stmt_name,
            "periods": records, "source": _src,
        }
        cache.set(cache_key, result, TTL_FINANCIAL)
        return result

    raise ValueError(f"在三大财务报表中未找到科目 '{item}'")


def get_financial_indicators(symbol: str, num_periods: int = 8) -> dict[str, Any]:
    """财务分析指标（ROE/毛利率/净利率/资产负债率等）。"""
    symbol = normalize_symbol(symbol)
    cache_key = f"fin_indicators:{symbol}:{num_periods}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    df, _src = _router.route("financial_stmt", endpoint="indicator", symbol=symbol)
    if df is None or df.empty:
        raise ValueError(f"财务指标数据为空 ({symbol})")
    if num_periods > 0:
        df = df.head(num_periods)
    df = slim_df(df)
    records = _df_to_records(df)
    result = {"symbol": symbol, "indicators": records, "source": _src}
    cache.set(cache_key, result, TTL_FINANCIAL)
    return result


def get_growth_rates(symbol: str, num_periods: int = 8) -> dict[str, Any]:
    """成长性指标（营收增长率/净利润增长率等）。"""
    symbol = normalize_symbol(symbol)
    cache_key = f"growth_rates:{symbol}:{num_periods}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    df, _src = _router.route("financial_stmt", endpoint="indicator", symbol=symbol)
    if df is None or df.empty:
        raise ValueError(f"增长指标数据为空 ({symbol})")
    growth_cols = [
        c for c in df.columns
        if "增长" in c or "同比" in c or "环比" in c or "日期" in c or "报告" in c
    ]
    if not growth_cols:
        raise ValueError(
            f"未在返回数据中找到增长指标列 (实际列: {list(df.columns)[:10]}...)，"
            "数据源表结构可能已变化"
        )
    df = df[growth_cols]
    if num_periods > 0:
        df = df.head(num_periods)
    df = slim_df(df)
    records = _df_to_records(df)
    result = {"symbol": symbol, "growth": records, "source": _src}
    cache.set(cache_key, result, TTL_FINANCIAL)
    return result


def get_per_share_data(symbol: str, num_periods: int = 8) -> dict[str, Any]:
    """每股指标（EPS/BPS/CFPS）。"""
    symbol = normalize_symbol(symbol)
    cache_key = f"per_share:{symbol}:{num_periods}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    df, _src = _router.route("financial_stmt", endpoint="indicator", symbol=symbol)
    if df is None or df.empty:
        raise ValueError(f"每股指标数据为空 ({symbol})")
    share_cols = [c for c in df.columns if "每股" in c or "日期" in c or "报告" in c]
    if not share_cols:
        raise ValueError(
            f"未在返回数据中找到每股指标列 (实际列: {list(df.columns)[:10]}...)，"
            "数据源表结构可能已变化"
        )
    df = df[share_cols]
    if num_periods > 0:
        df = df.head(num_periods)
    df = slim_df(df)
    records = _df_to_records(df)
    result = {"symbol": symbol, "per_share": records, "source": _src}
    cache.set(cache_key, result, TTL_FINANCIAL)
    return result


def get_segments_revenue(symbol: str) -> dict[str, Any]:
    """主营业务构成（按产品/地区分拆营收）。"""
    symbol = normalize_symbol(symbol)
    em_symbol = format_em_symbol(symbol)
    cache_key = f"segments:{symbol}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    df, _src = _router.route("financial_stmt", endpoint="segments", symbol=em_symbol)
    if df is None or df.empty:
        raise ValueError(f"主营构成数据为空 ({symbol})")
    df = slim_df(df)
    records = _df_to_records(df)
    result = {"symbol": symbol, "segments": records, "source": _src}
    cache.set(cache_key, result, TTL_FINANCIAL)
    return result
