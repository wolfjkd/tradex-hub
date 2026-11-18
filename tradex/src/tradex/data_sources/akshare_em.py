"""东财 datacenter / push2 直连族（QI-ARCH-09 拆分，2026-11-19）：龙虎榜 dt 族 / 两融 / 大宗交易 / 大市值 / 全球指数快照 / 机构持仓直取。
上游归属：东财 datacenter-web 与 push2（与 akshare 主族同站但独立接口）。"""
from __future__ import annotations
import logging
import time
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from ..utils.cache import cache, TTL_DAILY, TTL_REALTIME
from .akshare_common import _ak, _prev_quarter_end

logger = logging.getLogger("tradex.akshare")

def _ak_date_range_kwargs(
    start_date: str | None, end_date: str | None, default_days: int = 5,
) -> tuple[str, str]:
    """统一处理 start_date/end_date 参数：兼容 YYYY-MM-DD / YYYYMMDD / None。

    返回 (start, end) 都是 YYYYMMDD 格式（akshare 接受的格式）。
    任一缺失时按 default_days 天回溯填充。
    """
    def _norm(d: str | None) -> str | None:
        if not d:
            return None
        s = str(d).strip().replace("-", "")
        return s if len(s) == 8 else None

    s = _norm(start_date)
    e = _norm(end_date)
    if not e:
        e = datetime.now().strftime("%Y%m%d")
    if not s:
        s = (datetime.now() - timedelta(days=default_days)).strftime("%Y%m%d")
    return s, e


_EM_ZLSJ_URL = "http://data.eastmoney.com/dataapi/zlsj/list"

_FUND_HOLD_SYMBOL_MAP = {
    "基金持仓": "1",
    "QFII持仓": "2",
    "社保持仓": "3",
    "券商持仓": "4",
    "保险持仓": "5",
    "信托持仓": "6",
}

_FUND_HOLD_FIELDS = [
    ("SECURITY_CODE", "股票代码"),
    ("SECURITY_NAME_ABBR", "股票简称"),
    ("HOULD_NUM", "持有基金家数"),
    ("TOTAL_SHARES", "持股总数"),
    ("HOLD_VALUE", "持股市值"),
    ("HOLDCHA", "持股变化"),          # 增仓 / 减仓（方向）
    ("HOLDCHA_NUM", "持股变动数值"),   # 股数增减
    ("HOLDCHA_RATIO", "持股变动比例"), # 百分比
    ("FREESHARES_RATIO", "持股占流通股比"),  # 新增列（akshare 原 schema 无此列）
]

_FUND_HOLD_NUM_COLS = (
    "持有基金家数", "持股总数", "持股市值", "持股变动数值",
    "持股变动比例", "持股占流通股比",
)

_GLOBAL_INDEX_MIN_INTERVAL = 60.0

_last_global_index_call = 0.0

