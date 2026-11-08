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
from ..utils.cache import TTL_DAILY, cache

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


def ensure_prev_zt_seal_times(snapshot: PoolSnapshot) -> None:
    """给 prev_zt 池注入昨日首次/最后封板时间（2026-11-08 票B）。

    上游 stock_zt_pool_previous_em 无封板时间列；用前一交易日的 zt 池
    （stock_zt_pool_em，含首封/末封）按 code 对齐注入。失败只记原因，
    不进 missing（不影响 close_fetch 的 partial 判定）。

    调用点收敛在 store.close_fetch（落库定稿）——封板时间唯一消费方是
    TradeX T8 样本页（读落库 records）；不挂在 collect_snapshot，
    避免快照公共路径（live/daily/ladder）多发一次 zt 取数。
    """
    if not snapshot.prev_zt:
        return
    try:
        prev_day = _prev_trading_day(snapshot.date)
        payload, _src = _router.route(
            "limit_up_board", board_type="zt", date=prev_day, timeout=30
        )
        seal_map = {
            str(r.get("code") or ""): r
            for r in ((payload or {}).get("data") or [])
        }
        injected = 0
        for row in snapshot.prev_zt:
            info = seal_map.get(str(row.get("code") or ""))
            if info:
                row["first_seal_time"] = str(info.get("first_seal_time") or "") or str(row.get("first_seal_time") or "")
                row["last_seal_time"] = str(info.get("last_seal_time") or "")
                injected += 1
        if injected:
            logger.info("prev_zt 封板时间注入 %d/%d（%s 池）", injected, len(snapshot.prev_zt), prev_day)
        else:
            snapshot.reasons["prev_zt_seal_times"] = f"{prev_day} 涨停池与昨日名单无交集，封板时间缺数"
    except Exception as exc:  # noqa: BLE001 - 封板时间是增强字段，缺数不拦截
        logger.warning("prev_zt 封板时间注入失败(%s): %s", snapshot.date, exc)
        snapshot.reasons["prev_zt_seal_times"] = f"封板时间注入失败：{exc}"


def _prev_trading_day(date_str: str) -> str:
    """前一交易日（YYYYMMDD）。sina 全表日历带 TTL 缓存，跨月安全。"""
    import pandas as pd
    from ..data_sources.akshare_fetchers import _ak

    cache_key = f"trade_dates_all:{pd.Timestamp.now().strftime('%Y%m')}"
    cached = cache.get(cache_key)
    if cached is None:
        df = _ak().tool_trade_date_hist_sina()
        if df is None or df.empty or "trade_date" not in df.columns:
            raise ValueError("sina 交易日清单返回空或结构变化")
        cached = pd.to_datetime(df["trade_date"], errors="coerce").dropna().dt.strftime("%Y%m%d").tolist()
        cache.set(cache_key, cached, TTL_DAILY)
    days = sorted(cached)
    target = str(date_str).replace("-", "")
    prior = [d for d in days if d < target]
    if not prior:
        raise ValueError(f"交易日历无 {target} 之前的记录")
    return prior[-1]


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
    history, missing_dates, history_note = _load_history(window_days, end_date=snapshot.date)
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


def _load_history(days: int, end_date: str = "") -> tuple[list[dict], list[str], str | None]:
    """从收盘定稿库读历史。

    只取 ``end_date`` 之前的记录：当日读数由实时快照给出，历史里同日记录会重复计数。
    """
    try:
        from ..shortline import store
        payload = store.history(days=max(1, days) + 1, date=end_date)
        records = [
            record for record in payload.get("records", [])
            if not end_date or str(record.get("date")) < str(end_date)
        ][-max(1, days):]
        return records, payload.get("missing_dates", []), None
    except Exception as exc:  # noqa: BLE001
        return [], [], f"历史不可读：{exc}"


# ---------------------------------------------------------------- H6：题材归因


