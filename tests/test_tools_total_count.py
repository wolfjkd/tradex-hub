"""
工具总数回归断言（T5，v0.1.0-DEV，SP-2026-09-21-001）。

QI-ARCH-02/06（2026-11-18 质检整改）：总账本由「AST 数 @mcp.tool() 文本」
改「**注册过程衍生**」——工具体上提模块级后无装饰器可数（AST 数文本账本
退役；试点 event_driven 6 工具上提实证：AST 账本掉数 192→187）；实例化
FastMCP + ToolRegistry.discover_and_register 走真实注册路径，数
_tool_manager._tools 实际注册数（与 tradex/tests/test_server.py 同口径，
清单数据源单点）。

tdx_mcp/tdx_tq 两文件的「恰好贡献 N 个」断言保留 AST 口径（该两文件
工具体尚未上提，AST 数与注册数一一对应；全量上提时一并退役）。
"""

import ast
import os

import pytest
from mcp.server.fastmcp import FastMCP

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TOOLS_DIR = os.path.join(_ROOT, "tradex", "src", "tradex", "tools")


def _count_decorators(path: str) -> int:
    """AST 计数该模块中所有被 @mcp.tool(...) 装饰的函数（含 async def）。"""
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                func = dec.func if isinstance(dec, ast.Call) else dec
                if isinstance(func, ast.Attribute) and func.attr == "tool":
                    count += 1
    return count


def _register_all_tools_full(mcp) -> dict:
    """发现并注册全部工具（跳过 signal_data_* 兼容子模块防重复），不做
    profile 可见性过滤（本机 config/mcp_tool_profile.json=lean 会隐藏 75 个，
    计数须与 profile 无关）。返回 {工具名: tool}。"""
    import importlib
    import pkgutil

    import tradex.tools as tools_pkg

    for _, mod_name, _ in pkgutil.iter_modules(tools_pkg.__path__):
        if mod_name.startswith("signal_data_"):
            continue  # 由 signal_data 兼容入口统一注册，避免重复
        mod = importlib.import_module(f"{tools_pkg.__name__}.{mod_name}")
        if hasattr(mod, "register"):
            mod.register(mcp)
    return mcp._tool_manager._tools


def _registered_tools() -> dict:
    """注册过程衍生计数（A⑥ 账本引用化，profile 无关全量）。"""
    mcp = FastMCP("count-derived")
    return _register_all_tools_full(mcp)


class TestTdxMcpToolCount:
    def test_tdx_mcp_contributes_exactly_three(self):
        p = os.path.join(_TOOLS_DIR, "tdx_mcp.py")
        assert os.path.exists(p), f"tdx_mcp.py 不存在: {p}"
        assert _count_decorators(p) == 3

    def test_tdx_tq_contributes_exactly_two(self):
        """QI-ARCH-02（2026-11-19）：tdx_tq 工具体上提后改注册衍生口径
        （AST 数装饰器断言退役——工具体无装饰器可数）。"""
        tools = _registered_tools()
        tq_tools = [n for n in tools if n in ("get_l2_stats", "run_tdx_formula")]
        assert len(tq_tools) == 2, f"tdx_tq 应贡献 2 工具，实得 {tq_tools}"


class TestTotalToolCount:
    def test_total_tool_count_is_192(self):
        """全量工具数 = 192（注册过程衍生，2026-11-11 裁决① +1 后基线）。"""
        tools = _registered_tools()
        assert len(tools) == 192, f"期望工具总数 192，实得 {len(tools)}"

    def test_event_driven_six_tools_registered(self):
        """A② 试点背书：上提 6 工具经 register 引用注册真实在册。"""
        tools = _registered_tools()
        for name in (
            "get_earnings_forecast",
            "get_institution_survey",
            "get_holder_trades",
            "get_share_buyback",
            "get_equity_pledge",
            "get_ipo_calendar",
        ):
            assert name in tools, f"{name} 未注册（上提后引用注册失效）"
