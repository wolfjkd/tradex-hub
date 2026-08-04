"""
Dragon Tiger Board (龙虎榜) data module.

Data source: 东方财富 datacenter-web
- 上榜记录 (RPT_DAILYBILLBOARD_DETAILSNEW)
- 买卖席位明细 (RPT_BILLBOARD_DAILYDETAILSBUY / SELL)
- 机构动向 (筛选 OPERATEDEPT_CODE="0")

TradingAgents-astock 移植模块。V0.1。
"""

from __future__ import annotations

import json as _json
import logging
from datetime import datetime, timedelta

import pandas as pd

from .anti_ban_client import em_datacenter

logger = logging.getLogger(__name__)


def get_dragon_tiger_board(
    code: str,
    trade_date: str = "",
    look_back_days: int = 30,
) -> str:
    """Get dragon-tiger board (龙虎榜) appearances and seat details.

    Args:
        code: 6-digit A-share code, e.g. '000858'
        trade_date: YYYY-MM-DD, empty string defaults to today.
        look_back_days: how many days back to search (default 30)

    Returns:
        Formatted text with LHB appearances, top buyer/seller seats,
        and institutional activity.
    """
    if not trade_date:
        trade_date = datetime.now().strftime("%Y-%m-%d")

    end_dt = datetime.strptime(trade_date, "%Y-%m-%d")
    start_dt = end_dt - timedelta(days=look_back_days)
    start_date_str = start_dt.strftime("%Y-%m-%d")
    lines = [f"# 龙虎榜数据 | {code} | {trade_date} (近{look_back_days}日)"]

    buy_data = []
    sell_data = []

    # 1. 上榜记录
    try:
        data = em_datacenter(
            "RPT_DAILYBILLBOARD_DETAILSNEW",
            filter_str=(
                f"(TRADE_DATE>='{start_date_str}')"
                f"(TRADE_DATE<='{trade_date}')"
                f"(SECURITY_CODE=\"{code}\")"
            ),
            page_size=50,
            sort_columns="TRADE_DATE",
            sort_types="-1",
        )
        if not data:
            lines.append(f"\n近{look_back_days}日未上龙虎榜。")
        else:
            lines.append(f"\n## 上榜记录 ({len(data)} 次)")
            lines.append("日期 | 原因 | 净买入(万) | 换手率")
            for row in data:
                net_buy = round((row.get("BILLBOARD_NET_AMT") or 0) / 10000, 1)
                turnover = round(float(row.get("TURNOVERRATE") or 0), 2)
                lines.append(
                    f"  {str(row.get('TRADE_DATE', ''))[:10]} "
                    f"| {row.get('EXPLANATION', '')} "
                    f"| {net_buy:.0f} "
                    f"| {turnover:.2f}%"
                )
    except Exception as e:
        lines.append(f"龙虎榜列表查询失败: {e}")
        data = []

    # 2. 最近上榜的买卖席位
    try:
        if data:
            latest_date = str(data[0].get("TRADE_DATE", ""))[:10]
            lines.append(f"\n## 最近上榜席位明细 ({latest_date})")

            # 买入席位
            buy_data = em_datacenter(
                "RPT_BILLBOARD_DAILYDETAILSBUY",
                filter_str=f"(TRADE_DATE='{latest_date}')(SECURITY_CODE=\"{code}\")",
                page_size=10,
                sort_columns="BUY",
                sort_types="-1",
            )
            if buy_data:
                lines.append("\n### 买入席位 TOP5")
                lines.append("营业部 | 买入(万) | 卖出(万) | 净额(万)")
                for row in buy_data[:5]:
                    buy_amt = round((row.get("BUY") or 0) / 10000, 1)
                    sell_amt = round((row.get("SELL") or 0) / 10000, 1)
                    net = round((row.get("NET") or 0) / 10000, 1)
                    lines.append(
                        f"  {row.get('OPERATEDEPT_NAME', '')} "
                        f"| {buy_amt:.0f} | {sell_amt:.0f} | {net:.0f}"
                    )

            # 卖出席位
            sell_data = em_datacenter(
                "RPT_BILLBOARD_DAILYDETAILSSELL",
                filter_str=f"(TRADE_DATE='{latest_date}')(SECURITY_CODE=\"{code}\")",
                page_size=10,
                sort_columns="SELL",
                sort_types="-1",
            )
            if sell_data:
                lines.append("\n### 卖出席位 TOP5")
                lines.append("营业部 | 买入(万) | 卖出(万) | 净额(万)")
                for row in sell_data[:5]:
                    buy_amt = round((row.get("BUY") or 0) / 10000, 1)
                    sell_amt = round((row.get("SELL") or 0) / 10000, 1)
                    net = round((row.get("NET") or 0) / 10000, 1)
                    lines.append(
                        f"  {row.get('OPERATEDEPT_NAME', '')} "
                        f"| {buy_amt:.0f} | {sell_amt:.0f} | {net:.0f}"
                    )
    except Exception as e:
        logger.debug("dragon_tiger buy/sell seats query failed: %s", e)

    # 3. 机构动向
    try:
        inst_buy = 0.0
        inst_sell = 0.0
        for detail, side in [(buy_data, "buy"), (sell_data, "sell")]:
            for row in (detail or []):
                if str(row.get("OPERATEDEPT_CODE", "")) == "0":
                    if side == "buy":
                        inst_buy += (row.get("BUY") or 0)
                    else:
                        inst_sell += (row.get("SELL") or 0)
        if inst_buy > 0 or inst_sell > 0:
            lines.append("\n## 机构动向")
            lines.append(
                f"  机构买入 {inst_buy/1e4:.0f} 万 "
                f"| 卖出 {inst_sell/1e4:.0f} 万 "
                f"| 净额 {(inst_buy - inst_sell)/1e4:.0f} 万"
            )
    except Exception as e:
        logger.debug("dragon_tiger institution query failed: %s", e)

    return "\n".join(lines)


