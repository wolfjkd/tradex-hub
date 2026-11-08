"""短线四池读数计算层（工单 H2）。

口径全部写在函数里，避免再变成口头传说。所有函数都是纯函数：
输入 PoolSnapshot（四池数据），输出 (result, text)，不碰网络、不碰缓存——
这样口径可单测、可复算，服务层只负责取数与缓存。

四池字段（akshare_em）：
  zt      今日涨停池（consecutive_days=连板数，1=首板）
  zb      今日炸板池
  dt      今日跌停池
  prev_zt 昨日涨停池（行内 change_pct 是「昨日涨停股今日的涨跌幅」）

核心口径：
  - 炸板率 = 炸板数 / (涨停数 + 炸板数)
  - 晋级率 = 昨日涨停今日仍涨停 / 昨日涨停数
  - 1进2   = 昨日首板今日涨停 / 昨日首板数
  - 连板溢价 = 昨日连板股今日均涨幅 − 昨日首板股今日均涨幅（接力溢价）
  - 封板率 = 涨停数 / (涨停数 + 炸板数)
  - 梯队断层 = 今日最大连板高度以内缺失的层级（有 4 板无 3 板 → 缺 3）
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field

# 涨跌停阈值判定（与 akshare 池口径一致）
_LIMIT_RATIO_ST = 4.8
_LIMIT_RATIO_MAIN = 9.8
_LIMIT_RATIO_GEM = 19.8


@dataclass
class PoolSnapshot:
    """一次四池快照。"""

    date: str  # YYYYMMDD
    zt: list[dict] = field(default_factory=list)
    zb: list[dict] = field(default_factory=list)
    dt: list[dict] = field(default_factory=list)
    prev_zt: list[dict] = field(default_factory=list)
    fields: dict[str, list[str]] = field(default_factory=dict)
    reasons: dict[str, str] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)

    def has(self, pool: str) -> bool:
        return pool not in self.missing

    def missing_reason(self, pool: str) -> str:
        return self.reasons.get(pool, f"{pool} 池未取到")


# ---------------------------------------------------------------- 小工具


def _f(value, default=None):
    """安全转 float（None/空/非法 → default）。"""
    if value is None or value == "":
        return default
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return v


def _i(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _mean(values: list[float]) -> float | None:
    return round(statistics.mean(values), 2) if values else None


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 2) if values else None


def _pct(part: int | None, whole: int | None) -> float | None:
    if part is None or not whole:
        return None
    return round(part / whole * 100, 2)


def _limit_ratio(code: str, name: str = "") -> float:
    """按代码/名称判定该票的涨停阈值（用于判断「今日是否仍涨停」）。"""
    if "ST" in str(name) or "ST" in str(code):
        return _LIMIT_RATIO_ST
    code = str(code)
    if code.startswith(("688", "689", "300", "301")):
        return _LIMIT_RATIO_GEM
    return _LIMIT_RATIO_MAIN


def _is_limit_up_today(row: dict) -> bool:
    change = _f(row.get("change_pct"))
    if change is None:
        return False
    return change >= _limit_ratio(row.get("code", ""), row.get("name", ""))


def _levels(rows: list[dict]) -> dict[int, list[dict]]:
    """按连板数分组（只保留 >=1）。"""
    out: dict[int, list[dict]] = {}
    for row in rows:
        level = _i(row.get("consecutive_days"))
        if level >= 1:
            out.setdefault(level, []).append(row)
    return dict(sorted(out.items(), reverse=True))


def _codes(rows: list[dict]) -> set[str]:
    return {str(row.get("code")) for row in rows if row.get("code")}


def _stock_brief(row: dict) -> dict:
    """榜单里展示用的个股字段（去掉原始脏字段）。"""
    return {
        "code": row.get("code"),
        "name": row.get("name"),
        "consecutive_days": _i(row.get("consecutive_days")),
        "change_pct": _f(row.get("change_pct")),
        "latest_price": _f(row.get("latest_price")),
        "deal_amount_yi": round((_f(row.get("deal_amount")) or 0) / 1e8, 4),
        "turnover_rate": _f(row.get("turnover_rate")),
        "sealed_capital_yi": round((_f(row.get("sealed_capital")) or 0) / 1e8, 4),
        "first_seal_time": row.get("first_seal_time"),
        "last_seal_time": row.get("last_seal_time"),
        "break_count": _i(row.get("break_count")),
        "limit_up_stats": row.get("limit_up_stats"),
        "industry": row.get("industry"),
    }


# ---------------------------------------------------------------- 八个端点


def _promotion_tiers(prev_rows: list[dict], hit_codes: set) -> list[dict]:
    """晋级率按昨日板位分档（1进2 / 2进3 / 3板以上）。

    同一批票按昨日连板数拆开算，各档 base/promoted 加总 = 整体晋级率；
    昨日池里板位缺失的票归「板位未知」档（仅在该档非空时出现），恒等式不被破坏。
    """
    tiers: list[dict] = []
    known: set = set()
    for name, lo, hi in (("1进2", 1, 1), ("2进3", 2, 2), ("3板以上", 3, None)):
        codes: set = set()
        for r in prev_rows:
            raw = r.get("consecutive_days")
            if raw in (None, ""):
                continue
            d = _i(raw, default=-1)
            if d >= lo and (hi is None or d <= hi):
                codes.add(r.get("code"))
        known |= codes
        base = len(codes)
        p = len(codes & hit_codes)
        tiers.append({"tier": name, "base": base, "promoted": p, "rate": _pct(p, base)})
    unknown = {r.get("code") for r in prev_rows} - known
    if unknown:
        p = len(unknown & hit_codes)
        tiers.append({"tier": "板位未知", "base": len(unknown), "promoted": p, "rate": _pct(p, len(unknown))})
    return tiers


def emotion(snapshot: PoolSnapshot) -> tuple[dict, str]:
    """情绪四项：赚钱效应 / 晋级率 / 连板溢价 / 梯队断层。"""
    prev = snapshot.prev_zt
    prev_ok = snapshot.has("prev_zt") and bool(prev)
    missing: list[str] = []
    if not snapshot.has("prev_zt"):
        missing.append("prev_zt 池缺数，赚钱效应/晋级率/连板溢价无法计算")
    elif not prev:
        missing.append("prev_zt 池为空（可能前一交易日无涨停）")

    up_rows = [row for row in prev if (_f(row.get("change_pct")) or 0) > 0]
    money_effect = {
        "up_ratio": _pct(len(up_rows), len(prev)) if prev_ok else None,
        "avg_change_pct": _mean([_f(r.get("change_pct")) for r in prev if _f(r.get("change_pct")) is not None])
        if prev_ok else None,
        "up_count": len(up_rows) if prev_ok else None,
        "sample": len(prev) if prev_ok else None,
    }

    promoted = None
    promotion_rate = None
    promotion_tiers = None
    if prev_ok:
        hit = _codes(prev) & _codes(snapshot.zt)
        promoted = len(hit)
        promotion_rate = _pct(promoted, len(prev))
        promotion_tiers = _promotion_tiers(prev, hit)

    premium = None
    if prev_ok:
        lianban = [r for r in prev if _i(r.get("consecutive_days")) >= 2]
        first = [r for r in prev if _i(r.get("consecutive_days")) == 1]
        lianban_avg = _mean([_f(r.get("change_pct")) for r in lianban if _f(r.get("change_pct")) is not None])
        first_avg = _mean([_f(r.get("change_pct")) for r in first if _f(r.get("change_pct")) is not None])
        premium = {
            "lianban_avg": lianban_avg,
            "first_avg": first_avg,
            "diff": round(lianban_avg - first_avg, 2)
            if lianban_avg is not None and first_avg is not None
            else None,
        }

    grouped = _levels(snapshot.zt)
    max_board = max(grouped) if grouped else 0
    gaps = [lv for lv in range(1, max_board) if lv not in grouped]
    ladder_gap = {"max_board": max_board, "gaps": gaps, "has_gap": bool(gaps)}

    result = {
        "money_effect": money_effect,
        "promotion_rate": promotion_rate,
        "promoted": promoted,
        "promotion_tiers": promotion_tiers,
        "premium": premium,
        "ladder_gap": ladder_gap,
        "missing_reason": missing or None,
    }
    parts = [
        f"赚钱效应 {money_effect['up_ratio']}%（昨日涨停 {money_effect['up_count']}/{money_effect['sample']} 上涨）"
        if prev_ok else "赚钱效应 —（昨日涨停池缺数）",
        f"晋级率 {promotion_rate}%（{promoted}/{len(prev)}）" if prev_ok else "晋级率 —",
        "晋级分档 " + "、".join(f"{t['tier']} {t['promoted']}/{t['base']}" for t in (promotion_tiers or []) if t["base"])
        if prev_ok else "晋级分档 —",
        f"连板溢价 {premium['diff']:+}pct（连板均 {premium['lianban_avg']}% − 首板均 {premium['first_avg']}%）"
        if premium and premium["diff"] is not None else "连板溢价 —",
        f"梯队{'断层：缺 ' + '/'.join(str(g) for g in gaps) + ' 板' if gaps else '完整'}（最高 {max_board} 板）",
    ]
    return result, f"{snapshot.date} 情绪四项：" + "；".join(parts)


def daily(snapshot: PoolSnapshot) -> tuple[dict, str]:
    """每日读数：涨停数 / 最高板 / 炸板率 / 昨日涨停今日中位 / 1进2。"""
    missing: list[str] = []
    zt_count = len(snapshot.zt)
    grouped = _levels(snapshot.zt)
    max_board = max(grouped) if grouped else 0

    broken = None
    break_rate = None
    if snapshot.has("zb"):
        broken = len(snapshot.zb)
        break_rate = _pct(broken, zt_count + broken)
    else:
        missing.append("zb 池缺数，炸板率无法计算")

    prev = snapshot.prev_zt
    prev_median = None
    if snapshot.has("prev_zt"):
        prev_median = _median([_f(r.get("change_pct")) for r in prev if _f(r.get("change_pct")) is not None])
    else:
        missing.append("prev_zt 池缺数，昨日涨停今日中位无法计算")

    first_to_second = None
    if snapshot.has("prev_zt"):
        first = [r for r in prev if _i(r.get("consecutive_days")) == 1]
        advanced = _codes(first) & _codes(snapshot.zt)
        first_to_second = {
            "prev_first": len(first),
            "advanced": len(advanced),
            "ratio": _pct(len(advanced), len(first)),
        }
    else:
        missing.append("prev_zt 池缺数，1进2 无法计算")

    result = {
        "limit_up_count": zt_count,
        "max_board": max_board,
        "broken_count": broken,
        "break_rate": break_rate,
        "prev_zt_median": prev_median,
        "first_to_second": first_to_second,
        "missing_reason": missing or None,
    }
    text = (
        f"{snapshot.date} 每日读数：涨停 {zt_count} 家，最高 {max_board} 板；"
        f"炸板率 {break_rate}%({broken}/{zt_count + (broken or 0)})；"
        f"昨日涨停今日中位 {prev_median}%；"
        f"1进2 {first_to_second['advanced']}/{first_to_second['prev_first']}"
        f"（{first_to_second['ratio']}%）"
        if first_to_second else
        f"{snapshot.date} 每日读数：涨停 {zt_count} 家，最高 {max_board} 板；炸板率 {break_rate}%"
    )
    return result, text


def settled(snapshot: PoolSnapshot) -> tuple[dict, str]:
    """昨日涨停股当日表现明细（按今日涨跌幅降序）。"""
    if not snapshot.has("prev_zt"):
        return {
            "count": 0,
            "stocks": [],
            "missing_reason": ["prev_zt 池缺数，无法给出昨日涨停股今日表现"],
        }, f"{snapshot.date} 昨日涨停股今日表现 —（prev_zt 池缺数）"

    stocks = [_stock_brief(row) for row in snapshot.prev_zt]
    stocks.sort(key=lambda s: (-(s["change_pct"] if s["change_pct"] is not None else -999), s["code"] or ""))
    result = {
        "count": len(stocks),
        "stocks": stocks,
        "missing_reason": None,
        "stats": {
            "up": sum(1 for s in stocks if (s["change_pct"] or 0) > 0),
            "down": sum(1 for s in stocks if (s["change_pct"] or 0) < 0),
            "median": _median([s["change_pct"] for s in stocks if s["change_pct"] is not None]),
        },
    }
    text = (
        f"{snapshot.date} 昨日涨停 {len(stocks)} 只今日表现："
        f"上涨 {result['stats']['up']} / 下跌 {result['stats']['down']}，"
        f"中位 {result['stats']['median']}%"
    )
    return result, text


def live(snapshot: PoolSnapshot) -> tuple[dict, str]:
    """此刻情绪：涨停 / 炸板 / 跌停家数、封板率、1进2。"""
    zt_count = len(snapshot.zt)
    broken = len(snapshot.zb) if snapshot.has("zb") else None
    limit_down = len(snapshot.dt) if snapshot.has("dt") else None
    seal_rate = None
    if broken is not None:
        seal_rate = _pct(zt_count, zt_count + broken)

    first_to_second = None
    if snapshot.has("prev_zt") and snapshot.prev_zt:
        first = [r for r in snapshot.prev_zt if _i(r.get("consecutive_days")) == 1]
        advanced = _codes(first) & _codes(snapshot.zt)
        first_to_second = {"prev_first": len(first), "advanced": len(advanced),
                           "ratio": _pct(len(advanced), len(first))}

    missing = [f"{p} 池缺数" for p in ("zb", "dt", "prev_zt") if not snapshot.has(p)]
    result = {
        "limit_up": zt_count,
        "broken": broken,
        "limit_down": limit_down,
        "seal_rate": seal_rate,
        "first_to_second": first_to_second,
        "missing_reason": missing or None,
    }
    text = (
        f"{snapshot.date} 此刻：涨停 {zt_count}，炸板 {broken if broken is not None else '—'}，"
        f"跌停 {limit_down if limit_down is not None else '—'}，封板率 {seal_rate if seal_rate is not None else '—'}%"
    )
    return result, text


def ladder(snapshot: PoolSnapshot) -> tuple[dict, str]:
    """昨日全部涨停股按连板数排（梯队 + 各层名单）。"""
    if not snapshot.has("prev_zt"):
        return {
            "levels": [],
            "stocks": [],
            "missing_reason": ["prev_zt 池缺数，无法给出昨日梯队"],
        }, f"{snapshot.date} 昨日梯队 —（prev_zt 池缺数）"

    grouped = _levels(snapshot.prev_zt)
    levels = []
    for level, rows in grouped.items():
        briefs = [_stock_brief(r) for r in rows]
        levels.append({"level": level, "label": f"{level}板", "count": len(rows), "stocks": briefs})
    all_stocks = sorted(
        [_stock_brief(r) for r in snapshot.prev_zt],
        key=lambda s: (-s["consecutive_days"], s["code"] or ""),
    )
    result = {"levels": levels, "stocks": all_stocks, "missing_reason": None}
    text = (
        f"{snapshot.date} 昨日涨停梯队："
        + " / ".join(f"{lv['label']} {lv['count']} 只" for lv in levels)
        if levels else f"{snapshot.date} 昨日梯队：空"
    )
    return result, text


def board_ladder(snapshot: PoolSnapshot) -> tuple[dict, str]:
    """连板天梯 + 低一层没接上的票去向。"""
    today_levels = _levels(snapshot.zt)
    levels = [
        {"level": level, "label": f"{level}板", "count": len(rows),
         "stocks": [_stock_brief(r) for r in rows]}
        for level, rows in today_levels.items()
    ]

    missed: list[dict] = []
    missing_reason = None
    if snapshot.has("prev_zt"):
        today_codes = _codes(snapshot.zt)
        for row in snapshot.prev_zt:
            prev_level = _i(row.get("consecutive_days"))
            if prev_level < 1:
                continue
            if str(row.get("code")) in today_codes:
                continue  # 晋级成功
            change = _f(row.get("change_pct"))
            if _is_limit_up_today(row):
                fate = "涨停未入池异常"
            elif change is None:
                fate = "缺数"
            elif change <= -_limit_ratio(row.get("code", ""), row.get("name", "")):
                fate = "跌停"
            elif change < 0:
                fate = "走弱"
            else:
                fate = "炸板/冲高回落"
            missed.append({
                "code": row.get("code"),
                "name": row.get("name"),
                "prev_level": prev_level,
                "change_pct": change,
                "fate": fate,
            })
        missed.sort(key=lambda m: (-m["prev_level"], m["code"] or ""))
    else:
        missing_reason = ["prev_zt 池缺数，无法给出「低一层没接上的票去向」"]

    result = {"levels": levels, "missed": missed, "missing_reason": missing_reason}
    text = (
        f"{snapshot.date} 连板天梯："
        + " / ".join(f"{lv['label']} {lv['count']}" for lv in levels)
        + (f"；未晋级 {len(missed)} 只" if missed else "")
    )
    return result, text


_BOARD_PREFIX = {
    "主板": ("600", "601", "603", "605", "000", "001", "002", "003"),
    "创业板": ("300", "301"),
    "科创板": ("688", "689"),
    "北交所": ("43", "83", "87", "92"),
}


def _board_name(code: str) -> str:
    for name, prefixes in _BOARD_PREFIX.items():
        if str(code).startswith(prefixes):
            return name
    return "其他"


def structure(snapshot: PoolSnapshot) -> tuple[dict, str]:
    """涨停结构（板块/ST/首板占比）+ 四池上游字段清单（防假断点）。"""
    total = len(snapshot.zt)
    boards: dict[str, int] = {}
    st_count = 0
    first_board = 0
    lianban = 0
    for row in snapshot.zt:
        boards[_board_name(row.get("code", ""))] = boards.get(_board_name(row.get("code", "")), 0) + 1
        if "ST" in str(row.get("name", "")):
            st_count += 1
        level = _i(row.get("consecutive_days"))
        if level == 1:
            first_board += 1
        elif level >= 2:
            lianban += 1

    upstream = {pool: snapshot.fields.get(pool, []) for pool in ("zt", "zb", "dt", "prev_zt")}
    missing = [f"{p} 池缺数（字段清单为空）" for p in ("zb", "dt", "prev_zt") if not snapshot.has(p)]

    result = {
        "limit_up_count": total,
        "boards": {
            name: {"count": count, "ratio": _pct(count, total)}
            for name, count in sorted(boards.items(), key=lambda kv: -kv[1])
        },
        "st": {"count": st_count, "ratio": _pct(st_count, total)},
        "streak": {
            "first_board": first_board,
            "lianban": lianban,
            "first_ratio": _pct(first_board, total),
        },
        "upstream_fields": upstream,
        "missing_reason": missing or None,
    }
    text = (
        f"{snapshot.date} 涨停结构：共 {total} 家；"
        + "、".join(f"{name} {v['count']}" for name, v in result["boards"].items())
        + f"；首板 {first_board}、连板 {lianban}；ST {st_count}"
    )
    return result, text


def cycle(
    snapshot: PoolSnapshot,
    days: int = 5,
    history: list[dict] | None = None,
    missing_dates: list[str] | None = None,
) -> tuple[dict, str]:
    """近 N 日涨停数 / 最高板 / 炸板率合成窗口分位。

    history 来自收盘定稿落库（H3 之前为空，标 missing_reason，不当 0）。
    """
    days = max(int(days or 5), 2)
    window: list[dict] = []
    for item in (history or []):
        if item.get("limit_up_count") is None:
            continue
        window.append({
            "date": item.get("date"),
            "limit_up_count": item.get("limit_up_count"),
            "max_board": item.get("max_board"),
            "break_rate": item.get("break_rate"),
        })
    window = window[-days + 1:]  # 留一格给今天

    grouped = _levels(snapshot.zt)
    today = {
        "date": snapshot.date,
        "limit_up_count": len(snapshot.zt),
        "max_board": max(grouped) if grouped else 0,
        "break_rate": _pct(len(snapshot.zb), len(snapshot.zt) + len(snapshot.zb)) if snapshot.has("zb") else None,
    }
    window.append(today)

    metrics: dict[str, dict] = {}
    for key in ("limit_up_count", "max_board", "break_rate"):
        values = [row[key] for row in window if row.get(key) is not None]
        current = today.get(key)
        if not values or current is None:
            metrics[key] = {"value": current, "window": values, "percentile": None}
            continue
        rank = sum(1 for v in values if v <= current) / len(values) * 100
        metrics[key] = {
            "value": current,
            "window": values,
            "percentile": round(rank, 1),
            "median": _median(values),
            "max": max(values),
        }

    percentiles = [m["percentile"] for m in metrics.values() if m["percentile"] is not None]
    composite = round(sum(percentiles) / len(percentiles), 1) if percentiles else None

    missing_reason = []
    if not history:
        missing_reason.append("历史未积累（需先跑 15:35 收盘落库），当前分位只含今日")
    if missing_dates:
        missing_reason.append(f"窗口缺 {len(missing_dates)} 天：" + ",".join(missing_dates))
    if today["break_rate"] is None:
        missing_reason.append("zb 池缺数，炸板率分位无法计算")

    result = {
        "window_days": len(window),
        "requested_days": days,
        "metrics": metrics,
        "composite_percentile": composite,
        "missing_dates": missing_dates or [],
        "missing_reason": missing_reason or None,
    }
    text = (
        f"{snapshot.date} 情绪周期（{len(window)} 日窗口）："
        f"涨停 {today['limit_up_count']}（分位 {metrics['limit_up_count']['percentile']}）；"
        f"最高板 {today['max_board']}（分位 {metrics['max_board']['percentile']}）；"
        f"炸板率 {today['break_rate']}（分位 {metrics['break_rate']['percentile']}）；"
        f"合成分位 {composite}"
    )
    return result, text


# ---------------------------------------------------------------- H6：题材 / 首板 / 事实 / 轮动

_REASON_SPLIT = re.compile(r"[、,，;；+＋|/]")


def _reason_tokens(reason: str) -> list[str]:
    """把涨停原因拆成题材关键词（去掉过长句子与空串）。"""
    tokens: list[str] = []
    for part in _REASON_SPLIT.split(str(reason or "")):
        token = part.strip()
        if not token or len(token) > 15:
            continue
        if token in tokens:
            continue
        tokens.append(token)
    return tokens


def themes(
    snapshot: PoolSnapshot,
    reasons: dict[str, str] | None = None,
    source: str = "同花顺涨停归因",
) -> tuple[dict, str]:
    """题材事件树：涨停原因归组（问财优先 / 同花顺兜底）。"""
    reasons = reasons or {}
    events: dict[str, list[dict]] = {}
    keyword_counts: dict[str, int] = {}
    unattributed: list[dict] = []
    for row in snapshot.zt:
        code = str(row.get("code") or "")
        reason = str(reasons.get(code) or "").strip()
        if not reason:
            unattributed.append({"code": code, "name": row.get("name")})
            continue
        events.setdefault(reason, []).append({"code": code, "name": row.get("name")})
        for token in _reason_tokens(reason):
            keyword_counts[token] = keyword_counts.get(token, 0) + 1

    event_list = [
        {"theme": theme, "count": len(stocks), "stocks": stocks}
        for theme, stocks in events.items()
    ]
    event_list.sort(key=lambda item: (-item["count"], item["theme"]))
    keywords = [
        {"theme": name, "count": count}
        for name, count in sorted(keyword_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ][:20]

    missing_reason = None
    if not reasons:
        missing_reason = ["涨停原因源不可用（问财/同花顺均失败或空），题材树只有未归因名单"]
    elif unattributed:
        missing_reason = [f"{len(unattributed)} 只涨停股没有归因（原因源未覆盖）"]

    result = {
        "reason_source": source,
        "events": event_list,
        "keywords": keywords,
        "unattributed": unattributed,
        "unattributed_count": len(unattributed),
        "missing_reason": missing_reason,
    }
    top = "、".join(f"{k['theme']}({k['count']})" for k in keywords[:3]) or "—"
    text = (
        f"{snapshot.date} 题材事件树（{source}）：{len(event_list)} 个事件，"
        f"{len(keywords)} 个关键词；热度前列 {top}；未归因 {len(unattributed)} 只"
    )
    return result, text


def _seal_minutes(value) -> int | None:
    """把封板时间（HHMMSS / HH:MM:SS）转成当日分钟数，用于排序/中位。"""
    raw = str(value or "").replace(":", "").strip()
    if len(raw) != 6 or not raw.isdigit():
        return None
    hh, mm, ss = int(raw[0:2]), int(raw[2:4]), int(raw[4:6])
    if hh > 23 or mm > 59 or ss > 59:
        return None
    return hh * 60 + mm


def _reversal_flag(limit_up_stats: str) -> tuple[bool | None, str]:
    """从「涨停统计」判断反包：格式 今涨停数/近N日涨停数，近N>1 视为反包。"""
    raw = str(limit_up_stats or "").strip()
    if "/" not in raw:
        return None, "涨停统计缺失，无法判定反包"
    left, right = raw.split("/", 1)
    try:
        today_count = int(left)
        window_count = int(right)
    except ValueError:
        return None, f"涨停统计格式无法解析：{raw}"
    return window_count > 1 and today_count <= 1, f"涨停统计 {raw}"


def firstboard(snapshot: PoolSnapshot) -> tuple[dict, str]:
    """首板名单：按首次封板时间排序，反包票单标。"""
    rows = [row for row in snapshot.zt if _i(row.get("consecutive_days")) == 1]
    stocks: list[dict] = []
    for row in rows:
        minutes = _seal_minutes(row.get("first_seal_time"))
        reversal, note = _reversal_flag(row.get("limit_up_stats"))
        stocks.append({
            **_stock_brief(row),
            "first_seal_minutes": minutes,
            "is_reversal": reversal,
            "reversal_note": note,
        })
    # 缺封板时间的排最后（None → 极大值），同时间按代码
    stocks.sort(key=lambda s: (s["first_seal_minutes"] is None, s["first_seal_minutes"] or 0, s["code"] or ""))

    missing_reason = None
    if not rows:
        missing_reason = ["今日无首板（涨停池为空或全部为连板）"]
    result = {
        "count": len(stocks),
        "stocks": stocks,
        "reversal_count": sum(1 for s in stocks if s["is_reversal"]),
        "missing_reason": missing_reason,
    }
    text = (
        f"{snapshot.date} 首板 {len(stocks)} 只（反包 {result['reversal_count']} 只）："
        + "、".join(f"{s['name']}{'(反包)' if s['is_reversal'] else ''}" for s in stocks[:8])
        if stocks else f"{snapshot.date} 首板：无"
    )
    return result, text


def _fate_of_change(change: float | None, row: dict) -> str:
    if change is None:
        return "缺数"
    ratio = _limit_ratio(row.get("code", ""), row.get("name", ""))
    if change >= ratio:
        return "涨停"
    if change <= -ratio:
        return "跌停"
    if change > 0:
        return "上涨"
    if change < 0:
        return "下跌"
    return "走平"


def _level_bucket(level: int) -> str:
    if level <= 1:
        return "首板"
    if level == 2:
        return "2板"
    return "3板+"


def facts(snapshot: PoolSnapshot) -> tuple[dict, str]:
    """盘面事实：封板质量 / 亏钱效应 / 强势股反馈矩阵。"""
    zt = snapshot.zt
    seal_minutes = [m for m in (_seal_minutes(r.get("first_seal_time")) for r in zt) if m is not None]
    sealed_capital = [_f(r.get("sealed_capital")) for r in zt if _f(r.get("sealed_capital")) is not None]
    break_counts = [_i(r.get("break_count")) for r in zt]

    quality = {
        "avg_sealed_capital_yi": round(sum(sealed_capital) / len(sealed_capital) / 1e8, 4)
        if sealed_capital else None,
        "median_first_seal_time": _fmt_minutes(_median(seal_minutes)),
        "avg_break_count": round(sum(break_counts) / len(break_counts), 2) if break_counts else None,
        "seal_rate": _pct(len(zt), len(zt) + len(snapshot.zb)) if snapshot.has("zb") else None,
        "sample": len(zt),
    }

    missing: list[str] = []
    if snapshot.has("prev_zt") and snapshot.prev_zt:
        changes = [_f(r.get("change_pct")) for r in snapshot.prev_zt if _f(r.get("change_pct")) is not None]
        down = [c for c in changes if c < 0]
        losing = {
            "prev_zt_count": len(snapshot.prev_zt),
            "down_ratio": _pct(len(down), len(changes)),
            "median_change": _median(changes),
            "limit_down_count": len(snapshot.dt) if snapshot.has("dt") else None,
        }
    else:
        losing = {"prev_zt_count": None, "down_ratio": None, "median_change": None,
                  "limit_down_count": len(snapshot.dt) if snapshot.has("dt") else None}
        missing.append("prev_zt 池缺数，亏钱效应无法计算")

    matrix: dict[str, dict[str, int]] = {}
    if snapshot.has("prev_zt"):
        for row in snapshot.prev_zt:
            bucket = _level_bucket(_i(row.get("consecutive_days")))
            fate = _fate_of_change(_f(row.get("change_pct")), row)
            matrix.setdefault(bucket, {})
            matrix[bucket][fate] = matrix[bucket].get(fate, 0) + 1
    else:
        missing.append("prev_zt 池缺数，反馈矩阵无法计算")

    result = {
        "seal_quality": quality,
        "losing_effect": losing,
        "feedback_matrix": matrix,
        "missing_reason": missing or None,
    }
    text = (
        f"{snapshot.date} 盘面事实：封板率 {quality['seal_rate']}%，"
        f"均封单 {quality['avg_sealed_capital_yi']} 亿，封板中位时间 {quality['median_first_seal_time']}；"
        f"昨日涨停今日下跌占比 {losing['down_ratio']}%，中位 {losing['median_change']}%"
    )
    return result, text


def _fmt_minutes(minutes: float | None) -> str | None:
    """分钟数 → HH:MM。"""
    if minutes is None:
        return None
    total = int(round(minutes))
    return f"{total // 60:02d}:{total % 60:02d}"


def theme_rotation(
    days_records: list[dict],
    missing_dates: list[str] | None = None,
) -> tuple[dict, str]:
    """题材轮动：近 N 日每天只数 / 名次 / 连续 / 回流；缺天画「—」不当 0。

    Args:
        days_records: 升序列表，每项 {"date","available":bool,"theme_counts":{...}|None}
    """
    missing_dates = missing_dates or []
    days = [{"date": r["date"], "available": bool(r.get("available", True))} for r in days_records]
    if not days:
        return {
            "days": [],
            "rows": [],
            "missing_dates": missing_dates,
            "missing_reason": ["无可用题材历史（需先跑收盘落库并成功归因）"],
        }, "题材轮动：无历史数据"

    today = days_records[-1]
    today_counts: dict[str, int] = dict(today.get("theme_counts") or {})
    themes_sorted = sorted(today_counts.items(), key=lambda kv: (-kv[1], kv[0]))

    rows = []
    for theme, _count in themes_sorted:
        counts: list[int | None] = []
        displays: list[str] = []
        ranks: list[int | None] = []
        for record in days_records:
            if not record.get("available", True) or record.get("theme_counts") is None:
                counts.append(None)
                displays.append("—")
                ranks.append(None)
                continue
            value = int(record["theme_counts"].get(theme, 0))
            counts.append(value)
            displays.append(str(value))
            ordered = sorted(record["theme_counts"].items(), key=lambda kv: -kv[1])
            ranks.append(next((i + 1 for i, (name, _) in enumerate(ordered) if name == theme), None))

        streak = 0
        for value in reversed(counts):
            if value is None or value <= 0:
                break
            streak += 1

        previous_available = next(
            (c for c in reversed(counts[:-1]) if c is not None), None
        )
        is_returning = bool(counts[-1]) and previous_available == 0

        rows.append({
            "theme": theme,
            "counts": counts,
            "display": " / ".join(displays),
            "ranks": ranks,
            "streak": streak,
            "is_returning": is_returning,
            "today_count": counts[-1],
        })

    result = {
        "days": [d["date"] for d in days],
        "rows": rows,
        "missing_dates": missing_dates,
        "missing_reason": None,
    }
    text = (
        f"题材轮动（{len(days)} 日）："
        + "；".join(
            f"{r['theme']} {r['display']}"
            + (f"（连续{r['streak']}日）" if r["streak"] >= 2 else "")
            + ("（回流）" if r["is_returning"] else "")
            for r in rows[:5]
        )
    )
    return result, text
