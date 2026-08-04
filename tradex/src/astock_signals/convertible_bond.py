"""
可转债数据模块 — 基于 AKShare 现成接口。

提供可转债实时行情、基本信息、转股溢价率、到期收益率、价值分析等能力。
一主一备：AKShare(东财 bond_zh_cov)为主力源，bond_cb_jsl(集思录)为备用源。
"""

from __future__ import annotations

import json as _json
import logging
from datetime import datetime
from typing import Optional

import akshare as ak
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 可转债实时行情（全部）
# ---------------------------------------------------------------------------

def get_cb_realtime(top_n: int = 50, sort_by: str = "成交额") -> list[dict]:
    """获取所有可转债实时行情（东财 bond_zh_cov）。

    Args:
        top_n: 返回前 N 只可转债
        sort_by: 排序字段，默认成交额

    Returns:
        list of dicts with bond_code/bond_name/price/change_pct/
        stock_code/stock_name/stock_price/conversion_price/
        conversion_value/conversion_premium/credit_rating 等
    """
    try:
        df = ak.bond_zh_cov()
        if df is None or df.empty:
            return []

        # 精确匹配列名（避免子串匹配导致多列映射同名）
        _EXACT_MAP = {
            "债券代码": "bond_code",
            "债券简称": "bond_name",
            "正股代码": "stock_code",
            "正股简称": "stock_name",
            "正股价": "stock_price",
            "转股价": "conversion_price",
            "转股价值": "conversion_value",
            "债现价": "bond_price",
            "转股溢价率(%)": "conversion_premium",
            "转股溢价率": "conversion_premium",
            "信用评级": "credit_rating",
            "评级": "credit_rating",
        }
        col_map = {}
        seen_targets = set()
        for col in df.columns:
            col_str = str(col).strip()
            target = _EXACT_MAP.get(col_str)
            if target and target not in seen_targets:
                col_map[col] = target
                seen_targets.add(target)

        df = df.rename(columns=col_map)
        # 去除重名列（防止 AKShare 返回含重复列名的 DataFrame）
        df = df.loc[:, ~df.columns.duplicated()]

        # 排序
        if sort_by == "转股溢价率" and "conversion_premium" in df.columns:
            df["conversion_premium"] = pd.to_numeric(df["conversion_premium"], errors="coerce")
            df = df.sort_values("conversion_premium", ascending=True)
        elif sort_by == "成交额" and "成交额" in df.columns:
            df = df.sort_values("成交额", ascending=False)

        df = df.head(top_n)
        records = df.to_dict("records")
        for r in records:
            for k, v in list(r.items()):
                if isinstance(v, float) and pd.isna(v):
                    r[k] = None
        return records

    except Exception as e:
        logger.error("get_cb_realtime failed: %s", e)
        return []


def get_cb_realtime_json(top_n: int = 50, sort_by: str = "成交额") -> dict:
    """获取可转债实时行情，返回结构化 dict。"""
    return {
        "source": "AKShare (东财 bond_zh_cov)",
        "data_type": "cb_realtime",
        "timestamp": datetime.now().isoformat(),
        "top_n": top_n,
        "sort_by": sort_by,
        "bonds": get_cb_realtime(top_n, sort_by),
    }


# ---------------------------------------------------------------------------
# 可转债价值分析（历史转股溢价率曲线）
# ---------------------------------------------------------------------------

def get_cb_value_analysis(symbol: str, days: int = 30) -> list[dict]:
    """获取可转债价值分析数据（转股溢价率历史曲线）。

    Args:
        symbol: 可转债代码，如 '113527'
        days: 返回最近 N 天数据

    Returns:
        list of dicts with date/close/conversion_value/bond_premium/conversion_premium
    """
    try:
        df = ak.bond_zh_cov_value_analysis(symbol=symbol)
        if df is None or df.empty:
            return []

        col_map = {}
        for col in df.columns:
            col_str = str(col)
            if "日期" in col_str:
                col_map[col] = "date"
            elif "收盘价" in col_str:
                col_map[col] = "close"
            elif "纯债价值" in col_str:
                col_map[col] = "bond_value"
            elif "转股价值" in col_str:
                col_map[col] = "conversion_value"
            elif "纯债溢价率" in col_str:
                col_map[col] = "bond_premium"
            elif "转股溢价率" in col_str:
                col_map[col] = "conversion_premium"

        df = df.rename(columns=col_map)
        df["date"] = df["date"].astype(str)
        df = df.tail(days)
        records = df.to_dict("records")
        for r in records:
            for k, v in list(r.items()):
                if isinstance(v, float) and pd.isna(v):
                    r[k] = None
        return records

    except Exception as e:
        logger.error("get_cb_value_analysis(%s) failed: %s", symbol, e)
        return []


