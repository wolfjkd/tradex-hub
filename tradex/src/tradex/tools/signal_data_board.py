"""
Signal Data — 涨停板类子模块 (signal_data_board)。

原 signal_data.py 拆分自 v3.0.0，本子模块承载打板层工具：
涨停四池、打板情绪速算、涨停揭秘。

V0.9 打板层 — 涨停四池 + 情绪速算（a-stock-data 融合）。

v3.1.0 起：所有数据获取通过 SmartRouter.route() 路由，
不再直接 import astock_signals 数据源函数。

Tools (共 3 个):
  get_limit_up_board   - 涨停四池（东财 push2ex：涨停/炸板/跌停/昨日涨停）
  get_board_sentiment  - 打板情绪速算（炸板率/连板梯队/晋级率）
  get_limit_up_insight - 涨停揭秘（同花顺：题材/封板成功率/板型/封单额）
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..data_sources import get_router
from ..utils.cache import TTL_DAILY, TTL_REALTIME, cache
from ..utils.formatter import error_response, dict_to_json

_router = get_router()


def _try_push_limit_up_signal(board_type: str, count: int) -> None:
    """如果 WsServer 已启动，推送涨停信号（跨线程，失败静默）。

    通过 asyncio.run_coroutine_threadsafe 将推送协程调度到 WsServer 的事件循环。
    推送失败不影响工具返回值。
    """
    try:
        from astock_signals.ws_server import get_ws_server
        import asyncio

        ws = get_ws_server()
        if ws.is_running and ws._loop is not None:
            asyncio.run_coroutine_threadsafe(
                ws.push_signal("limit_up", {
                    "board_type": board_type,
                    "count": count,
                }),
                ws._loop,
            )
    except Exception:
        pass  # 推送失败静默处理，不影响工具返回


def register(mcp: FastMCP):
    """Register signal data limit-up board tools with the MCP server."""

    # ----------------------------------------------------------------
    # V0.9: 打板层 — 涨停四池 + 情绪速算（a-stock-data 融合）
    # ----------------------------------------------------------------

    @mcp.tool()
    async def get_limit_up_board(board_type: str = "zt") -> str:
        """
        获取涨停板数据（东财 push2ex）。

        支持四种类型：涨停池/炸板池/跌停池/昨日涨停池。

        Args:
            board_type: 板类型，可选 zt(涨停)/zb(炸板)/dt(跌停)/prev_zt(昨日涨停)。

        Returns:
            板数据 (JSON)，含股票列表及对应字段。
        """
        board_type = board_type.lower().strip()
        if board_type not in ["zt", "zb", "dt", "prev_zt"]:
            return error_response(
                f"无效的板类型: {board_type}。可选: zt, zb, dt, prev_zt",
                "get_limit_up_board",
            )

        cache_key = f"limit_up_board:{board_type}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            # limit_up_board: board_type → get_limit_up_board_json(board_type)
            result, _src = _router.route("limit_up_board", board_type=board_type)
            output = dict_to_json(result)
            if result.get("data"):
                cache.set(cache_key, output, TTL_REALTIME)
                # 可选：检测到新涨停时通过 WsServer 推送（仅涨停池）
                if board_type == "zt":
                    _try_push_limit_up_signal(board_type, len(result["data"]))
            return output
        except Exception as e:
            return error_response(
                f"获取涨停板数据失败: {e}", "get_limit_up_board"
            )

    @mcp.tool()
    async def get_board_sentiment() -> str:
        """
        获取打板情绪数据（炸板率/连板梯队/晋级率）。

        综合涨停四池数据，计算市场打板情绪指标：炸板率、连板梯队、
        昨日涨停晋级率、平均溢价、热门题材等。

        Returns:
            打板情绪数据 (JSON)，含涨停数/炸板数/跌停数/炸板率/
            连板梯队/晋级率/平均溢价/热门题材。
        """
        cache_key = "board_sentiment"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            # limit_up_board: board_type="sentiment" → get_board_sentiment_json()
            result, _src = _router.route(
                "limit_up_board", board_type="sentiment"
            )
            output = dict_to_json(result)
            if not result.get("error"):
                cache.set(cache_key, output, TTL_REALTIME)
            return output
        except Exception as e:
            return error_response(
                f"获取打板情绪数据失败: {e}", "get_board_sentiment"
            )

    @mcp.tool()
    async def get_limit_up_insight(code: str = "") -> str:
        """
        获取涨停揭秘数据（同花顺）。

        包含涨停原因题材、封板成功率、板型（一字/换手/T字）、封单额等。

        Args:
            code: 股票代码（可选，不传则返回当日全部涨停揭秘）。

        Returns:
            涨停揭秘数据 (JSON)，含题材原因/封板成功率/板型/封单额/换手率。
        """
        cache_key = f"limit_up_insight:{code or 'all'}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            # hot_money: code 非空 → get_limit_up_insight(code)
            result, _src = _router.route("hot_money", code=code)
            output = dict_to_json(result)
            if result.get("data"):
                cache.set(cache_key, output, TTL_DAILY)
            return output
        except Exception as e:
            return error_response(
                f"获取涨停揭秘数据失败: {e}", "get_limit_up_insight"
            )
