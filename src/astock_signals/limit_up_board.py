"""
Limit-up board data — 打板层：涨停四池 + 同花顺涨停揭秘 + 情绪速算。
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
import logging

import requests as _requests

from .anti_ban_client import em_get

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _em_clist_get(fields: str = "", timeout: int = 15) -> list[dict]:
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": "1",
        "pz": "200",
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": "m:0+t:6,m:0+t:13,m:0+t:80,m:1+t:2,m:1+t:23",
        "fields": fields,
    }

    all_items = []
    page = 1
    max_pages = 30

    while page <= max_pages:
        params["pn"] = str(page)
        try:
            r = em_get(url, params=params, timeout=timeout)
            data = r.json()
            items = data.get("data", {}).get("diff", [])
            if not items:
                break
            all_items.extend(items)
            page += 1
        except Exception as e:
            logger.error("Error fetching page %d: %s", page, e)
            break

    return all_items


def _get_limit_threshold(code: str) -> tuple[float, float]:
    if code.startswith("688"):
        return 19.8, -19.8
    if code.startswith("300"):
        return 19.8, -19.8
    if code.startswith("301"):
        return 19.8, -19.8
    if code.startswith("605"):
        return 9.8, -9.8
    if code.startswith("001"):
        return 9.8, -9.8
    if code.startswith("003"):
        return 9.8, -9.8
    if code.startswith("ST"):
        return 4.8, -4.8
    if "ST" in code:
        return 4.8, -4.8
    return 9.8, -9.8


def _is_limit_up(code: str, change_pct: float) -> bool:
    up_thresh, _ = _get_limit_threshold(code)
    return change_pct >= up_thresh


def _is_limit_down(code: str, change_pct: float) -> bool:
    _, down_thresh = _get_limit_threshold(code)
    return change_pct <= down_thresh


def get_limit_up_pool() -> dict:
    fields = "f2,f3,f4,f5,f7,f12,f14,f15,f16,f17,f18,f100"
    items = _em_clist_get(fields)
    pool = []
    for item in items:
        try:
            code = item.get("f12", "")
            change_pct = float(item.get("f3", 0))
            if _is_limit_up(code, change_pct):
                pool.append({
                    "code": code,
                    "name": item.get("f14", ""),
                    "price": float(item.get("f2", 0)) if item.get("f2") else 0,
                    "change_pct": change_pct,
                    "volume": float(item.get("f4", 0)) * 10000 if item.get("f4") else 0,
                    "amount": float(item.get("f5", 0)) * 10000 if item.get("f5") else 0,
                    "turnover": float(item.get("f18", 0)) if item.get("f18") else 0,
                    "high_pct": float(item.get("f15", 0)) if item.get("f15") else 0,
                    "low_pct": float(item.get("f16", 0)) if item.get("f16") else 0,
                    "open_pct": float(item.get("f17", 0)) if item.get("f17") else 0,
                    "amplitude": float(item.get("f7", 0)) if item.get("f7") else 0,
                    "industry": item.get("f100", ""),
                })
        except (ValueError, TypeError):
            continue
    return {"type": "zt", "data": pool, "count": len(pool), "source": "eastmoney_clist"}


def get_break_board_pool() -> dict:
    fields = "f2,f3,f4,f5,f7,f12,f14,f15,f16,f17,f18,f100"
    items = _em_clist_get(fields)
    pool = []
    for item in items:
        try:
            code = item.get("f12", "")
            change_pct = float(item.get("f3", 0))
            high_pct = float(item.get("f15", 0)) if item.get("f15") else 0
            up_thresh, _ = _get_limit_threshold(code)
            if high_pct >= up_thresh and change_pct < up_thresh:
                pool.append({
                    "code": code,
                    "name": item.get("f14", ""),
                    "price": float(item.get("f2", 0)) if item.get("f2") else 0,
                    "change_pct": change_pct,
                    "high_pct": high_pct,
                    "low_pct": float(item.get("f16", 0)) if item.get("f16") else 0,
                    "open_pct": float(item.get("f17", 0)) if item.get("f17") else 0,
                    "amplitude": float(item.get("f7", 0)) if item.get("f7") else 0,
                    "volume": float(item.get("f4", 0)) * 10000 if item.get("f4") else 0,
                    "amount": float(item.get("f5", 0)) * 10000 if item.get("f5") else 0,
                    "turnover": float(item.get("f18", 0)) if item.get("f18") else 0,
                    "industry": item.get("f100", ""),
                })
        except (ValueError, TypeError):
            continue
    return {"type": "zb", "data": pool, "count": len(pool), "source": "eastmoney_clist"}


def get_limit_down_pool() -> dict:
    fields = "f2,f3,f4,f5,f12,f14,f18,f100"
    items = _em_clist_get(fields)
    pool = []
    for item in items:
        try:
            code = item.get("f12", "")
            change_pct = float(item.get("f3", 0))
            if _is_limit_down(code, change_pct):
                pool.append({
                    "code": code,
                    "name": item.get("f14", ""),
                    "price": float(item.get("f2", 0)) if item.get("f2") else 0,
                    "change_pct": change_pct,
                    "volume": float(item.get("f4", 0)) * 10000 if item.get("f4") else 0,
                    "amount": float(item.get("f5", 0)) * 10000 if item.get("f5") else 0,
                    "turnover": float(item.get("f18", 0)) if item.get("f18") else 0,
                    "industry": item.get("f100", ""),
                })
        except (ValueError, TypeError):
            continue
    return {"type": "dt", "data": pool, "count": len(pool), "source": "eastmoney_clist"}


def get_prev_limit_up_pool() -> dict:
    return {"type": "prev_zt", "data": [], "count": 0, "source": "eastmoney_clist", "error": "暂不支持"}


def get_limit_up_insight(code: str = "") -> dict:
    result = {"data": [], "error": None}
    try:
        url = "https://data.10jqka.com.cn/dataapi/limit_up/limit_up_detail"
        params = {"code": code} if code else {}
        headers = {"User-Agent": _UA}
        r = _requests.get(url, params=params, headers=headers, timeout=10)
        data = r.json()
        if data.get("code", 0) != 0:
            result["error"] = data.get("msg", "unknown error")
            return result
        rows = data.get("data", {}).get("list", [])
        for row in rows:
            result["data"].append({
                "code": row.get("stock_code", ""),
                "name": row.get("stock_name", ""),
                "reason": row.get("reason", ""),
                "seal_success_rate": row.get("seal_success_rate", ""),
                "board_type": row.get("board_type", ""),
                "seal_amount": row.get("seal_amount", ""),
                "turnover_pct": row.get("turnover_rate", ""),
                "volume_ratio": row.get("volume_ratio", ""),
                "change_pct": row.get("change_rate", ""),
                "industry": row.get("industry", ""),
            })
        result["count"] = len(result["data"])
        result["source"] = "同花顺 limit_up_detail"
    except Exception as e:
        logger.error("Error fetching limit-up insight: %s", e)
        result["error"] = str(e)
    return result


def calculate_board_sentiment() -> dict:
    zt = get_limit_up_pool()
    zb = get_break_board_pool()
    dt = get_limit_down_pool()

    zt_count = zt.get("count", 0)
    zb_count = zb.get("count", 0)
    dt_count = dt.get("count", 0)

    break_rate = round(zb_count / (zt_count + zb_count) * 100, 1) if (zt_count + zb_count) > 0 else 0

    zt_stocks = zt.get("data", [])
    themes = []
    for stock in zt_stocks:
        industry = stock.get("industry", "")
        if industry:
            themes.append(industry)
    theme_counter = Counter(themes)

    avg_amount = sum(s.get("amount", 0) for s in zt_stocks) / zt_count if zt_count > 0 else 0
    avg_turnover = sum(s.get("turnover", 0) for s in zt_stocks) / zt_count if zt_count > 0 else 0

    return {
        "zt_count": zt_count,
        "zb_count": zb_count,
        "dt_count": dt_count,
        "break_rate": break_rate,
        "max_consecutive_limit_up": 0,
        "ladder": {},
        "prev_zt_count": 0,
        "prev_zt_promotion_rate": 0,
        "prev_zt_avg_premium": 0,
        "top_themes": dict(theme_counter.most_common(10)),
        "zt_avg_amount": round(avg_amount / 100000000, 2) if avg_amount > 0 else 0,
        "zt_avg_turnover": round(avg_turnover, 2),
        "calculated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def get_limit_up_board_json(board_type: str = "zt") -> dict:
    board_type = board_type.lower().strip()
    if board_type == "zt":
        return get_limit_up_pool()
    elif board_type == "zb":
        return get_break_board_pool()
    elif board_type == "dt":
        return get_limit_down_pool()
    elif board_type == "prev_zt":
        return get_prev_limit_up_pool()
    else:
        return {"error": f"Unknown board type: {board_type}. Supported: zt, zb, dt, prev_zt"}


def get_board_sentiment_json() -> dict:
    try:
        return calculate_board_sentiment()
    except Exception as e:
        logger.error("Error calculating board sentiment: %s", e)
        return {"error": str(e)}