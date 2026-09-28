"""
astock_signals 函数 fetch_fn 包装器。

将 astock_signals 包的数据获取函数注册为 SmartRouter fetch_fn。
仅本文件（及 data_sources 包内其他 fetcher 文件）允许 `from astock_signals import ...`。

包含：
  - 东财 em_datacenter 源（dragon_tiger）
  - 同花顺 ths_hsgt 源（northbound）
  - 同花顺 ths_editorial 源（hot_money: 涨停归因/涨停揭秘）
  - 东财 em_datacenter 源（lockup_expiry）
  - akshare 生态源（etf_data / cb_data）

2026-09-28 审计清理：fund_flow / industry_comparison / concept_attribution /
limit_up_board 的东财 push2 族 fetcher 已删（push2 域名族 2026-09-23 起被风控
退役，四个函数零注册零消费，复启将走同花顺备源而非旧 push2 代码）。
"""

from __future__ import annotations

import logging

logger = logging.getLogger("tradex.astock_signals")


def _as():
    """延迟导入 astock_signals。"""
    import astock_signals as asig
    return asig



# ============================================================
# dragon_tiger — 东财 em_datacenter 源（主源）
# ============================================================

def fetch_dragon_tiger_em(code: str = "", symbol: str = "", trade_date: str = "", look_back_days: int = 30, **kwargs) -> dict:
    """龙虎榜（东财 datacenter，via astock_signals.get_dragon_tiger_board_json）。

    空数据/异常时抛 RuntimeError 触发 SmartRouter 降级到 akshare。
    兼容 symbol/code 两种参数名（SmartRouter 路由归一化）。
    """
    asig = _as()
    code = code or symbol
    result = asig.get_dragon_tiger_board_json(code, trade_date, look_back_days)
    has_data = (
        result.get("appearances")
        or result.get("latest_seats", {}).get("buy")
        or result.get("latest_seats", {}).get("sell")
        or result.get("institutional")
    )
    if not has_data:
        err = result.get("error_appearances") or result.get("error_seats") or "东财返回空数据"
        raise RuntimeError(err)
    return result



# ============================================================
# northbound — 同花顺 ths_hsgt 源（主源）
# ============================================================

def fetch_northbound_ths(curr_date: str = "", include_history: bool = False, **kwargs) -> dict:
    """北向资金（同花顺 hsgtApi，via astock_signals.get_northbound_flow_json）。

    返回 dict（含 realtime/history/signal）。
    """
    asig = _as()
    result = asig.get_northbound_flow_json(curr_date, include_history)
    if result.get("error") and not result.get("realtime"):
        raise RuntimeError(result.get("error", "同花顺北向资金返回空数据"))
    return result


# ============================================================
# hot_money — 同花顺 ths_editorial 源（独占）
# ============================================================

def fetch_hot_money(date: str = "", code: str = "", symbol: str = "", **kwargs):
    """涨停归因/涨停揭秘（同花顺 editorial，独占源）。

    通过 code 参数分派：
      - code 为空: 调用 get_hot_stocks_json(date) 返回涨停归因
      - code 非空: 调用 get_limit_up_insight(code) 返回涨停揭秘
    兼容 symbol/code 两种参数名（SmartRouter 路由归一化）。
    """
    asig = _as()
    code = code or symbol
    if code:
        return asig.get_limit_up_insight(code)
    return asig.get_hot_stocks_json(date)


# ============================================================
# lockup_expiry — 东财 em_datacenter 源（独占）
# ============================================================

def fetch_lockup_expiry(symbol: str = "", code: str = "", trade_date: str = "", forward_days: int = 90, **kwargs) -> dict:
    """限售解禁日历（东财 datacenter，独占源，via astock_signals.get_lockup_expiry_json）。

    兼容 symbol/code 两种参数名（SmartRouter 路由归一化）。
    """
    asig = _as()
    symbol = symbol or code
    return asig.get_lockup_expiry_json(symbol, trade_date, forward_days)




# ============================================================
# etf_data — akshare 生态源（via astock_signals）
# ============================================================

def fetch_etf_data(
    symbol: str = "",
    code: str = "",
    period: str = "daily",
    start_date: str = "",
    end_date: str = "",
    adjust: str = "",
    top_n: int = 50,
    sort_by: str = "成交额",
    **kwargs,
):
    """ETF 数据（via astock_signals）。

    通过 symbol 分派：
      - symbol 非空: 调用 get_etf_kline_json 返回历史 K 线
      - symbol 为空: 调用 get_etf_realtime_json 返回实时行情
    兼容 symbol/code 两种参数名（SmartRouter 路由归一化）。
    """
    asig = _as()
    symbol = symbol or code
    if symbol:
        return asig.get_etf_kline_json(symbol, period, start_date, end_date, adjust)
    return asig.get_etf_realtime_json(top_n, sort_by)


# ============================================================
# cb_data — akshare 生态源（via astock_signals）
# ============================================================

def fetch_cb_data(
    symbol: str = "",
    code: str = "",
    top_n: int = 50,
    sort_by: str = "成交额",
    days: int = 30,
    **kwargs,
):
    """可转债数据（via astock_signals）。

    通过 symbol 分派：
      - symbol 非空: 调用 get_cb_value_analysis_json 返回价值分析
      - symbol 为空: 调用 get_cb_realtime_json 返回实时行情
    兼容 symbol/code 两种参数名（SmartRouter 路由归一化）。
    """
    asig = _as()
    symbol = symbol or code
    if symbol:
        return asig.get_cb_value_analysis_json(symbol, days)
    return asig.get_cb_realtime_json(top_n, sort_by)
