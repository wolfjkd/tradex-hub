"""短线读数 service（工单 H2）。

职责边界：
  - 取数：四池并发走 SmartRouter（复用既有 limit_up_board，不重复造 fetcher）
  - 口径：委托 ``tradex.shortline.compute`` 纯函数
  - 缓存：按 ``tradex.shortline.meta`` 的声明解析，不在函数里写死 TTL
  - 输出：统一信封 result + text + computation，MCP / REST 共用

partial 判定（决定是否允许长期缓存）：
  1. 请求的是「今天」且当前未到 15:05 → 盘中，partial
  2. 任一辅助池缺数 → partial（缓存会把坏数据冻住，宁可下次重取）
  3. live 端点本身就是「此刻」快照，永远 partial（只允许 15 秒缓存）
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time

from ..data_sources import get_router
from ..shortline import compute
from ..shortline.compute import PoolSnapshot
from ..shortline.meta import cache_key, get_endpoint, resolve_cache
from ..utils.cache import cache

logger = logging.getLogger(__name__)

_router = get_router()

_COMPLIANCE = "cn-public"
_SOURCE = "akshare_em(zt/zb/dt/prev_zt)"
_CLOSE_TIME = time(15, 5)
_AUX_POOLS = ("zb", "dt", "prev_zt")

_DEFINITIONS: dict[str, dict[str, str]] = {
    "shortline.emotion": {
        "赚钱效应": "昨日涨停股今日上涨家数 / 昨日涨停家数",
        "晋级率": "昨日涨停 ∩ 今日涨停 / 昨日涨停家数",
        "连板溢价": "昨日连板股今日均涨幅 − 昨日首板股今日均涨幅",
        "梯队断层": "今日最大连板高度以内缺失的层级",
    },
    "shortline.cycle": {
        "窗口分位": "当日指标在近 N 日窗口内的百分位（≤ 当日值的样本占比）",
        "合成": "涨停数 / 最高板 / 炸板率 三项分位均值",
    },
    "shortline.daily": {
        "炸板率": "炸板数 /（涨停数 + 炸板数）",
        "昨日涨停今日中位": "昨日涨停股今日涨跌幅中位数",
        "1进2": "昨日首板今日涨停 / 昨日首板家数",
    },
    "shortline.settled": {
        "明细": "昨日涨停池逐票今日涨跌幅，按涨幅降序",
    },
    "shortline.live": {
        "封板率": "涨停数 /（涨停数 + 炸板数）",
        "1进2": "昨日首板今日涨停 / 昨日首板家数（此刻）",
    },
    "shortline.ladder": {
        "梯队": "昨日涨停池按连板数分组，降序排列",
    },
    "shortline.board_ladder": {
        "天梯": "今日涨停池按连板数分组",
        "未晋级去向": "昨日各层未进入今日涨停池的票，按今日涨跌幅归类（炸板/走弱/跌停）",
    },
    "shortline.structure": {
        "板块占比": "涨停股按主板/创业板/科创板/北交所分组",
        "字段清单": "四池上游原始列名，用于识别「真 0」与「字段变了」",
    },
}


# ---------------------------------------------------------------- 快照


def collect_snapshot(date: str = "", need: tuple[str, ...] = ("zt", *_AUX_POOLS)) -> PoolSnapshot:
    """并发取四池，返回 PoolSnapshot。

    zt 池是核心口径，取不到直接抛；辅助池失败只记 missing + 原因，不拦截。

    Raises:
        RuntimeError: 涨停池取不到（调用方转成错误响应）。
    """
    zt_payload, _src = _router.route("limit_up_board", board_type="zt", date=date, timeout=30)
    if not isinstance(zt_payload, dict):
        raise RuntimeError(f"涨停池返回结构异常（type={type(zt_payload).__name__}）")
    rows = zt_payload.get("data") or []
    if not rows:
        raise RuntimeError(f"涨停池为空（date={date or 'auto'}），无法计算读数")

    resolved_date = str(zt_payload.get("date") or date or "")
    snapshot = PoolSnapshot(
        date=resolved_date,
        zt=rows,
        fields={"zt": list(zt_payload.get("fields") or [])},
    )

    aux = [pool for pool in _AUX_POOLS if pool in need]
    if aux:
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {
                name: pool.submit(
                    _router.route, "limit_up_board",
                    board_type=name, date=resolved_date, timeout=30,
                )
                for name in aux
            }
            for name, future in futures.items():
                try:
                    payload, _ = future.result(timeout=35)
                    data_rows = (payload or {}).get("data") or []
                    if not data_rows:
                        snapshot.missing.append(name)
                        snapshot.reasons[name] = f"{name} 池为空（可能当日无该状态）"
                        continue
                    setattr(snapshot, name, data_rows)
                    snapshot.fields[name] = list((payload or {}).get("fields") or [])
                except Exception as exc:  # noqa: BLE001 - 辅助池只降级不拦截
                    logger.warning("shortline snapshot: %s 池失败(%s): %s", name, resolved_date, exc)
                    snapshot.missing.append(name)
                    snapshot.reasons[name] = str(exc)
    return snapshot


def _is_intraday(date_str: str) -> bool:
    """请求的是今天且未到 15:05（交易日近似：周一~周五）。"""
    today = datetime.now().strftime("%Y%m%d")
    if str(date_str) != today:
        return False
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    return now.time() < _CLOSE_TIME


def _effective_date(date: str) -> str:
    """缓存键用的日期：显式日期归一化，空则用今天。"""
    s = str(date or "").strip().replace("-", "")
    return s or datetime.now().strftime("%Y%m%d")


# ---------------------------------------------------------------- 统一信封


def _serve(endpoint_id: str, date: str, need: tuple[str, ...], compute_fn) -> dict:
    meta = get_endpoint(endpoint_id)
    key = cache_key(endpoint_id, date=_effective_date(date))

    cached = cache.get(key)
    if cached is not None:
        result = dict(cached)
        result["cache_hit"] = True
        return result

    snapshot = collect_snapshot(date=date, need=need)
    payload, text = compute_fn(snapshot)

    partial = bool(snapshot.missing) or _is_intraday(snapshot.date)
    if endpoint_id == "shortline.live":
        partial = True  # 此刻快照天然是盘中态

    reasons = dict(snapshot.reasons)
    endpoint_missing = payload.get("missing_reason") if isinstance(payload, dict) else None
    if endpoint_missing:
        reasons["endpoint"] = endpoint_missing

    decision = resolve_cache(meta.cache_policy, partial=partial)
    envelope = {
        "endpoint": endpoint_id,
        "date": snapshot.date,
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": _SOURCE,
        "compliance": _COMPLIANCE,
        "partial": partial,
        "missing_reason": reasons or None,
        "result": payload,
        "text": text,
        "computation": {
            "params": {"date": date or "auto"},
            "pools_used": ["zt", *(p for p in _AUX_POOLS if snapshot.has(p))],
            "missing_pools": list(snapshot.missing),
            "definitions": _DEFINITIONS.get(endpoint_id, {}),
            "computed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
        "cache": {
            "policy": meta.cache_policy,
            "ttl_seconds": decision.ttl_seconds,
            "reason": decision.reason,
        },
        "cache_hit": False,
    }
    if decision.enabled:
        cache.set(key, envelope, decision.ttl_seconds)
    return envelope


# ---------------------------------------------------------------- 八个端点


def get_emotion(date: str = "") -> dict:
    """情绪四项。"""
    return _serve("shortline.emotion", date, ("zt", "prev_zt"), compute.emotion)


def get_daily(date: str = "") -> dict:
    """每日读数。"""
    return _serve("shortline.daily", date, ("zt", "zb", "prev_zt"), compute.daily)


def get_settled(date: str = "") -> dict:
    """昨日涨停股当日表现明细。"""
    return _serve("shortline.settled", date, ("zt", "prev_zt"), compute.settled)


def get_live() -> dict:
    """盘中情绪（15 秒缓存）。"""
    return _serve("shortline.live", "", ("zt", "zb", "dt", "prev_zt"), compute.live)


def get_ladder(date: str = "") -> dict:
    """昨日梯队。"""
    return _serve("shortline.ladder", date, ("zt", "prev_zt"), compute.ladder)


def get_board_ladder(date: str = "") -> dict:
    """连板天梯 + 未晋级去向。"""
    return _serve("shortline.board_ladder", date, ("zt", "prev_zt"), compute.board_ladder)


def get_structure(date: str = "") -> dict:
    """涨停结构 + 四池上游字段清单。"""
    return _serve("shortline.structure", date, ("zt", *_AUX_POOLS), compute.structure)


_CYCLE_WINDOW_MAX = 60


def get_cycle(days: int = 5, date: str = "") -> dict:
    """情绪周期（窗口来自收盘定稿落库，缺天写 missing_dates 不当 0）。"""
    try:
        window_days = max(2, min(int(days or 5), _CYCLE_WINDOW_MAX))
    except (TypeError, ValueError):
        window_days = 5

    meta = get_endpoint("shortline.cycle")
    key = cache_key("shortline.cycle", date=_effective_date(date), days=window_days)
    cached = cache.get(key)
    if cached is not None:
        result = dict(cached)
        result["cache_hit"] = True
        return result

    snapshot = collect_snapshot(date=date, need=("zt", *_AUX_POOLS))
    history, missing_dates, history_note = _load_history(window_days)
    payload, text = compute.cycle(snapshot, days=window_days, history=history, missing_dates=missing_dates)

    partial = bool(snapshot.missing) or not history or _is_intraday(snapshot.date)
    reasons = dict(snapshot.reasons)
    if history_note:
        reasons["history"] = history_note
    if payload.get("missing_reason"):
        reasons["endpoint"] = payload["missing_reason"]

    decision = resolve_cache(meta.cache_policy, partial=partial)
    envelope = {
        "endpoint": "shortline.cycle",
        "date": snapshot.date,
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": f"shortline_store + {_SOURCE}",
        "compliance": _COMPLIANCE,
        "partial": partial,
        "missing_reason": reasons or None,
        "result": payload,
        "text": text,
        "computation": {
            "params": {"days": window_days, "date": date or "auto"},
            "pools_used": ["zt", *(p for p in _AUX_POOLS if snapshot.has(p))],
            "missing_pools": list(snapshot.missing),
            "definitions": _DEFINITIONS.get("shortline.cycle", {}),
            "computed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
        "cache": {
            "policy": meta.cache_policy,
            "ttl_seconds": decision.ttl_seconds,
            "reason": decision.reason,
        },
        "cache_hit": False,
    }
    if decision.enabled:
        cache.set(key, envelope, decision.ttl_seconds)
    return envelope


def _load_history(days: int) -> tuple[list[dict], list[str], str | None]:
    """从收盘定稿库读历史（H3 实现前为空，标 missing_reason）。"""
    try:
        from ..shortline import store  # 延迟导入：H2 阶段该模块可能尚未实现
        payload = store.history(days=days)
        return payload.get("records", []), payload.get("missing_dates", []), None
    except Exception as exc:  # noqa: BLE001
        return [], [], f"历史不可读：{exc}"
