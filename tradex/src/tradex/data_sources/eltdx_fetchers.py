"""
eltdx 数据源 fetch_fn 包装器。

所有 eltdx (通达信行情协议) 的数据获取函数在此注册为 SmartRouter fetch_fn。
仅本文件（及 data_sources 包内其他 fetcher 文件）允许 `from eltdx import ...`。

复用原 eltdx_data.py 的 _get_client() 单例模式（TdxClient.from_hosts + connect）。
"""

from __future__ import annotations

import logging
import threading
import atexit
from typing import Any, Optional

logger = logging.getLogger("tradex.eltdx")


# ============================================================
# 客户端管理（单例）— 从 eltdx_data.py 迁移
# ============================================================

_client: Optional[Any] = None
_client_lock = threading.Lock()
_client_initializing = False


def _get_client():
    """获取/创建 eltdx TdxClient 单例。

    关闭 probe_hosts（避免冷启动慢），使用默认 host 列表。
    第一次调用时建立连接，后续复用。
    v3.1.4 起：使用 threading.Lock 替代布尔值标志，修复多线程竞态。
    """
    global _client, _client_initializing
    if _client is not None:
        return _client
    with _client_lock:
        # 双重检查：拿到锁后再次确认（其他线程可能已初始化）
        if _client is not None:
            return _client
        if _client_initializing:
            return None
        _client_initializing = True
    try:
        from eltdx import TdxClient
        _client = TdxClient.from_hosts(timeout=8.0, pool_size=1)
        _client.connect()
        logger.info("eltdx TdxClient connected")
        return _client
    except Exception as e:
        logger.error(f"eltdx client init failed: {e}")
        _client = None
        return None
    finally:
        with _client_lock:
            _client_initializing = False


def _shutdown_client() -> None:
    global _client
    if _client is not None:
        try:
            _client.close()
        except Exception:
            pass
        _client = None


atexit.register(_shutdown_client)


def _normalize_code(code: str) -> str:
    """把 6 位代码或带前缀代码统一成 eltdx 期望的格式。

    eltdx 的 TdxClient 通常接受 'sz000001' / 'sh600000' 或 6 位纯代码。
    """
    code = code.strip().lower()
    if code.startswith(("sz", "sh", "bj")):
        return code
    if len(code) == 6 and code.isdigit():
        if code.startswith(("60", "68", "90", "11", "13")):
            return "sh" + code
        if code.startswith(("00", "30", "20")):
            return "sz" + code
        if code.startswith(("8", "43", "92")):
            return "bj" + code
    return code


def _strip_prefix(code: str) -> str:
    """去除 sh/sz/bj 前缀，返回 6 位纯代码。"""
    code = code.strip().lower()
    if code.startswith(("sh", "sz", "bj")):
        return code[2:]
    return code


# ============================================================
# fetch_fn 包装器
# ============================================================

def _normalize_symbol_code(symbol: str = "", code: str = "") -> str:
    """归一化股票代码参数：同时接受 symbol 和 code，返回非空者。

    解决 SmartRouter.route(**kwargs) 原样转发参数时，
    不同 fetcher 参数名不一致（symbol vs code）导致主源失败的 P0 bug。
    """
    raw = code or symbol
    if not raw:
        raise RuntimeError("stock code is required (symbol or code)")
    return _normalize_code(raw)


def fetch_call_auction(code: str = "", symbol: str = "", **kwargs) -> Any:
    """集合竞价数据（eltdx 独占源）。返回 eltdx auctions.series 原始结果对象。

    兼容 symbol/code 两种参数名（SmartRouter 路由归一化）。
    """
    client = _get_client()
    if client is None:
        raise RuntimeError("eltdx client not available")
    norm_code = _normalize_symbol_code(symbol, code)
    result = client.auctions.series(norm_code)
    if result is None:
        raise RuntimeError("auction series is empty")
    points = getattr(result, "points", None) or []
    if not points:
        raise RuntimeError("no auction points")
    return result


def fetch_tick_data(code: str = "", symbol: str = "", trading_date: str = "", count: int = 2000, **kwargs) -> Any:
    """逐笔成交数据（eltdx 独占源）。返回 eltdx trades.history 原始结果对象。

    兼容 symbol/code 两种参数名（SmartRouter 路由归一化）。
    """
    client = _get_client()
    if client is None:
        raise RuntimeError("eltdx client not available")
    norm_code = _normalize_symbol_code(symbol, code)
    norm_date = (trading_date or "").replace("-", "").replace("/", "")
    result = client.trades.history(norm_code, norm_date, count=count)
    ticks = getattr(result, "ticks", None) or []
    if not ticks:
        raise RuntimeError(f"no ticks on {norm_date}")
    return result


