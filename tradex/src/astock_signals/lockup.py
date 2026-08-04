"""
Lockup expiry calendar (限售解禁日历) for A-stock individual stocks.

Uses 东方财富 datacenter RPT_LIFT_STAGE report for history and upcoming
unlock schedules. Pure direct HTTP, zero dependency on akshare.

TradingAgents-astock 移植模块。V0.1。
"""

from __future__ import annotations

from datetime import datetime
import logging

import pandas as pd

from .anti_ban_client import em_datacenter

logger = logging.getLogger(__name__)


def get_lockup_expiry(
    ticker: str,
    trade_date: str,
    forward_days: int = 90,
) -> str:
    """Get lockup expiry schedule for an A-stock.

    Args:
        ticker: 6-digit A-share code, e.g. '000858'.
        trade_date: Reference date in YYYY-MM-DD format.
        forward_days: How many days forward to check (default 90).

    Returns:
        Formatted text with historical unlock records and upcoming
        expiry calendar with impact metrics.
    """
    code = ticker.strip()
    lines = [f"# 限售解禁日历 | {code} | {trade_date}"]

    # 1. Historical unlock records
    try:
        history_data = em_datacenter(
            "RPT_LIFT_STAGE",
            filter_str=f'(SECURITY_CODE="{code}")',
            page_size=15,
            sort_columns="FREE_DATE",
            sort_types="-1",
        )
        if history_data:
            lines.append(f"\n## 个股解禁记录 (共 {len(history_data)} 批)")
            lines.append("解禁时间 | 类型 | 解禁数量 | 占比")
            for row in history_data:
                lines.append(
                    f"  {str(row.get('FREE_DATE', ''))[:10]} "
                    f"| {row.get('LIMITED_STOCK_TYPE', '')} "
                    f"| {row.get('FREE_SHARES_NUM', '')} "
                    f"| {row.get('FREE_RATIO', '')}"
                )
        else:
            lines.append("\n无历史解禁记录。")
    except Exception as e:
        logger.warning("Lockup history query failed for %s: %s", code, e)
        lines.append(f"个股解禁查询失败: {e}")

    # 2. Upcoming unlock schedule
    try:
        end_dt = datetime.strptime(trade_date, "%Y-%m-%d") + pd.Timedelta(
            days=forward_days
        )
        end_str = end_dt.strftime("%Y-%m-%d")
        upcoming_data = em_datacenter(
            "RPT_LIFT_STAGE",
            filter_str=(
                f'(SECURITY_CODE="{code}")'
                f"(FREE_DATE>='{trade_date}')"
                f"(FREE_DATE<='{end_str}')"
            ),
            page_size=20,
            sort_columns="FREE_DATE",
            sort_types="1",
        )
        if upcoming_data:
            lines.append(f"\n## 未来 {forward_days} 天待解禁")
            for row in upcoming_data:
                lines.append(
                    f"  {str(row.get('FREE_DATE', ''))[:10]} "
                    f"| {row.get('LIMITED_STOCK_TYPE', '')} "
                    f"| 数量 {row.get('FREE_SHARES_NUM', '')} "
                    f"| 占比 {row.get('FREE_RATIO', '')}"
                )

            # Risk summary
            total_ratio = 0.0
            for row in upcoming_data:
                try:
                    total_ratio += float(row.get("FREE_RATIO", 0))
                except (ValueError, TypeError):
                    pass
            if total_ratio > 5:
                lines.append(
                    f"\n⚠️ 风险提示: 未来{forward_days}天累计解禁占比 {total_ratio:.1f}%, "
                    f"可能对股价产生较大压力"
                )
        else:
            lines.append(f"\n未来 {forward_days} 天无待解禁。")
    except Exception as e:
        logger.warning("Upcoming lockup query failed for %s: %s", code, e)
        lines.append(f"解禁日历查询失败: {e}")

    return "\n".join(lines)


def get_lockup_expiry_json(
    ticker: str,
    trade_date: str,
    forward_days: int = 90,
) -> dict:
    """Get lockup expiry as structured JSON dict (for MCP tools).

    Returns:
        Dict with 'history' and 'upcoming' keys, each a list of dicts.
    """
    code = ticker.strip()
    result = {"code": code, "trade_date": trade_date, "history": [], "upcoming": []}

    try:
        history_data = em_datacenter(
            "RPT_LIFT_STAGE",
            filter_str=f'(SECURITY_CODE="{code}")',
            page_size=15,
            sort_columns="FREE_DATE",
            sort_types="-1",
        )
        for row in (history_data or []):
            result["history"].append({
                "date": str(row.get("FREE_DATE", ""))[:10],
                "type": row.get("LIMITED_STOCK_TYPE", ""),
                "shares": row.get("FREE_SHARES_NUM", ""),
                "ratio": row.get("FREE_RATIO", ""),
            })
    except Exception as e:
        result["history_error"] = str(e)

    try:
        end_dt = datetime.strptime(trade_date, "%Y-%m-%d") + pd.Timedelta(
            days=forward_days
        )
        end_str = end_dt.strftime("%Y-%m-%d")
        upcoming_data = em_datacenter(
            "RPT_LIFT_STAGE",
            filter_str=(
                f'(SECURITY_CODE="{code}")'
                f"(FREE_DATE>='{trade_date}')"
                f"(FREE_DATE<='{end_str}')"
            ),
            page_size=20,
            sort_columns="FREE_DATE",
            sort_types="1",
        )
        total_ratio = 0.0
        for row in (upcoming_data or []):
            result["upcoming"].append({
                "date": str(row.get("FREE_DATE", ""))[:10],
                "type": row.get("LIMITED_STOCK_TYPE", ""),
                "shares": row.get("FREE_SHARES_NUM", ""),
                "ratio": row.get("FREE_RATIO", ""),
            })
            try:
                total_ratio += float(row.get("FREE_RATIO", 0))
            except (ValueError, TypeError):
                pass
        result["total_upcoming_ratio"] = round(total_ratio, 2)
        result["risk_warning"] = total_ratio > 5
    except Exception as e:
        result["upcoming_error"] = str(e)

    return result
