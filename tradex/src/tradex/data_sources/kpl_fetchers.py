"""
开盘啦（KPL / longhuvip）数据源 fetch_fn 包装器。

对应交接文档 07（T1' 逆向摸排）+ 09（T3 适配器施工）。接口参数组合来自
GitHub 开源抓包文档（LowellLee/kpl 的 KPL接口.md 等），并于 2026-11-07
本机逐接口实测验证（errcode=0）。

实测结论（2026-11-07，全接口免鉴权直连）：
  - 域名按用途分四个：apphq / apphwhq（涨停实时）/ apphwshhq（情绪·板块
    实时）/ apphis（历史）。07 号交接曾用 apphq 打涨停实时导致参数错。
  - UA 必须是安卓 Dalvik（app 自带 UA），07 号交接用的 UA "ad" 会得到
    errcode=1020「参数出错」。
  - 涨停接口 a=DailyLimitPerformance 的 PidType 只接受 1~5（1 首板 …
    5 更高连板），传 0 报 1020——"全量" 由本层循环 1~5 拼接。
  - 涨停行是无字段名的位置数组（实测 23 位；文档注释 21 位），字段映射
    见 KPL_LIMIT_UP_FIELDS，尾部未知位不消费。
  - DeviceID/Token 用社区文档样例值即可（多数接口不校验其真实性）。
  - 竞价历史数据保留期短（实测 2026-11-06 在 11-07 已查不到，info=[]）。

设计原则：
  - 失败抛异常由 SmartRouter 记账降级（2026-09-28 审计纪律）
  - 直连铁律：Session trust_env=False，禁读 HTTP(S)_PROXY
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import requests

logger = logging.getLogger("tradex.kpl")

# 域名（2026-11-07 实测；apphwhq 的 w 是涨停实时专用，apphwshhq 是沪端）
KPL_HQ = "https://apphq.longhuvip.com/w1/api/index.php"       # 实时通用
KPL_HWHQ = "https://apphwhq.longhuvip.com/w1/api/index.php"   # 涨停实时
KPL_SHHQ = "https://apphwshhq.longhuvip.com/w1/api/index.php"  # 情绪/板块实时
KPL_HIS = "https://apphis.longhuvip.com/w1/api/index.php"     # 历史

KPL_HEADERS = {
    "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 14; V2178A Build/UP1A.231005.007)",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}
KPL_DEVICE_ID = "d66474b3-fd78-3a95-a56d-76e29e765ea3"  # 社区文档样例设备号
KPL_TIMEOUT = 30

# 涨停行字段映射（位置索引 → 语义名）。来源： LowellLee/kpl 文档示例 32/33
# 的逐位注释 + 2026-11-07 实测（PidType=5 为 23 位）。0 起。
KPL_LIMIT_UP_FIELDS: dict[int, str] = {
    0: "code",
    1: "name",
    4: "limit_up_time",        # 涨停时间 epoch 秒
    5: "reason",               # 涨停原因（KPL 题材口径）
    6: "seal_amount",          # 当前封单额（元）
    7: "max_seal_amount",      # 最大封单额（元）
    8: "main_net_inflow",      # 主力净额（元）
    9: "main_buy",             # 主力买入（元）
    10: "main_sell",           # 主力卖出（元）
    11: "turnover",            # 成交额（元）
    12: "board_tags",          # 板块/属性串（顿号分隔）
    13: "actual_circulation",  # 实际流通（元）
    14: "actual_turnover_rate",  # 实际换手（%）
    17: "amplitude",           # 振幅（%）
    19: "kpl_board_code",      # KPL 概念板块码（801xxx）
    20: "board_limit_up_count",  # 该板块涨停家数
}

# 精选板块行字段映射（19 位；来源：文档示例 21 逐位注释）
KPL_BOARD_FIELDS: dict[int, str] = {
    0: "kpl_board_code",
    1: "name",
    2: "strength",          # 强度（KPL 板块强度值）
    3: "pct_change",        # 涨幅（%）
    4: "speed",             # 涨速
    5: "turnover",          # 成交额（元）
    6: "main_net_inflow",   # 主力净额（元）
    7: "main_buy",
    8: "main_sell",
    9: "vol_ratio",         # 量比
    10: "circulation_value",  # 流通值
    12: "big_order_net_3m",   # 300万大单净额
    13: "market_cap",         # 总市值
    14: "institution_change",  # 机构增仓
}

# 竞价行字段映射（17 位；来源：文档示例 19 逐位注释）
KPL_BIDDING_FIELDS: dict[int, str] = {
    0: "code",
    1: "name",
    2: "pre_close",
    3: "pct_change",          # 实时涨幅（%）
    4: "bid_buy_amount",      # 涨停委买额（元）
    5: "bid_pct_change",      # 竞价涨幅（%）
    6: "bid_net_amount",      # 竞价净额（元）
    7: "bid_turnover_rate",   # 竞价换手（%）
    8: "bid_turnover",        # 竞价成交额（元）
    9: "bid_buy_20m",         # 20分后委买（元）
    11: "board_tags",
    12: "actual_circulation",
    16: "ladder_tag",         # 连板标签，如 "6天4板"
}

_session: requests.Session | None = None


def _kpl_session() -> requests.Session:
    """KPL 会话（懒初始化）。铁律：国内接口直连，禁读代理环境变量。"""
    global _session
    if _session is None:
        _session = requests.Session()
        _session.trust_env = False
        _session.headers.update(KPL_HEADERS)
    return _session


def _kpl_get(base: str, params: dict[str, Any]) -> dict[str, Any]:
    """GET 一帧 KPL 应答并校验 errcode。

    Raises:
        RuntimeError: errcode 非 "0"（含 1020 参数出错）或应答结构异常。
        requests.HTTPError / Timeout: HTTP 层错误。
    """
    try:
        resp = _kpl_session().get(base, params=params, timeout=KPL_TIMEOUT)
        resp.raise_for_status()
    except Exception as e:
        logger.warning("kpl request failed (a=%s): %s", params.get("a"), e)
        raise
    payload = resp.json()
    errcode = str(payload.get("errcode", ""))
    if errcode != "0":
        raise RuntimeError(
            f"KPL {params.get('a')} 返回 errcode={errcode} "
            f"errmsg={payload.get('errmsg')!r}"
        )
    return payload


def _rows_to_df(rows: list, fields: dict[int, str]) -> pd.DataFrame:
    """位置数组行 → 命名 DataFrame（映射外的位置忽略）。"""
    if not rows:
        return pd.DataFrame()
    records = []
    for row in rows:
        if not isinstance(row, list):
            continue
        records.append({name: row[i] for i, name in fields.items() if i < len(row)})
    return pd.DataFrame(records)


def _common_params(apiv: str, version: str, **extra: Any) -> dict[str, Any]:
    """KPL 公共参数（PhoneOSNew/DeviceID/VerSion/apiv）。"""
    return {
        "PhoneOSNew": "1",
        "DeviceID": KPL_DEVICE_ID,
        "VerSion": version,
        "apiv": apiv,
        **extra,
    }


# ============================================================
# 涨停复盘 — kpl_limit_up（实时 + 历史，PidType 1~5）
# ============================================================

def fetch_kpl_limit_up(
    date: str = "",
    pid_type: int = 0,
    **kwargs,
) -> pd.DataFrame:
    """KPL 涨停复盘（代码/涨停时间/原因/封单/主力/板块码/连板板位）。

    Args:
        date: 交易日 ``YYYY-MM-DD``（或 ``YYYYMMDD``，自动转格式）。
            空 = 实时（最近交易日/盘中实时）。
        pid_type: 板位 1~5（1 首板…5 更高连板）；0 = 全部（循环 1~5 拼接）。

    Returns:
        DataFrame：列见 KPL_LIMIT_UP_FIELDS，另加 ladder 列（板位 1~5）。
    """
    day = _normalize_day(date)

    def one(pid: int) -> pd.DataFrame:
        if day:
            # 历史接口（文档原文组合，VerSion/apiv 用 5.7.0.12/w31）
            payload = _kpl_get(
                KPL_HIS,
                _common_params("w31", "5.7.0.12", Order="0", st="1000",
                               a="DailyLimitPerformance", c="HisHomeDingPan",
                               Index="0", PidType=str(pid), Type="4", Day=day),
            )
        else:
            # 实时接口（apphwhq + HomeDingPan，VerSion 5.18.0.2/w39）
            payload = _kpl_get(
                KPL_HWHQ,
                _common_params("w39", "5.18.0.2", Order="0", st="2000",
                               a="DailyLimitPerformance", c="HomeDingPan",
                               Index="0", PidType=str(pid), Type="4"),
            )
        info = payload.get("info") or []
        # info 结构：[ [ 行, 行, ... ] ]（单元素包裹），部分应答直接是行数组
        rows = info[0] if info and isinstance(info[0], list) and info[0] and isinstance(info[0][0], list) else info
        df = _rows_to_df(rows, KPL_LIMIT_UP_FIELDS)
        if not df.empty:
            df.insert(0, "ladder", pid)  # 板位（1 首板 … 5 更高）
        return df

    pids = range(1, 6) if int(pid_type) == 0 else [int(pid_type)]
    frames = [one(p) for p in pids]
    frames = [f for f in frames if not f.empty]
    if not frames:
        logger.debug("fetch_kpl_limit_up(date=%s): empty", date or "realtime")
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


# ============================================================
# 市场情绪 — kpl_sentiment（涨停/跌停/炸板率 + 情绪值/连板高度）
# ============================================================

def fetch_kpl_sentiment(**kwargs) -> dict[str, Any]:
    """KPL 市场情绪读数（实时）。

    Returns:
        dict：limit_up / limit_down / zhaban / zhaban_rate（RiseFallAnalysis）
        + strength / ladder_height / ztjs（ChangeStatistics 情绪指标）+ day。
    """
    rise = _kpl_get(
        KPL_SHHQ,
        _common_params("w43", "5.22.0.2", a="RiseFallAnalysis", c="HomeDingPan"),
    )
    out: dict[str, Any] = {}
    info = (rise.get("info") or [None])[0]
    if isinstance(info, list) and len(info) >= 7:
        out.update({
            "limit_up": info[0],        # 涨停家数
            "limit_down": info[1],      # 跌停家数
            "natural_limit_up": info[2],  # 自然涨停
            "once_limit_down": info[3],   # 曾跌停
            "zhaban_rate": info[4],       # 炸板率（%）
            "zhaban": info[5],            # 炸板家数
            "day": info[6],               # 应答日期
        })
    try:
        stat = _kpl_get(KPL_HQ, {"a": "ChangeStatistics", "st": "10", "c": "HomeDingPan"})
        item = (stat.get("info") or [{}])[0]
        if isinstance(item, dict) and item:
            extras = {
                "strength": item.get("strong"),       # KPL 情绪指标（0-100）
                "ladder_height": item.get("lbgd"),    # 连板高度
                "ztjs": item.get("ztjs"),             # 涨停家数
                "day": item.get("Day") or out.get("day"),
            }
            # 只并入非 None 键：空应答不能让主读数结构被 None 污染
            out.update({k: v for k, v in extras.items() if v is not None})
    except Exception as exc:  # noqa: BLE001 - 情绪指标失败不拖垮主读数
        logger.debug("fetch_kpl_sentiment: ChangeStatistics failed: %s", exc)
        out["strength_error"] = str(exc)
    if not out:
        raise RuntimeError("KPL 情绪应答结构异常（info 为空）")
    return out


# ============================================================
# 精选板块 — kpl_boards（801xxx 板块强度/主力净额）
# ============================================================

def fetch_kpl_boards(date: str = "", **kwargs) -> pd.DataFrame:
    """KPL 精选板块列表（801xxx 板块码/强度/涨幅/主力净额）。

    Args:
        date: 交易日 ``YYYY-MM-DD``；空 = 实时。

    Returns:
        DataFrame：列见 KPL_BOARD_FIELDS。
    """
    day = _normalize_day(date)
    if day:
        payload = _kpl_get(
            KPL_HIS,
            _common_params("w41", "5.20.0.2", Order="1", st="60",
                           a="RealRankingInfo", c="ZhiShuRanking", PhoneOSNew="1",
                           RStart="0925", REnd="1500", Index="0",
                           Date=day, Type="5", ZSType="7"),
        )
    else:
        payload = _kpl_get(
            KPL_SHHQ,
            _common_params("w44", "5.23.0.4", Order="1", st="60",
                           a="RealRankingInfo", c="ZhiShuRanking",
                           RStart="0925", REnd="1500", Index="0",
                           Type="1", ZSType="7"),
        )
    rows = payload.get("list") or []
    return _rows_to_df(rows, KPL_BOARD_FIELDS)


# ============================================================
# 竞价涨停委买额 — kpl_bidding（MorningBiddingList）
# ============================================================

def fetch_kpl_bidding(date: str = "", **kwargs) -> pd.DataFrame:
    """KPL 竞价涨停委买额榜（9:15-9:25 竞价口径）。

    ⚠️ 历史数据保留期短（实测 2026-11-06 在次日已查不到），交易日盘中调用。

    Args:
        date: 交易日 ``YYYY-MM-DD``；空 = 实时。

    Returns:
        DataFrame：列见 KPL_BIDDING_FIELDS。
    """
    day = _normalize_day(date)
    if day:
        payload = _kpl_get(
            KPL_HIS,
            _common_params("w41", "5.20.0.2", Order="1", st="60",
                           a="MorningBiddingList", c="HisHomeDingPan",
                           Index="0", PidType="0", Date=day, Type="4"),
        )
    else:
        payload = _kpl_get(
            KPL_HWHQ,
            _common_params("w41", "5.20.0.2", Order="1", st="60",
                           a="MorningBiddingList", c="HomeDingPan",
                           Index="0", PidType="0", Type="4"),
        )
    rows = payload.get("info") or []
    return _rows_to_df(rows, KPL_BIDDING_FIELDS)


def _normalize_day(date: str) -> str:
    """``YYYYMMDD``/``YYYY-MM-DD``/空 → ``YYYY-MM-DD``（空返回空=实时）。"""
    s = str(date or "").strip().replace("-", "")
    if not s:
        return ""
    if len(s) != 8 or not s.isdigit():
        raise ValueError(f"非法日期参数：{date!r}（期望 YYYYMMDD 或 YYYY-MM-DD）")
    return f"{s[:4]}-{s[4:6]}-{s[6:]}"
