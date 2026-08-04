"""
Northbound capital flow (沪深股通) data module.

Data source: 同花顺 hsgtApi (data.hexin.cn)
- Realtime: minute-level cumulative net buying for HGT(沪股通) + SGT(深股通)
- History: local CSV cache (upstream APIs stopped updating northbound history since 2024-08)

TradingAgents-astock 移植模块。V0.1。
"""

from __future__ import annotations

import csv
import json as _json
import os
import logging
from datetime import datetime

import requests as _requests

logger = logging.getLogger(__name__)

_HSGT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "Chrome/117.0.0.0 Safari/537.36"
    ),
    "Host": "data.hexin.cn",
    "Referer": "https://data.hexin.cn/",
}

# Local cache for daily northbound close snapshots
_CACHE_DIR = os.path.join(os.path.expanduser("~"), ".workbuddy", "cache")
_CACHE_FILE = os.path.join(_CACHE_DIR, "northbound_daily.csv")


def _ensure_cache_dir() -> None:
    os.makedirs(_CACHE_DIR, exist_ok=True)


def _save_snapshot(date_str: str, hgt: float, sgt: float) -> None:
    """Append today's northbound close to local CSV cache (dedup by date)."""
    _ensure_cache_dir()
    existing: dict[str, tuple[str, str]] = {}
    if os.path.exists(_CACHE_FILE):
        with open(_CACHE_FILE, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)
            for row in reader:
                if len(row) >= 3:
                    existing[row[0]] = (row[1], row[2])
    existing[date_str] = (f"{hgt:.2f}", f"{sgt:.2f}")
    sorted_dates = sorted(existing.keys())
    with open(_CACHE_FILE, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "hgt", "sgt"])
        for d in sorted_dates:
            writer.writerow([d, existing[d][0], existing[d][1]])


def _load_history(n: int = 20) -> list[tuple[str, float, float]]:
    """Load last N days of northbound close data from local cache."""
    if not os.path.exists(_CACHE_FILE):
        return []
    rows: list[tuple[str, float, float]] = []
    with open(_CACHE_FILE, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if len(row) >= 3:
                try:
                    rows.append((row[0], float(row[1]), float(row[2])))
                except ValueError:
                    continue
    return rows[-n:]


def get_northbound_flow(
    curr_date: str = "",
    include_history: bool = False,
) -> str:
    """Get northbound capital flow (沪深股通) from 同花顺 hsgtApi.

    Realtime: minute-level cumulative net buying for HGT(沪股通) + SGT(深股通).
    History: self-cached daily close snapshots.

    Args:
        curr_date: Date YYYY-MM-DD, empty string defaults to today.
        include_history: Include historical daily data (last 20 trading days).

    Returns:
        Formatted text with northbound flow data.
    """
    if not curr_date:
        curr_date = datetime.now().strftime("%Y-%m-%d")

    lines = [
        f"# Northbound Capital Flow ({curr_date})",
        "# Source: 同花顺 hsgtApi (沪深股通) + local cache",
        "",
    ]

    hgt_close = 0.0
    sgt_close = 0.0
    got_realtime = False

    try:
        url_rt = "https://data.hexin.cn/market/hsgtApi/method/dayChart/"
        r = _requests.get(url_rt, headers=_HSGT_HEADERS, timeout=10)
        d = r.json()

        times = d.get("time", [])
        hgt = d.get("hgt", [])
        sgt = d.get("sgt", [])

        if times:
            lines.append("## Realtime (cumulative net buying, 亿元)")
            n = len(times)
            start_idx = max(0, n - 10)
            for i in range(start_idx, n):
                t = times[i]
                h = hgt[i] if i < len(hgt) else "N/A"
                s = sgt[i] if i < len(sgt) else "N/A"
                lines.append(f"  {t}: HGT={h} SGT={s}")

            hgt_close = float(hgt[-1]) if hgt else 0
            sgt_close = float(sgt[-1]) if sgt else 0
            total = hgt_close + sgt_close
            lines.append(
                f"\nClose: HGT(沪股通)={hgt_close:.2f}亿 "
                f"SGT(深股通)={sgt_close:.2f}亿 "
                f"Total={total:.2f}亿"
            )
            if total > 0:
                lines.append("Signal: Net northbound INFLOW (bullish)")
            elif total < 0:
                lines.append("Signal: Net northbound OUTFLOW (bearish)")
            got_realtime = True
        else:
            lines.append("No realtime data (non-trading hours or holiday)")

        if got_realtime:
            _save_snapshot(curr_date, hgt_close, sgt_close)

        if include_history:
            history = _load_history(20)
            if history:
                lines.append("\n## Historical Daily Close (local cache, 亿元)")
                lines.append("Date       | HGT(沪股通) | SGT(深股通) | Total")
                for date, h, s in history:
                    lines.append(
                        f"  {date}: HGT={h:.2f} SGT={s:.2f} Total={h + s:.2f}"
                    )
                avg_total = sum(h + s for _, h, s in history) / len(history)
                lines.append(
                    f"\n{len(history)}-day avg net flow: {avg_total:.2f}亿"
                )
                if got_realtime:
                    today_total = hgt_close + sgt_close
                    diff = today_total - avg_total
                    lines.append(
                        f"Today vs avg: {'+' if diff >= 0 else ''}{diff:.2f}亿 "
                        f"({'above' if diff >= 0 else 'below'} average)"
                    )
            else:
                lines.append(
                    "\n## Historical Daily: No cached data yet. "
                    "History accumulates automatically with each call."
                )

        return "\n".join(lines)

    except Exception as e:
        return f"Error fetching northbound flow: {str(e)}"


def get_northbound_flow_json(
    curr_date: str = "",
    include_history: bool = False,
) -> dict:
    """Get northbound capital flow as structured dict.

    Returns dict with keys:
      - source, date, realtime (dict with times/hgt/sgt/close/total/signal),
      - history (list of dicts)
    """
    if not curr_date:
        curr_date = datetime.now().strftime("%Y-%m-%d")

    result: dict = {
        "source": "同花顺 hsgtApi",
        "date": curr_date,
        "realtime": None,
        "history": [],
    }

    try:
        url_rt = "https://data.hexin.cn/market/hsgtApi/method/dayChart/"
        r = _requests.get(url_rt, headers=_HSGT_HEADERS, timeout=10)
        d = r.json()

        times = d.get("time", [])
        hgt = d.get("hgt", [])
        sgt = d.get("sgt", [])

        if times:
            hgt_close = float(hgt[-1]) if hgt else 0
            sgt_close = float(sgt[-1]) if sgt else 0
            total = hgt_close + sgt_close

            n = len(times)
            start_idx = max(0, n - 10)
            data_points = []
            for i in range(start_idx, n):
                data_points.append({
                    "time": times[i],
                    "hgt": float(hgt[i]) if i < len(hgt) and hgt[i] else None,
                    "sgt": float(sgt[i]) if i < len(sgt) and sgt[i] else None,
                })

            signal = "neutral"
            if total > 0:
                signal = "bullish_inflow"
            elif total < 0:
                signal = "bearish_outflow"

            result["realtime"] = {
                "data_points": data_points,
                "hgt_close": round(hgt_close, 2),
                "sgt_close": round(sgt_close, 2),
                "total": round(total, 2),
                "signal": signal,
            }

            _save_snapshot(curr_date, hgt_close, sgt_close)

        if include_history:
            history = _load_history(20)
            result["history"] = [
                {"date": date, "hgt": round(h, 2), "sgt": round(s, 2), "total": round(h + s, 2)}
                for date, h, s in history
            ]

    except Exception as e:
        result["error"] = str(e)

    return result
