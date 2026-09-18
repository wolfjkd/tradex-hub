"""industry_service：板块/行业类业务逻辑层（工单 07 抽出）。

从 tools/industry.py 的 @mcp.tool() 装饰器内抽出 5 个业务函数：
- get_industry_list / get_industry_stocks（核心，工单 07 指定）
- get_concept_list / get_sector_fund_flow / get_industry_pe（同领域，一并抽出）
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from ..data_sources import get_router
from ..utils.cache import TTL_DAILY, cache
from ..utils.formatter import df_to_json, slim_df

logger = logging.getLogger(__name__)
_router = get_router()


def _df_to_records(df: pd.DataFrame, max_rows: int | None = None) -> list[dict]:
    if df is None or df.empty:
        return []
    if max_rows is not None:
        df = df.head(max_rows)
    return df.where(pd.notnull(df), None).to_dict(orient="records")


def get_industry_list() -> dict[str, Any]:
    """行业板块列表（板块名/涨跌幅/总市值/换手率/领涨股）。"""
    cache_key = "industry_list"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    for ep in ["board_industry_name_em", "board_industry_name_ths"]:
        try:
            df, _src = _router.route("industry_data", endpoint=ep)
            if df is not None and not df.empty:
                records = _df_to_records(df)
                result = {"industries": records, "source": _src, "endpoint": ep}
                cache.set(cache_key, result, TTL_DAILY)
                return result
        except Exception:
            continue

    raise RuntimeError("获取行业板块列表失败: 所有数据源均不可用")


def get_industry_stocks(industry: str) -> dict[str, Any]:
    """指定行业板块的成分股列表。

    Args:
        industry: 行业名（如"白酒"/"银行"/"半导体"）。

    Returns:
        dict：含 industry/stocks（成分股列表）。

    Raises:
        Exception: 数据源异常。
    """
    cache_key = f"industry_stocks:{industry}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    df, _src = _router.route(
        "industry_data", endpoint="board_industry_cons_em", industry=industry
    )
    df = slim_df(df)
    records = _df_to_records(df)
    result = {"industry": industry, "stocks": records, "source": _src}
    cache.set(cache_key, result, TTL_DAILY)
    return result


def get_concept_list() -> dict[str, Any]:
    """概念板块列表（华为概念/ChatGPT/锂电池/芯片/光伏等）。"""
    cache_key = "concept_list"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    for ep in ["board_concept_name_em", "board_concept_name_ths"]:
        try:
            df, _src = _router.route("industry_data", endpoint=ep)
            if df is not None and not df.empty:
                records = _df_to_records(df)
                result = {"concepts": records, "source": _src, "endpoint": ep}
                cache.set(cache_key, result, TTL_DAILY)
                return result
        except Exception:
            continue

    raise RuntimeError("获取概念板块列表失败: 所有数据源均不可用")


def get_sector_fund_flow(
    sector_type: str = "行业资金流", indicator: str = "今日"
) -> dict[str, Any]:
    """板块资金流向排名。

    Args:
        sector_type: "行业资金流"/"概念资金流"/"地域资金流"。
        indicator: "今日"/"5日"/"10日"。

    Returns:
        dict：含 sector_type/flows（排名列表）。
    """
    cache_key = f"sector_fund_flow:{sector_type}:{indicator}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    df = None
    fallback_note = None
    try:
        df, _src = _router.route(
            "industry_data",
            endpoint="sector_fund_flow_rank",
            sector_type=sector_type,
            indicator=indicator,
        )
    except Exception:
        pass

    if df is None or df.empty:
        # Fallback: 新浪板块行情（不含资金流明细）
        try:
            import akshare as ak
            sina_df = ak.stock_sector_spot()
            if sina_df is not None and not sina_df.empty:
                _col_map = {
                    "板块": "板块", "涨跌幅": "涨跌幅", "涨跌额": "涨跌额",
                    "总成交额": "总成交额", "总成交量": "总成交量",
                    "公司家数": "公司家数", "平均价格": "平均价格",
                }
                keep = [c for c in _col_map if c in sina_df.columns]
                df = sina_df[keep].rename(
                    columns={k: v for k, v in _col_map.items() if k in keep}
                )
                fallback_note = "新浪财经（备源-无资金流明细）"
        except Exception:
            pass

    if df is None or df.empty:
        result = {
            "sector_type": sector_type,
            "indicator": indicator,
            "flows": [],
            "message": f"板块资金流向暂不可用 ({sector_type})",
        }
        cache.set(cache_key, result, TTL_DAILY)
        return result

    records = _df_to_records(df, max_rows=30)
    result = {
        "sector_type": sector_type,
        "indicator": indicator,
        "flows": records,
        "fallback": fallback_note,
    }
    cache.set(cache_key, result, TTL_DAILY)
    return result


def get_industry_pe(
    industry: str, start_date: str = "", end_date: str = ""
) -> dict[str, Any]:
    """行业板块历史行情数据（用于计算 PE 估值趋势）。"""
    cache_key = f"industry_pe:{industry}:{start_date}:{end_date}"
    cached = cache.get(cache_key)
    if cached is not None:
        import json
        return json.loads(cached) if isinstance(cached, str) else cached

    df, _src = _router.route(
        "industry_data",
        endpoint="board_industry_hist_em",
        industry=industry,
        period="日k",
        start_date=start_date,
        end_date=end_date,
    )
    records = _df_to_records(df, max_rows=250)
    result = {
        "industry": industry,
        "start_date": start_date,
        "end_date": end_date,
        "bars": records,
        "source": _src,
    }
    cache.set(cache_key, result, TTL_DAILY)
    return result
