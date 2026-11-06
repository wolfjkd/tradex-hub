"""全市场成交额榜 service（工单 H5）。

主路径：通达信官网盘后包（g4day，17:00 后发布，全市场日线含成交额）
降级路径：实时成交额榜（eltdx category_quotes），标 kind=realtime /「此刻榜」

口径：
  - 只保留 A 股个股：沪 600/601/603/605/688/689、深 000/001/002/003/300/301、
    京 43/83/87/92；指数（880/881/899）、债券（204/11x/12x）、基金（5xx/15x）一律剔除
  - amount 原始单位「元」，输出统一为「亿元」
  - 涨跌幅 = close / prev_close − 1（盘后包自带昨收，不猜）
"""

from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd

from ..data_sources import get_router
from ..shortline.meta import cache_key, get_endpoint, resolve_cache
from ..utils.cache import cache

logger = logging.getLogger(__name__)

_router = get_router()

ENDPOINT_ID = "shortline.turnover_top"
_COMPLIANCE = "cn-public"
_MAX_CACHE_ROWS = 500

# A 股个股代码前缀（按市场）
_A_SHARE_PREFIXES: dict[str, tuple[str, ...]] = {
    "sh": ("600", "601", "603", "605", "688", "689"),
    "sz": ("000", "001", "002", "003", "300", "301"),
    "bj": ("43", "83", "87", "92"),
}


def is_a_share(market: str, code: str) -> bool:
    """判断是否 A 股个股（剔除指数 / 债券 / 基金 / 回购）。"""
    prefixes = _A_SHARE_PREFIXES.get(market)
    if not prefixes:
        return False
    return str(code).startswith(prefixes)


def rank_rows(rows: list[dict], limit: int) -> list[dict]:
    """把盘后包全市场行按成交额降序排成榜单（纯函数）。"""
    picked = [row for row in rows if is_a_share(row.get("market", ""), row.get("code", ""))]
    picked.sort(key=lambda row: (-float(row.get("amount") or 0), row.get("code", "")))
    out: list[dict] = []
    for i, row in enumerate(picked[: max(0, limit)]):
        prev_close = float(row.get("prev_close") or 0)
        close = float(row.get("close") or 0)
        out.append({
            "rank": i + 1,
            "code": row.get("code"),
            "name": row.get("name"),
            "amount_yi": round(float(row.get("amount") or 0) / 1e8, 4),
            "close": close,
            "change_pct": round((close / prev_close - 1) * 100, 2) if prev_close > 0 else None,
            "volume": row.get("volume"),
        })
    return out


def _rank_realtime(df: pd.DataFrame, limit: int) -> list[dict]:
    """实时榜 DataFrame → 统一榜单结构。"""
    if df is None or df.empty:
        raise RuntimeError("实时成交额榜返回空")
    rows: list[dict] = []
    for _, row in df.iterrows():
        raw_code = str(row.get("代码") or "")
        code = raw_code[-6:]
        market = raw_code[:2] if raw_code[:2] in ("sh", "sz", "bj") else _infer_market(code)
        if not is_a_share(market, code):
            continue
        try:
            amount = float(row.get("成交额") or 0)
        except (TypeError, ValueError):
            amount = 0.0
        rows.append({
            "code": code,
            "name": None,
            "amount": amount,
            "close": row.get("现价"),
            "change_pct": row.get("涨跌幅"),
        })
    rows.sort(key=lambda item: (-item["amount"], item["code"]))
    return [
        {
            "rank": i + 1,
            "code": item["code"],
            "name": item["name"],
            "amount_yi": round(item["amount"] / 1e8, 4),
            "close": item["close"],
            "change_pct": item["change_pct"],
            "volume": None,
        }
        for i, item in enumerate(rows[: max(0, limit)])
    ]


def _infer_market(code: str) -> str:
    """按代码前缀推断市场（无前缀的实时行用）。"""
    if code.startswith(("6",)):
        return "sh"
    if code.startswith(("0", "3")):
        return "sz"
    return "bj"