def fetch_fund_hold_direct(
    endpoint: str = "hold", symbol: str = "基金持仓", date: str = "", **kwargs
) -> pd.DataFrame:
    """机构持仓汇总 —— 直取东财 datacenter，按字段名映射列（修复列错位）。

    仅支持 endpoint="hold"；其余 endpoint 抛 ValueError，交由 SmartRouter
    降级到 akshare 源（后者负责 detail）。

    Args:
        endpoint: 仅 "hold"
        symbol: {"基金持仓","QFII持仓","社保持仓","券商持仓","保险持仓","信托持仓"}
        date: 财报日期 "YYYYMMDD"，默认上一季度末

    Returns:
        DataFrame，列沿用 akshare 原有命名以保证下游不被打断：
        序号 / 股票代码 / 股票简称 / 持有基金家数 / 持股总数 / 持股市值 /
        持股变化 / 持股变动数值 / 持股变动比例，并追加 持股占流通股比。
        其中「持股变化」为方向文本（增仓/减仓），「持股变动数值」为股数，
        「持股变动比例」为百分比。
    """
    if endpoint != "hold":
        raise ValueError(
            f"fetch_fund_hold_direct 仅支持 endpoint='hold'，收到 {endpoint!r}"
            "（detail 请走 akshare 源）"
        )
    t = str(symbol or "基金持仓").strip()
    if t not in _FUND_HOLD_SYMBOL_MAP:
        raise ValueError(
            f"未知机构类型 {symbol!r}（支持: {list(_FUND_HOLD_SYMBOL_MAP)}）"
        )
    if not date:
        date = _prev_quarter_end()
    em_date = (
        f"{date[:4]}-{date[4:6]}-{date[6:]}"
        if (len(date) == 8 and date.isdigit())
        else date
    )

    from .em_client import em_get

    rows: list = []
    page = 1
    total_pages = 1
    while page <= total_pages:
        params = {
            "date": em_date,
            "type": _FUND_HOLD_SYMBOL_MAP[t],
            "zjc": "0",
            "sortField": "HOULD_NUM",
            "sortDirec": "1",
            "pageNum": str(page),
            "pageSize": "500",
            "p": str(page),
            "pageNo": str(page),
        }
        resp = em_get(_EM_ZLSJ_URL, params=params, timeout=25)
        payload = resp.json()
        if not payload or not payload.get("data"):
            break
        rows.extend(payload["data"])
        try:
            total_pages = int(payload.get("pages") or 1)
        except (TypeError, ValueError):
            total_pages = 1
        page += 1
        if page > 60:  # 安全阀：最多 60 页（3 万条），防上游 pages 异常导致死循环
            logger.warning("fetch_fund_hold_direct(%s): 分页超过 60 页，提前截断", t)
            break

    if not rows:
        raise RuntimeError(f"东财机构持仓({t}, {date}) 返回空数据")

    out = pd.DataFrame(
        [{cn: r.get(en) for en, cn in _FUND_HOLD_FIELDS} for r in rows]
    )
    out.insert(0, "序号", range(1, len(out) + 1))
    for c in _FUND_HOLD_NUM_COLS:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    # 护栏：列错位会立刻暴露 —— 股票代码必须是 6 位数字，否则宁可失败也不给错标数据
    codes = out["股票代码"].astype(str).str.strip()
    if not codes.str.fullmatch(r"\d{6}").all():
        bad = codes[~codes.str.fullmatch(r"\d{6}")].head(3).tolist()
        raise RuntimeError(
            f"东财机构持仓({t}) 股票代码列异常（疑似上游字段再变）：{bad}"
        )
    return out


def fetch_dt_detail_em(
    *, start_date: str | None = None, end_date: str | None = None, **kwargs,
) -> list[dict]:
    """龙虎榜上榜个股详情 —— akshare stock_lhb_detail_em 包装。

    字段对齐主源 em_datacenter.fetch_dragon_tiger_detail：
      code/name/date/close/change_pct/net_buy/buy_amt/sell_amt/deal_amt/
      net_buy_ratio/deal_amount_ratio/turnover_rate/float_market_value/
      reason/after_1d/after_2d/after_5d/after_10d
    """
    ak = _ak()
    s, e = _ak_date_range_kwargs(start_date, end_date, default_days=5)
    df = ak.stock_lhb_detail_em(start_date=s, end_date=e)
    if df is None or df.empty:
        raise RuntimeError(f"AKShare stock_lhb_detail_em 返回空（{s}~{e}）")
    result: list[dict] = []
    for _, row in df.iterrows():
        result.append({
            "code": str(row.get("代码", "")),
            "name": str(row.get("名称", "")),
            "date": str(row.get("上榜日", "")),
            "close": float(row.get("收盘价", 0) or 0),
            "change_pct": float(row.get("涨跌幅", 0) or 0),
            "net_buy": float(row.get("龙虎榜净买额", 0) or 0),
            "buy_amt": float(row.get("龙虎榜买入额", 0) or 0),
            "sell_amt": float(row.get("龙虎榜卖出额", 0) or 0),
            "deal_amt": float(row.get("龙虎榜成交额", 0) or 0),
            "total_amount": float(row.get("市场总成交额", 0) or 0),
            "net_buy_ratio": float(row.get("净买额占总成交比", 0) or 0),
            "deal_amount_ratio": float(row.get("成交额占总成交比", 0) or 0),
            "turnover_rate": float(row.get("换手率", 0) or 0),
            "float_market_value": float(row.get("流通市值", 0) or 0),
            "reason": str(row.get("上榜原因", "")),
            "after_1d": float(row.get("上榜后1日", 0) or 0) if pd.notna(row.get("上榜后1日")) else 0.0,
            "after_2d": float(row.get("上榜后2日", 0) or 0) if pd.notna(row.get("上榜后2日")) else 0.0,
            "after_5d": float(row.get("上榜后5日", 0) or 0) if pd.notna(row.get("上榜后5日")) else 0.0,
            "after_10d": float(row.get("上榜后10日", 0) or 0) if pd.notna(row.get("上榜后10日")) else 0.0,
            "source": "AKShare_stock_lhb_detail_em",
        })
    return result


