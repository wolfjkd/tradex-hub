"""
cn-financial-mcp: China Financial Data MCP Server based on AKShare.

Provides free financial data for Chinese mainland market via MCP protocol.
Supports stdio (dev) and HTTP/SSE (production) transport modes.
"""

from mcp.server.fastmcp import FastMCP

# Create the MCP server instance
mcp = FastMCP(
    name="cn-financial-mcp",
    instructions=(
        "cn-financial-mcp provides free Chinese mainland financial data via AKShare. "
        "Use the available tools to search stocks, get real-time quotes, historical prices, "
        "financial statements, valuation metrics, industry data, market overview, news, "
        "and macroeconomic indicators. All stock codes should be 6-digit A-share codes "
        "(e.g., '000001' for Ping An Bank, '600519' for Kweichow Moutai)."
    ),
)


def register_all_tools():
    """Register all tool modules with the MCP server."""
    # 公司信息 + 行情数据
    from .tools.company_info import register as reg_company
    from .tools.price_data import register as reg_price

    reg_company(mcp)
    reg_price(mcp)

    # 财务报表 + 估值
    from .tools.financial_stmt import register as reg_financial
    from .tools.valuation import register as reg_valuation

    reg_financial(mcp)
    reg_valuation(mcp)

    # 行业板块 + 市场总览 + 新闻公告
    from .tools.industry import register as reg_industry
    from .tools.market import register as reg_market
    from .tools.news_events import register as reg_news

    reg_industry(mcp)
    reg_market(mcp)
    reg_news(mcp)

    # 宏观数据 + 外汇
    from .tools.macro_fx import register as reg_macro

    reg_macro(mcp)

    # 通达信独有数据（集合竞价/逐笔成交/F10）
    from .tools.eltdx_data import register as reg_eltdx

    reg_eltdx(mcp)

    # A股信号数据（涨停归因/解禁日历/概念归属/一致预期/技术指标）
    from .tools.signal_data import register as reg_signal

    reg_signal(mcp)

    # V2.5.0 新增：量化计算工具组（智能决策中台）
    # 技术指标计算（纯函数，输入价格数组）
    from .tools.technical_indicators import register as reg_ti
    reg_ti(mcp)

    # 绩效指标计算
    from .tools.performance_metrics import register as reg_pm
    reg_pm(mcp)

    # 信号生成
    from .tools.signal_generation import register as reg_sg
    reg_sg(mcp)

    # 因子分析
    from .tools.factor_analysis import register as reg_fa
    reg_fa(mcp)

    # 条件选股
    from .tools.stock_screening import register as reg_ss
    reg_ss(mcp)


# Register all tools at import time
register_all_tools()
