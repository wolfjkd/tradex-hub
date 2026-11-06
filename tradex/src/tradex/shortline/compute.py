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
        "break_count": _i(row.get("break_count")),
        "industry": row.get("industry"),
    }


# ---------------------------------------------------------------- 八个端点


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
    if prev_ok:
        hit = _codes(prev) & _codes(snapshot.zt)
        promoted = len(hit)
        promotion_rate = _pct(promoted, len(prev))

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
        "premium": premium,
        "ladder_gap": ladder_gap,
        "missing_reason": missing or None,
    }
    parts = [
        f"赚钱效应 {money_effect['up_ratio']}%（昨日涨停 {money_effect['up_count']}/{money_effect['sample']} 上涨）"
        if prev_ok else "赚钱效应 —（昨日涨停池缺数）",
        f"晋级率 {promotion_rate}%（{promoted}/{len(prev)}）" if prev_ok else "晋级率 —",
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