def fetch_dt_institution_em(
    *, start_date: str | None = None, end_date: str | None = None, **kwargs,
) -> list[dict]:
    """龙虎榜机构买卖统计 —— akshare stock_lhb_jgmmtj_em 包装。

    字段对齐主源 em_datacenter.fetch_dragon_tiger_institution。
    """
    ak = _ak()
    s, e = _ak_date_range_kwargs(start_date, end_date, default_days=30)
    df = ak.stock_lhb_jgmmtj_em(start_date=s, end_date=e)
    if df is None or df.empty:
        raise RuntimeError(f"AKShare stock_lhb_jgmmtj_em 返回空（{s}~{e}）")
    result: list[dict] = []
    for _, row in df.iterrows():
        result.append({
            "code": str(row.get("代码", "")),
            "name": str(row.get("名称", "")),
            "date": str(row.get("上榜日期", "")),
            "close": float(row.get("收盘价", 0) or 0),
            "change_pct": float(row.get("涨跌幅", 0) or 0),
            "buy_org_count": int(row.get("买方机构数", 0) or 0),
            "sell_org_count": int(row.get("卖方机构数", 0) or 0),
            "org_buy_amt": float(row.get("机构买入总额", 0) or 0),
            "org_sell_amt": float(row.get("机构卖出总额", 0) or 0),
            "org_net_amt": float(row.get("机构买入净额", 0) or 0),
            "source": "AKShare_stock_lhb_jgmmtj_em",
        })
    return result


def fetch_dt_stock_stats_em(*, period: str = "1month", **kwargs) -> list[dict]:
    """龙虎榜个股上榜统计（机构席位追踪） —— akshare stock_lhb_jgstatistic_em 包装。

    与主源 dt_stock_stats 字段一致（个股视角，按周期聚合）。
    akshare symbol 参数：'近一月'/'近三月'/'近六月'/'近一年'。
    """
    ak = _ak()
    period_map = {
        "1month": "近一月", "3month": "近三月",
        "6month": "近六月", "1year": "近一年",
    }
    sym = period_map.get(period)
    if not sym:
        raise ValueError(f"period 必须是 {list(period_map.keys())} 之一，实际 {period}")
    df = ak.stock_lhb_jgstatistic_em(symbol=sym)
    if df is None or df.empty:
        raise RuntimeError(f"AKShare stock_lhb_jgstatistic_em 返回空（{sym}）")
    result: list[dict] = []
    for _, row in df.iterrows():
        result.append({
            "code": str(row.get("代码", "")),
            "name": str(row.get("名称", "")),
            "close": float(row.get("收盘价", 0) or 0),
            "change_pct": float(row.get("涨跌幅", 0) or 0),
            "appearances": int(row.get("上榜次数", 0) or 0),
            "total_buy": float(row.get("机构买入额", 0) or 0),
            "total_sell": float(row.get("机构卖出额", 0) or 0),
            "total_net": float(row.get("机构净买额", 0) or 0),
            "buy_org_count": int(row.get("机构买入次数", 0) or 0),
            "sell_org_count": int(row.get("机构卖出次数", 0) or 0),
            "deal_amt": float(row.get("龙虎榜成交金额", 0) or 0),
            "source": "AKShare_stock_lhb_jgstatistic_em",
        })
    return result


