"""company_service：公司基本信息业务逻辑层（工单 05 抽出）。

从 tools/company_info.py 的 @mcp.tool() 装饰器内抽出核心业务逻辑为纯函数。
MCP 工具和 REST 路由各自薄包装，共享同一份代码（契约一致性）。

覆盖工具：
- search_stock（搜索）
- get_company_info（基本信息）
- get_company_profile（主营构成）
- get_competitors（同行业）
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from ..data_sources import get_router
from ..utils.cache import TTL_COMPANY, cache
from ..utils.formatter import df_to_json, dict_to_json, slim_df

logger = logging.getLogger(__name__)
_router = get_router()


def _find_code_col(df) -> str:
    """Find the stock code column in a DataFrame."""
    for c in df.columns:
        if c in ("代码", "code", "symbol"):
            return c
        if "代码" in c or "code" in c.lower() or "symbol" in c.lower():
            return c
    return df.columns[0]


def search_stock(keyword: str) -> dict[str, Any]:
    """按名称或代码模糊搜索 A 股股票。

    Args:
        keyword: 股票名称（如"贵州茅台"）或代码（如"600519"）。

    Returns:
        dict：含 matches（list of {code, name}，最多 20 条）。

    Raises:
        Exception: 数据源异常时向上抛。
    """
    cache_key = f"search_stock:{keyword}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    df, _src = _router.route("company_info", endpoint="code_name")
    mask = df["code"].str.contains(keyword, case=False, na=False) | df[
        "name"
    ].str.contains(keyword, case=False, na=False)
    matched = df[mask].head(20)
    records = matched.where(pd.notnull(matched), None).to_dict(orient="records")
    result = {"keyword": keyword, "matches": records, "source": _src}
    cache.set(cache_key, result, TTL_COMPANY)
    return result


def get_company_info(symbol: str) -> dict[str, Any]:
    """公司基本信息（行业/市值/股本等）。

    Args:
        symbol: 6 位股票代码。

    Returns:
        dict：公司基本字段集。

    Raises:
        ValueError: 未找到股票。
        Exception: 数据源异常。
    """
    from ..utils.symbol import normalize_symbol
    symbol = normalize_symbol(symbol)
    cache_key = f"company_info:{symbol}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    # Primary: 东方财富个股信息
    try:
        df, _src = _router.route(
            "company_info", endpoint="individual_info", symbol=symbol
        )
        if df is not None and not df.empty:
            info = {}
            for _, row in df.iterrows():
                info[row.iloc[0]] = row.iloc[1]
            if info:
                result = {"symbol": symbol, "info": info, "source": _src}
                cache.set(cache_key, result, TTL_COMPANY)
                return result
    except Exception as e:
        logger.debug("company_info primary 失败(%s): %s", symbol, e)

    # Fallback: 全量行情列表提取
    df, _src = _router.route("realtime_quote", symbol="")
    code_col = _find_code_col(df)
    row = df[df[code_col].astype(str).str.strip() == symbol]
    if row.empty:
        raise ValueError(f"未找到股票 {symbol} 的公司信息")
    records = row.where(pd.notnull(row), None).to_dict(orient="records")
    result = {"symbol": symbol, "info": records[0] if records else {}, "source": _src}
    cache.set(cache_key, result, TTL_COMPANY)
    return result


def get_company_profile(symbol: str) -> dict[str, Any]:
    """公司主营业务构成。

    Args:
        symbol: 6 位股票代码。

    Returns:
        dict：含 segments（主营构成列表）。

    Raises:
        Exception: 数据源异常。
    """
    from ..utils.symbol import normalize_symbol
    symbol = normalize_symbol(symbol)
    cache_key = f"company_profile:{symbol}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    df, _src = _router.route("company_info", endpoint="profile", symbol=symbol)
    if df is None or df.empty:
        result = {"symbol": symbol, "segments": [], "source": _src}
    else:
        records = df.where(pd.notnull(df), None).to_dict(orient="records")
        result = {"symbol": symbol, "segments": records, "source": _src}
    cache.set(cache_key, result, TTL_COMPANY)
    return result


def get_competitors(symbol: str, industry: str = "") -> dict[str, Any]:
    """同行业竞争对手列表。

    Args:
        symbol: 6 位股票代码（若提供 industry 则忽略此参数推断）。
        industry: 行业板块名称（如"白酒"）；空则从 symbol 推断。

    Returns:
        dict：含 industry（推断出的行业名）+ peers（同行业公司列表）。

    Raises:
        ValueError: 无法确定行业。
        Exception: 数据源异常。
    """
    from ..utils.symbol import normalize_symbol
    symbol = normalize_symbol(symbol)
    cache_key = f"competitors:{symbol}:{industry}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    # 行业推断
    if not industry:
        try:
            df, _src = _router.route(
                "company_info", endpoint="individual_info", symbol=symbol
            )
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    key = str(row.iloc[0])
                    if "行业" in key:
                        industry = str(row.iloc[1])
                        break
        except Exception:
            pass

    if not industry:
        try:
            board_df, _src = _router.route(
                "industry_data", endpoint="board_industry_name_em"
            )
            if board_df is not None and not board_df.empty:
                spot_df, _src2 = _router.route("realtime_quote", symbol="")
                if spot_df is not None and not spot_df.empty:
                    code_col = _find_code_col(spot_df)
                    row = spot_df[spot_df[code_col].astype(str).str.strip() == symbol]
                    if not row.empty:
                        for c in row.columns:
                            if "行业" in c or "板块" in c:
                                industry = str(row.iloc[0][c])
                                break
        except Exception:
            pass

    if not industry:
        raise ValueError(f"无法确定 {symbol} 所属行业，请手动传入 industry 参数")

    df, _src = _router.route(
        "industry_data", endpoint="board_industry_cons_em", industry=industry
    )
    df = slim_df(df)
    records = df.where(pd.notnull(df), None).to_dict(orient="records")[:30]
    result = {"symbol": symbol, "industry": industry, "peers": records, "source": _src}
    cache.set(cache_key, result, TTL_COMPANY)
    return result