def get_turnover_top(date: str = "", limit: int = 20, kind: str = "auto") -> dict:
    """取成交额榜。

    Args:
        date: 交易日 YYYYMMDD；空 = 今天（该日包未发布则降级实时榜）。
        limit: 返回前 N（上限 500）。
        kind: auto（默认，历史优先、失败降级）/ history（只允许历史，失败仍降级并标注）
              / realtime（直接走实时榜）。

    Returns:
        dict：含 kind（history / realtime）、as_of、source、degradation、stocks。
    """
    kind = (kind or "auto").strip().lower()
    if kind not in ("auto", "history", "realtime"):
        raise ValueError(f"非法 kind: {kind}（可选 auto / history / realtime）")
    try:
        limit_n = int(limit or 0)
    except (TypeError, ValueError):
        limit_n = 0
    limit_n = max(1, min(limit_n or 20, _MAX_CACHE_ROWS))

    meta = get_endpoint(ENDPOINT_ID)

    if kind != "realtime":
        history = _try_history(date, meta)
        if isinstance(history, dict):
            return _slice(history, limit_n)
        degradation_reason = history
    else:
        degradation_reason = "指定 kind=realtime"

    # 降级实时榜
    decision = resolve_cache("live_15s", partial=True)
    key = cache_key(ENDPOINT_ID, kind="realtime")
    cached = cache.get(key)
    if cached is not None:
        result = dict(cached)
        result["cache_hit"] = True
        return _slice(result, limit_n)

    df, source = _router.route(
        "category_quotes", sort_by="成交额", count=max(50, limit_n), timeout=20
    )
    result = {
        "endpoint": ENDPOINT_ID,
        "date": None,
        "kind": "realtime",
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": f"{source}（此刻榜）",
        "source_note": "实时成交额榜按此刻成交额排序，非当日定稿；盘中读数会继续变化",
        "compliance": _COMPLIANCE,
        "count": None,
        "stocks": _rank_realtime(df, limit_n),
        "degradation": {
            "from": "history",
            "to": "realtime",
            "reason": str(degradation_reason),
        },
        "cache_hit": False,
        "cache": {"policy": "live_15s", "ttl_seconds": decision.ttl_seconds},
    }
    result["count"] = len(result["stocks"])
    if decision.enabled:
        cache.set(key, result, decision.ttl_seconds)
    return _slice(result, limit_n)


def _try_history(date: str, meta) -> dict | str | None:
    """尝试走盘后包；成功返回结果 dict，失败返回字符串原因（不抛）。"""
    key = cache_key(ENDPOINT_ID, date=(date or "").replace("-", "") or "latest")
    cached = cache.get(key)
    if cached is not None:
        result = dict(cached)
        result["cache_hit"] = True
        return result

    decision = resolve_cache(meta.cache_policy, partial=False)
    try:
        payload, source = _router.route("tdx_daily_package", date=date, timeout=120)
    except Exception as exc:  # noqa: BLE001 - 包未发布/下载失败一律走实时降级
        logger.warning("turnover_top: 盘后包不可用（%s），降级实时榜", exc)
        return f"盘后包不可用：{exc}"

    if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
        return f"盘后包返回结构异常（source={source}）"

    stocks = rank_rows(payload["rows"], _MAX_CACHE_ROWS)
    result = {
        "endpoint": ENDPOINT_ID,
        "date": payload.get("date"),
        "kind": "history",
        "as_of": payload.get("as_of"),
        "source": payload.get("source") or source,
        "source_url": payload.get("source_url"),
        "source_note": (
            "通达信官网盘后包（g4day，17:00 后发布）全市场日线；"
            "amount 原始单位元，已换算亿元；仅保留 A 股个股"
        ),
        "compliance": _COMPLIANCE,
        "count": len(stocks),
        "stocks": stocks,
        "degradation": None,
        "cache_hit": False,
        "cache": {"policy": meta.cache_policy, "ttl_seconds": decision.ttl_seconds},
    }
    if decision.enabled:
        cache.set(key, result, decision.ttl_seconds)
    return result


def _slice(result: dict, limit: int) -> dict:
    """按 limit 截断榜单（count 保留缓存全量）。"""
    stocks = result.get("stocks") or []
    if len(stocks) > limit:
        result["stocks"] = stocks[:limit]
    result["returned"] = len(result["stocks"])
    return result