def fetch_dt_branch_rank_em(*, period: str = "1month", **kwargs) -> list[dict]:
    """龙虎榜营业部排行 —— akshare stock_lhb_yybph_em 包装。

    主源 em_datacenter 没有对应 report（之前手写删除），akshare 是这个维度的
    **唯一可用源**，注册为 priority=1 主源（而非备源）。
    """
    ak = _ak()
    period_map = {
        "1month": "近一月", "3month": "近三月",
        "6month": "近六月", "1year": "近一年",
    }
    sym = period_map.get(period)
    if not sym:
        raise ValueError(f"period 必须是 {list(period_map.keys())} 之一，实际 {period}")
    df = ak.stock_lhb_yybph_em(symbol=sym)
    if df is None or df.empty:
        raise RuntimeError(f"AKShare stock_lhb_yybph_em 返回空（{sym}）")
    result: list[dict] = []
    for _, row in df.iterrows():
        result.append({
            "branch_name": str(row.get("营业部名称", "")),
            "buy_count_1d": int(row.get("上榜后1天-买入次数", 0) or 0),
            "avg_change_1d": float(row.get("上榜后1天-平均涨幅", 0) or 0),
            "win_rate_1d": float(row.get("上榜后1天-上涨概率", 0) or 0),
            "buy_count_2d": int(row.get("上榜后2天-买入次数", 0) or 0),
            "avg_change_2d": float(row.get("上榜后2天-平均涨幅", 0) or 0),
            "win_rate_2d": float(row.get("上榜后2天-上涨概率", 0) or 0),
            "buy_count_3d": int(row.get("上榜后3天-买入次数", 0) or 0),
            "avg_change_3d": float(row.get("上榜后3天-平均涨幅", 0) or 0),
            "win_rate_3d": float(row.get("上榜后3天-上涨概率", 0) or 0),
            "buy_count_5d": int(row.get("上榜后5天-买入次数", 0) or 0),
            "avg_change_5d": float(row.get("上榜后5天-平均涨幅", 0) or 0),
            "win_rate_5d": float(row.get("上榜后5天-上涨概率", 0) or 0),
            "buy_count_10d": int(row.get("上榜后10天-买入次数", 0) or 0),
            "avg_change_10d": float(row.get("上榜后10天-平均涨幅", 0) or 0),
            "win_rate_10d": float(row.get("上榜后10天-上涨概率", 0) or 0),
            "source": "AKShare_stock_lhb_yybph_em",
        })
    return result


def fetch_margin_account_info_em(**kwargs) -> list[dict]:
    """两融账户统计 —— akshare stock_margin_account_info 包装。

    字段对齐主源 em_datacenter.fetch_margin_account_info。
    akshare 无日期过滤参数（一次拉全市场全历史，按日期倒序），按需返回近 N 日。
    """
    ak = _ak()
    df = ak.stock_margin_account_info()
    if df is None or df.empty:
        raise RuntimeError("AKShare stock_margin_account_info 返回空")
    # 按日期倒序排列后取最近 500 日（主源 page_size=500 对齐）
    df = df.sort_values(by="日期", ascending=False).head(500)
    result: list[dict] = []
    for _, row in df.iterrows():
        result.append({
            "date": str(row.get("日期", "")),
            "fin_balance": float(row.get("融资余额", 0) or 0) if pd.notna(row.get("融资余额")) else 0.0,
            "loan_balance": float(row.get("融券余额", 0) or 0) if pd.notna(row.get("融券余额")) else 0.0,
            "fin_buy_amt": float(row.get("融资买入额", 0) or 0) if pd.notna(row.get("融资买入额")) else 0.0,
            "loan_sell_amt": float(row.get("融券卖出额", 0) or 0) if pd.notna(row.get("融券卖出额")) else 0.0,
            "investor_count": int(row.get("参与交易的投资者数量", 0) or 0) if pd.notna(row.get("参与交易的投资者数量")) else 0,
            "liability_investor_count": int(row.get("有融资融券负债的投资者数量", 0) or 0) if pd.notna(row.get("有融资融券负债的投资者数量")) else 0,
            "broker_count": int(row.get("证券公司数量", 0) or 0) if pd.notna(row.get("证券公司数量")) else 0,
            "branch_count": int(row.get("营业部数量", 0) or 0) if pd.notna(row.get("营业部数量")) else 0,
            "total_guarantee": float(row.get("担保物总价值", 0) or 0) if pd.notna(row.get("担保物总价值")) else 0.0,
            "avg_guarantee_ratio": float(row.get("平均维持担保比例", 0) or 0) if pd.notna(row.get("平均维持担保比例")) else 0.0,
            "source": "AKShare_stock_margin_account_info",
        })
    return result