def fetch_reasons(date: str = "") -> tuple[dict[str, str], str, list[str]]:
    """取涨停原因映射：问财优先、同花顺补缺（合并制）。

    2026-11-07 升级（配合 wencai WAP 通道锁页限制）：问财 WAP 单会话最多
    返回 10 行，涨停家数多时归因不全——改为问财结果优先、同花顺结果补缺，
    同 code 冲突时问财覆盖同花顺，来源按实际组合标注。

    Returns:
        (reasons_by_code, source, problems)
    """
    problems: list[str] = []
    wencai_reasons: dict[str, str] = {}
    try:
        wencai_reasons = _reasons_from_wencai(date)
        if not wencai_reasons:
            problems.append("问财返回空（无 key 或未覆盖）")
    except Exception as exc:  # noqa: BLE001 - 缺 key/依赖缺失都走兜底
        problems.append(f"问财不可用：{exc}")

    ths_reasons: dict[str, str] = {}
    try:
        ths_reasons = _reasons_from_ths(date)
        if not ths_reasons:
            problems.append("同花顺归因为空")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"同花顺归因不可用：{exc}")

    merged = {**ths_reasons, **wencai_reasons}  # 问财优先：同 code 覆盖同花顺
    if merged:
        if wencai_reasons and ths_reasons:
            source = "问财+同花顺补缺"
        elif wencai_reasons:
            source = "问财"
        else:
            source = "同花顺涨停归因"
        return merged, source, problems
    return {}, "无（问财与同花顺均失败）", problems


def _reasons_from_wencai(date: str) -> dict[str, str]:
    """问财：查询当日涨停原因。返回空表 / 缺列都当失败（触发同花顺兜底）。"""
    query = f"{date or datetime.now().strftime('%Y%m%d')}涨停股票 涨停原因"
    df, _src = _router.route("wencai_query", query=query, timeout=40)
    if df is None or getattr(df, "empty", True):
        return {}
    columns = [str(c) for c in df.columns]
    code_col = next((c for c in columns if "代码" in c), None)
    reason_col = next((c for c in columns if "涨停原因" in c or "原因" in c), None)
    if not code_col or not reason_col:
        raise RuntimeError(f"问财返回缺少代码/原因列（{columns[:6]}）")
    reasons: dict[str, str] = {}
    for _, row in df.iterrows():
        code = str(row.get(code_col) or "")[-6:]
        reason = str(row.get(reason_col) or "").strip()
        if code and reason:
            reasons[code] = reason
    return reasons


def _reasons_from_ths(date: str) -> dict[str, str]:
    """同花顺：涨停归因（hot_money 全市场）。"""
    payload, _src = _router.route("hot_money", code="", date=_date_dash(date), timeout=25)
    if not isinstance(payload, dict):
        raise RuntimeError("同花顺归因返回结构异常")
    if payload.get("error"):
        raise RuntimeError(str(payload["error"]))
    reasons = {
        str(row.get("code") or "")[-6:]: str(row.get("reason") or "").strip()
        for row in (payload.get("stocks") or [])
        if row.get("code") and row.get("reason")
    }
    return reasons


def _date_dash(date: str) -> str:
    s = str(date or "").replace("-", "")
    if not s:
        return datetime.now().strftime("%Y-%m-%d")
    return f"{s[:4]}-{s[4:6]}-{s[6:]}"


_THEME_DEFINITIONS = {
    "题材事件树": "涨停股按涨停原因整体归组；关键词按原因拆分（、，+等分隔）",
    "首板": "连板数=1 的涨停股，按首次封板时间升序",
    "反包": "涨停统计（今涨停数/近N日涨停数）中 N>1 的首板票",
    "封板质量": "平均封单额 / 封板时间中位 / 平均炸板次数 / 封板率",
    "亏钱效应": "昨日涨停股今日下跌占比 + 中位涨跌幅 + 跌停数",
    "题材轮动": "近 N 日各题材只数与名次；连续天数与回流；缺天画「—」",
}


