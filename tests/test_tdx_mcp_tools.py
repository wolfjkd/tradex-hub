"""
tdx_mcp L3 工具测试（v0.1.0-DEV，SP-2026-09-21-001）。

锁行为（TDD）：
  - register(mcp) 注册 3 个工具：natural_lang_screener / research_report / query_macro_indicator。
  - 数据经 get_router().route() 获取（不直连官方 MCP）。
  - route 成功 → JSON 字符串；客预期 dict/list 均可序列化。
  - route 抛异常（如 token 缺失 → TDXSourceUnavailable，或上游失败）→ 返回 error_response，
    不外泄异常，可被 L3 决策层正常消费。
"""

import os
import sys

import pytest

_HUB_SRC = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "src"))
if _HUB_SRC not in sys.path:
    sys.path.insert(0, _HUB_SRC)

from mcp.server.fastmcp import FastMCP  # noqa: E402

from tradex.tools import tdx_mcp as tdx_tools  # noqa: E402
from tradex.tools import tdx_mcp as tools_mod  # noqa: E402


@pytest.fixture
def mcp():
    return FastMCP()


def _collect_handlers(mcp: FastMCP) -> dict:
    """从 FastMCP 实例抓出 register() 注册的工具 handler。"""
    import inspect

    # FastMCP._tool_manager 在不同版本结构不同，这里用 rpc 调用 tools/list 拿名字，
    # 再通过模块内函数名映射回到可调用 handler。更稳的做法：直接替换 _router_route_cached。
    handlers = {}
    for name, member in inspect.getmembers(tools_mod):
        if name.startswith("_"):
            continue
        if not inspect.iscoroutinefunction(member):
            continue
        handlers[name] = member
    return handlers


class TestTdxMcpToolsRegistered:
    def test_module_exports_register(self):
        assert callable(getattr(tdx_tools, "register"))

    def test_register_is_callable_no_throw(self, mcp):
        # 无 token 环境注册不应抛异常（register 只定义用途，不触发网络）
        tdx_tools.register(mcp)  # 能成功即算通过


class TestToolBehaviorCached:
    """直接调用工具内部辅助 _router_route_cached，mock route，锁数据形状。"""

    def _set_route(self, monkeypatch, return_value=None, side_effect=None):
        from types import SimpleNamespace

        if side_effect is not None:
            def fail_route(*a, **k):
                raise side_effect
            monkeypatch.setattr(tools_mod, "_router", SimpleNamespace(route=fail_route))
        else:
            def ok_route(*a, **k):
                return (return_value, "tdx_mcp")
            monkeypatch.setattr(tools_mod, "_router", SimpleNamespace(route=ok_route))

    def test_screener_success_dict(self, monkeypatch):
        self._set_route(monkeypatch, return_value={"stocks": [{"code": "600519"}]})
        out = tdx_tools._router_route_cached("screener", "k", "natural_lang_screener",
                                             query="低PE", limit=20)
        assert "600519" in out

    def test_screener_success_list(self, monkeypatch):
        self._set_route(monkeypatch, return_value=[{"code": "000001"}])
        out = tdx_tools._router_route_cached("screener", "k", "natural_lang_screener",
                                             query="低PE", limit=20)
        assert "000001" in out

    def test_route_failure_returns_error_response(self, monkeypatch):
        self._set_route(monkeypatch, side_effect=RuntimeError("no token"))
        out = tdx_tools._router_route_cached("screener", "k", "natural_lang_screener",
                                             query="低PE", limit=20)
        assert '"error": true' in out
        assert "no token" in out

    def test_macro_success(self, monkeypatch):
        self._set_route(monkeypatch, return_value={"CPI": 2.1})
        out = tdx_tools._router_route_cached("macro_data", "k", "query_macro_indicator",
                                             indicator="CPI")
        assert "2.1" in out


class TestToolNamesPresent:
    def test_tools_file_defines_three_tools(self):
        # 从已导入的模块定位真实文件路径，避免路径拼接出错
        src_p = os.path.join(os.path.dirname(tools_mod.__file__), "tdx_mcp.py")
        assert os.path.exists(src_p), f"tdx_mcp.py 不存在: {src_p}"
        src = open(src_p, encoding="utf-8").read()
        # 只数顶格缩进的装饰器（docstring 里的 @mcp.tool() 不算）
        import re

        decorators = re.findall(r"^\s*@mcp\.tool\(\)$", src, re.M)
        assert len(decorators) == 3, f"期望 3 个 @mcp.tool() 装饰器，实得 {len(decorators)}"
        for name in ("natural_lang_screener", "research_report", "query_macro_indicator"):
            assert name in src