"""短线收盘定稿落库（工单 H3）。

为什么必须落库：东财四池只保留约一个月，且四池函数全部是「当前态」、不带
历史日期参数——今天不存，下个月永久补不回来。

落库规则：
  1. 幂等：同一日重复调用不重复写（已有 final 直接跳过）
  2. 不覆盖坏数据：partial 永不覆盖 final；partial→final 允许升级
  3. 缺数写 missing_reason，不当 0
  4. schema_version 逐文件记录，结构变更必须 +1
  5. 写失败 ERROR 日志 + ``health()`` 可查（H7 接入数据源健康页）

文件：``data/shortline/close/YYYYMMDD.json``（可用 SHORTLINE_DATA_DIR 覆盖根目录）
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path

from ..shortline import compute
from ..shortline.compute import PoolSnapshot

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 2  # v2（H6）：新增 themes 读数 + theme_counts（题材轮动的历史原料）

# 落定的读数（H6 起含题材；后续再扩必须 schema +1）
_READINGS = ("emotion", "daily", "settled", "ladder", "board_ladder", "structure", "themes")

_state_guard = threading.Lock()
_date_locks: dict[str, threading.Lock] = {}

_health: dict = {
    "writes": 0,
    "skips": 0,
    "last_write_at": None,
    "last_date": None,
    "last_error": None,
    "last_error_at": None,
}


def _base_dir() -> Path:
    """落库根目录（默认仓库根/data/shortline，可用环境变量覆盖）。"""
    env = os.getenv("SHORTLINE_DATA_DIR", "").strip()
    if env:
        return Path(env)
    # store.py → shortline → tradex(pkg) → src → tradex(子目录) → 仓库根
    return Path(__file__).resolve().parents[4] / "data" / "shortline"


def _close_dir() -> Path:
    return _base_dir() / "close"


def record_path(date: str) -> Path:
    """某交易日的定稿文件路径。"""
    return _close_dir() / f"{date}.json"


def _lock_for(date: str) -> threading.Lock:
    with _state_guard:
        lock = _date_locks.get(date)
        if lock is None:
            lock = threading.Lock()
            _date_locks[date] = lock
        return lock


def _write_atomic(path: Path, payload: dict) -> None:
    """原子写：临时文件 + os.replace（进程崩溃不会留半截 JSON）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def load(date: str) -> dict | None:
    """读取某日定稿（不存在/损坏返回 None，损坏时记 health）。"""
    path = record_path(date)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - 损坏文件不能拖垮历史读取
        logger.error("shortline store: %s 读取失败: %s", path, exc)
        _mark_error(f"读取 {date} 失败: {exc}")
        return None