def fetch_block_trade_market_stat_em(**kwargs) -> list[dict]:
    """大宗交易市场统计 —— akshare stock_dzjy_sctj 包装。

    字段对齐主源 em_datacenter.fetch_block_trade_market_stat。
    akshare 无参数（一次拉全历史，按日期倒序），取最近 500 日对齐主源。
    """
    ak = _ak()
    df = ak.stock_dzjy_sctj()
    if df is None or df.empty:
        raise RuntimeError("AKShare stock_dzjy_sctj 返回空")
    df = df.sort_values(by="交易日期", ascending=False).head(500)
    result: list[dict] = []
    for _, row in df.iterrows():
        result.append({
            "date": str(row.get("交易日期", "")),
            "sz_index": float(row.get("上证指数", 0) or 0),
            "sz_change_pct": float(row.get("上证指数涨跌幅", 0) or 0),
            "total_amount": float(row.get("大宗交易成交总额", 0) or 0),
            "premium_amount": float(row.get("溢价成交总额", 0) or 0),
            "premium_ratio": float(row.get("溢价成交总额占比", 0) or 0),
            "discount_amount": float(row.get("折价成交总额", 0) or 0),
            "discount_ratio": float(row.get("折价成交总额占比", 0) or 0),
            "source": "AKShare_stock_dzjy_sctj",
        })
    return result


def fetch_block_trade_detail_em(
    *, start_date: str | None = None, end_date: str | None = None, **kwargs,
) -> list[dict]:
    """大宗交易明细 —— akshare stock_dzjy_mrmx 包装。

    字段对齐主源 em_datacenter.fetch_block_trade_detail。
    """
    ak = _ak()
    s, e = _ak_date_range_kwargs(start_date, end_date, default_days=5)
    df = ak.stock_dzjy_mrmx(start_date=s, end_date=e)
    if df is None or df.empty:
        raise RuntimeError(f"AKShare stock_dzjy_mrmx 返回空（{s}~{e}）")
    result: list[dict] = []
    for _, row in df.iterrows():
        result.append({
            "code": str(row.get("证券代码", "")),
            "name": str(row.get("证券简称", "")),
            "date": str(row.get("交易日期", "")),
            "deal_price": float(row.get("成交价", 0) or 0),
            "deal_volume": float(row.get("成交量", 0) or 0),
            "deal_amount": float(row.get("成交额", 0) or 0),
            "buy_branch": str(row.get("买方营业部", "")),
            "sell_branch": str(row.get("卖方营业部", "")),
            "source": "AKShare_stock_dzjy_mrmx",
        })
    return result


def fetch_block_trade_daily_stat_em(
    *, start_date: str | None = None, end_date: str | None = None, **kwargs,
) -> list[dict]:
    """大宗交易每日统计 —— akshare stock_dzjy_mrtj 包装。

    字段对齐主源 em_datacenter.fetch_block_trade_daily_stat。
    """
    ak = _ak()
    s, e = _ak_date_range_kwargs(start_date, end_date, default_days=5)
    df = ak.stock_dzjy_mrtj(start_date=s, end_date=e)
    if df is None or df.empty:
        raise RuntimeError(f"AKShare stock_dzjy_mrtj 返回空（{s}~{e}）")
    result: list[dict] = []
    for _, row in df.iterrows():
        result.append({
            "code": str(row.get("证券代码", "")),
            "name": str(row.get("证券简称", "")),
            "date": str(row.get("交易日期", "")),
            "close": float(row.get("收盘价", 0) or 0),
            "change_pct": float(row.get("涨跌幅", 0) or 0),
            "deal_price": float(row.get("成交价", 0) or 0),
            "premium_rate": float(row.get("折溢率", 0) or 0),
            "deal_count": int(row.get("成交笔数", 0) or 0),
            "deal_total_volume": float(row.get("成交总量", 0) or 0),
            "deal_total_amount": float(row.get("成交总额", 0) or 0),
            "deal_amount_ratio": float(row.get("成交总额/流通市值", 0) or 0),
            "source": "AKShare_stock_dzjy_mrtj",
        })
    return result