def fetch_f10_profile(code: str = "", symbol: str = "", **kwargs) -> dict:
    """F10 资料（eltdx 独占源）。返回含 profile/topics/diagnosis 原始响应的 dict。

    兼容 symbol/code 两种参数名（SmartRouter 路由归一化）。
    """
    client = _get_client()
    if client is None:
        raise RuntimeError("eltdx client not available")
    raw = code or symbol
    if not raw:
        raise RuntimeError("stock code is required (symbol or code)")
    norm_code = raw.strip()
    if norm_code.startswith(("sz", "sh", "bj")):
        norm_code = norm_code[2:]

    profile_resp = client.f10.company_profile(norm_code)
    topics_resp = client.f10.hot_topics(norm_code)
    diag_resp = client.f10.finance_diagnosis(norm_code)

    return {
        "profile_resp": profile_resp,
        "topics_resp": topics_resp,
        "diag_resp": diag_resp,
        "code": norm_code,
    }


def fetch_realtime_quote(code: str = "", symbol: str = "", **kwargs):
    """实时行情（eltdx 源）。返回单行 DataFrame，含'代码'列。

    使用 client.helpers.full_quotes() 获取真正的实时报价（QuoteSnapshot），
    字段比 K 线最后一根完整：含涨跌额/涨跌幅/昨收/内外盘/现手等。
    v3.3.6: eltdx 2.0 移除旧式 client.get_quote()，迁移至 client.helpers.full_quotes()。
    兼容 symbol/code 两种参数名（SmartRouter 路由归一化）。
    """
    import pandas as pd
    client = _get_client()
    if client is None:
        raise RuntimeError("eltdx client not available")
    norm_code = _normalize_symbol_code(symbol, code)
    quotes = client.helpers.full_quotes(norm_code)
    if not quotes:
        raise RuntimeError("eltdx returned no quote")
    q = quotes[0]
    return pd.DataFrame([{
        "代码": getattr(q, "code", _strip_prefix(norm_code)),
        "最新价": getattr(q, "last_price", None),
        "昨收": getattr(q, "pre_close_price", None),
        "今开": getattr(q, "open_price", None),
        "最高": getattr(q, "high_price", None),
        "最低": getattr(q, "low_price", None),
        "涨跌额": getattr(q, "change", None),
        "涨跌幅": getattr(q, "change_pct", None),
        "成交量": getattr(q, "total_hand", None),  # 单位：手
        "成交额": getattr(q, "amount", None),
        "内盘": getattr(q, "inside_dish", None),
        "外盘": getattr(q, "outer_disc", None),
        "现手": getattr(q, "current_hand", None),
    }])


_PERIOD_ALIASES = {
    "day": "day", "daily": "day", "d": "day", "1d": "day",
    "week": "week", "weekly": "week", "w": "week", "1w": "week",
    "month": "month", "monthly": "month", "m": "month", "1m": "month",
}


def _normalize_period(period: str) -> str:
    """归一化 K 线周期命名（eltdx 只认 day/week/month）。

    SmartRouter 上层调用方习惯传 akshare 风格命名（daily/weekly/monthly），
    若不归一化会抛错→静默降级 akshare,绕过主源。非法周期直接抛错让上层可见。
    """
    key = str(period or "").strip().lower()
    normalized = _PERIOD_ALIASES.get(key)
    if normalized is None:
        raise ValueError(
            f"unsupported period: {period!r} "
            "(supported: day/daily/d/1d, week/weekly/w/1w, month/monthly/m/1m)"
        )
    return normalized


def fetch_historical_kline(code: str = "", symbol: str = "", period: str = "day", count: int = 100, **kwargs):
    """历史 K 线（eltdx 源）。返回中文列名 DataFrame（与 akshare 口径对齐）。

    兼容 symbol/code 两种参数名（SmartRouter 路由归一化）。
    KlineBar 字段映射（v3.1.3 修复）：date→time, volume→volume_lots。
    """
    import pandas as pd
    client = _get_client()
    if client is None:
        raise RuntimeError("eltdx client not available")
    norm_code = _normalize_symbol_code(symbol, code)
    period = _normalize_period(period)
    result = client.bars.get(norm_code, period=period, count=count)
    bars = getattr(result, "bars", None) or []
    if not bars:
        raise RuntimeError(f"no kline bars for period={period}")
    rows = []
    for b in bars:
        rows.append({
            "日期": getattr(b, "time", None),
            "开盘": getattr(b, "open", None),
            "最高": getattr(b, "high", None),
            "最低": getattr(b, "low", None),
            "收盘": getattr(b, "close", None),
            "成交量": getattr(b, "volume_lots", None),
            "成交额": getattr(b, "amount", None),
        })
    return pd.DataFrame(rows)