def _mark_error(message: str) -> None:
    _health["last_error"] = message
    _health["last_error_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def health() -> dict:
    """落库健康状态（供数据源健康 / 诊断页读取）。"""
    return {
        **dict(_health),
        "dir": str(_close_dir()),
        "schema_version": SCHEMA_VERSION,
        "dates": len(_stored_dates()),
    }


# ---------------------------------------------------------------- 落库


def _should_write(
    existing: dict | None, new_status: str, force: bool, new_schema: int = SCHEMA_VERSION
) -> tuple[bool, str]:
    """幂等/防覆盖判定。"""
    if existing is None:
        return True, "首次落库"
    existing_status = existing.get("status")
    if existing_status == "final":
        if new_status != "final":
            return False, "已存在 final，拒绝 partial 覆盖"
        old_schema = int(existing.get("schema_version") or 0)
        if old_schema < new_schema:
            # schema 升级（如 v1→v2 新增 theme_counts）：不带 force 也必须重算升级，
            # 否则旧结构会永久卡住历史（轮动永远「—」）。新记录同样必须是 final。
            return True, f"schema 升级 {old_schema}→{new_schema}，重算覆盖 final"
        if not force:
            return False, "已存在 final，幂等跳过（force=true 可重算）"
        return True, "force 重算并覆盖 final"
    if new_status == "final":
        return True, "partial → final 升级"
    if force:
        return True, "force 重算 partial"
    return False, "已存在 partial，幂等跳过（force=true 可重算）"


def close_fetch(date: str = "", force: bool = False) -> dict:
    """收盘定稿取数 + 落库（幂等）。

    Args:
        date: 交易日 YYYYMMDD，默认今天。
        force: 已有记录时强制重算（仍拒绝 partial 覆盖 final）。

    Returns:
        {"date","status","written","reason","schema_version","missing_reasons","path"}

    Raises:
        RuntimeError: 四池取数失败（涨停池是核心口径，取不到不写坏数据）。
    """
    from ..service import shortline_service  # 延迟导入避免循环

    snapshot = shortline_service.collect_snapshot(
        date=date, need=("zt", "zb", "dt", "prev_zt")
    )
    if not snapshot.date:
        raise RuntimeError("无法确定交易日（涨停池未返回日期）")

    # 封板时间注入（2026-11-08 票B）：仅落库路径做，失败只记原因不拦截
    shortline_service.ensure_prev_zt_seal_times(snapshot)

    partial = shortline_service._is_intraday(snapshot.date) or bool(snapshot.missing)
    status = "partial" if partial else "final"

    results: dict[str, dict] = {}
    for name, fn in (
        ("emotion", compute.emotion),
        ("daily", compute.daily),
        ("settled", compute.settled),
        ("ladder", compute.ladder),
        ("board_ladder", compute.board_ladder),
        ("structure", compute.structure),
    ):
        payload, text = fn(snapshot)
        results[name] = {"result": payload, "text": text}

    # 题材归因走外部源（问财→同花顺）；取不到不算落库失败，但要写明原因
    try:
        reasons, reason_source, reason_problems = shortline_service.fetch_reasons(snapshot.date)
    except Exception as exc:  # noqa: BLE001
        reasons, reason_source, reason_problems = {}, "无", [f"归因异常：{exc}"]
    theme_result, theme_text = compute.themes(snapshot, reasons, reason_source)
    if reason_problems and not theme_result.get("missing_reason"):
        theme_result["missing_reason"] = reason_problems
    results["themes"] = {"result": theme_result, "text": theme_text}
    theme_counts = {
        item["theme"]: item["count"] for item in theme_result.get("keywords", [])
    }

    missing_reasons: dict = {"pools": dict(snapshot.reasons)}
    for name in _READINGS:
        endpoint_missing = results[name]["result"].get("missing_reason")
        if endpoint_missing:
            missing_reasons[name] = endpoint_missing

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "date": snapshot.date,
        "status": status,
        "fetched_at": now,
        "source": shortline_service._SOURCE,
        "compliance": "cn-public",
        "readings": results,
        "daily_metrics": _daily_metrics(results["daily"]["result"]),
        "theme_counts": theme_counts,
        "raw_fields": {pool: list(snapshot.fields.get(pool) or []) for pool in ("zt", "zb", "dt", "prev_zt")},
        "missing_reason": missing_reasons,
    }

    path = record_path(snapshot.date)
    with _lock_for(snapshot.date):
        existing = load(snapshot.date)
        should_write, reason = _should_write(existing, status, bool(force))
        if not should_write:
            _health["skips"] += 1
            logger.info("shortline store: %s 跳过落库（%s）", snapshot.date, reason)
            return {
                "date": snapshot.date,
                "status": existing.get("status") if existing else status,
                "written": False,
                "reason": reason,
                "schema_version": SCHEMA_VERSION,
                "missing_reasons": missing_reasons,
                "path": str(path),
            }
        try:
            _write_atomic(path, payload)
        except Exception as exc:  # noqa: BLE001 - 写失败必须留痕，不能静默
            _mark_error(f"写入 {snapshot.date} 失败: {exc}")
            _health["last_date"] = snapshot.date
            logger.error("shortline store: 写入 %s 失败: %s", path, exc, exc_info=True)
            raise
        _health["writes"] += 1
        _health["last_write_at"] = now
        _health["last_date"] = snapshot.date
        logger.info("shortline store: %s 已落库（status=%s, %s）", snapshot.date, status, reason)

    return {
        "date": snapshot.date,
        "status": status,
        "written": True,
        "reason": reason,
        "schema_version": SCHEMA_VERSION,
        "missing_reasons": missing_reasons,
        "path": str(path),
    }


def _daily_metrics(daily_result: dict) -> dict:
    """从 daily 读数里提取 cycle 需要的三个指标。"""
    return {
        "limit_up_count": daily_result.get("limit_up_count"),
        "max_board": daily_result.get("max_board"),
        "break_rate": daily_result.get("break_rate"),
    }