def get_dragon_tiger_board_json(
    code: str,
    trade_date: str = "",
    look_back_days: int = 30,
) -> dict:
    """Get dragon-tiger board data as structured dict.

    Returns dict with keys:
      - symbol, source, trade_date, look_back_days
      - appearances (list of dicts)
      - latest_seats (dict with buy/sell lists)
      - institutional (dict with buy/sell/net)
    """
    if not trade_date:
        trade_date = datetime.now().strftime("%Y-%m-%d")

    end_dt = datetime.strptime(trade_date, "%Y-%m-%d")
    start_dt = end_dt - timedelta(days=look_back_days)
    start_date_str = start_dt.strftime("%Y-%m-%d")

    result: dict = {
        "symbol": code,
        "source": "东财 datacenter",
        "trade_date": trade_date,
        "look_back_days": look_back_days,
        "appearances": [],
        "latest_seats": {"buy": [], "sell": []},
        "institutional": None,
    }

    buy_data = []
    sell_data = []

    # 1. 上榜记录
    try:
        data = em_datacenter(
            "RPT_DAILYBILLBOARD_DETAILSNEW",
            filter_str=(
                f"(TRADE_DATE>='{start_date_str}')"
                f"(TRADE_DATE<='{trade_date}')"
                f"(SECURITY_CODE=\"{code}\")"
            ),
            page_size=50,
            sort_columns="TRADE_DATE",
            sort_types="-1",
        )
        for row in (data or []):
            result["appearances"].append({
                "date": str(row.get("TRADE_DATE", ""))[:10],
                "reason": row.get("EXPLANATION", ""),
                "net_buy_wan": round((row.get("BILLBOARD_NET_AMT") or 0) / 10000, 1),
                "turnover_pct": round(float(row.get("TURNOVERRATE") or 0), 2),
            })
    except Exception as e:
        result["error_appearances"] = str(e)

    # 2. 买卖席位
    try:
        if result["appearances"]:
            latest_date = result["appearances"][0]["date"]

            buy_data = em_datacenter(
                "RPT_BILLBOARD_DAILYDETAILSBUY",
                filter_str=f"(TRADE_DATE='{latest_date}')(SECURITY_CODE=\"{code}\")",
                page_size=10,
                sort_columns="BUY",
                sort_types="-1",
            )
            for row in (buy_data or []):
                result["latest_seats"]["buy"].append({
                    "name": row.get("OPERATEDEPT_NAME", ""),
                    "buy_wan": round((row.get("BUY") or 0) / 10000, 1),
                    "sell_wan": round((row.get("SELL") or 0) / 10000, 1),
                    "net_wan": round((row.get("NET") or 0) / 10000, 1),
                    "is_institutional": str(row.get("OPERATEDEPT_CODE", "")) == "0",
                })

            sell_data = em_datacenter(
                "RPT_BILLBOARD_DAILYDETAILSSELL",
                filter_str=f"(TRADE_DATE='{latest_date}')(SECURITY_CODE=\"{code}\")",
                page_size=10,
                sort_columns="SELL",
                sort_types="-1",
            )
            for row in (sell_data or []):
                result["latest_seats"]["sell"].append({
                    "name": row.get("OPERATEDEPT_NAME", ""),
                    "buy_wan": round((row.get("BUY") or 0) / 10000, 1),
                    "sell_wan": round((row.get("SELL") or 0) / 10000, 1),
                    "net_wan": round((row.get("NET") or 0) / 10000, 1),
                    "is_institutional": str(row.get("OPERATEDEPT_CODE", "")) == "0",
                })
    except Exception as e:
        result["error_seats"] = str(e)

    # 3. 机构动向
    try:
        inst_buy = 0.0
        inst_sell = 0.0
        for detail, side in [(buy_data, "buy"), (sell_data, "sell")]:
            for row in (detail or []):
                if str(row.get("OPERATEDEPT_CODE", "")) == "0":
                    if side == "buy":
                        inst_buy += (row.get("BUY") or 0)
                    else:
                        inst_sell += (row.get("SELL") or 0)
        if inst_buy > 0 or inst_sell > 0:
            result["institutional"] = {
                "buy_wan": round(inst_buy / 10000, 1),
                "sell_wan": round(inst_sell / 10000, 1),
                "net_wan": round((inst_buy - inst_sell) / 10000, 1),
            }
    except Exception as e:
        logger.debug("dragon_tiger JSON institution query failed: %s", e)

    return result
