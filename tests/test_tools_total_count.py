"""
工具总数回归断言（T5，v0.1.0-DEV，SP-2026-09-21-001）。

锁行为：
  - 全 tools/ 目录的 @mcp.tool() 装饰器总数 = 132（129 存量 + tdx_mcp 新增 3）。
  - tdx_mcp.py 恰好贡献 3 个装饰器（natural_lang_screener / research_report / query_macro_indicator）。

说明：沿用仓库既有惯例（test_signal_data_mcp.py 用源码计数而非 import server），
避免 import server 触发数据源注册的副作用；装饰器计数与真实注册一一对应
（tools/registry.py 会为每个含 register() 的模块调用其 register(mcp)）。
"""

import glob
import os
import re

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TOOLS_DIR = os.path.join(_ROOT, "tradex", "src", "tradex", "tools")


def _count_decorators(path: str) -> int:
    with open(path, encoding="utf-8") as f:
        src = f.read()
    # 只数顶格缩进的装饰器，排除 docstring/注释里的 "@mcp.tool()" 字样
    return len(re.findall(r"^\s*@mcp\.tool\(\)$", src, re.M))


class TestTdxMcpToolCount:
    def test_tdx_mcp_contributes_exactly_three(self):
        p = os.path.join(_TOOLS_DIR, "tdx_mcp.py")
        assert os.path.exists(p), f"tdx_mcp.py 不存在: {p}"
        assert _count_decorators(p) == 3

    def test_total_tool_count_is_132(self):
        """全量工具数 = 129（存量） + 3（tdx_mcp 新增） = 132。"""
        total = 0
        for py in glob.glob(os.path.join(_TOOLS_DIR, "*.py")):
            if py.endswith("__init__.py") or py.endswith("registry.py"):
                continue
            total += _count_decorators(py)
        assert total == 132, f"期望工具总数 132，实得 {total}"