def fetch_minute_data(code: str = "", symbol: str = "", **kwargs):
    """分时数据（eltdx 源）。返回中文列名 DataFrame（时间/价格/均价/成交量）。

    兼容 symbol/code 两种参数名（SmartRouter 路由归一化）。
    """
    import pandas as pd
    client = _get_client()
    if client is None:
        raise RuntimeError("eltdx client not available")
    norm_code = _normalize_symbol_code(symbol, code)
    result = client.minutes.today(norm_code)
    points = getattr(result, "points", None) or []
    if not points:
        raise RuntimeError("no minute points")
    rows = []
    for p in points:
        rows.append({
            "时间": getattr(p, "time_label", None) or getattr(p, "time", None),
            "价格": getattr(p, "price", None),
            "均价": getattr(p, "avg_price", None),
            "成交量": getattr(p, "volume", None),
        })
    return pd.DataFrame(rows)


def fetch_security_codes(market: str = "all", **kwargs):
    """全市场证券代码表（eltdx 源，v3.3.7 新增）。

    通过 codes.all / codes.all_markets 返回精确的证券分类清单：
    含代码、名称、类别（a_share/etf/index/bond 等）、板块（主板/创业板/科创板）。

    相比 akshare 行情快照，这是权威代码表：含停牌股、精确分类。
    market 取值：'sh' / 'sz' / 'bj' / 'all'（默认沪深京三市场）。
    """
    import pandas as pd
    client = _get_client()
    if client is None:
        raise RuntimeError("eltdx client not available")
    market = (market or "all").strip().lower()
    if market == "all":
        items = client.codes.all_markets()
    else:
        items = client.codes.all(market)
    if not items:
        raise RuntimeError(f"no securities for market={market}")
    rows = []
    for item in items:
        full_code = getattr(item, "full_code", None) or (
            f"{getattr(item, 'exchange', '')}{getattr(item, 'code', '')}"
        )
        rows.append({
            "代码": full_code,
            "名称": getattr(item, "name", None),
            "类别": getattr(item, "category", None),
            "板块": getattr(item, "board", None),
        })
    return pd.DataFrame(rows)


def _market_cn(code) -> str:
    """把证券代码（sh600000/sz000001/bj430001 或 6 位纯数字）映射为市场中文名。

    返回 沪/深/京；无法识别时返回空串（而非静默 NaN），供调用方显式处理。
    """
    s = (str(code) if code is not None else "").strip().lower()
    prefix = s[:2]
    if prefix in ("sh", "sz", "bj"):
        return {"sh": "沪", "sz": "深", "bj": "京"}[prefix]
    if s.startswith(("600", "601", "603", "605", "688", "689", "900", "901")):
        return "沪"
    if s.startswith(("000", "001", "002", "003", "300", "301")):
        return "深"
    if s.startswith(("43", "83", "87", "88", "920")) or s.startswith("8"):
        return "京"
    return ""


def _pure_code(code) -> str:
    """剥离证券代码的交易所前缀（sh600000 → 600000）；纯数字原样返回。"""
    s = (str(code) if code is not None else "").strip().lower()
    return s[2:] if s[:2] in ("sh", "sz", "bj") else s


def fetch_all_a_shares(**kwargs):
    """全市场 A 股代码列表（eltdx 源，v3.3.7 新增）。

    返回权威 A 股代码清单（约 5500 只，含停牌股），量化选股股票池底座。
    """
    import pandas as pd
    client = _get_client()
    if client is None:
        raise RuntimeError("eltdx client not available")
    codes = client.codes.all_a_shares()
    if not codes:
        raise RuntimeError("no a-share codes")
    df = pd.DataFrame({"代码": codes})
    df["市场"] = df["代码"].map(_market_cn)
    df["纯代码"] = df["代码"].map(_pure_code)
    return df


def fetch_minute_history(code: str = "", symbol: str = "", trading_date: str = "", **kwargs):
    """历史分时数据（eltdx 源，v3.3.7 新增）。

    返回指定交易日的历史分时（约 240 点/日），用于盘后复盘。
    trading_date 格式 YYYYMMDD 或 YYYY-MM-DD。
    """
    import pandas as pd
    client = _get_client()
    if client is None:
        raise RuntimeError("eltdx client not available")
    norm_code = _normalize_symbol_code(symbol, code)
    norm_date = (trading_date or "").replace("-", "").replace("/", "")
    result = client.minutes.history(norm_code, norm_date)
    points = getattr(result, "points", None) or []
    if not points:
        raise RuntimeError(f"no minute history for {norm_code} on {norm_date}")
    rows = []
    for p in points:
        rows.append({
            "时间": getattr(p, "time_label", None) or getattr(p, "time", None),
            "价格": getattr(p, "price", None),
            "均价": getattr(p, "avg_price", None),
            "成交量": getattr(p, "volume", None),
        })
    return pd.DataFrame(rows)


