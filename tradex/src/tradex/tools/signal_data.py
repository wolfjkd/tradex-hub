"""
signal_data 兼容入口 — v3.0.0 起拆分为 5 个子模块。

原 Category 9: Signal Data — A-stock signal/event tools。
TradingAgents-astock 移植层 + 品种扩展层（涨停归因/解禁日历/概念归属/
一致预期/技术指标/北向资金/个股资金流/龙虎榜/行业对比 + ETF/可转债 + 涨停板）。

子模块（共 17 个工具）：
  signal_data_base   (6) - 涨停归因/解禁/概念/一致预期/技术指标
  signal_data_flow   (4) - 北向资金/个股资金流/龙虎榜/行业对比
  signal_data_etf    (2) - ETF 实时行情/历史K线
  signal_data_cb     (2) - 可转债实时行情/价值分析
  signal_data_board  (3) - 涨停四池/打板情绪/涨停揭秘

本文件仅作兼容入口：register(mcp) 会委托给 5 个子模块的 register。
新代码请直接从对应子模块导入。
"""

from .signal_data_base import register as _register_base
from .signal_data_flow import register as _register_flow
from .signal_data_etf import register as _register_etf
from .signal_data_cb import register as _register_cb
from .signal_data_board import register as _register_board


def register(mcp):
    """注册所有 signal_data 子模块的工具。

    依次调用 5 个子模块的 register，完成全部 17 个工具的注册。
    """
    _register_base(mcp)
    _register_flow(mcp)
    _register_etf(mcp)
    _register_cb(mcp)
    _register_board(mcp)
