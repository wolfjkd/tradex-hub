"""东财统一请求客户端 —— 限流防封 + slist 板块归属。

借鉴 a-stock-data 的 em_get 防封机制：
  - 串行限流：最小间隔 ≥1s + 随机抖动（东财风控：>5次/秒触发封禁）
  - 会话复用 + 默认浏览器 UA + Referer
  - 所有 eastmoney.com 接口都应走 em_get，避免高频被封 IP。

东财风控阈值（社区实测）：
  - 每秒 >5 次 / 并发 ≥10 / 5分钟 ≥300 次 → 触发封禁
"""
from __future__ import annotations

import random
import re
import threading
import time

import pandas as pd
from curl_cffi import requests as _rq

logger = __import__("logging").getLogger("tradex.em")

# 东财风控：最小请求间隔（秒）
EM_MIN_INTERVAL = 1.0

# v3.3.9+：限流时间戳加锁保护——多线程同时穿透间隔会导致并发请求数超风控阈值封 IP。
_em_last_call = [0.0]
_em_throttle_lock = threading.Lock()
_EM_SESSION = _rq.Session()

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36")
_REFERER = "https://quote.eastmoney.com/"


def em_get(url: str, params: dict | None = None, headers: dict | None = None,
           timeout: int = 15, **kwargs):
    """东财统一请求入口：自动节流 + 复用 session + 默认 UA。

    节流检查与时间戳更新在同一把锁内完成（含 sleep），
    保证任意时刻只有一个请求在"检查-等待-发出"临界区，
    多线程并发调用时严格维持 ≥EM_MIN_INTERVAL 的实际间隔。
    """
    with _em_throttle_lock:
        wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
        if wait > 0:
            time.sleep(wait + random.uniform(0.1, 0.5))
        h = {"User-Agent": _UA, "Referer": _REFERER}
        if headers:
            h.update(headers)
        try:
            resp = _EM_SESSION.get(url, params=params, headers=h, timeout=timeout,
                                   impersonate="chrome120", **kwargs)
        finally:
            _em_last_call[0] = time.time()
    return resp


def fetch_stock_boards(code: str, **kwargs) -> pd.DataFrame:
    """个股所属板块/概念归属（东财 slist，一次请求拿全行业/概念/地域 + 龙头股）。

    Returns:
        DataFrame columns: 板块名称 / 板块代码(BK) / 涨跌幅 / 领涨股票
    """
    code = str(code).split(".")[0].split("_")[0]  # 归一纯 6 位
    market_code = 1 if code.startswith("6") else 0
    params = {
        "fltt": "2", "invt": "2",
        "secid": f"{market_code}.{code}",
        "spt": "3", "pi": "0", "pz": "200", "po": "1",
        "fields": "f12,f14,f3,f128",
    }
    r = em_get("https://push2.eastmoney.com/api/qt/slist/get", params=params, timeout=15)
    r.raise_for_status()
    diff = (r.json().get("data") or {}).get("diff") or {}
    items = diff.values() if isinstance(diff, dict) else diff
    rows = []
    for it in items:
        rows.append({
            "板块名称": it.get("f14", ""),
            "板块代码": it.get("f12", ""),
            "涨跌幅": it.get("f3", ""),
            "领涨股票": it.get("f128", ""),
        })
    return pd.DataFrame(rows)


# ============================================================
# 公共辅助函数（datacenter 字段映射通用工具）
# ============================================================

def _to_float(v) -> float | None:
    """datacenter 数值字段安全转 float（None/空字符串/无效值都返回 None）。"""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_int(v) -> int | None:
    """datacenter 数值字段安全转 int（按 float 转后再 int，避免字符串小数报错）。"""
    f = _to_float(v)
    return int(f) if f is not None else None