def fetch_minute_aux(code: str = "", symbol: str = "", kind: str = "buy_sell_strength", **kwargs):
    """分时买卖强度数据（eltdx 源，v3.3.7 新增）。

    返回日内买卖力量对比（buy_commission/sell_commission），
    用于 T0 盘口强弱判断。kind=buy_sell_strength 为买卖强度。
    """
    import pandas as pd
    client = _get_client()
    if client is None:
        raise RuntimeError("eltdx client not available")
    norm_code = _normalize_symbol_code(symbol, code)
    result = client.minutes.aux(norm_code, kind=kind)
    points = getattr(result, "points", None) or []
    if not points:
        raise RuntimeError(f"no minute aux for {norm_code}")
    rows = []
    for p in points:
        rows.append({
            "时间": getattr(p, "time_label", None),
            "买盘": getattr(p, "buy_commission", None),
            "卖盘": getattr(p, "sell_commission", None),
            "序列A": getattr(p, "series_a", None),
            "序列B": getattr(p, "series_b", None),
        })
    return pd.DataFrame(rows)


def _tick_to_row(t) -> dict:
    """TradeTick → 中文列名 dict。"""
    return {
        "时间": getattr(t, "time_label", None),
        "价格": getattr(t, "price", None),
        "成交量": getattr(t, "volume", None),
        "成交额": getattr(t, "trade_amount_yuan", None),
        "方向": getattr(t, "side", None),
        "是否开盘撮合": getattr(t, "is_opening_match", None),
        "是否竞价快照": getattr(t, "is_auction_snapshot", None),
        "竞价匹配量": getattr(t, "auction_matched_volume", None),
    }


def fetch_today_ticks(code: str = "", symbol: str = "", count: int = 2000, **kwargs):
    """当日逐笔成交（eltdx 源，v3.3.7 新增）。

    返回当日逐笔成交明细（单页，count 上限 1800）。
    与 fetch_tick_data（历史逐笔）互补，用于盘中实时逐笔。
    """
    import pandas as pd
    client = _get_client()
    if client is None:
        raise RuntimeError("eltdx client not available")
    norm_code = _normalize_symbol_code(symbol, code)
    result = client.trades.today(norm_code, count=count)
    ticks = getattr(result, "ticks", None) or []
    if not ticks:
        raise RuntimeError(f"no today ticks for {norm_code}")
    return pd.DataFrame([_tick_to_row(t) for t in ticks])


def fetch_opening_match(code: str = "", symbol: str = "", **kwargs):
    """9:25 开盘撮合（eltdx 源，v3.3.7 新增）。

    返回当日 9:25 正式开盘撮合那一笔（开盘价形成），T0 竞价判断核心。
    """
    import pandas as pd
    client = _get_client()
    if client is None:
        raise RuntimeError("eltdx client not available")
    norm_code = _normalize_symbol_code(symbol, code)
    result = client.trades.opening_match_today(norm_code)
    if result is None:
        raise RuntimeError(f"no opening match for {norm_code}")
    return pd.DataFrame([_tick_to_row(result)])


def _bar_to_row(b) -> dict:
    """KlineBar → 中文列名 dict。"""
    time_val = getattr(b, "time", None)
    if hasattr(time_val, "strftime"):
        time_val = time_val.strftime("%Y-%m-%d %H:%M")
    return {
        "日期": str(time_val) if time_val is not None else None,
        "开盘": getattr(b, "open", None),
        "最高": getattr(b, "high", None),
        "最低": getattr(b, "low", None),
        "收盘": getattr(b, "close", None),
        "成交量": getattr(b, "volume_lots", None),
        "成交额": getattr(b, "amount", None),
    }


def _bar_sort_key(bar) -> float:
    """K 线时间排序键（跨页合并后重排用）。

    eltdx 分页按「最近页 → 更早页」返回，页内升序；跨页合并后必须重排。
    用 timestamp() 比较，规避 tz-aware 与 None 混排的 TypeError。

    v3.3.14: 收窄异常捕获（原 `except Exception: return 0.0` 会静默把异常 bar
    排到最前、污染回测首行）。现在只捕获可预期的取值异常并记 warning，
    异常 bar 返回 +inf 排到末尾（不丢数据、不污染首行），异常不再被静默吞掉。
    """
    t = getattr(bar, "time", None)
    try:
        return float(t.timestamp())
    except (AttributeError, TypeError, ValueError, OSError) as exc:
        logger.warning("K线 bar 时间字段无法解析(%r: %s)，排序时置于末尾", t, exc)
        return float("inf")


def fetch_full_kline(code: str = "", symbol: str = "", period: str = "day", max_pages: int = 30, **kwargs):
    """全量 K 线（eltdx 源，v3.3.7 新增）。

    自动分页拉取全量历史 K 线（bars.get(all_pages=True)），适合回测。
    与 fetch_historical_kline（单页 bars.get）互补。

    v3.3.13: eltdx 3.x 移除 client.bars.all()，改用 bars.get(all_pages=True, max_pages=...)。
    """
    import pandas as pd
    client = _get_client()
    if client is None:
        raise RuntimeError("eltdx client not available")
    norm_code = _normalize_symbol_code(symbol, code)
    result = client.bars.get(norm_code, period=period, all_pages=True, max_pages=max_pages)
    bars = getattr(result, "bars", None) or []
    if not bars:
        raise RuntimeError(f"no kline bars for {norm_code}")
    # v3.3.13: 跨页合并后按时间升序重排（分页序为「最近页→更早页」，直接拼接会乱序）
    bars = sorted(bars, key=_bar_sort_key)
    return pd.DataFrame([_bar_to_row(b) for b in bars])


