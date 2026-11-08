"""
工具可见性 profile 测试（2026-11-08 一键启停功能）。

覆盖：
  - profile 文件缺失 / full → 不过滤（190 全量）
  - hidden 名单 → FastMCP _tools 摘除，数量与命中数正确
  - 损坏 JSON → 回退 full 不挡启动
  - env MCP_TOOL_PROFILE 路径覆盖
  - 黑名单语义：名单外工具（含新工具）默认可见
"""

import json
from unittest.mock import MagicMock

import pytest

from tradex.tools import registry as tool_registry


@pytest.fixture()
def fastmcp_like():
    """构造带 N 个假工具的 FastMCP 替身（_tool_manager._tools dict）。"""
    mcp = MagicMock()
    mcp._tool_manager._tools = {f"tool_{i}": object() for i in range(10)}
    return mcp


def _write_profile(tmp_path, profile: str, hidden: list[str]) -> None:
    (tmp_path / "mcp_tool_profile.json").write_text(
        json.dumps(
            {"profile": profile, "hidden_tools": hidden, "updated_at": "t"},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_missing_profile_means_full(fastmcp_like, monkeypatch, tmp_path):
    monkeypatch.setenv("MCP_TOOL_PROFILE", str(tmp_path / "nope.json"))
    profile, visible, hidden_n = tool_registry._apply_tool_visibility(fastmcp_like)
    assert profile == "full"
    assert visible == -1  # 未启用过滤
    assert hidden_n == 0
    assert len(fastmcp_like._tool_manager._tools) == 10


def test_hidden_tools_removed(fastmcp_like, monkeypatch, tmp_path):
    _write_profile(tmp_path, "lean", ["tool_0", "tool_3", "not_registered"])
    monkeypatch.setenv("MCP_TOOL_PROFILE", str(tmp_path / "mcp_tool_profile.json"))
    profile, visible, hidden_n = tool_registry._apply_tool_visibility(fastmcp_like)
    assert profile == "lean"
    assert visible == 8
    assert hidden_n == 2  # 名单 3 项，not_registered 未命中
    assert "tool_0" not in fastmcp_like._tool_manager._tools
    assert "tool_3" not in fastmcp_like._tool_manager._tools


def test_full_profile_no_filter(fastmcp_like, monkeypatch, tmp_path):
    _write_profile(tmp_path, "full", ["tool_0"])
    monkeypatch.setenv("MCP_TOOL_PROFILE", str(tmp_path / "mcp_tool_profile.json"))
    _p, visible, _h = tool_registry._apply_tool_visibility(fastmcp_like)
    assert visible == -1
    assert len(fastmcp_like._tool_manager._tools) == 10


def test_broken_json_falls_back_to_full(fastmcp_like, monkeypatch, tmp_path):
    bad = tmp_path / "mcp_tool_profile.json"
    bad.write_text("{ not json", encoding="utf-8")
    monkeypatch.setenv("MCP_TOOL_PROFILE", str(bad))
    profile, visible, _h = tool_registry._apply_tool_visibility(fastmcp_like)
    assert profile == "full"
    assert visible == -1
    assert len(fastmcp_like._tool_manager._tools) == 10


def test_blacklist_semantics_new_tools_visible(fastmcp_like, monkeypatch, tmp_path):
    """黑名单语义：名单外工具默认可见（新增工具不会被悄悄丢）。"""
    _write_profile(tmp_path, "custom", ["tool_0"])
    monkeypatch.setenv("MCP_TOOL_PROFILE", str(tmp_path / "mcp_tool_profile.json"))
    fastmcp_like._tool_manager._tools["brand_new_tool"] = object()
    _p, visible, _h = tool_registry._apply_tool_visibility(fastmcp_like)
    assert visible == 10  # 10 - 1 + 1 新增
    assert "brand_new_tool" in fastmcp_like._tool_manager._tools


def test_malformed_manager_skips_filter(monkeypatch, tmp_path):
    _write_profile(tmp_path, "lean", ["x"])
    monkeypatch.setenv("MCP_TOOL_PROFILE", str(tmp_path / "mcp_tool_profile.json"))
    weird = MagicMock()
    weird._tool_manager = "not-a-manager"
    profile, visible, _h = tool_registry._apply_tool_visibility(weird)
    assert profile == "lean"
    assert visible == -1  # 结构异常 → 跳过过滤，不挡启动
