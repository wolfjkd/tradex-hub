"""
baostock 数据源 fetch_fn 包装器（TCP 协议，零鉴权）。

提供以下 fetcher：
  - fetch_baostock_valuation_history: 估值历史（PE/PB/PS/股息率）
  - fetch_baostock_delisting_date:    上市/退市日期
  - fetch_baostock_st_list:           ST 名单（兜底）

作为 valuation 的独立 TCP 备源（priority=200），与 akshare(HTTP 抓东财)/eltdx(TCP) 完全独立。
注意：baostock 不支持北交所股票，遇到北交所代码时优雅返回空。

借鉴：simonlin1212/a-stock-data 的 §6.5 / §6.6 / §6.8 端点实现思路。
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger("tradex.baostock")

# baostock 是可选依赖（TCP 库，需要安装 baostock）
_BAOSTOCK_AVAILABLE = False
try:
    import baostock as bs
    _BAOSTOCK_AVAILABLE = True
except ImportError:
    logger.debug("baostock not installed; baostock_* fetchers will return empty")


# 模块级登录状态（baostock 需 login 才能查询）
_logged_in = False


def _ensure_login() -> bool:
    """确保 baostock 已登录。返回是否可用。"""
    global _logged_in
    if not _BAOSTOCK_AVAILABLE:
        return False
    if not _logged_in:
        try:
            lg = bs.login()
            if lg.error_code == "0":
                _logged_in = True
            else:
                logger.warning("baostock login failed: %s", lg.error_msg)
                return False
        except Exception as e:
            logger.warning("baostock login exception: %s", e)
            return False
    return True


def _normalize_to_baostock(symbol: str) -> str | None:
    """将 6 位代码转换为 baostock 格式：sh.600519 / sz.000001。
    返回 None 表示不支持的代码（如北交所）。
    """
    sym = symbol.strip().lower()
    if not sym or len(sym) != 6 or not sym.isdigit():
        return None
    if sym.startswith("6"):
        return f"sh.{sym}"
    if sym.startswith(("0", "3")):
        return f"sz.{sym}"
    # 北交所不支持
    return None


# ============================================================
# 估值历史 — baostock_valuation_history
# ============================================================

def fetch_baostock_valuation_history(
    symbol: str = "",
    code: str = "",
    start_date: str = "",
    end_date: str = "",
    **kwargs,
) -> pd.DataFrame:
    """baostock 估值历史（PE/PB/PS/股息率），作为 valuation 的独立 TCP 备源。

    与 akshare(抓东财)、eltdx 完全独立。零鉴权，免费。

    Args:
        symbol: 6 位股票代码
        code: 6 位股票代码（别名）
        start_date: 起始日期 YYYY-MM-DD，默认 1 年前
        end_date: 截止日期 YYYY-MM-DD，默认今天

    Returns:
        DataFrame with columns: 日期, PE(TTM), PB, PS(TTM), 股息率
    """
    sym = symbol or code
    if not sym:
        raise ValueError("stock code is required")

    if not _ensure_login():
        logger.warning("baostock unavailable; valuation_history returns empty")
        return pd.DataFrame()

    bs_code = _normalize_to_baostock(sym)
    if bs_code is None:
        logger.warning("baostock does not support code: %s (北交所?)", sym)
        return pd.DataFrame()

    try:
        from datetime import datetime, timedelta
        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")
        if not start_date:
            start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,peTTM,pbMRQ,psTTM,pcfNcfTTM",
            start_date=start_date,
            end_date=end_date,
            frequency="d",
        )
        if rs.error_code != "0":
            logger.warning("baostock query failed: %s", rs.error_msg)
            return pd.DataFrame()

        rows = []
        while rs.next():
            row = rs.get_row_data()
            if len(row) >= 4:
                try:
                    rows.append({
                        "日期": row[0],
                        "PE(TTM)": float(row[1]) if row[1] else 0,
                        "PB": float(row[2]) if row[2] else 0,
                        "PS(TTM)": float(row[3]) if row[3] else 0,
                    })
                except ValueError:
                    continue

        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df = df[df["PE(TTM)"] > 0].reset_index(drop=True)
        return df

    except Exception as e:
        logger.warning("fetch_baostock_valuation_history(%s) failed: %s", sym, e)
        return pd.DataFrame()


# ============================================================
# 上市/退市日期 — baostock_delisting_date
# ============================================================

def fetch_baostock_delisting_date(
    symbol: str = "",
    code: str = "",
    **kwargs,
) -> pd.DataFrame:
    """baostock 查询上市日期 / 退市日期。

    baostock 是少数零鉴权可拿退市日期的源（用于历史回测时过滤已退市股票）。

    Returns:
        DataFrame with columns: 代码, 上市日期, 退市日期(空表示在市)
    """
    sym = symbol or code
    if not sym:
        raise ValueError("stock code is required")

    if not _ensure_login():
        return pd.DataFrame()

    bs_code = _normalize_to_baostock(sym)
    if bs_code is None:
        return pd.DataFrame()

    try:
        rs = bs.query_stock_basic(code=bs_code)
        if rs.error_code != "0":
            return pd.DataFrame()

        rows = []
        while rs.next():
            row = rs.get_row_data()
            # baostock: code, code_name,IPOdate, outDate, type, status
            if len(row) >= 5:
                rows.append({
                    "代码": sym,
                    "名称": row[1] if row[1] else "",
                    "上市日期": row[2] if row[2] else "",
                    "退市日期": row[3] if row[3] else "",
                    "状态": "在市" if row[4] == "1" else "退市",
                })
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)

    except Exception as e:
        logger.warning("fetch_baostock_delisting_date(%s) failed: %s", sym, e)
        return pd.DataFrame()


# ============================================================
# ST 名单（兜底）— baostock_st_list
# ============================================================

def fetch_baostock_st_list(**kwargs) -> pd.DataFrame:
    """baostock ST 股票名单（兜底源，作为 st_stock_list 的第二备源）。

    通过查询全市场股票 status，过滤名称含 ST 的股票。

    Returns:
        DataFrame with columns: 代码, 名称, 上市日期
    """
    if not _ensure_login():
        return pd.DataFrame()

    try:
        # baostock 查询全部 A 股
        rs = bs.query_stock_basic()
        if rs.error_code != "0":
            return pd.DataFrame()

        rows = []
        while rs.next():
            row = rs.get_row_data()
            if len(row) >= 3:
                name = (row[1] or "").upper()
                if "ST" in name or "*ST" in name:
                    code = (row[0] or "").replace("sh.", "").replace("sz.", "")
                    rows.append({
                        "代码": code,
                        "名称": row[1] or "",
                        "上市日期": row[2] if len(row) > 2 else "",
                    })
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)

    except Exception as e:
        logger.warning("fetch_baostock_st_list failed: %s", e)
        return pd.DataFrame()


def cleanup() -> None:
    """退出前调用，登出 baostock 释放连接。"""
    global _logged_in
    if _logged_in and _BAOSTOCK_AVAILABLE:
        try:
            bs.logout()
            _logged_in = False
        except Exception:
            pass
