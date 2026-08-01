"""
cn-financial-mcp: China Financial Data MCP Server based on AKShare.

Provides free financial data for Chinese mainland market via MCP protocol.
Supports stdio (dev) and HTTP/SSE (production) transport modes.
"""

import importlib
import logging

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

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
    """Register all tool modules with the MCP server.

    使用自动发现机制扫描 tools/ 目录下所有模块，
    调用每个模块的 register(mcp) 函数完成注册。
    新增工具只需在 tools/ 下创建文件，无需修改本函数。
    """
    from .tools.registry import ToolRegistry

    tools_package = importlib.import_module("cn_financial_mcp.tools")
    registered = ToolRegistry.discover_and_register(tools_package, mcp)
    logger.info("已注册 %d 个工具模块: %s", len(registered), ", ".join(registered))


# Register all tools at import time
register_all_tools()