def fetch_adjusted_kline(code: str = "", symbol: str = "", period: str = "day", adjust: str = "qfq", count: int = 800, **kwargs):
    """复权 K 线（eltdx 源，v3.3.7 新增）。

    通过 bars.get(adjust=...) 返回前复权(qfq)/后复权(hfq) K 线，
    复权由主站计算（eltdx 3.x 起；2.x 时代为 helpers.adjusted_kline 本地计算）。
    """
    import pandas as pd
    client = _get_client()
    if client is None:
        raise RuntimeError("eltdx client not available")
    norm_code = _normalize_symbol_code(symbol, code)
    period = _normalize_period(period)
    result = client.bars.get(norm_code, period=period, adjust=adjust, count=count)
    bars = getattr(result, "bars", None) or []
    if not bars:
        raise RuntimeError(f"no adjusted kline bars for {norm_code}")
    return pd.DataFrame([_bar_to_row(b) for b in bars])


def _parse_codes_arg(codes) -> list[str]:
    """把 codes 参数（逗号分隔字符串或列表）解析成归一化代码列表。"""
    if isinstance(codes, str):
        raw_list = [c.strip() for c in codes.split(",") if c.strip()]
    else:
        raw_list = [str(c).strip() for c in (codes or []) if str(c).strip()]
    return [_normalize_code(c) for c in raw_list]


def fetch_stock_profile(codes="", symbol: str = "", **kwargs):
    """全景档案（eltdx 源，v3.3.7 新增）。

    通过 helpers.stock_profile_table 返回「行情 + 证券信息 + 财务」一张表：
    含最新价/涨跌幅/换手率/总市值/流通市值/EPS 等。量化选股神器。
    codes 支持逗号分隔多只股票，如 "600170,000001"。
    """
    import pandas as pd
    client = _get_client()
    if client is None:
        raise RuntimeError("eltdx client not available")
    raw = codes or symbol
    if not raw:
        raise RuntimeError("stock code(s) required")
    norm_codes = _parse_codes_arg(raw)
    if not norm_codes:
        raise RuntimeError("no valid stock codes")
    table = client.helpers.stock_profile_table(norm_codes)
    rows = []
    for r in table.rows:
        rows.append({
            "代码": getattr(r, "full_code", None),
            "名称": getattr(r, "name", None),
            "最新价": getattr(r, "last_price", None),
            "涨跌幅": getattr(r, "change_pct", None),
            "换手率": getattr(r, "turnover_rate", None),
            "总市值": getattr(r, "total_market_value", None),
            "流通市值": getattr(r, "circulating_market_value", None),
            "总股本": getattr(r, "total_shares", None),
            "流通股本": getattr(r, "circulating_shares", None),
            "EPS": getattr(r, "eps", None),
            "板块": getattr(r, "board", None),
        })
    return pd.DataFrame(rows)


_SHORTLINE_FIELD_MAP = {
    "full_code": "代码",
    "limit_status": "涨停状态",
    "limit_board_text": "涨停板类型",
    "limit_up_streak_days": "连板天数",
    "limit_up_count_in_stat_days": "统计期涨停次数",
    "year_limit_up_days": "年内涨停天数",
    "seal_to_float_ratio": "封单流通比",
    "prev_seal_amount": "昨日封单额",
    "prev2_seal_amount": "前日封单额",
    "pe_ttm": "市盈率TTM",
    "beta_60d": "60日贝塔",
    "free_float_market_value": "自由流通市值",
    "free_float_shares": "自由流通股本",
    "open_turnover_z": "开盘换手Z",
    "open_prev_amount_ratio": "开盘额比",
    "auction_prev_volume_ratio": "竞价量比",
    "ladder_level": "梯度等级",
}


def fetch_shortline_indicators(codes="", symbol: str = "", **kwargs):
    """短线指标（eltdx 源，v3.3.7 新增）。

    通过 helpers.shortline_indicators 返回 21 项短线打板指标：
    连板天数/涨停次数/封单流通比/市盈率TTM/60日贝塔/自由流通市值等。
    短线打板分析核心。codes 支持逗号分隔多只股票。
    """
    import pandas as pd
    client = _get_client()
    if client is None:
        raise RuntimeError("eltdx client not available")
    raw = codes or symbol
    if not raw:
        raise RuntimeError("stock code(s) required")
    norm_codes = _parse_codes_arg(raw)
    if not norm_codes:
        raise RuntimeError("no valid stock codes")
    table = client.helpers.shortline_indicators(norm_codes)
    rows = []
    for r in table.rows:
        row = {}
        for eng, zh in _SHORTLINE_FIELD_MAP.items():
            row[zh] = getattr(r, eng, None)
        rows.append(row)
    return pd.DataFrame(rows)


