"""涨停四池簇（QI-ARCH-09 拆分，2026-11-19）：limit_up_board 路由入口、打板情绪速算、四池行映射与交易日回溯——内部互相调用，自包含成簇。"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta

import pandas as pd

from ..utils.cache import cache, TTL_DAILY
from .akshare_common import _ak

logger = logging.getLogger("tradex.akshare")

_POOL_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "sealed_capital": ("封板资金", "封单资金", "封单额"),
    "first_seal_time": ("首次封板时间", "昨日封板时间"),
    "last_seal_time": ("最后封板时间",),
    "break_count": ("炸板次数", "开板次数"),
    "consecutive_days": ("连板数", "昨日连板数", "连续跌停"),
}


_POOL_AK_FUNCS: dict[str, str] = {
    "zt": "stock_zt_pool_em",
    "zb": "stock_zt_pool_zbgc_em",
    "dt": "stock_zt_pool_dtgc_em",
    "prev_zt": "stock_zt_pool_previous_em",
}


_BOARD_TYPE_ALIASES = {
    "zt": "zt", "涨停": "zt", "limit_up": "zt",
    "zb": "zb", "炸板": "zb", "break": "zb",
    "dt": "dt", "跌停": "dt", "limit_down": "dt",
    "prev_zt": "prev_zt", "prev": "prev_zt", "昨日涨停": "prev_zt",
}

# ============================================================
# 涨停板池 —— akshare stock_zt_pool_em（2026-09-26 新增，修复 limit_up_board 整类型失效）
# 原 em_push2_clist 主源在 push2 IP 风控中已删除（registry.py:235），整类型失效。
# akshare 包装东财涨停板池接口，由 akshare 维护字段映射，独立于 push2 域名族。
# 实测返回字段包含「连板数」（原 SPEC 假设无该字段，实测纠正）。
# ============================================================
def fetch_limit_up_board_em(*, date: str = "", **kwargs) -> list[dict]:
    """涨停板池 —— akshare stock_zt_pool_em 包装。

    Args:
        date: 交易日日期 YYYYMMDD 格式（必填，akshare 该接口必须传日期）

    Returns:
        list[dict] with keys:
            code/nickname/change_pct/latest_price/deal_amount/float_mv/
            total_mv/turnover_rate/sealed_capital/first_seal_time/last_seal_time/
            break_count/limit_up_stats/consecutive_days/industry

    字段映射说明（对齐 SPEC §S1）：
        - 连板数：实测 akshare 直接提供，无需历史推断（原 SPEC 假设已纠正）
        - 涨停统计：格式 "今涨停数/历史涨停数"，可用作题材热度参考
        - 所属行业：东财二级行业分类

    Raises:
        ValueError: date 格式错误
        RuntimeError: akshare 返回空（非交易日 / 数据未更新）
    """
    s = _normalize_board_date(date) if date else _latest_board_date()

    ak = _ak()
    df = ak.stock_zt_pool_em(date=s)
    if df is None or df.empty:
        raise RuntimeError(f"AKShare stock_zt_pool_em 返回空（date={s}，可能非交易日或数据未更新）")
    return _map_pool_rows(df, "zt")


def _normalize_board_date(date: str) -> str:
    """校验并归一日期为 YYYYMMDD（允许 YYYY-MM-DD）。"""
    s = str(date or "").strip().replace("-", "")
    if len(s) != 8 or not s.isdigit():
        raise ValueError(f"date 参数格式错误：{date!r}（应为 YYYYMMDD 8 位数字）")
    return s


def _latest_board_date(max_back_days: int = 15) -> str:
    """从今天往回找最近一个「涨停池有数据」的交易日。

    非交易日（周末/长假）直接传当天会拿到空表，调用方还得自己猜哪天是交易日。
    这里代劳：最多回溯 max_back_days 个自然日（覆盖春节/国庆长假）。
    """
    date_str, _rows = _latest_board_date_with_rows(max_back_days)
    return date_str


def _trade_dates_recent() -> list[str]:
    """全量交易日清单（YYYYMMDD 升序；TTL 到当日午夜的统一缓存条目）。

    批次C4 并入统一序列化边界（get_or_set）：缓存键含获取日期 → 跨天（含
    跨年）即自然换键重拉（保证清单始终覆盖「今天」所在年份，替代批次A的
    (获取日戳, days) 手工日戳结构）；TTL 设到当日午夜，进程内最多一日一拉。
    """
    today = datetime.now().strftime("%Y%m%d")

    def _fetch() -> list[str]:
        ak = _ak()
        df = ak.tool_trade_date_hist_sina()
        if df is None or df.empty or "trade_date" not in df.columns:
            raise RuntimeError("sina 交易日清单返回空或结构变化")
        days = pd.to_datetime(df["trade_date"], errors="coerce").dropna()
        return sorted(days.dt.strftime("%Y%m%d").tolist())

    midnight = datetime.strptime(today, "%Y%m%d") + timedelta(days=1)
    ttl = max(60, int((midnight - datetime.now()).total_seconds()))
    return cache.get_or_set(f"trade_dates_recent:{today}", _fetch, ttl=ttl)


def _latest_board_date_with_rows(
    max_back_days: int = 15,
) -> tuple[str, list[dict]]:
    """同 _latest_board_date，但顺带返回涨停池已取到的行，省一次重复请求。

    2026-11-08 修复：回溯改为只试交易日——东财对非交易日 date 不再返回
    空表而是返回最近交易日数据（实测周日 20261108 返回 11-06 池但标签
    写 20261108），旧逻辑 back=0 命中自然日造成日期语义污染，连累
    collect_snapshot 的 prev_zt 封板时间注入对错位。
    """
    today = datetime.now().strftime("%Y%m%d")
    trade_days = [d for d in _trade_dates_recent() if d <= today]
    ak = _ak()  # 日历缓存命中时无需拉 akshare 模块
    for candidate in trade_days[-max_back_days:][::-1]:
        try:
            df = ak.stock_zt_pool_em(date=candidate)
        except Exception:  # noqa: BLE001 - 单日探测失败继续回溯
            continue
        if df is not None and not df.empty:
            return candidate, _map_pool_rows(df, "zt")
    raise RuntimeError(
        f"近 {max_back_days} 个交易日内未取到涨停池数据，无法推断最近交易日；"
        "请显式传 date（YYYYMMDD）"
    )


def _pick_field(row, columns, aliases: tuple[str, ...], default=0):
    """按别名顺序从行里取第一个存在的字段。"""
    for name in aliases:
        if name in columns:
            value = row.get(name)
            if value is not None and not (isinstance(value, float) and pd.isna(value)):
                return value
    return default


def _map_pool_rows(df: pd.DataFrame, board_type: str) -> list[dict]:
    """把某个池的原始表映射为统一字段结构。"""
    if df is None or df.empty:
        return []
    columns = set(df.columns)
    source = f"AKShare_{_POOL_AK_FUNCS.get(board_type, 'stock_zt_pool_em')}"
    rows: list[dict] = []
    for _, row in df.iterrows():
        rows.append({
            "code": str(row.get("代码", "")).zfill(6),
            "name": str(row.get("名称", "")),
            "change_pct": float(row.get("涨跌幅", 0) or 0),
            "latest_price": float(row.get("最新价", 0) or 0),
            "deal_amount": float(row.get("成交额", 0) or 0),
            "float_mv": float(row.get("流通市值", 0) or 0),
            "total_mv": float(row.get("总市值", 0) or 0),
            "turnover_rate": float(row.get("换手率", 0) or 0),
            "sealed_capital": float(
                _pick_field(row, columns, _POOL_FIELD_ALIASES["sealed_capital"], 0) or 0
            ),
            "first_seal_time": str(
                _pick_field(row, columns, _POOL_FIELD_ALIASES["first_seal_time"], "")
            ),
            "last_seal_time": str(
                _pick_field(row, columns, _POOL_FIELD_ALIASES["last_seal_time"], "")
            ),
            "break_count": int(
                _pick_field(row, columns, _POOL_FIELD_ALIASES["break_count"], 0) or 0
            ),
            "limit_up_stats": str(row.get("涨停统计", "")),
            "consecutive_days": int(
                _pick_field(row, columns, _POOL_FIELD_ALIASES["consecutive_days"], 0) or 0
            ),
            "industry": str(row.get("所属行业", "")),
            "source": source,
        })
    return rows


def _fetch_pool_rows(board_type: str, date: str) -> list[dict]:
    """取单个池（日期已归一）。空表返回空列表，不抛。"""
    rows, _fields = _fetch_pool_with_fields(board_type, date)
    return rows


def _fetch_pool_with_fields(board_type: str, date: str) -> tuple[list[dict], list[str]]:
    """取单个池，并带回上游原始列名（工单 H2/H7 的字段清单 / 漂移检测原料）。"""
    func_name = _POOL_AK_FUNCS.get(board_type)
    if func_name is None:
        raise ValueError(
            f"未知 board_type：{board_type!r}（可选 zt/zb/dt/prev_zt/sentiment）"
        )
    ak = _ak()
    df = getattr(ak, func_name)(date=date)
    fields = list(df.columns) if df is not None and not df.empty else []
    return _map_pool_rows(df, board_type), fields


def fetch_limit_up_board(
    *,
    board_type: str = "zt",
    date: str = "",
    **kwargs,
) -> dict:
    """涨停四池（统一信封）—— limit_up_board 路由入口。

    board_type: zt(涨停) / zb(炸板) / dt(跌停) / prev_zt(昨日涨停) / sentiment(打板情绪)

    Returns:
        {"board_type","date","count","data":[...]}；sentiment 见 fetch_board_sentiment
    """
    bt = _BOARD_TYPE_ALIASES.get(str(board_type or "zt").strip().lower())
    if str(board_type or "").strip().lower() == "sentiment":
        return fetch_board_sentiment(date=date)

    if bt is None:
        raise ValueError(
            f"未知 board_type：{board_type!r}（可选 zt/zb/dt/prev_zt/sentiment）"
        )

    s = _normalize_board_date(date) if date else _latest_board_date()
    rows, fields = _fetch_pool_with_fields(bt, s)
    if not rows:
        raise RuntimeError(f"{bt} 池返回空（date={s}，可能非交易日或数据未更新）")
    return {
        "board_type": bt,
        "date": s,
        "count": len(rows),
        "data": rows,
        # 上游原始列名：structure 端点展示 + H7 字段漂移检测都用这一份
        "fields": fields,
    }


def fetch_board_sentiment(*, date: str = "", **kwargs) -> dict:
    """打板情绪速算（由涨停四池现算，不依赖已失效的 push2 clist）。

    指标口径（写在代码里，避免以后又变成口头传说）：
      - 炸板率 = 炸板数 / (涨停数 + 炸板数)，反映封板强度
      - 连板梯队 = 涨停池中连板数 ≥2 的分档计数
      - 晋级率 = 今日涨停 ∩ 昨日涨停池 / 昨日涨停池数量
      - 平均溢价 = 昨日涨停股「今日」涨跌幅均值（打板次日收益的近似）
      - 热门题材 = 涨停池按所属行业计数 Top5

    涨停池取不到直接抛错（核心口径不可缺）；其余三池缺失时降级为空并标注
    missing，绝不拿 0 冒充有效值。
    """
    s = _normalize_board_date(date) if date else ""

    from collections import Counter
    from concurrent.futures import ThreadPoolExecutor

    if s:
        zt_rows = _fetch_pool_rows("zt", s)
    else:
        s, zt_rows = _latest_board_date_with_rows()

    if not zt_rows:
        raise RuntimeError(f"涨停池为空（date={s}），无法计算打板情绪")

    missing: list[str] = []
    aux: dict[str, list[dict]] = {}
    # 三个辅助池并发取：串行 4 池会把路由的单次尝试超时（12s）顶穿
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {key: pool.submit(_fetch_pool_rows, key, s) for key in ("zb", "dt", "prev_zt")}
        for key, future in futures.items():
            try:
                aux[key] = future.result(timeout=10)
            except Exception as exc:  # noqa: BLE001 - 辅助池失败只降级不拦截
                logger.warning("board_sentiment: %s 池获取失败(%s): %s", key, s, exc)
                aux[key] = []
                missing.append(key)

    zb_rows, dt_rows, prev_rows = aux["zb"], aux["dt"], aux["prev_zt"]

    # 辅助池缺失时计数必须是 None —— 用 0 会算出「炸板率 0%」这种伪造的强封板信号
    limit_up_count = len(zt_rows)
    broken_count = None if "zb" in missing else len(zb_rows)
    limit_down_count = None if "dt" in missing else len(dt_rows)
    seal_base = (
        limit_up_count + broken_count if broken_count is not None else None
    )
    broken_rate = (
        round(broken_count / seal_base * 100, 2) if seal_base else None
    )

    ladder_counter = Counter(
        row["consecutive_days"] for row in zt_rows if row["consecutive_days"] >= 2
    )
    ladder = {
        f"{days}连板": ladder_counter[days]
        for days in sorted(ladder_counter, reverse=True)
    }
    max_consecutive = max((row["consecutive_days"] for row in zt_rows), default=0)

    prev_codes = {row["code"] for row in prev_rows}
    today_codes = {row["code"] for row in zt_rows}
    promoted = None if "prev_zt" in missing else len(prev_codes & today_codes)
    promotion_rate = (
        round(promoted / len(prev_codes) * 100, 2)
        if promoted is not None and prev_codes
        else None
    )

    premium_values = [row["change_pct"] for row in prev_rows]
    avg_premium = (
        round(sum(premium_values) / len(premium_values), 2) if premium_values else None
    )

    hot_industries = [
        {"题材": name, "涨停数": count}
        for name, count in Counter(
            row["industry"] for row in zt_rows if row["industry"]
        ).most_common(5)
    ]

    return {
        "date": s,
        "涨停数": limit_up_count,
        "炸板数": broken_count,
        "跌停数": limit_down_count,
        "炸板率(%)": broken_rate,
        "最高连板": max_consecutive,
        "连板梯队": ladder,
        "昨日涨停数": len(prev_rows),
        "晋级数": promoted,
        "晋级率(%)": promotion_rate,
        "平均溢价(%)": avg_premium,
        "热门题材": hot_industries,
        "missing_pools": missing,
        "source": "akshare_em(zt/zb/dt/prev_zt)",
    }
