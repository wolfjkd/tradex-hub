"""
Individual stock fund flow (个股资金流向) data module.

Data source: 东方财富 push2 / push2his
- Realtime: minute-level main/large/medium/small/super order net inflow
- History: daily net inflow for 20 trading days

TradingAgents-astock 移植模块。V0.1。
"""

from __future__ import annotations

import json as _json
import logging
from datetime import datetime

from .anti_ban_client import em_push2_fund_flow, em_push2his_fund_flow

logger = logging.getLogger(__name__)


def _secid(code: str) -> str:
    """Convert 6-digit code to secid format for Eastmoney API."""
    if code.startswith("6"):
        return f"1.{code}"
    return f"0.{code}"


def get_fund_flow(
    code: str,
    curr_date: str = "",
    include_history: bool = True,
) -> str:
    """Get individual stock fund flow from 东财 push2.

    Realtime: minute-level main/large/medium/small/super order net inflow.
    History: daily net inflow for 20 trading days (push2his).

    Args:
        code: 6-digit A-stock code, e.g. "600519".
        curr_date: Date YYYY-MM-DD (for display only), empty defaults to today.
        include_history: Include historical daily fund flow (last 20 days).

    Returns:
        Formatted text with fund flow data.
    """
    if not curr_date:
        curr_date = datetime.now().strftime("%Y-%m-%d")

    secid = _secid(code)
    lines = [
        f"# Fund Flow for {code} (A-stock)",
        f"# Source: 东财 push2 (Eastmoney)",
        f"# Date: {curr_date}",
        "",
    ]

    try:
        # Realtime minute-level fund flow
        d = em_push2_fund_flow(secid, timeout=10)
        klines = d.get("data", {}).get("klines", [])

        if klines:
            lines.append(
                "## Realtime Minute Flow "
                "(主力/小单/中单/大单/超大单 净流入, 元)"
            )
            for line in klines[-10:]:
                parts = line.split(",")
                if len(parts) >= 6:
                    lines.append(
                        f"  {parts[0]}: "
                        f"主力={float(parts[1])/1e4:.0f}万 "
                        f"大单={float(parts[4])/1e4:.0f}万 "
                        f"超大单={float(parts[5])/1e4:.0f}万"
                    )

            last_parts = klines[-1].split(",")
            if len(last_parts) >= 2:
                main_net = float(last_parts[1])
                lines.append(f"\nClose: 主力净流入={main_net/1e4:.0f}万元")
                if main_net > 0:
                    lines.append("Signal: Net main force INFLOW (bullish)")
                elif main_net < 0:
                    lines.append("Signal: Net main force OUTFLOW (bearish)")
        else:
            lines.append(
                "No realtime fund flow (non-trading hours or holiday)"
            )

        # Historical daily fund flow (push2his)
        if include_history:
            dh = em_push2his_fund_flow(secid, limit=20, timeout=10)
            hist_klines = dh.get("data", {}).get("klines", [])

            if hist_klines:
                lines.append(
                    f"\n## Historical Daily Fund Flow "
                    f"(last {len(hist_klines)} trading days)"
                )
                lines.append(
                    "Date | 主力净流入(万) | 大单(万) "
                    "| 中单(万) | 小单(万) | 超大单(万)"
                )
                for line in hist_klines:
                    parts = line.split(",")
                    if len(parts) >= 6:
                        lines.append(
                            f"  {parts[0]} "
                            f"| main={float(parts[1])/1e4:.0f} "
                            f"| large={float(parts[4])/1e4:.0f} "
                            f"| mid={float(parts[3])/1e4:.0f} "
                            f"| small={float(parts[2])/1e4:.0f} "
                            f"| super={float(parts[5])/1e4:.0f}"
                        )

        return "\n".join(lines)

    except Exception as e:
        return f"Error fetching fund flow for {code}: {str(e)}"


def get_fund_flow_json(
    code: str,
    curr_date: str = "",
    include_history: bool = True,
) -> dict:
    """Get individual stock fund flow as structured dict.

    Returns dict with keys:
      - symbol, source, date
      - realtime (list of minute-level data points)
      - history (list of daily data points)
      - signal (bullish/bearish/neutral)
    """
    if not curr_date:
        curr_date = datetime.now().strftime("%Y-%m-%d")

    secid = _secid(code)
    result: dict = {
        "symbol": code,
        "source": "东财 push2",
        "date": curr_date,
        "realtime": [],
        "history": [],
        "signal": "neutral",
    }

    try:
        d = em_push2_fund_flow(secid, timeout=10)
        klines = d.get("data", {}).get("klines", [])

        if klines:
            for line in klines:
                parts = line.split(",")
                if len(parts) >= 6:
                    result["realtime"].append({
                        "time": parts[0],
                        "main_net": float(parts[1]),
                        "small": float(parts[2]),
                        "mid": float(parts[3]),
                        "large": float(parts[4]),
                        "super_large": float(parts[5]),
                    })

            if result["realtime"]:
                last = result["realtime"][-1]
                main_net = last["main_net"]
                if main_net > 0:
                    result["signal"] = "bullish_inflow"
                elif main_net < 0:
                    result["signal"] = "bearish_outflow"

        if include_history:
            dh = em_push2his_fund_flow(secid, limit=20, timeout=10)
            hist_klines = dh.get("data", {}).get("klines", [])
            for line in hist_klines:
                parts = line.split(",")
                if len(parts) >= 6:
                    result["history"].append({
                        "date": parts[0],
                        "main_net": float(parts[1]),
                        "small": float(parts[2]),
                        "mid": float(parts[3]),
                        "large": float(parts[4]),
                        "super_large": float(parts[5]),
                    })

    except Exception as e:
        result["error"] = str(e)

    return result