def fetch_finance_batch(codes="", symbol: str = "", **kwargs):
    """批量财务字段（eltdx 源，v3.3.7 新增）。

    通过 corporate.finance_batch 一次拉取多只股票的财务字段：
    总股本/流通股本/总资产/净利润/每股收益/行业等。量化选股估值利器。
    codes 支持逗号分隔多只股票。
    """
    import pandas as pd
    client = _get_client()
    if client is None:
        raise RuntimeError("eltdx client not available")
    raw = codes or symbol
    if not raw:
        raise RuntimeError("stock code(s) required")
    norm_codes = _parse_codes_arg(raw)
    if not norm_codes:
        raise RuntimeError("no valid stock codes")
    batch = client.corporate.finance_batch(norm_codes)
    records = getattr(batch, "records", None) or ()
    rows = []
    for r in records:
        rows.append({
            "代码": getattr(r, "full_code", None),
            "总股本": getattr(r, "total_shares", None),
            "流通股本": getattr(r, "circulating_shares", None),
            "总资产": getattr(r, "total_assets_yuan", None),
            "净利润": getattr(r, "net_profit_yuan", None),
            "每股收益": getattr(r, "eps_raw", None),
            "行业": getattr(r, "industry_raw", None),
            "上市日期": getattr(r, "ipo_date", None),
        })
    return pd.DataFrame(rows)


def fetch_special_limits(**kwargs):
    """特殊涨跌停参考价（eltdx 源，v3.3.7 新增）。

    通过 limits.special 返回特殊品种（ST/新股/复牌）的涨跌停参考价。
    """
    import pandas as pd
    client = _get_client()
    if client is None:
        raise RuntimeError("eltdx client not available")
    page = client.limits.special()
    records = getattr(page, "records", None) or ()
    rows = []
    for r in records:
        rows.append({
            "代码": getattr(r, "full_code", None),
            "涨停价": getattr(r, "limit_up_price", None),
            "跌停价": getattr(r, "limit_down_price", None),
        })
    return pd.DataFrame(rows)


def _f10_rows_to_df(resp) -> "pd.DataFrame":
    """F10Response → DataFrame（原始列名，含通达信字段编码 T007 等）。"""
    import pandas as pd
    rows = getattr(resp, "rows", None) or ()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(list(rows))


def _strip_code6(code: str) -> str:
    """归一化并去 sh/sz/bj 前缀，返回 6 位纯代码（f10 接口要求）。"""
    return _strip_prefix(_normalize_symbol_code("", code))


def fetch_finance_report(code: str = "", symbol: str = "", report_type: str = "zcfzb", **kwargs):
    """财务报表（eltdx F10，v3.3.7 新增）。

    通过 f10.finance_report 返回通达信财务报表。report_type：
    zcfzb=资产负债表 / lrb=利润表 / xjllb=现金流量表。
    字段为通达信内部编码（T007/T008 等）。作为 akshare 财务的降级补充源。
    """
    client = _get_client()
    if client is None:
        raise RuntimeError("eltdx client not available")
    code6 = _strip_code6(code or symbol)
    resp = client.f10.finance_report(code6, report_type=report_type)
    return _f10_rows_to_df(resp)


def fetch_dividend_financing(code: str = "", symbol: str = "", **kwargs):
    """分红融资（eltdx F10，v3.3.7 新增）。

    通过 f10.dividend_financing 返回分红方案历史。
    字段为通达信内部编码。作为 akshare 分红的降级补充源。
    """
    client = _get_client()
    if client is None:
        raise RuntimeError("eltdx client not available")
    code6 = _strip_code6(code or symbol)
    resp = client.f10.dividend_financing(code6)
    return _f10_rows_to_df(resp)


def fetch_company_news(code: str = "", symbol: str = "", **kwargs):
    """公司资讯（eltdx F10，v3.3.7 新增）。

    通过 f10.company_news 返回公司研报/监管措施资讯。
    字段为通达信内部编码。作为 akshare 资讯的降级补充源。
    """
    client = _get_client()
    if client is None:
        raise RuntimeError("eltdx client not available")
    code6 = _strip_code6(code or symbol)
    resp = client.f10.company_news(code6)
    return _f10_rows_to_df(resp)