def get_cb_value_analysis_json(symbol: str, days: int = 30) -> dict:
    """获取可转债价值分析，返回结构化 dict。"""
    return {
        "source": "AKShare (东财)",
        "data_type": "cb_value_analysis",
        "symbol": symbol,
        "days": days,
        "history": get_cb_value_analysis(symbol, days),
    }


# ---------------------------------------------------------------------------
# 可转债比价表（含转股溢价率、纯债价值等）
# ---------------------------------------------------------------------------

def get_cb_comparison(top_n: int = 50) -> list[dict]:
    """获取可转债比价表（东财 bond_cov_comparison）。

    Returns:
        list of dicts with bond_code/bond_name/bond_price/stock_code/
        stock_name/conversion_price/conversion_value/conversion_premium/
        bond_value 等
    """
    try:
        df = ak.bond_cov_comparison()
        if df is None or df.empty:
            return []

        _EXACT_MAP = {
            "转债代码": "bond_code",
            "转债名称": "bond_name",
            "转债最新价": "bond_price",
            "正股代码": "stock_code",
            "正股名称": "stock_name",
            "转股价": "conversion_price",
            "转股价值": "conversion_value",
            "转股溢价率(%)": "conversion_premium",
            "转股溢价率": "conversion_premium",
            "纯债价值": "bond_value",
        }
        col_map = {}
        seen_targets = set()
        for col in df.columns:
            col_str = str(col).strip()
            target = _EXACT_MAP.get(col_str)
            if target and target not in seen_targets:
                col_map[col] = target
                seen_targets.add(target)

        df = df.rename(columns=col_map)
        df = df.loc[:, ~df.columns.duplicated()]
        df = df.head(top_n)
        records = df.to_dict("records")
        for r in records:
            for k, v in list(r.items()):
                if isinstance(v, float) and pd.isna(v):
                    r[k] = None
        return records

    except Exception as e:
        logger.error("get_cb_comparison failed: %s", e)
        return []


def get_cb_comparison_json(top_n: int = 50) -> dict:
    """获取可转债比价表，返回结构化 dict。"""
    return {
        "source": "AKShare (东财 bond_cov_comparison)",
        "data_type": "cb_comparison",
        "timestamp": datetime.now().isoformat(),
        "top_n": top_n,
        "bonds": get_cb_comparison(top_n),
    }


# ---------------------------------------------------------------------------
# 可转债详情（基本信息/中签号/筹资用途/重要日期）
# ---------------------------------------------------------------------------

def get_cb_info(symbol: str, indicator: str = "基本信息") -> list[dict]:
    """获取可转债详细信息。

    Args:
        symbol: 可转债代码，如 '123121'
        indicator: 信息类型 (基本信息/中签号/筹资用途/重要日期)

    Returns:
        list of dicts
    """
    try:
        df = ak.bond_zh_cov_info(symbol=symbol, indicator=indicator)
        if df is None or df.empty:
            return []
        records = df.to_dict("records")
        for r in records:
            for k, v in list(r.items()):
                if isinstance(v, float) and pd.isna(v):
                    r[k] = None
        return records

    except Exception as e:
        logger.error("get_cb_info(%s, %s) failed: %s", symbol, indicator, e)
        return []


def get_cb_info_json(symbol: str, indicator: str = "基本信息") -> dict:
    """获取可转债详情，返回结构化 dict。"""
    return {
        "source": "AKShare (东财)",
        "data_type": "cb_info",
        "symbol": symbol,
        "indicator": indicator,
        "data": get_cb_info(symbol, indicator),
    }
