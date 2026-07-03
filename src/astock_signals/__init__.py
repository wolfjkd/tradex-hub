"""
astock_signals — A-stock signal data modules for trader-finance-hub.

TradingAgents-astock 移植层。提供以下核心能力:
  - anti_ban_client:  东财防封客户端（节流+Session复用）
  - lockup:           限售解禁日历（RPT_LIFT_STAGE）
  - hot_money:        涨停归因/热点资金追踪（同花顺 editorial）
  - concept:          概念板块归属（东财 push2delay）
  - indicators:       技术指标计算（MACD/RSI/Boll/ATR 等）
  - northbound:       北向资金流向（沪深股通，同花顺 hsgtApi）
  - fund_flow:        个股资金流向（东财 push2）
  - dragon_tiger:     龙虎榜席位明细（东财 datacenter）
  - industry:         行业横向对比（东财 push2 行业排名）

V0.3 — 新增 ETF / 可转债 2 个品种模块 + 智能路由 / Tick存储 / WebSocket 3 个基础设施模块。

模块清单（14个）:
  - anti_ban_client / lockup / hot_money / concept / indicators
  - northbound / fund_flow / dragon_tiger / industry  (V0.2)
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
    em_reset_session,
)

from .lockup import get_lockup_expiry, get_lockup_expiry_json
from .hot_money import get_hot_stocks, get_hot_stocks_json
from .concept import get_concept_blocks, get_concept_blocks_json
from .indicators import (
    get_supported_indicators,
    get_indicator_description,
    calculate_indicators,
    get_indicators_text,
)
from .northbound import get_northbound_flow, get_northbound_flow_json
from .fund_flow import get_fund_flow, get_fund_flow_json
from .dragon_tiger import get_dragon_tiger_board, get_dragon_tiger_board_json
from .industry import get_industry_comparison, get_industry_comparison_json
from .etf import get_etf_realtime, get_etf_realtime_json, get_etf_kline, get_etf_kline_json, get_etf_list, get_etf_list_json
from .convertible_bond import get_cb_realtime, get_cb_realtime_json, get_cb_value_analysis, get_cb_value_analysis_json, get_cb_comparison, get_cb_comparison_json, get_cb_info, get_cb_info_json
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

__all__ = [
    # anti_ban_client
    "em_get",
    "em_datacenter",
    "em_push2",
    "em_push2_fund_flow",
    "em_push2his_fund_flow",
    "set_min_interval",
    "em_reset_session",
    # lockup
    "get_lockup_expiry",
    "get_lockup_expiry_json",
    # hot_money
    "get_hot_stocks",
    "get_hot_stocks_json",
    # concept
    "get_concept_blocks",
    "get_concept_blocks_json",
    # indicators
    "get_supported_indicators",
    "get_indicator_description",
    "calculate_indicators",
    "get_indicators_text",
    # northbound
    "get_northbound_flow",
    "get_northbound_flow_json",
    # fund_flow
    "get_fund_flow",
    "get_fund_flow_json",
    # dragon_tiger
    "get_dragon_tiger_board",
    "get_dragon_tiger_board_json",
    # industry
    "get_industry_comparison",
    "get_industry_comparison_json",
    # etf
    "get_etf_realtime",
    "get_etf_realtime_json",
    "get_etf_kline",
    "get_etf_kline_json",
    "get_etf_list",
    "get_etf_list_json",
    # convertible_bond
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

__version__ = "0.3.2"