def fetch_northbound_holding(code: str = "", symbol: str = "", **kwargs):
    """北向持股（eltdx F10，v3.3.7 新增）。

    通过 f10.northbound_holding 返回沪深股通持股变化。
    字段为通达信内部编码。作为 akshare 北向的降级补充源。
    """
    client = _get_client()
    if client is None:
        raise RuntimeError("eltdx client not available")
    code6 = _strip_code6(code or symbol)
    resp = client.f10.northbound_holding(code6)
    return _f10_rows_to_df(resp)


def fetch_stock_topics(code: str = "", symbol: str = "", **kwargs):
    """个股全题材（eltdx helpers，v3.3.7 新增）。

    通过 helpers.stock_topics 返回个股关联的全部题材（合并题材ID+热点），
    含题材名/关联度/入选理由。题材挖掘核心。
    """
    import pandas as pd
    client = _get_client()
    if client is None:
        raise RuntimeError("eltdx client not available")
    norm_code = _normalize_symbol_code(symbol, code)
    result = client.helpers.stock_topics(norm_code)
    topics = getattr(result, "topics", None) or ()
    rows = []
    for t in topics:
        rows.append({
            "题材名": getattr(t, "topic_name", None),
            "关联度": getattr(t, "relation_level", None),
            "入选理由": getattr(t, "reason", None),
            "题材ID": getattr(t, "topic_id", None),
        })
    return pd.DataFrame(rows)


def fetch_topic_stocks(code: str = "", symbol: str = "", topic_name: str = "", **kwargs):
    """题材成分股（eltdx helpers，v3.3.7 新增）。

    通过 helpers.topic_stocks 返回某题材下的成分股排名（涨跌幅/排名）。
    topic_name 为空时用种子股首个题材。
    """
    import pandas as pd
    client = _get_client()
    if client is None:
        raise RuntimeError("eltdx client not available")
    norm_code = _normalize_symbol_code(symbol, code)
    result = client.helpers.topic_stocks(norm_code, topic_name=topic_name or None)
    rows = []
    for r in (getattr(result, "rows", None) or ()):
        rows.append({
            "代码": getattr(r, "full_code", None),
            "名称": getattr(r, "name", None),
            "排名": getattr(r, "rank", None),
            "涨跌幅": getattr(r, "change_pct", None),
            "3日涨跌幅": getattr(r, "change_pct_3d", None),
            "5日涨跌幅": getattr(r, "change_pct_5d", None),
            "20日涨跌幅": getattr(r, "change_pct_20d", None),
            "60日涨跌幅": getattr(r, "change_pct_60d", None),
        })
    return pd.DataFrame(rows)


def fetch_auction_data(code: str = "", symbol: str = "", **kwargs):
    """竞价汇总（eltdx helpers，v3.3.7 新增）。

    通过 helpers.auction_data 返回竞价汇总：开盘价/开盘量/开盘额/开盘涨跌，
    聚合集合竞价序列 + 9:25 快照 + 行情。
    """
    import pandas as pd
    client = _get_client()
    if client is None:
        raise RuntimeError("eltdx client not available")
    norm_code = _normalize_symbol_code(symbol, code)
    result = client.helpers.auction_data(norm_code)
    return pd.DataFrame([{
        "代码": getattr(result, "code", None),
        "开盘价": getattr(result, "open_price", None),
        "开盘量": getattr(result, "open_volume", None),
        "开盘额": getattr(result, "open_amount", None),
        "开盘涨跌幅": getattr(result, "open_change_pct", None),
        "昨收": getattr(result, "pre_close_price", None),
    }])


def fetch_category_quotes(category: str = "沪深a股", sort_by: str = "涨幅", count: int = 80, **kwargs):
    """分类行情列表（eltdx 源，v3.3.7 新增，B 级）。

    通过 quotes.list_by_category 返回分类行情（如 A股涨幅榜/成交额榜/封单榜），
    实时性强于 akshare。category：沪深a股/a股；sort_by：涨幅/成交额/现价/封单额等。
    """
    import pandas as pd
    client = _get_client()
    if client is None:
        raise RuntimeError("eltdx client not available")
    page = client.quotes.list_by_category(category, sort_by=sort_by, count=count)
    records = getattr(page, "records", None) or ()
    rows = []
    for r in records:
        rows.append({
            "代码": getattr(r, "full_code", None),
            "现价": getattr(r, "last_price", None),
            "涨跌幅": getattr(r, "change_pct", None),
            "涨跌额": getattr(r, "change", None),
            "成交额": getattr(r, "amount", None),
            "买一": getattr(r, "bid1", None),
            "卖一": getattr(r, "ask1", None),
            "涨速": getattr(r, "rise_speed", None),
            "短换手": getattr(r, "short_turnover", None),
        })
    return pd.DataFrame(rows)


def fetch_trading_day(**kwargs):
    """交易日判定（eltdx 源，v3.3.7 新增，B 级）。

    通过 session.handshake 返回服务器日期（当前交易日）。
    """
    import pandas as pd
    client = _get_client()
    if client is None:
        raise RuntimeError("eltdx client not available")
    h = client.session.handshake()
    return pd.DataFrame([{
        "服务器日期": getattr(h, "server_date_1", None),
        "服务器日期2": getattr(h, "server_date_2", None),
        "服务器时间": getattr(h, "server_datetime", None),
    }])