def _normalize_date(d) -> str:
    """日期归一化：YYYYMMDD / YYYY/MM/DD / YYYY-MM-DD[T ]HH:MM:SS → YYYY-MM-DD。

    无法识别的原样返回（调用方按需处理）。
    """
    if not d:
        return ""
    s = str(d).strip()
    if "/" in s:
        s = s.replace("/", "-")
    # 兼容完整日期时间："2026-09-25T00:00:00" / "2026-09-25 00:00:00"
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", s)
    if m:
        return m.group(1)
    # YYYYMMDD
    if re.match(r"^\d{8}$", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s


def _to_iso_date(d) -> str:
    """alias for _normalize_date（保持与 stock-sdk 同名函数一致的语义）。"""
    return _normalize_date(d)


def _build_date_range_filter(
    start_date: str | None, end_date: str | None,
    field: str = "TRADE_DATE",
) -> str:
    """构造 (FIELD>='YYYY-MM-DD')(FIELD<='YYYY-MM-DD') 过滤表达式。"""
    parts: list[str] = []
    if start_date:
        parts.append(f"({field}>='{_normalize_date(start_date)}')")
    if end_date:
        parts.append(f"({field}<='{_normalize_date(end_date)}')")
    return "".join(parts)


# ============================================================
# datacenter-web 通用请求器（P999 降级源，2026-09-23 老板批准可用）
# ============================================================
# 上游：https://datacenter-web.eastmoney.com/api/data/v1/get
# 借鉴 chengzuopeng/stock-sdk 的 fetchDatacenterList 设计（ISC license，
# attribution: 此处 datacenter 分页拉取逻辑参考其 src/providers/eastmoney/datacenter.ts）
# 关键点：
#   - 首页串行探明总页数，其余页按需翻页（这里简化为串行，避免触发风控）
#   - 所有东财请求统一走 em_get 限流器（≥1s 间隔 + 抖动）
#   - 服务端返回 result=null 或 result.data 非数组时按空数据处理

_EM_DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"


def fetch_datacenter_list(
    report_name: str,
    *,
    columns: str = "ALL",
    filter_expr: str | None = None,
    sort_columns: str | None = None,
    sort_types: str | None = None,
    page_size: int = 500,
    max_pages: int = 1000,
    extra_params: dict | None = None,
) -> list[dict]:
    """东财 datacenter-web 通用分页拉取。

    Args:
        report_name: 报表名，如 'RPT_WATCH_UNUSUAL_FLUCTUATE'
        columns: 返回字段，默认 'ALL'
        filter_expr: 过滤表达式（不带括号），如 "(TRADE_DATE='2026-09-25')"
        sort_columns: 排序字段，多个逗号分隔
        sort_types: 排序方向，'-1' 降序 / '1' 升序，多个逗号分隔
        page_size: 每页大小，默认 500
        max_pages: 最大拉取页数（安全阀，避免坏数据导致死循环）
        extra_params: 额外的查询参数

    Returns:
        list[dict]: 所有页合并后的原始记录列表（每条是 datacenter 返回的 dict）

    Raises:
        RuntimeError: 上游返回非 2xx 或 JSON 解析失败
    """
    all_data: list[dict] = []
    total_pages = 1

    for page in range(1, max_pages + 1):
        params = {
            "reportName": report_name,
            "columns": columns,
            "pageSize": str(page_size),
            "pageNumber": str(page),
            "source": "WEB",
            "client": "WEB",
        }
        if filter_expr:
            params["filter"] = filter_expr
        if sort_columns:
            params["sortColumns"] = sort_columns
        if sort_types:
            params["sortTypes"] = sort_types
        if extra_params:
            params.update(extra_params)

        resp = em_get(_EM_DATACENTER_URL, params=params, timeout=20)
        resp.raise_for_status()
        try:
            payload = resp.json()
        except Exception as e:
            raise RuntimeError(
                f"em_datacenter({report_name}) page={page} JSON 解析失败: {e}"
            ) from e

        result = (payload or {}).get("result")
        if not result or not isinstance(result.get("data"), list):
            # 首页就空：返回空；后续页空：正常终止
            break

        all_data.extend(result["data"])
        if page == 1:
            total_pages = int(result.get("pages") or 1)

        # 坏页安全阀
        if len(result["data"]) < page_size:
            break
        if page >= total_pages:
            break

    if len(all_data) == 0 and page == 1 and total_pages == 1:
        # 真正的零数据，不警告；但要区分"首页就异常返回空"
        pass
    elif page >= max_pages and total_pages > max_pages:
        logger.warning(
            "em_datacenter(%s) 在 max_pages=%d 处截断（服务端报告共 %d 页）",
            report_name, max_pages, total_pages,
        )

    return all_data


# ============================================================
# 监管异动（交易所股票交易异常波动预警）
# ============================================================
# 借鉴 chengzuopeng/stock-sdk 的 getUnusualFluctuation（ISC license，
# attribution: 字段语义参考 src/providers/eastmoney/topicData.ts）
# 数据源：RPT_WATCH_UNUSUAL_FLUCTUATE 报表（datacenter-web 子域，老板批准 P999）
#
# 业务含义：
#   - 交易所对连续涨跌偏离值达阈值（深中华A 100/100 达规则阈值）的个股
#     发布「股票交易异常波动」监管预警
#   - IS_HAPPEN=1 时偏离值正好达规则阈值（已触发公告）
#   - IS_HAPPEN=0 时逼近未达（即将触发，提前预警）
#   - IS_POSITIVE=1 为正向（上涨偏离），0 为负向（下跌偏离）
#   - 实测约 4038 条历史数据，自带约两个月滚动窗口

_EM_DATACENTER_UNUSUAL_DEFAULT_PAGE_SIZE = 500


def fetch_unusual_fluctuation(
    *,
    trade_date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    triggered: bool | None = None,
    **kwargs,
) -> list[dict]:
    """交易所股票交易异常波动预警（监管异动）。

    Args:
        trade_date: 单日过滤，YYYY-MM-DD 或 YYYYMMDD。与 start_date/end_date 互斥。
        start_date: 区间起始（含），与 trade_date 互斥。
        end_date: 区间结束（含），与 trade_date 互斥。
        triggered: True 仅返回已触发（IS_HAPPEN=1）；False 仅返回逼近未达（IS_HAPPEN=0）；
                   None 不加过滤。
        **kwargs: 透传给 fetch_datacenter_list（如 max_pages）

    Returns:
        list[dict]，每条字段：
          - code: 证券代码
          - name: 证券简称
          - date: 交易日期 (YYYY-MM-DD)
          - rule: 触发规则（中文原文）
          - triggered: True=已触发公告，False=逼近未达
          - deviation_value: 偏离值（DEVUATION_VALUE，规则阈值通常为 100）
          - window_days: 观察窗口天数（MAX_DAYS）
          - change_pct: 区间累计涨跌幅（CHANGE_RATE）
          - direction: 'up' 上涨偏离 / 'down' 下跌偏离
          - target_change_pct: 目标涨跌幅（CHANGE_RATE_TARGET，语义未完全确认，按上游原值透传）
          - source: 固定 'EM_Datacenter_RPT_WATCH_UNUSUAL_FLUCTUATE'

    Raises:
        ValueError: trade_date 与 start_date/end_date 同时指定
        RuntimeError: 上游请求失败
    """
    if trade_date and (start_date or end_date):
        raise ValueError(
            "fetch_unusual_fluctuation: trade_date 与 start_date/end_date 不能同时指定"
        )

    def _normalize_date_local(d: str) -> str:
        # 保留兼容签名（与本次新增的模块级 _normalize_date 行为一致）
        return _normalize_date(d)

    clauses: list[str] = []
    if trade_date:
        clauses.append(f"(TRADE_DATE='{_normalize_date_local(trade_date)}')")
    else:
        if start_date:
            clauses.append(f"(TRADE_DATE>='{_normalize_date_local(start_date)}')")
        if end_date:
            clauses.append(f"(TRADE_DATE<='{_normalize_date_local(end_date)}')")
    if triggered is not None:
        clauses.append(f'(IS_HAPPEN="{1 if triggered else 0}")')

    rows = fetch_datacenter_list(
        "RPT_WATCH_UNUSUAL_FLUCTUATE",
        columns="ALL",
        sort_columns="TRADE_DATE,SECURITY_CODE",
        sort_types="-1,1",
        page_size=_EM_DATACENTER_UNUSUAL_DEFAULT_PAGE_SIZE,
        filter_expr="".join(clauses) if clauses else None,
        **kwargs,
    )

    result: list[dict] = []
    for item in rows:
        date_str = _normalize_date(item.get("TRADE_DATE") or "")

        result.append({
            "code": str(item.get("SECURITY_CODE") or ""),
            "name": str(item.get("SECURITY_NAME_ABBR") or ""),
            "date": date_str,
            "rule": str(item.get("UNUSUAL_TYPE") or ""),
            "triggered": str(item.get("IS_HAPPEN") or "") == "1",
            "deviation_value": _to_float(item.get("DEVUATION_VALUE")),
            "window_days": _to_float(item.get("MAX_DAYS")),
            "change_pct": _to_float(item.get("CHANGE_RATE")),
            "direction": "up" if str(item.get("IS_POSITIVE") or "") == "1" else "down",
            "target_change_pct": _to_float(item.get("CHANGE_RATE_TARGET")),
            "source": "EM_Datacenter_RPT_WATCH_UNUSUAL_FLUCTUATE",
        })
    return result


# ============================================================
# 龙虎榜扩展族（借鉴 stock-sdk dragonTiger.ts，ISC license）
# ============================================================
# 全部走 datacenter-web 子域，老板批准的 P999 降级源
#
# tradex-hub 现有龙虎榜能力（akshare/exchange_official）覆盖：
#   - 单股上榜记录、沪市官方龙虎榜、深市官方龙虎榜
# 本次借鉴补全的 5 个新维度：
#   - 龙虎榜详情（含 D1/D2/D5/D10 上榜后股价表现跟踪）
#   - 个股上榜次数统计（按 1/3/6/12 月聚合）
#   - 机构买卖统计（机构席位层面）
#   - 营业部排行（全市场热门营业部）
#   - 个股席位明细（单股某日买卖营业部）

_DT_PERIOD_MAP = {"1month": "01", "3month": "02", "6month": "03", "1year": "04"}


def fetch_dragon_tiger_detail(
    *, start_date: str, end_date: str, **kwargs,
) -> list[dict]:
    """龙虎榜上榜个股详情（含 D1/D2/D5/D10 上榜后涨跌幅跟踪）。

    Args:
        start_date: 起始日期（含），YYYY-MM-DD / YYYYMMDD
        end_date: 结束日期（含），YYYY-MM-DD / YYYYMMDD
        **kwargs: 透传 fetch_datacenter_list

    Returns:
        list[dict]，每条字段：
          code/name/date/close/change_pct/net_buy/buy_amt/sell_amt/deal_amt/
          net_buy_ratio/deal_amount_ratio/turnover_rate/float_market_value/
          reason/after_1d/after_2d/after_5d/after_10d
    """
    rows = fetch_datacenter_list(
        "RPT_DAILYBILLBOARD_DETAILSNEW",
        columns="ALL",
        sort_columns="SECURITY_CODE,TRADE_DATE",
        sort_types="1,-1",
        page_size=5000,
        filter_expr=_build_date_range_filter(start_date, end_date),
        **kwargs,
    )
    return [
        {
            "code": str(item.get("SECURITY_CODE") or ""),
            "name": str(item.get("SECURITY_NAME_ABBR") or ""),
            "date": _normalize_date(item.get("TRADE_DATE")),
            "close": _to_float(item.get("CLOSE_PRICE")),
            "change_pct": _to_float(item.get("CHANGE_RATE")),
            "net_buy": _to_float(item.get("BILLBOARD_NET_AMT")),
            "buy_amt": _to_float(item.get("BILLBOARD_BUY_AMT")),
            "sell_amt": _to_float(item.get("BILLBOARD_SELL_AMT")),
            "deal_amt": _to_float(item.get("BILLBOARD_DEAL_AMT")),
            "total_amount": _to_float(item.get("ACCUM_AMOUNT")),
            "net_buy_ratio": _to_float(item.get("DEAL_NET_RATIO")),
            "deal_amount_ratio": _to_float(item.get("DEAL_AMOUNT_RATIO")),
            "turnover_rate": _to_float(item.get("TURNOVERRATE")),
            "float_market_value": _to_float(item.get("FREE_MARKET_CAP")),
            "reason": str(item.get("EXPLANATION") or item.get("EXPLAIN") or ""),
            "after_1d": _to_float(item.get("D1_CLOSE_ADJCHRATE")),
            "after_2d": _to_float(item.get("D2_CLOSE_ADJCHRATE")),
            "after_5d": _to_float(item.get("D5_CLOSE_ADJCHRATE")),
            "after_10d": _to_float(item.get("D10_CLOSE_ADJCHRATE")),
            "source": "EM_Datacenter_RPT_DAILYBILLBOARD_DETAILSNEW",
        }
        for item in rows
    ]


def fetch_dragon_tiger_stock_stats(*, period: str = "1month", **kwargs) -> list[dict]:
    """龙虎榜个股上榜统计（按周期聚合：上榜次数、累计买卖额等）。

    Args:
        period: '1month' / '3month' / '6month' / '1year'，默认 '1month'
    """
    cycle = _DT_PERIOD_MAP.get(period)
    if not cycle:
        raise ValueError(f"period 必须是 {list(_DT_PERIOD_MAP.keys())} 之一，实际为 {period}")

    rows = fetch_datacenter_list(
        "RPT_BILLBOARD_TRADEALL",
        columns="ALL",
        page_size=5000,
        filter_expr=f'(STATISTICS_CYCLE="{cycle}")',
        **kwargs,
    )
    return [
        {
            "code": str(item.get("SECURITY_CODE") or ""),
            "name": str(item.get("SECURITY_NAME_ABBR") or ""),
            "latest_date": _normalize_date(item.get("LATEST_TDATE")),
            "close": _to_float(item.get("CLOSE_PRICE")),
            "change_pct": _to_float(item.get("CHANGE_RATE")),
            "appearances": _to_int(item.get("BILLBOARD_TIMES")),
            "total_buy": _to_float(item.get("BILLBOARD_BUY_AMT")),
            "total_sell": _to_float(item.get("BILLBOARD_SELL_AMT")),
            "total_net": _to_float(item.get("BILLBOARD_NET_BUY")),
            "total_deal": _to_float(item.get("BILLBOARD_DEAL_AMT")),
            "buy_org_count": _to_int(item.get("ORG_BUY_TIMES")),
            "sell_org_count": _to_int(item.get("ORG_SELL_TIMES")),
            "source": "EM_Datacenter_RPT_BILLBOARD_TRADEALL",
        }
        for item in rows
    ]


def fetch_dragon_tiger_institution(
    *, start_date: str, end_date: str, **kwargs,
) -> list[dict]:
    """龙虎榜机构买卖统计（机构席位层面，按日期范围筛选）。

    与 stock_stats 不同：这里按机构视角聚合，每行是一只个股在某日的机构席位明细。
    """
    rows = fetch_datacenter_list(
        "RPT_ORGANIZATION_TRADE_DETAILS",
        columns="ALL",
        sort_columns="TRADE_DATE,SECURITY_CODE",
        sort_types="-1,1",
        page_size=5000,
        filter_expr=_build_date_range_filter(start_date, end_date),
        **kwargs,
    )
    return [
        {
            "code": str(item.get("SECURITY_CODE") or ""),
            "name": str(item.get("SECURITY_NAME_ABBR") or ""),
            "date": _normalize_date(item.get("TRADE_DATE")),
            "close": _to_float(item.get("CLOSE_PRICE")),
            "change_pct": _to_float(item.get("CHANGE_RATE")),
            "buy_org_count": _to_int(item.get("BUY_TIMES")),
            "sell_org_count": _to_int(item.get("SELL_TIMES")),
            "org_buy_amt": _to_float(item.get("BUY_AMT")),
            "org_sell_amt": _to_float(item.get("SELL_AMT")),
            "org_net_amt": _to_float(item.get("NET_BUY_AMT")),
            "source": "EM_Datacenter_RPT_ORGANIZATION_TRADE_DETAILS",
        }
        for item in rows
    ]


def fetch_dragon_tiger_seat_detail(
    *, symbol: str, date: str, **kwargs,
) -> list[dict]:
    """个股某日龙虎榜席位明细（买入榜 + 卖出榜合并）。

    上游怪癖：RPT_BILLBOARD_DAILYDETAILSBUY/SELL 不接受 (SECURITY_CODE)(TRADE_DATE)
    组合 filter（会返回 0 条），必须只用 SECURITY_CODE 过滤、按 TRADE_DATE 倒序拿最新日。
    2026-09-25 烟雾测试验证此行为后采用此策略。

    Args:
        symbol: 6 位股票代码
        date: 期望的上榜日期（实际只用于校验返回数据日期是否匹配，不强制过滤）
    """
    code = re.sub(r"\D", "", str(symbol))[:6]
    if not code:
        raise ValueError(f"symbol 无法解析为 6 位代码: {symbol}")
    target_date = _normalize_date(date)
    # 只按 SECURITY_CODE 过滤，按 TRADE_DATE 倒序，首页即最新交易日数据
    filter_expr = f'(SECURITY_CODE="{code}")'

    buy_rows = fetch_datacenter_list(
        "RPT_BILLBOARD_DAILYDETAILSBUY",
        columns="ALL",
        sort_columns="TRADE_DATE",
        sort_types="-1",
        page_size=100,
        filter_expr=filter_expr,
        **kwargs,
    )
    sell_rows = fetch_datacenter_list(
        "RPT_BILLBOARD_DAILYDETAILSSELL",
        columns="ALL",
        sort_columns="TRADE_DATE",
        sort_types="-1",
        page_size=100,
        filter_expr=filter_expr,
        **kwargs,
    )
    # 如果上游返回的最新日期与目标 date 不一致，仍然返回（让调用方判断是否过期），
    # 但日志记录差异（避免静默）
    if buy_rows:
        latest = _normalize_date(buy_rows[0].get("TRADE_DATE"))
        if latest != target_date:
            logger.warning(
                "dt_seat_detail(%s) 目标日期 %s 但上游最新数据日期为 %s",
                code, target_date, latest,
            )

    result: list[dict] = []
    for idx, item in enumerate(buy_rows):
        result.append({
            "rank": _to_int(item.get("RANK")) or idx + 1,
            "branch_name": str(item.get("OPERATEDEPT_NAME") or ""),
            "buy_amt": _to_float(item.get("BUY")),
            "sell_amt": _to_float(item.get("SELL")),
            "net_amt": _to_float(item.get("NET")),
            "close": _to_float(item.get("CLOSE_PRICE")),
            "change_pct": _to_float(item.get("CHANGE_RATE")),
            "date": _normalize_date(item.get("TRADE_DATE")),
            "reason": str(item.get("EXPLANATION") or ""),
            "side": "buy",
            "source": "EM_Datacenter_RPT_BILLBOARD_DAILYDETAILSBUY",
        })
    for idx, item in enumerate(sell_rows):
        result.append({
            "rank": _to_int(item.get("RANK")) or idx + 1,
            "branch_name": str(item.get("OPERATEDEPT_NAME") or ""),
            "buy_amt": _to_float(item.get("BUY")),
            "sell_amt": _to_float(item.get("SELL")),
            "net_amt": _to_float(item.get("NET")),
            "close": _to_float(item.get("CLOSE_PRICE")),
            "change_pct": _to_float(item.get("CHANGE_RATE")),
            "date": _normalize_date(item.get("TRADE_DATE")),
            "reason": str(item.get("EXPLANATION") or ""),
            "side": "sell",
            "source": "EM_Datacenter_RPT_BILLBOARD_DAILYDETAILSSELL",
        })
    return result


# ============================================================
# 融资融券族（借鉴 stock-sdk margin.ts，ISC license）
# ============================================================
# 走 datacenter-web 子域，老板批准的 P999 降级源
# tradex-hub 已有交易所官方的两融明细（sse/szse_official），
# 这里补「账户统计 + 标的列表」两个新维度。

def fetch_margin_account_info(**kwargs) -> list[dict]:
    """全市场融资融券账户统计（按日）。

    Returns:
        list[dict]，每条字段：
          date/fin_balance（融资余额）/loan_balance（融券余额）/
          fin_buy_amt/loan_sell_amt/investor_count/...
    """
    rows = fetch_datacenter_list(
        "RPTA_WEB_MARGIN_DAILYTRADE",
        columns="ALL",
        sort_columns="STATISTICS_DATE",
        sort_types="-1",
        page_size=500,
        **kwargs,
    )
    return [
        {
            "date": _normalize_date(item.get("STATISTICS_DATE") or item.get("TRADE_DATE")),
            "fin_balance": _to_float(item.get("FIN_BALANCE")),
            "loan_balance": _to_float(item.get("LOAN_BALANCE")),
            "fin_buy_amt": _to_float(item.get("FIN_BUY_AMT")),
            "loan_sell_amt": _to_float(item.get("LOAN_SELL_AMT")),
            "investor_count": _to_int(item.get("OPERATE_INVESTOR_NUM") or item.get("INVESTOR_NUM")),
            "liability_investor_count": _to_int(item.get("MARGIN_INVESTOR_NUM")),
            "total_guarantee": _to_float(item.get("TOTAL_GUARANTEE")),
            "avg_guarantee_ratio": _to_float(item.get("AVG_GUARANTEE_RATIO")),
            "source": "EM_Datacenter_RPTA_WEB_MARGIN_DAILYTRADE",
        }
        for item in rows
    ]


def fetch_margin_target_list(*, trade_date: str | None = None, **kwargs) -> list[dict]:
    """融资融券个股明细（按日）。

    上游真实字段（datacenter-web RPTA_WEB_RZRQ_GGMX，2026-09-25 烟雾验证）：
      SCODE/SECNAME/DATE/MARKET/RZYE（融资余额）/RQYE（融券余额）/RZRQYE（合计）/RZMRE（融资买入额）/RZCHE（融资偿还额）/RQYL（融券余量）/RQMCL（融券卖出量）/RZJME（融资净额）/RQJMG（融券净额）

    Args:
        trade_date: 交易日 YYYY-MM-DD / YYYYMMDD；不传则取最新
    """
    filter_expr = None
    if trade_date:
        filter_expr = f"(DATE='{_normalize_date(trade_date)}')"

    rows = fetch_datacenter_list(
        "RPTA_WEB_RZRQ_GGMX",
        columns="ALL",
        page_size=5000,
        filter_expr=filter_expr,
        **kwargs,
    )
    return [
        {
            "code": str(item.get("SCODE") or ""),
            "name": str(item.get("SECNAME") or ""),
            "date": _normalize_date(item.get("DATE")),
            "market": str(item.get("MARKET") or ""),
            "fin_balance": _to_float(item.get("RZYE")),
            "fin_buy_amt": _to_float(item.get("RZMRE")),
            "fin_repay_amt": _to_float(item.get("RZCHE")),
            "fin_net_amt": _to_float(item.get("RZJME")),
            "loan_balance": _to_float(item.get("RQYE")),
            "loan_volume": _to_float(item.get("RQYL")),
            "loan_sell_volume": _to_float(item.get("RQMCL")),
            "loan_net_volume": _to_float(item.get("RQJMG")),
            "total_balance": _to_float(item.get("RZRQYE")),
            "source": "EM_Datacenter_RPTA_WEB_RZRQ_GGMX",
        }
        for item in rows
    ]


# ============================================================
# 大宗交易族（借鉴 stock-sdk blockTrade.ts，ISC license）
# ============================================================
# 走 datacenter-web 子域，老板批准的 P999 降级源
# tradex-hub 当前完全没有大宗交易能力，本次补齐 3 个维度。

def fetch_block_trade_market_stat(**kwargs) -> list[dict]:
    """大宗交易市场每日总览（全市场汇总）。

    上游真实字段（datacenter-web PRT_BLOCKTRADE_MARKET_STA，2026-09-25 烟雾验证）：
      TRADE_DATE / SZ_INDEX / SZ_CHANGE_RATE / BLOCKTRADE_DEAL_AMT /
      PREMIUM_DEAL_AMT / PREMIUM_RATIO / DISCOUNT_DEAL_AMT / DISCOUNT_RATIO

    Returns:
        list[dict]，字段：
          date/sz_index/sz_change_pct/total_amount/premium_amount/premium_ratio/
          discount_amount/discount_ratio
    """
    rows = fetch_datacenter_list(
        "PRT_BLOCKTRADE_MARKET_STA",
        columns="ALL",
        sort_columns="TRADE_DATE",
        sort_types="-1",
        page_size=500,
        **kwargs,
    )
    return [
        {
            "date": _normalize_date(item.get("TRADE_DATE")),
            "sz_index": _to_float(item.get("SZ_INDEX")),
            "sz_change_pct": _to_float(item.get("SZ_CHANGE_RATE")),
            "total_amount": _to_float(item.get("BLOCKTRADE_DEAL_AMT")),
            "premium_amount": _to_float(item.get("PREMIUM_DEAL_AMT")),
            "premium_ratio": _to_float(item.get("PREMIUM_RATIO")),
            "discount_amount": _to_float(item.get("DISCOUNT_DEAL_AMT")),
            "discount_ratio": _to_float(item.get("DISCOUNT_RATIO")),
            "source": "EM_Datacenter_PRT_BLOCKTRADE_MARKET_STA",
        }
        for item in rows
    ]


def fetch_block_trade_detail(
    *, start_date: str | None = None, end_date: str | None = None, **kwargs,
) -> list[dict]:
    """大宗交易明细（按日期范围筛选个股大宗交易记录）。

    上游真实字段（datacenter-web RPT_DATA_BLOCKTRADE，2026-09-25 烟雾验证）：
      SECURITY_CODE/SECURITY_NAME_ABBR/TRADE_DATE/CLOSE_PRICE/DEAL_PRICE/PREMIUM_RATIO/
      DEAL_VOLUME/DEAL_AMT/BUYER_NAME/SELLER_NAME/CHANGE_RATE/TURNOVER_RATE
    """
    rows = fetch_datacenter_list(
        "RPT_DATA_BLOCKTRADE",
        columns="ALL",
        page_size=5000,
        filter_expr=_build_date_range_filter(start_date, end_date) or None,
        **kwargs,
    )
    return [
        {
            "code": str(item.get("SECURITY_CODE") or ""),
            "name": str(item.get("SECURITY_NAME_ABBR") or ""),
            "date": _normalize_date(item.get("TRADE_DATE")),
            "close": _to_float(item.get("CLOSE_PRICE")),
            "change_pct": _to_float(item.get("CHANGE_RATE")),
            "deal_price": _to_float(item.get("DEAL_PRICE")),
            "deal_volume": _to_float(item.get("DEAL_VOLUME")),
            "deal_amount": _to_float(item.get("DEAL_AMT")),
            "premium_rate": _to_float(item.get("PREMIUM_RATIO")),
            "turnover_rate": _to_float(item.get("TURNOVER_RATE")),
            "buy_branch": str(item.get("BUYER_NAME") or ""),
            "sell_branch": str(item.get("SELLER_NAME") or ""),
            "source": "EM_Datacenter_RPT_DATA_BLOCKTRADE",
        }
        for item in rows
    ]


def fetch_block_trade_daily_stat(
    *, start_date: str | None = None, end_date: str | None = None, **kwargs,
) -> list[dict]:
    """大宗交易每日统计（按股票汇总成交笔数、总额等）。

    上游真实字段（datacenter-web RPT_BLOCKTRADE_STA，2026-09-25 烟雾验证）：
      SECURITY_CODE/SECURITY_NAME_ABBR/TRADE_DATE/DEAL_NUM/VOLUME/DEAL_AMT/AVERAGE_PRICE/
      CLOSE_PRICE/PREMIUM_RATIO/CHANGE_RATE/D1/D5/D10/D20_CLOSE_ADJCHRATE/PREMIUM_TIMES/DISCOUNT_TIMES
    """
    rows = fetch_datacenter_list(
        "RPT_BLOCKTRADE_STA",
        columns="ALL",
        page_size=5000,
        filter_expr=_build_date_range_filter(start_date, end_date) or None,
        **kwargs,
    )
    return [
        {
            "code": str(item.get("SECURITY_CODE") or ""),
            "name": str(item.get("SECURITY_NAME_ABBR") or ""),
            "date": _normalize_date(item.get("TRADE_DATE")),
            "change_pct": _to_float(item.get("CHANGE_RATE")),
            "close": _to_float(item.get("CLOSE_PRICE")),
            "deal_count": _to_int(item.get("DEAL_NUM")),
            "deal_total_amount": _to_float(item.get("DEAL_AMT")),
            "deal_total_volume": _to_float(item.get("VOLUME")),
            "average_price": _to_float(item.get("AVERAGE_PRICE")),
            "premium_rate": _to_float(item.get("PREMIUM_RATIO")),
            "premium_times": _to_int(item.get("PREMIUM_TIMES")),
            "discount_times": _to_int(item.get("DISCOUNT_TIMES")),
            "after_1d": _to_float(item.get("D1_CLOSE_ADJCHRATE")),
            "after_5d": _to_float(item.get("D5_CLOSE_ADJCHRATE")),
            "after_10d": _to_float(item.get("D10_CLOSE_ADJCHRATE")),
            "after_20d": _to_float(item.get("D20_CLOSE_ADJCHRATE")),
            "source": "EM_Datacenter_RPT_BLOCKTRADE_STA",
        }
        for item in rows
    ]