# ---------------------------------------------------------------- 历史读取


def _stored_dates() -> list[str]:
    """已落库的日期列表（升序）。"""
    directory = _close_dir()
    if not directory.is_dir():
        return []
    dates = []
    for path in directory.glob("*.json"):
        name = path.stem
        if len(name) == 8 and name.isdigit():
            dates.append(name)
    return sorted(dates)


def _weekday_gaps(start: str, end: str, present: set[str]) -> list[str]:
    """start~end 之间缺失的工作日（周末不算；节假日可能误报，调用方需注明）。"""
    try:
        start_dt = datetime.strptime(start, "%Y%m%d")
        end_dt = datetime.strptime(end, "%Y%m%d")
    except ValueError:
        return []
    missing: list[str] = []
    cursor = start_dt
    while cursor <= end_dt:
        key = cursor.strftime("%Y%m%d")
        if cursor.weekday() < 5 and key not in present:
            missing.append(key)
        cursor += timedelta(days=1)
    return missing


def history(days: int = 5, date: str = "") -> dict:
    """读取最近的定稿记录（升序）。

    Args:
        days: 取最近 N 条已落库记录（不是 N 个自然日）。
        date: 截止日期 YYYYMMDD，默认今天。

    Returns:
        {"count","dates","records","missing_dates","schema_version","note"}
        records 里每项含 date/status/limit_up_count/max_board/break_rate。
    """
    try:
        n = max(1, int(days or 5))
    except (TypeError, ValueError):
        n = 5
    end = str(date or "").replace("-", "") or datetime.now().strftime("%Y%m%d")

    dates = [d for d in _stored_dates() if d <= end]
    picked = dates[-n:]
    records: list[dict] = []
    # 窗口分位与 compute.cycle 同口径：当日读数在「窗口内全部读数（含当日）」中的排名百分位；
    # 窗口随序列增长，首日 window_days=1 时恒为 100（无历史可比，诚实标注不算错）。
    windows: dict[str, list] = {"limit_up_count": [], "max_board": [], "break_rate": []}
    for day in picked:
        record = load(day) or {}
        metrics = record.get("daily_metrics") or {}
        readings = record.get("readings") or {}
        daily_result = (readings.get("daily") or {}).get("result") or {}
        emotion_result = (readings.get("emotion") or {}).get("result") or {}
        row = {
            "date": day,
            "status": record.get("status"),
            "fetched_at": record.get("fetched_at"),
            "limit_up_count": metrics.get("limit_up_count"),
            "max_board": metrics.get("max_board"),
            "break_rate": metrics.get("break_rate"),
            # v1 记录没有这些读数 → None（前端显示「—」），不伪造成 0
            "first_to_second": daily_result.get("first_to_second"),
            "promotion_rate": emotion_result.get("promotion_rate"),
            # v1 记录没有 theme_counts → None（轮动显示「—」），不伪造成 0
            "theme_counts": record.get("theme_counts"),
            "missing_reason": record.get("missing_reason"),
        }
        for key in windows:
            if row[key] is not None:
                windows[key].append(row[key])
        percentiles = []
        for key in ("limit_up_count", "max_board", "break_rate"):
            values = windows[key]
            if values and row[key] is not None:
                percentiles.append(round(sum(1 for v in values if v <= row[key]) / len(values) * 100, 1))
        row["composite_percentile"] = round(sum(percentiles) / len(percentiles), 1) if percentiles else None
        row["window_days"] = min(len(windows[k]) for k in windows) if any(windows.values()) else 0
        records.append(row)

    missing_dates = _weekday_gaps(picked[0], picked[-1], set(picked)) if len(picked) >= 2 else []
    return {
        "count": len(records),
        "dates": picked,
        "records": records,
        "missing_dates": missing_dates,
        "schema_version": SCHEMA_VERSION,
        "note": "missing_dates 按工作日推算，节假日可能误报，仅作缺天提示",
    }


def field_snapshot(date: str = "") -> dict | None:
    """读取某日落库的字段清单（H7 漂移检测用）。"""
    day = str(date or "").replace("-", "")
    record = load(day) if day else None
    if not record:
        return None
    return record.get("raw_fields")
