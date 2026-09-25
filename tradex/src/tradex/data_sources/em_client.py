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

    def _normalize_date(d: str) -> str:
        d = str(d).strip()
        if "/" in d:
            d = d.replace("/", "-")
        if re.match(r"^\d{8}$", d):
            d = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        return d

    clauses: list[str] = []
    if trade_date:
        clauses.append(f"(TRADE_DATE='{_normalize_date(trade_date)}')")
    else:
        if start_date:
            clauses.append(f"(TRADE_DATE>='{_normalize_date(start_date)}')")
        if end_date:
            clauses.append(f"(TRADE_DATE<='{_normalize_date(end_date)}')")
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
        trade_date_raw = str(item.get("TRADE_DATE") or "")
        # 兼容 "2026-09-25T00:00:00" / "2026-09-25 00:00:00" / "2026-09-25"
        m = re.match(r"^(\d{4}-\d{2}-\d{2})", trade_date_raw)
        date_str = m.group(1) if m else trade_date_raw

        def _to_float(v) -> float | None:
            if v is None or v == "":
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

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
