"""
Industry sector comparison (行业横向对比) data module.

Data source: 东方财富 push2 (行业板块排名)
- 全行业涨跌幅排名
- 上涨/下跌家数
- 领涨股

TradingAgents-astock 移植模块。V0.1。
"""

from __future__ import annotations

import json as _json
import logging
from datetime import datetime

from .anti_ban_client import em_push2

logger = logging.getLogger(__name__)


def get_industry_comparison(
    code: str = "",
    trade_date: str = "",
    top_n: int = 20,
) -> str:
    """Get industry sector performance comparison.

    Args:
        code: 6-digit A-share code (used to identify relevant sector), optional.
        trade_date: YYYY-MM-DD (for display), empty defaults to today.
        top_n: number of top/bottom industries to show (default 20).

    Returns:
        Formatted text with sector performance ranking.
    """
    if not trade_date:
        trade_date = datetime.now().strftime("%Y-%m-%d")

    lines = [f"# 行业横向对比 | {trade_date}"]
    if code:
        lines[0] = f"# 行业横向对比 | {code} | {trade_date}"

    # 东财 push2 行业板块排名
    try:
        params = {
            "pn": "1",
            "pz": "100",
            "po": "1",
            "np": "1",
            "fltt": "2",
            "invt": "2",
            "fs": "m:90+t:2",
            "fields": "f2,f3,f4,f12,f13,f14,f104,f105,f128,f136,f140,f141,f207",
        }
        d = em_push2(params, timeout=15)
        items = d.get("data", {}).get("diff", [])

        if items:
            lines.append(
                f"\n## 全行业表现 (东财 {len(items)} 个行业)"
            )
            lines.append(
                "排名 | 行业 | 涨跌幅 | 上涨 | 下跌 | 领涨股"
            )
            for i, item in enumerate(items):
                name = item.get("f14", "")
                change_pct = item.get("f3", 0)
                up_count = item.get("f104", 0)
                down_count = item.get("f105", 0)
                leader = item.get("f140", "")
                lines.append(
                    f"  {i+1}. {name} "
                    f"| {change_pct}% "
                    f"| {up_count} "
                    f"| {down_count} "
                    f"| {leader}"
                )
                if i >= top_n * 2 - 1:
                    lines.append(f"  ... (showing top/bottom {top_n})")
                    break
        else:
            lines.append("行业数据获取为空。")
    except Exception as e:
        lines.append(f"行业对比查询失败: {e}")

    return "\n".join(lines)


def get_industry_comparison_json(
    code: str = "",
    trade_date: str = "",
    top_n: int = 20,
) -> dict:
    """Get industry sector comparison as structured dict.

    Returns dict with keys:
      - source, date, code (optional)
      - industries (list of dicts with rank/name/change_pct/up/down/leader)
    """
    if not trade_date:
        trade_date = datetime.now().strftime("%Y-%m-%d")

    result: dict = {
        "source": "东财 push2",
        "date": trade_date,
        "code": code or None,
        "industries": [],
    }

    try:
        params = {
            "pn": "1",
            "pz": "100",
            "po": "1",
            "np": "1",
            "fltt": "2",
            "invt": "2",
            "fs": "m:90+t:2",
            "fields": "f2,f3,f4,f12,f13,f14,f104,f105,f128,f136,f140,f141,f207",
        }
        d = em_push2(params, timeout=15)
        items = d.get("data", {}).get("diff", [])

        for i, item in enumerate(items):
            result["industries"].append({
                "rank": i + 1,
                "name": item.get("f14", ""),
                "change_pct": item.get("f3", 0),
                "up_count": item.get("f104", 0),
                "down_count": item.get("f105", 0),
                "leader": item.get("f140", ""),
            })

    except Exception as e:
        result["error"] = str(e)

    return result