def fetch_bigcaps_em(min_mktcap_yi: float = 500, **kwargs) -> dict:
    """大市值名单（东财全市场快照备源）。"""
    ak = _ak()
    df = ak.stock_zh_a_spot_em()
    if df is None or df.empty:
        raise RuntimeError("东财全市场快照返回空（stock_zh_a_spot_em）")
    missing_cols = {"代码", "名称", "总市值"} - set(df.columns)
    if missing_cols:
        raise RuntimeError(f"东财全市场快照缺列 {sorted(missing_cols)}（字段可能漂移）")

    threshold = float(min_mktcap_yi or 0) * 1e8
    stocks: list[dict] = []
    unpriced: list[dict] = []
    for _, row in df.iterrows():
        code = str(row.get("代码") or "").strip()
        if not code:
            continue
        name = str(row.get("名称") or "").strip()
        total_mv = row.get("总市值")
        try:
            total_mv_f = float(total_mv)
        except (TypeError, ValueError):
            total_mv_f = 0.0
        if total_mv_f <= 0 or pd.isna(total_mv_f):
            unpriced.append({"code": code, "name": name, "reason": "total_mv_missing"})
            continue
        if total_mv_f < threshold:
            continue
        price = float(row.get("最新价") or 0)
        stocks.append({
            "code": code,
            "name": name,
            "market_cap_yi": round(total_mv_f / 1e8, 2),
            "float_cap_yi": (
                round(float(row.get("流通市值")) / 1e8, 2)
                if row.get("流通市值") not in (None, "") and not pd.isna(row.get("流通市值"))
                else None
            ),
            "price": price if price > 0 else None,
            "change_pct": float(row.get("涨跌幅") or 0),
            "amount_yi": round(float(row.get("成交额") or 0) / 1e8, 4),
            "turnover_pct": float(row.get("换手率") or 0),
            "suspended": price <= 0,
            **({"reason": "suspended"} if price <= 0 else {}),
        })
    stocks.sort(key=lambda item: (-item["market_cap_yi"], item["code"]))
    return {
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "akshare_em",
        "source_url": "akshare.stock_zh_a_spot_em",
        "threshold_yi": float(min_mktcap_yi or 0),
        "count": len(stocks),
        "stocks": stocks,
        "unpriced": unpriced,
        "source_note": (
            "东财全市场快照（stock_zh_a_spot_em）按总市值过滤；"
            "总市值原始单位元，已换算亿元；与新浪源口径一致"
        ),
    }


def fetch_global_index_spot(**kwargs) -> pd.DataFrame:
    """东财全球指数实时快照（ak.index_global_spot_em）。

    一次返回 56 个全球指数（韩国KOSPI=KS11、KOSPI200、恒生、恒生科技、日经、
    纳指、道指等），含 最新价/涨跌额/涨跌幅/开高低/昨收/振幅/最新行情时间；
    **无成交额字段**（东财全球指数不提供）。

    用途：TradeX 指数关注池海外指数行情（gi 前缀代码，如 giKS11 韩国KOSPI）。

    频控（QI-STD-95 契约代码化）：底层为 push2 clist 端点，一次取全表即可覆盖
    全部全球指数——模块级最小间隔 60s 节流（间隔不足自动补眠），调用方仍建议
    叠加 ≥60s 级缓存；勿做秒级轮询（push2 对高频有 IP 风控）。
    """
    global _last_global_index_call
    now = time.monotonic()
    wait = _GLOBAL_INDEX_MIN_INTERVAL - (now - _last_global_index_call)
    if wait > 0:
        time.sleep(wait)
    _last_global_index_call = time.monotonic()
    df = _ak().index_global_spot_em()
    # 空态：None → 空 DataFrame（诚实空态，AGENTS.md rule 5 书面豁免口径——
    # 本 fetcher 未注册 SmartRouter、TradeX 直连消费；注册前必须过空态语义检查）
    return df if df is not None else pd.DataFrame()
