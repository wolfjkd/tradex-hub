"""
工具总数回归断言（T5，v0.1.0-DEV，SP-2026-09-21-001）。

锁行为：
  - 全 tools/ 目录的 @mcp.tool(...) 装饰器总数 = 166（2026-09-28 审计基线 176，
    死源剥离再移除 10 个工具：期权 2 + 指数 3 + 互动 2 + 宏观 3）。
  - tdx_mcp.py 恰好贡献 3 个装饰器（natural_lang_screener / research_report / query_macro_indicator）。

说明：沿用仓库既有惯例（源码计数而非 import server），避免 import 触发数据源
注册的副作用；计数改用 AST（正则版会把 docstring/注释里的 "@mcp.tool()" 字样
误计 3 处，与真实注册数 176 对不上）。tools/registry.py 会为每个含 register()
的模块调用其 register(mcp)，装饰器数与真实注册一一对应（signal_data_* 子模块
由 signal_data.py 兼容入口统一注册，装饰器只计一次）。
"""

import ast
import glob
import os

import pytest

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


class TestTdxMcpToolCount:
    def test_tdx_mcp_contributes_exactly_three(self):
        p = os.path.join(_TOOLS_DIR, "tdx_mcp.py")
        assert os.path.exists(p), f"tdx_mcp.py 不存在: {p}"
        assert _count_decorators(p) == 3

    def test_total_tool_count_is_166(self):
        """全量工具数 = 166（2026-09-28 死源剥离后基线）。"""
        total = 0
        for py in glob.glob(os.path.join(_TOOLS_DIR, "*.py")):
            if py.endswith("__init__.py") or py.endswith("registry.py"):
                continue
            total += _count_decorators(py)
        assert total == 166, f"期望工具总数 166，实得 {total}"
