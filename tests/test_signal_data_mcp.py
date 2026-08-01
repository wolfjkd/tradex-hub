"""
signal_data.py MCP 工具注册测试（v3.0.0 拆分后）。

原 signal_data.py 已拆分为 5 个子模块，本测试验证：
  1. signal_data.py 兼容入口语法正确
  2. 5 个子模块合计注册 17 个 MCP 工具
  3. 每个子模块都定义了 register 函数
"""

import os
import pytest
import ast

# 项目根目录（tests 的上两级）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TOOLS_DIR = os.path.join(
    _PROJECT_ROOT, "tradex", "src", "tradex", "tools"
)
_SIGNAL_DATA_PY = os.path.join(_TOOLS_DIR, "signal_data.py")

# 拆分后的 5 个子模块
_SUBMODULES = [
    "signal_data_base.py",
    "signal_data_flow.py",
    "signal_data_etf.py",
    "signal_data_cb.py",
    "signal_data_board.py",
]


class TestSignalDataSyntax:
    """验证 signal_data 兼容入口及子模块语法正确。"""

    def test_parse_entry_ok(self):
        """signal_data.py 兼容入口语法正确。"""
        with open(_SIGNAL_DATA_PY, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source)
        assert tree is not None

    def test_entry_has_register(self):
        """signal_data.py 兼容入口仍提供 register 函数。"""
        with open(_SIGNAL_DATA_PY, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source)
        func_names = {
            n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
        }
        assert "register" in func_names

    def test_submodules_have_17_tools(self):
        """5 个子模块合计注册 17 个 MCP 工具。"""
        total = 0
        for sub in _SUBMODULES:
            path = os.path.join(_TOOLS_DIR, sub)
            with open(path, "r", encoding="utf-8") as f:
                source = f.read()
            total += source.count("@mcp.tool()")
        assert total == 17, f"Expected 17 @mcp.tool() across submodules, got {total}"

    def test_each_submodule_has_register(self):
        """每个子模块都定义了 register 函数。"""
        for sub in _SUBMODULES:
            path = os.path.join(_TOOLS_DIR, sub)
            with open(path, "r", encoding="utf-8") as f:
                source = f.read()
            tree = ast.parse(source)
            func_names = {
                n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
            }
            assert "register" in func_names, f"{sub} missing register()"

    def test_all_submodules_exist(self):
        """5 个子模块文件都存在。"""
        for sub in _SUBMODULES:
            path = os.path.join(_TOOLS_DIR, sub)
            assert os.path.isfile(path), f"{sub} not found"
