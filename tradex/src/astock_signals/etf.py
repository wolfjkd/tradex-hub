"""
ETF 数据模块 — 基于 AKShare 现成接口。

提供 ETF 实时行情、历史K线、分时数据、ETF列表等能力。
一主一备：AKShare(东财)为主力源，新浪为备用源。
"""

from __future__ import annotations

import json as _json
import logging
from datetime import datetime, timedelta
from typing import Optional

import akshare as ak
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ETF 实时行情
# ---------------------------------------------------------------------------

def get_etf_realtime(top_n: int = 50, sort_by: str = "成交额") -> list[dict]:
    """获取所有 ETF 实时行情（东财），按成交额排序。

    Args:
        top_n: 返回前 N 只 ETF
        sort_by: 排序字段，默认成交额

    Returns:
        list of dicts with etf_code/name/price/change_pct/volume/amount/turnover/iopv 等
    """
    try:
        df = ak.fund_etf_spot_em()
        if df is None or df.empty:
            return []

        # 去重列名（东财接口偶尔返回重复列，触发 pandas warning）
        df = df.loc[:, ~df.columns.duplicated()]

        # 标准化列名
        col_map = {}
        for col in df.columns:
            if "代码" in str(col):
                col_map[col] = "etf_code"
            elif "名称" in str(col):
                col_map[col] = "name"
            elif "最新" in str(col) or "最新价" in str(col):
                col_map[col] = "price"
            elif "涨跌幅" in str(col):
                col_map[col] = "change_pct"
            elif "涨跌额" in str(col):
                col_map[col] = "change_amt"
            elif "成交量" in str(col):
                col_map[col] = "volume"
            elif "成交额" in str(col):
                col_map[col] = "amount"
            elif "换手率" in str(col):
                col_map[col] = "turnover"
            elif "IOPV" in str(col):
                col_map[col] = "iopv"
            elif "开盘" in str(col):
                col_map[col] = "open"
            elif "最高" in str(col):
                col_map[col] = "high"
            elif "最低" in str(col):
                col_map[col] = "low"
            elif "昨收" in str(col):
                col_map[col] = "prev_close"

        df = df.rename(columns=col_map)

        # 去重列名（rename 后可能产生重复列名，如多个原始列映射到同一新列名）
        df = df.loc[:, ~df.columns.duplicated()]

        # 排序
        if sort_by == "成交额" and "amount" in df.columns:
            df = df.sort_values("amount", ascending=False)
        elif sort_by == "涨跌幅" and "change_pct" in df.columns:
            df = df.sort_values("change_pct", ascending=False)

        df = df.head(top_n)
        records = df.to_dict("records")
        # 清理 NaN
        for r in records:
            for k, v in list(r.items()):
                if pd.isna(v) if isinstance(v, float) else False:
                    r[k] = None
        return records

    except Exception as e:
        logger.error("get_etf_realtime failed: %s", e)
        return []


def get_etf_realtime_json(top_n: int = 50, sort_by: str = "成交额") -> dict:
    """获取 ETF 实时行情，返回结构化 dict。"""
    return {
        "source": "AKShare (东财)",
        "data_type": "etf_realtime",
        "timestamp": datetime.now().isoformat(),
        "top_n": top_n,
        "sort_by": sort_by,
        "etfs": get_etf_realtime(top_n, sort_by),
    }


# ---------------------------------------------------------------------------
# ETF 历史K线
# ---------------------------------------------------------------------------

def get_etf_kline(
    symbol: str,
    period: str = "daily",
    start_date: str = "",
    end_date: str = "",
    adjust: str = "",
) -> list[dict]:
    """获取 ETF 历史 K 线数据。

    Args:
        symbol: ETF 代码，如 '513500'
        period: daily/weekly/monthly
        start_date: 开始日期 YYYYMMDD，默认近1年
        end_date: 结束日期 YYYYMMDD，默认今天
        adjust: 复权方式 (''不复权, 'qfq'前复权, 'hfq'后复权)

    Returns:
        list of dicts with date/open/close/high/low/volume/amount/change_pct
    """
    if not start_date:
        start_date = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")
    if not end_date:
        end_date = datetime.now().strftime("%Y%m%d")

    try:
        df = ak.fund_etf_hist_em(
            symbol=symbol, period=period,
            start_date=start_date, end_date=end_date, adjust=adjust,
        )
        if df is None or df.empty:
            return []

        col_map = {}
        for col in df.columns:
            if "日期" in str(col):
                col_map[col] = "date"
            elif "开盘" in str(col):
                col_map[col] = "open"
            elif "收盘" in str(col):
                col_map[col] = "close"
            elif "最高" in str(col):
                col_map[col] = "high"
            elif "最低" in str(col):
                col_map[col] = "low"
            elif "成交量" in str(col):
                col_map[col] = "volume"
            elif "成交额" in str(col):
                col_map[col] = "amount"
            elif "涨跌幅" in str(col):
                col_map[col] = "change_pct"
            elif "振幅" in str(col):
                col_map[col] = "amplitude"
            elif "换手率" in str(col):
                col_map[col] = "turnover"

        df = df.rename(columns=col_map)
        df["date"] = df["date"].astype(str)
        records = df.to_dict("records")
        for r in records:
            for k, v in list(r.items()):
                if isinstance(v, float) and pd.isna(v):
                    r[k] = None
        return records

    except Exception as e:
        logger.error("get_etf_kline(%s) failed: %s", symbol, e)
        return []


def get_etf_kline_json(
    symbol: str, period: str = "daily",
    start_date: str = "", end_date: str = "", adjust: str = "",
) -> dict:
    """获取 ETF K线数据，返回结构化 dict。"""
    return {
        "source": "AKShare (东财)",
        "data_type": "etf_kline",
        "symbol": symbol,
        "period": period,
        "adjust": adjust,
        "klines": get_etf_kline(symbol, period, start_date, end_date, adjust),
    }


# ---------------------------------------------------------------------------
# ETF 列表 / 搜索
# ---------------------------------------------------------------------------

def get_etf_list(top_n: int = 100) -> list[dict]:
    """获取 ETF 列表（按成交额排序）。

    Returns:
        list of dicts with code/name/price/change_pct/amount
    """
    try:
        df = ak.fund_etf_category_sina(symbol="ETF基金")
        if df is None or df.empty:
            return []

        col_map = {}
        for col in df.columns:
            if "代码" in str(col):
                col_map[col] = "code"
            elif "名称" in str(col):
                col_map[col] = "name"
            elif "最新价" in str(col):
                col_map[col] = "price"
            elif "涨跌幅" in str(col):
                col_map[col] = "change_pct"
            elif "成交额" in str(col):
                col_map[col] = "amount"
        df = df.rename(columns=col_map)

        if "amount" in df.columns:
            df = df.sort_values("amount", ascending=False)
        df = df.head(top_n)
        records = df.to_dict("records")
        for r in records:
            for k, v in list(r.items()):
                if isinstance(v, float) and pd.isna(v):
                    r[k] = None
        return records

    except Exception as e:
        logger.error("get_etf_list failed: %s", e)
        return []


def get_etf_list_json(top_n: int = 100) -> dict:
    """获取 ETF 列表，返回结构化 dict。"""
    return {
        "source": "AKShare (新浪)",
        "data_type": "etf_list",
        "timestamp": datetime.now().isoformat(),
        "top_n": top_n,
        "etfs": get_etf_list(top_n),
    }
