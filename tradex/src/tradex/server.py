"""
tradex: China Financial Data MCP Server based on AKShare.

Provides free financial data for Chinese mainland market via MCP protocol.
Supports stdio (dev) and HTTP/SSE (production) transport modes.
"""

import importlib
import logging
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _server_lifespan(app):
    """MCP server 生命周期钩子（v3.3.11 起）。

    启动:无额外动作（数据源/工具在 import 时已注册）。
    关闭:清理常驻资源（eltdx 常驻推送连接等），避免进程退出悬挂。
    """
    logger.info("tradex MCP server starting")
    try:
        yield {}
    finally:
        logger.info("tradex MCP server stopping: cleaning up resources")
        try:
            from .data_sources.eltdx_stream import _shutdown_stream

            _shutdown_stream()
        except Exception as exc:  # noqa: BLE001
            logger.debug("cleanup eltdx stream failed: %s", exc)


# Create the MCP server instance
mcp = FastMCP(
    name="tradex",
    instructions=(
        "tradex provides free Chinese mainland financial data via AKShare. "
        "Use the available tools to search stocks, get real-time quotes, historical prices, "
        "financial statements, valuation metrics, industry data, market overview, news, "
        "and macroeconomic indicators. All stock codes should be 6-digit A-share codes "
        "(e.g., '000001' for Ping An Bank, '600519' for Kweichow Moutai)."
    ),
    lifespan=_server_lifespan,
    # 2026-09-19: HTTP 传输改为无状态——每个 /mcp 请求独立处理, 不依赖内存 session-id。
    # 根因: 网关因健康检查误杀/崩溃而重启时, 内存 session 表清空, 有状态客户端持有的
    # session-id 立即失效 → 报 "Session not found" → 表现为「时断时连」。改为无状态后,
    # 网关任意重启客户端均可继续调用, 从协议层根除该故障。
    # 仅影响 HTTP 模式; stdio 传输(本地 WorkBuddy/Claude Code)不受影响。
    stateless_http=True,
)

# v3.3.9+：工具注册幂等守卫——importlib.reload(server) 或重复 import 时
# 避免向同一 mcp 实例重复注册 129 个工具。
_tools_registered = False


def register_all_tools():
    """Register all tool modules with the MCP server.

    使用自动发现机制扫描 tools/ 目录下所有模块，
    调用每个模块的 register(mcp) 函数完成注册。
    新增工具只需在 tools/ 下创建文件，无需修改本函数。
    """
    global _tools_registered
    if _tools_registered:
        logger.debug("register_all_tools: already registered, skip")
        return
    from .tools.registry import ToolRegistry

    tools_package = importlib.import_module("tradex.tools")
    registered = ToolRegistry.discover_and_register(tools_package, mcp)
    _tools_registered = True
    logger.info("已注册 %d 个工具模块: %s", len(registered), ", ".join(registered))


# Register data sources first (L1 tools depend on SmartRouter), then tools
from .data_sources import register_all_sources  # noqa: E402

register_all_sources()
register_all_tools()
