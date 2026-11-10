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

# ── 东财 RPT_LIFT_STAGE 字段映射单点（批次C3 收敛，2026-11-11）──
# 2026-11-10 实测字段改版：LIMITED_STOCK_TYPE→FREE_SHARES_TYPE、
# FREE_SHARES_NUM→CURRENT_FREE_SHARES/FREE_SHARES。新名优先旧名兜底，
# 对再次改版容忍（按旧名取值全空串=空壳行，比断更隐蔽）。
# 此前 JSON 版 history/upcoming 两处 + 文本版 history/upcoming 两处各写一份
# 取值逻辑，重映射只修了 JSON 版 → 文本版漏成假 0（审计候选⑤实证）。
_LOCKUP_TYPE_FIELDS = ("FREE_SHARES_TYPE", "LIMITED_STOCK_TYPE")
_LOCKUP_SHARES_FIELDS = ("CURRENT_FREE_SHARES", "FREE_SHARES", "FREE_SHARES_NUM")


def _lockup_row(row: dict) -> dict:
    """RPT_LIFT_STAGE 行 → 统一 {date, type, shares, ratio}（映射单点）。"""
    def _first(*fields):
        for f in fields:
            v = row.get(f)
            if v not in (None, ""):
                return v
        return ""

    return {
        "date": str(row.get("FREE_DATE", ""))[:10],
        "type": _first(*_LOCKUP_TYPE_FIELDS),
        "shares": _first(*_LOCKUP_SHARES_FIELDS),
        "ratio": row.get("FREE_RATIO", ""),
    }


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
                r = _lockup_row(row)
                lines.append(
                    f"  {r['date']} "
                    f"| {r['type']} "
                    f"| {r['shares']} "
                    f"| {r['ratio']}"
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
                r = _lockup_row(row)
                lines.append(
                    f"  {r['date']} "
                    f"| {r['type']} "
                    f"| 数量 {r['shares']} "
                    f"| 占比 {r['ratio']}"
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
    # 2026-09-28 审计修复：此前查询失败只写 *_error 键后正常 return，
    # 独占源挂掉时被伪装成「无解禁」，SmartRouter 还记成功。改为：
    # 单边失败保留 partial 数据 + 错误键；双边全失败 raise 让路由记账。
    history_error: str | None = None
    upcoming_error: str | None = None

    try:
        history_data = em_datacenter(
            "RPT_LIFT_STAGE",
            filter_str=f'(SECURITY_CODE="{code}")',
            page_size=15,
            sort_columns="FREE_DATE",
            sort_types="-1",
        )
        for row in (history_data or []):
            result["history"].append(_lockup_row(row))
    except Exception as e:
        history_error = str(e)

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
            result["upcoming"].append(_lockup_row(row))
            try:
                total_ratio += float(row.get("FREE_RATIO", 0))
            except (ValueError, TypeError):
                pass
        result["total_upcoming_ratio"] = round(total_ratio, 2)
        result["risk_warning"] = total_ratio > 5
    except Exception as e:
        upcoming_error = str(e)

    if history_error is not None and upcoming_error is not None:
        raise RuntimeError(
            f"lockup_expiry both queries failed: "
            f"history: {history_error}; upcoming: {upcoming_error}"
        )
    if history_error is not None:
        result["history_error"] = history_error
    if upcoming_error is not None:
        result["upcoming_error"] = upcoming_error
    return result
