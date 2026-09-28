"""
astock_signals — A-stock signal data modules (独立包 v2.0.0).

TradingAgents-astock 移植层。提供以下核心能力:
  - anti_ban_client:  东财防封客户端（节流+Session复用）
  - lockup:           限售解禁日历（RPT_LIFT_STAGE）
  - hot_money:        涨停归因/热点资金追踪（同花顺 editorial）
  - indicators:       技术指标计算（MACD/RSI/Boll/ATR 等）
  - northbound:       北向资金流向（沪深股通，同花顺 hsgtApi）
  - dragon_tiger:     龙虎榜席位明细（东财 datacenter）
  - limit_up_board:   涨停四池/打板情绪（东财 push2ex + 同花顺）

V0.3 — 新增 ETF / 可转债 2 个品种模块 + 智能路由 / Tick存储 / WebSocket 3 个基础设施模块。

2026-09-28 审计清理：fund_flow / concept / industry 三个 push2 时代模块已删
（东财 push2 域名族 2026-09-23 起被风控退役，三模块自彼时起零生产消费）。

模块清单（12个）:
  - anti_ban_client / lockup / hot_money / indicators / northbound
  - dragon_tiger / limit_up_board
  - etf / convertible_bond  (V0.3 新品种)
  - smart_router / tick_store / ws_server  (V0.3 基础设施)
"""

from .anti_ban_client import (
    em_get,
    em_datacenter,
    em_push2,
    em_push2_fund_flow,
    em_push2his_fund_flow,
    set_min_interval,
    set_jitter_range,
    set_max_retry,
    em_reset_session,
)

from .lockup import get_lockup_expiry, get_lockup_expiry_json
from .hot_money import get_hot_stocks, get_hot_stocks_json
from .indicators import (
    get_supported_indicators,
    get_indicator_description,
    calculate_indicators,
    get_indicators_text,
)
from .northbound import get_northbound_flow, get_northbound_flow_json
from .dragon_tiger import get_dragon_tiger_board, get_dragon_tiger_board_json
from .limit_up_board import (
    get_limit_up_pool,
    get_break_board_pool,
    get_limit_down_pool,
    get_prev_limit_up_pool,
    get_limit_up_insight,
    calculate_board_sentiment,
    get_limit_up_board_json,
    get_board_sentiment_json,
)

_ETF_LOADED = False
_CB_LOADED = False
_ETF_MODULE = None
_CB_MODULE = None

__all__ = [
    # anti_ban_client
    "em_get",
    "em_datacenter",
    "em_push2",
    "em_push2_fund_flow",
    "em_push2his_fund_flow",
    "set_min_interval",
    "set_jitter_range",
    "set_max_retry",
    "em_reset_session",
    # lockup
    "get_lockup_expiry",
    "get_lockup_expiry_json",
    # hot_money
    "get_hot_stocks",
    "get_hot_stocks_json",
    # indicators
    "get_supported_indicators",
    "get_indicator_description",
    "calculate_indicators",
    "get_indicators_text",
    # northbound
    "get_northbound_flow",
    "get_northbound_flow_json",
    # dragon_tiger
    "get_dragon_tiger_board",
    "get_dragon_tiger_board_json",
    # etf (lazy loaded)
    "get_etf_realtime",
    "get_etf_realtime_json",
    "get_etf_kline",
    "get_etf_kline_json",
    "get_etf_list",
    "get_etf_list_json",
    # convertible_bond (lazy loaded)
    "get_cb_realtime",
    "get_cb_realtime_json",
    "get_cb_value_analysis",
    "get_cb_value_analysis_json",
    "get_cb_comparison",
    "get_cb_comparison_json",
    "get_cb_info",
    "get_cb_info_json",
    # limit_up_board
    "get_limit_up_pool",
    "get_break_board_pool",
    "get_limit_down_pool",
    "get_prev_limit_up_pool",
    "get_limit_up_insight",
    "calculate_board_sentiment",
    "get_limit_up_board_json",
    "get_board_sentiment_json",
]


def __getattr__(name):
    global _ETF_LOADED, _CB_LOADED, _ETF_MODULE, _CB_MODULE

    etf_funcs = [
        "get_etf_realtime", "get_etf_realtime_json",
        "get_etf_kline", "get_etf_kline_json",
        "get_etf_list", "get_etf_list_json",
    ]
    cb_funcs = [
        "get_cb_realtime", "get_cb_realtime_json",
        "get_cb_value_analysis", "get_cb_value_analysis_json",
        "get_cb_comparison", "get_cb_comparison_json",
        "get_cb_info", "get_cb_info_json",
    ]

    if name in etf_funcs:
        if not _ETF_LOADED:
            from . import etf as _etf_mod
            _ETF_MODULE = _etf_mod
            _ETF_LOADED = True
        return getattr(_ETF_MODULE, name)

    if name in cb_funcs:
        if not _CB_LOADED:
            from . import convertible_bond as _cb_mod
            _CB_MODULE = _cb_mod
            _CB_LOADED = True
        return getattr(_CB_MODULE, name)

    raise AttributeError(f"module 'astock_signals' has no attribute '{name}'")

# astock_signals 独立包,版本号独立维护
__version__ = "2.0.0"
