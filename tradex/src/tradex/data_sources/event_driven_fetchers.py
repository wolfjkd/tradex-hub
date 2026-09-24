"""
事件驱动数据源 fetch_fn 包装器（东财 datacenter）。

提供以下 fetcher（均通过 em_client 限流，避免封禁）：
  - fetch_earnings_forecast:   业绩预告
  - fetch_institution_survey:  机构调研
  - fetch_holder_trades:       股东增减持
  - fetch_share_buyback:       股票回购
  - fetch_equity_pledge:       股权质押
  - fetch_ipo_calendar:        新股申购日历

设计原则：
  - 全部走东财 datacenter-web，复用 em_client 限流策略
  - 失败时返回空 DataFrame，不抛异常
  - 与已有东财端点共享 em_client 单例

借鉴：simonlin1212/a-stock-data 的 §14 事件驱动层 6 个端点实现思路。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from .em_client import em_get  # 复用东财限流客户端

logger = logging.getLogger("tradex.event")

_PAGE_SIZE = 50


# ============================================================
# 业绩预告 — earnings_forecast
# ============================================================

def fetch_earnings_forecast(
    symbol: str = "",
    code: str = "",
    report_date: str = "",
    limit: int = 50,
    **kwargs,
) -> pd.DataFrame:
    """业绩预告（东财 datacenter）。

    Args:
        symbol: 6 位股票代码
        report_date: 报告期 YYYY-MM-DD（如 2024-12-31），留空则取最近
        limit: 返回条数

    Returns:
        DataFrame with columns: 代码, 预测类型(预增/预减/扭亏/续亏等), 预测净利润下限,
                                预测净利润上限, 预测净利润同比, 报告期, 公告日期
    """
    sym = (symbol or code or "").strip()
    try:
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        params = {
            "reportName": "RPT_LICO_FN_CPD",
            "columns": "ALL",
            "filter": f"(SECURITY_CODE=\"{sym}\")",
            "pageNumber": "1",
            "pageSize": str(min(max(limit, 1), 200)),
            "sortColumns": "NOTICE_DATE",
            "sortTypes": "-1",
        }
        if report_date:
            params["filter"] = f"(SECURITY_CODE=\"{sym}\")(REPORT_DATE='{report_date}')"

        data = em_get(url, params=params).json().json()
        rows_raw = (data.get("result") or {}).get("data", [])
        if not rows_raw:
            return pd.DataFrame()

        rows = []
        for it in rows_raw:
            rows.append({
                "代码": (it.get("SECURITY_CODE") or "").strip(),
                "预测类型": (it.get("PREDICT_TYPE") or "").strip(),
                "预测净利润下限": float(it.get("MIN_PROFIT") or 0),
                "预测净利润上限": float(it.get("MAX_PROFIT") or 0),
                "预测净利润同比": float(it.get("ADD_YPCT") or 0),
                "报告期": (it.get("REPORT_DATE") or "").split(" ")[0],
                "公告日期": (it.get("NOTICE_DATE") or "").split(" ")[0],
            })
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)

    except Exception as e:
        logger.warning("fetch_earnings_forecast(%s) failed: %s", sym, e)
        return pd.DataFrame()


# ============================================================
# 机构调研 — institution_survey
# ============================================================

def fetch_institution_survey(
    symbol: str = "",
    code: str = "",
    start_date: str = "",
    end_date: str = "",
    detail: bool = False,
    limit: int = 50,
    **kwargs,
) -> pd.DataFrame:
    """机构调研（东财 datacenter）。

    Args:
        symbol: 6 位股票代码
        start_date: 起始日期
        end_date: 截止日期
        detail: 是否返回明细（调研机构清单）
        limit: 返回条数

    Returns:
        DataFrame with columns: 代码, 公告日期, 调研机构, 调研方式, 接待人
    """
    sym = (symbol or code or "").strip()
    if not end_date:
        end_date = datetime.now().strftime("%Y-%m-%d")
    if not start_date:
        start_date = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")

    try:
        report_name = "RPT_ORG_SURVEYDET" if detail else "RPT_ORG_SURVEY"
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        params = {
            "reportName": report_name,
            "columns": "ALL",
            "filter": f"(SECURITY_CODE=\"{sym}\")(ESTARTDATE>='{start_date}')(EENDDATE<='{end_date}')",
            "pageNumber": "1",
            "pageSize": str(min(max(limit, 1), 200)),
            "sortColumns": "NOTICE_DATE",
            "sortTypes": "-1",
        }
        data = em_get(url, params=params).json().json()
        rows_raw = (data.get("result") or {}).get("data", [])
        if not rows_raw:
            return pd.DataFrame()

        rows = []
        for it in rows_raw:
            rows.append({
                "代码": (it.get("SECURITY_CODE") or "").strip(),
                "名称": (it.get("SECURITY_NAME") or "").strip(),
                "公告日期": (it.get("NOTICE_DATE") or "").split(" ")[0],
                "调研日期": (it.get("ESTARTDATE") or "").split(" ")[0],
                "调研机构": (it.get("ORG_NAME") or "").strip(),
                "调研方式": (it.get("VISIT_TYPE") or "").strip(),
                "接待人": (it.get("RECEIVE_PERSON") or "").strip(),
            })
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)

    except Exception as e:
        logger.warning("fetch_institution_survey(%s) failed: %s", sym, e)
        return pd.DataFrame()


# ============================================================
# 股东增减持 — holder_trades
# ============================================================

def fetch_holder_trades(
    symbol: str = "",
    code: str = "",
    direction: str = "",  # "" / "增持" / "减持"
    start_date: str = "",
    end_date: str = "",
    limit: int = 50,
    **kwargs,
) -> pd.DataFrame:
    """股东增减持（东财 datacenter）。

    Args:
        symbol: 6 位股票代码
        direction: 方向过滤（空=全部）
        limit: 返回条数

    Returns:
        DataFrame with columns: 代码, 变动方向, 变动股东, 变动数量, 变动比例, 公告日期
    """
    sym = (symbol or code or "").strip()
    if not end_date:
        end_date = datetime.now().strftime("%Y-%m-%d")
    if not start_date:
        start_date = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")

    try:
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        params = {
            "reportName": "RPT_SDP_HOLDERTRADE",
            "columns": "ALL",
            "filter": f"(SECURITY_CODE=\"{sym}\")(NOTICE_DATE>='{start_date}')(NOTICE_DATE<='{end_date}')",
            "pageNumber": "1",
            "pageSize": str(min(max(limit, 1), 200)),
            "sortColumns": "NOTICE_DATE",
            "sortTypes": "-1",
        }
        data = em_get(url, params=params).json()
        rows_raw = (data.get("result") or {}).get("data", [])
        if not rows_raw:
            return pd.DataFrame()

        rows = []
        for it in rows_raw:
            change_dir = (it.get("HOLDER_TYPE") or "").strip()
            if direction and change_dir != direction:
                continue
            rows.append({
                "代码": (it.get("SECURITY_CODE") or "").strip(),
                "名称": (it.get("SECURITY_NAME") or "").strip(),
                "变动方向": "增持" if "增" in change_dir else "减持",
                "变动股东": (it.get("HOLDER_NAME") or "").strip(),
                "变动数量": float(it.get("CHANGE_NUM") or 0),
                "变动比例": float(it.get("CHANGE_PCT") or 0),
                "公告日期": (it.get("NOTICE_DATE") or "").split(" ")[0],
            })
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)

    except Exception as e:
        logger.warning("fetch_holder_trades(%s) failed: %s", sym, e)
        return pd.DataFrame()


# ============================================================
# 股票回购 — share_buyback
# ============================================================

def fetch_share_buyback(
    symbol: str = "",
    code: str = "",
    progress: str = "",  # "" / "实施中" / "完成" / "停止"
    limit: int = 50,
    **kwargs,
) -> pd.DataFrame:
    """股票回购（东财 datacenter）。

    Returns:
        DataFrame with columns: 代码, 名称, 进度, 已回购金额, 已回购数量, 公告日期
    """
    sym = (symbol or code or "").strip()
    try:
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        params = {
            "reportName": "RPT_SSR_GFBACTIVITY",
            "columns": "ALL",
            "filter": f"(SECURITY_CODE=\"{sym}\")",
            "pageNumber": "1",
            "pageSize": str(min(max(limit, 1), 200)),
            "sortColumns": "END_DATE",
            "sortTypes": "-1",
        }
        data = em_get(url, params=params).json()
        rows_raw = (data.get("result") or {}).get("data", [])
        if not rows_raw:
            return pd.DataFrame()

        rows = []
        for it in rows_raw:
            status = (it.get("PROCESS") or "").strip()
            if progress and progress not in status:
                continue
            rows.append({
                "代码": (it.get("SECURITY_CODE") or "").strip(),
                "名称": (it.get("SECURITY_NAME") or "").strip(),
                "进度": status,
                "已回购金额": float(it.get("BUY_AMOUNT") or 0),
                "已回购数量": float(it.get("BUY_NUM") or 0),
                "公告日期": (it.get("END_DATE") or "").split(" ")[0],
            })
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)

    except Exception as e:
        logger.warning("fetch_share_buyback(%s) failed: %s", sym, e)
        return pd.DataFrame()


# ============================================================
# 股权质押 — equity_pledge
# ============================================================

def fetch_equity_pledge(
    symbol: str = "",
    code: str = "",
    date: str = "",
    limit: int = 50,
    **kwargs,
) -> pd.DataFrame:
    """股权质押（东财 datacenter，周度更新）。

    Returns:
        DataFrame with columns: 代码, 名称, 质押机构, 质押数量, 质押比例, 公告日期
    """
    sym = (symbol or code or "").strip()
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    try:
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        params = {
            "reportName": "RPT_EQUITYPLEDGE",
            "columns": "ALL",
            "filter": f"(SECURITY_CODE=\"{sym}\")(END_DATE<='{date}')",
            "pageNumber": "1",
            "pageSize": str(min(max(limit, 1), 200)),
            "sortColumns": "END_DATE",
            "sortTypes": "-1",
        }
        data = em_get(url, params=params).json()
        rows_raw = (data.get("result") or {}).get("data", [])
        if not rows_raw:
            return pd.DataFrame()

        rows = []
        for it in rows_raw:
            rows.append({
                "代码": (it.get("SECURITY_CODE") or "").strip(),
                "名称": (it.get("SECURITY_NAME") or "").strip(),
                "质押机构": (it.get("PLEDGEE") or "").strip(),
                "质押数量": float(it.get("PLEDGE_NUM") or 0),
                "质押比例": float(it.get("PLEDGE_PCT") or 0),
                "公告日期": (it.get("END_DATE") or "").split(" ")[0],
            })
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)

    except Exception as e:
        logger.warning("fetch_equity_pledge(%s) failed: %s", sym, e)
        return pd.DataFrame()


# ============================================================
# 新股申购日历 — ipo_calendar
# ============================================================

def fetch_ipo_calendar(
    days_ahead: int = 30,
    limit: int = 50,
    **kwargs,
) -> pd.DataFrame:
    """新股申购日历（东财 datacenter）。

    Args:
        days_ahead: 未来天数，默认 30

    Returns:
        DataFrame with columns: 代码, 名称, 申购日期, 上市板块, 发行价, 申购上限
    """
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        end = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        params = {
            "reportName": "RPT_APPLICATION_NEW",
            "columns": "ALL",
            "filter": f"(PURCHASE_DATE>='{today}')(PURCHASE_DATE<='{end}')",
            "pageNumber": "1",
            "pageSize": str(min(max(limit, 1), 200)),
            "sortColumns": "PURCHASE_DATE",
            "sortTypes": "1",
        }
        data = em_get(url, params=params).json()
        rows_raw = (data.get("result") or {}).get("data", [])
        if not rows_raw:
            return pd.DataFrame()

        rows = []
        for it in rows_raw:
            rows.append({
                "代码": (it.get("SECURITYCODE") or it.get("SECURITY_CODE") or "").strip(),
                "名称": (it.get("SECURITYNAME") or it.get("SECURITY_NAME") or "").strip(),
                "申购日期": (it.get("PURCHASE_DATE") or "").split(" ")[0],
                "上市板块": (it.get("BOARD") or "").strip(),
                "发行价": float(it.get("ISSUE_PRICE") or 0),
                "申购上限": float(it.get("PURCHASE_LIMIT") or 0),
            })
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)

    except Exception as e:
        logger.warning("fetch_ipo_calendar failed: %s", e)
        return pd.DataFrame()