def _themes_envelope(endpoint_id: str, date: str) -> dict:
    meta = get_endpoint(endpoint_id)
    key = cache_key(endpoint_id, date=_effective_date(date))
    cached = cache.get(key)
    if cached is not None:
        result = dict(cached)
        result["cache_hit"] = True
        return result

    snapshot = collect_snapshot(date=date, need=("zt",))
    reasons, source, problems = fetch_reasons(snapshot.date)
    payload, text = compute.themes(snapshot, reasons, source)
    partial = _is_intraday(snapshot.date) or not reasons

    decision = resolve_cache(meta.cache_policy, partial=partial)
    reasons_map: dict = dict(snapshot.reasons)
    if problems:
        reasons_map["theme_source"] = problems
    envelope = {
        "endpoint": endpoint_id,
        "date": snapshot.date,
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": source,
        "compliance": _COMPLIANCE,
        "partial": partial,
        "missing_reason": reasons_map or None,
        "result": payload,
        "text": text,
        "computation": {
            "params": {"date": date or "auto"},
            "pools_used": ["zt"],
            "missing_pools": list(snapshot.missing),
            "definitions": {"题材事件树": _THEME_DEFINITIONS["题材事件树"]},
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


def get_themes(date: str = "") -> dict:
    """题材事件树（问财优先 / 同花顺兜底）。"""
    return _themes_envelope("shortline.themes", date)


def get_firstboard(date: str = "") -> dict:
    """首板名单（按首封时间排序，反包单标）。"""
    return _serve("shortline.firstboard", date, ("zt",), compute.firstboard)


def get_facts(date: str = "") -> dict:
    """盘面事实（封板质量 / 亏钱效应 / 反馈矩阵）。"""
    return _serve("shortline.facts", date, ("zt", "zb", "dt", "prev_zt"), compute.facts)


_ROTATION_SCAN_DAYS = 60


def get_theme_rotation(days: int = 5, date: str = "") -> dict:
    """题材轮动（近 N 日只数/名次/连续/回流，缺天画「—」）。"""
    try:
        window = max(2, min(int(days or 5), _ROTATION_SCAN_DAYS))
    except (TypeError, ValueError):
        window = 5
    meta = get_endpoint("shortline.theme_rotation")
    key = cache_key("shortline.theme_rotation", date=_effective_date(date), days=window)
    cached = cache.get(key)
    if cached is not None:
        result = dict(cached)
        result["cache_hit"] = True
        return result

    snapshot = collect_snapshot(date=date, need=("zt",))
    reasons, source, problems = fetch_reasons(snapshot.date)
    payload, text = compute.themes(snapshot, reasons, source)
    today_counts = {item["theme"]: item["count"] for item in payload.get("keywords", [])}

    history, missing_dates, history_note = _load_history(window + 1, end_date=snapshot.date)
    days_records: list[dict] = []
    for record in history:
        if str(record.get("date")) == snapshot.date:
            continue  # 今日一律用实时快照重算，避免历史里的同日记录重复成两天
        counts = record.get("theme_counts")
        days_records.append({
            "date": record.get("date"),
            "available": counts is not None,
            "theme_counts": counts,
        })
    days_records.append({
        "date": snapshot.date,
        "available": bool(today_counts),
        "theme_counts": today_counts,
    })
    days_records = days_records[-window:]

    rotation, text = compute.theme_rotation(days_records, missing_dates=missing_dates)

    partial = _is_intraday(snapshot.date) or not today_counts or not history
    reasons_map: dict = dict(snapshot.reasons)
    if problems:
        reasons_map["theme_source"] = problems
    if history_note:
        reasons_map["history"] = history_note
    if partial:
        reasons_map.setdefault("endpoint", []).append(
            "题材轮动窗口不完整（历史缺天或今日归因缺失），缺天显示「—」"
        )

    decision = resolve_cache(meta.cache_policy, partial=partial)
    envelope = {
        "endpoint": "shortline.theme_rotation",
        "date": snapshot.date,
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": f"{source} + shortline_store",
        "compliance": _COMPLIANCE,
        "partial": partial,
        "missing_reason": reasons_map or None,
        "result": rotation,
        "text": text,
        "computation": {
            "params": {"days": window, "date": date or "auto"},
            "pools_used": ["zt"],
            "missing_pools": list(snapshot.missing),
            "definitions": {"题材轮动": _THEME_DEFINITIONS["题材轮动"]},
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