def fetch_opening_match_history(code: str = "", symbol: str = "", trading_date: str = "", **kwargs):
    """历史开盘撮合（eltdx 源，v3.3.7 新增，B 级）。

    通过 trades.opening_match_history 返回历史某日 9:25 开盘撮合，复盘用。
    """
    import pandas as pd
    client = _get_client()
    if client is None:
        raise RuntimeError("eltdx client not available")
    norm_code = _normalize_symbol_code(symbol, code)
    norm_date = (trading_date or "").replace("-", "").replace("/", "")
    result = client.trades.opening_match_history(norm_code, norm_date)
    if result is None:
        raise RuntimeError(f"no opening match for {norm_code} on {norm_date}")
    return pd.DataFrame([_tick_to_row(result)])


def fetch_capital_changes(code: str = "", symbol: str = "", **kwargs):
    """股本变动历史（eltdx 源，v3.3.7 新增，B 级）。

    通过 corporate.capital_changes 返回股本变动（分红/送股/增发等）历史。
    """
    import pandas as pd
    client = _get_client()
    if client is None:
        raise RuntimeError("eltdx client not available")
    norm_code = _normalize_symbol_code(symbol, code)
    block = client.corporate.capital_changes(norm_code)
    records = getattr(block, "records", None) or getattr(block, "items", None) or ()
    rows = []
    for r in records:
        rows.append({
            "日期": getattr(r, "date", None),
            "变动类型": getattr(r, "category_name", None),
            "变动前股本": getattr(r, "c1_float", None),
            "变动后股本": getattr(r, "c2_float", None),
        })
    return pd.DataFrame(rows)


def fetch_special_limits_scan(**kwargs):
    """扫描全部特殊涨跌停（eltdx 源，v3.3.7 新增，B 级）。

    通过 limits.scan_special 扫描全市场特殊品种（ST/新股/复牌）涨跌停参考价。
    """
    import pandas as pd
    client = _get_client()
    if client is None:
        raise RuntimeError("eltdx client not available")
    records = client.limits.scan_special(max_rows=10000)
    rows = []
    for r in records:
        rows.append({
            "代码": getattr(r, "full_code", None),
            "涨停价": getattr(r, "limit_up_price", None),
            "跌停价": getattr(r, "limit_down_price", None),
        })
    return pd.DataFrame(rows)


_F10_ENTRY_MAP = {
    "valuation": "估值",
    "theme_market": "题材行情",
    "stock_score": "个股总评",
    "profit_forecast": "盈利预测",
    "ranking_detail": "排名明细",
    "governance": "治理",
    "shareholder_change_plans": "增减持",
    "business_composition": "主营构成",
    "announcements": "公告",
    "news": "新闻",
    "stock_info": "基础信息",
}


def fetch_f10_extra(entry: str = "", code: str = "", symbol: str = "", **kwargs):
    """F10 额外资料通用入口（eltdx 源，v3.3.7 新增，B 级）。

    覆盖 F10 的 B 级接口：valuation/theme_market/stock_score/profit_forecast/
    ranking_detail/governance/shareholder_change_plans/business_composition/
    announcements/news/stock_info。
    字段为通达信内部编码（T007 等），作为 akshare 中文源的降级补充源。
    """
    client = _get_client()
    if client is None:
        raise RuntimeError("eltdx client not available")
    if entry not in _F10_ENTRY_MAP:
        raise RuntimeError(f"unsupported f10 entry: {entry}, choices: {list(_F10_ENTRY_MAP)}")
    code6 = _strip_code6(code or symbol)
    method = getattr(client.f10, entry, None)
    if method is None:
        raise RuntimeError(f"f10 entry not available: {entry}")
    resp = method(code6)
    return _f10_rows_to_df(resp)


# ============================================================
# v3.3.14 新增：估值备源（走通达信自有服务器，非东财 / 百度）
# ============================================================

def fetch_valuation_eltdx(
    endpoint: str = "baidu",
    code: str = "",
    symbol: str = "",
    **kwargs,
):
    """估值数据备源（eltdx F10 valuation）。

    v3.3.14 新增：valuation 此前只有 akshare 百度单源，百度接口收紧后无兜底。
    本备源走 eltdx（通达信行情服务器，与东财/百度完全独立），
    覆盖 PE / PB / PS / 市值等估值指标，仅对应主源的 baidu 语义。
    """
    if endpoint != "baidu":
        raise ValueError(
            f"eltdx 备源不支持 valuation endpoint={endpoint!r}（仅 baidu）"
        )
    return fetch_f10_extra(entry="valuation", code=code, symbol=symbol)
