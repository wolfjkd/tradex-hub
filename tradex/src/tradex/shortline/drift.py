"""短线数据源韧性：四池字段漂移检测（工单 H7）。

要防的「假断点」：
  上游把一列改名（比如「封板资金」→「封单额」再→「封单资金」），映射层取不到
  就默认 0——页面显示「封板 0 亿」，看起来像真实 0，其实是字段没了。
  所以每天把四池原始列名随定稿落库（H3 已存 raw_fields），这里做逐日比对：
    - added / removed：逐池列出新增/消失的列
    - alias_gaps：语义字段（封单额/封板时间/炸板次数/连板数）找不到任何别名
    - zero_suspects：别名缺失时，相关指标若为 0 一律标「可疑 0」（不是真 0）

缺数原因统一沿用 ``missing_reason`` 字段（各端点信封同名字段，H2 起已统一）。
"""

from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# 语义字段 → 上游列名别名（与 akshare_fetchers._POOL_FIELD_ALIASES 同源）
SEMANTIC_ALIASES: dict[str, tuple[str, ...]] = {
    "sealed_capital": ("封板资金", "封单资金", "封单额"),
    "first_seal_time": ("首次封板时间", "昨日封板时间"),
    "last_seal_time": ("最后封板时间",),
    "break_count": ("炸板次数", "开板次数"),
    "consecutive_days": ("连板数", "昨日连板数", "连续跌停"),
}

# 每个池**本来就应该有**的语义字段（2026-11-06 按真实四池列名核对）：
#   zt      序号/代码/名称/…/封板资金/首次封板时间/最后封板时间/炸板次数/连板数
#   zb      序号/…/首次封板时间/炸板次数（无封单额、无连板数）
#   dt      序号/…/封单资金/最后封板时间/开板次数/连续跌停（无首封时间）
#   prev_zt 序号/…/昨日封板时间/昨日连板数（无封单额）
POOL_SEMANTIC: dict[str, tuple[str, ...]] = {
    "zt": ("sealed_capital", "first_seal_time", "last_seal_time", "break_count", "consecutive_days"),
    "zb": ("first_seal_time", "break_count"),
    "dt": ("sealed_capital", "last_seal_time", "break_count", "consecutive_days"),
    "prev_zt": ("first_seal_time", "consecutive_days"),
}

_POOLS = ("zt", "zb", "dt", "prev_zt")


def compare_fields(current: dict[str, list[str]], reference: dict[str, list[str]]) -> dict:
    """逐池比对字段清单。"""
    added: dict[str, list[str]] = {}
    removed: dict[str, list[str]] = {}
    for pool in _POOLS:
        cur = set(current.get(pool) or [])
        ref = set(reference.get(pool) or [])
        if not cur or not ref:
            continue
        new_cols = sorted(cur - ref)
        gone_cols = sorted(ref - cur)
        if new_cols:
            added[pool] = new_cols
        if gone_cols:
            removed[pool] = gone_cols
    return {
        "added": added,
        "removed": removed,
        "drift": bool(added or removed),
    }


def alias_gaps(fields_by_pool: dict[str, list[str]]) -> dict[str, list[str]]:
    """找出「该池应有语义字段没有任何别名列」的缺口（相关指标会被映射成 0）。"""
    gaps: dict[str, list[str]] = {}
    for pool, expected in POOL_SEMANTIC.items():
        columns = set(fields_by_pool.get(pool) or [])
        if not columns:
            continue
        missing = [
            semantic for semantic in expected
            if not any(alias in columns for alias in SEMANTIC_ALIASES[semantic])
        ]
        if missing:
            gaps[pool] = missing
    return gaps


_ZERO_METRIC = {
    "sealed_capital": "封单额（sealed_capital_yi）",
    "first_seal_time": "首封时间（first_seal_time）",
    "last_seal_time": "最后封板时间（last_seal_time）",
    "break_count": "炸板次数（break_count）",
    "consecutive_days": "连板数（consecutive_days）",
}


def zero_suspects(gaps: dict[str, list[str]]) -> list[dict]:
    """别名缺失 → 相关指标若显示 0，是「字段变了」而不是「真 0」。"""
    return [
        {
            "pool": pool,
            "field": field,
            "metric": _ZERO_METRIC.get(field, field),
            "reason": "上游字段改名或消失，映射默认 0；显示为 0 时不可当真实值",
        }
        for pool, fields in gaps.items()
        for field in fields
    ]


def field_drift(date: str = "", lookback: int = 10) -> dict:
    """字段漂移报告：当前快照 vs 上一份快照 + 别名缺口。

    Args:
        date: 截止日期 YYYYMMDD，默认今天。
        lookback: 往回找参考快照的最大记录数。

    Returns:
        dict：drift / added / removed / alias_gaps / zero_suspects / alerts / missing_reason
    """
    from . import store

    end = str(date or "").replace("-", "") or datetime.now().strftime("%Y%m%d")
    stored = [d for d in store._stored_dates() if d <= end]
    if not stored:
        return {
            "date": None,
            "reference_date": None,
            "drift": None,
            "added": {},
            "removed": {},
            "alias_gaps": {},
            "zero_suspects": [],
            "alerts": [],
            "missing_reason": {
                "fields": "无字段快照：需先跑收盘落库（raw_fields 随定稿写入）",
            },
        }

    current_date = stored[-1]
    current = store.field_snapshot(current_date) or {}
    reference_date = None
    reference: dict[str, list[str]] = {}
    for day in reversed(stored[:-1][-max(1, int(lookback or 10)):]):
        snapshot = store.field_snapshot(day) or {}
        if any(snapshot.values()):
            reference_date = day
            reference = snapshot
            break

    comparison = compare_fields(current, reference) if reference else {
        "added": {}, "removed": {}, "drift": None,
    }
    gaps = alias_gaps(current)
    suspects = zero_suspects(gaps)

    alerts: list[str] = []
    for pool, cols in comparison["removed"].items():
        alerts.append(f"{pool} 池消失字段：{', '.join(cols)}")
    for pool, cols in comparison["added"].items():
        alerts.append(f"{pool} 池新增字段：{', '.join(cols)}（复核映射是否需要跟进）")
    for pool, fields in gaps.items():
        alerts.append(f"{pool} 池语义字段无匹配列：{', '.join(fields)}（相关指标可能假 0）")

    missing_reason = None
    if not reference:
        missing_reason = {"reference": "无更早的字段快照可比对（首次落库或历史不足）"}
    if not any(current.values()):
        missing_reason = {"fields": f"{current_date} 的字段快照为空"}

    return {
        "date": current_date,
        "reference_date": reference_date,
        "drift": comparison["drift"],
        "added": comparison["added"],
        "removed": comparison["removed"],
        "alias_gaps": gaps,
        "zero_suspects": suspects,
        "alerts": alerts,
        "missing_reason": missing_reason,
    }
