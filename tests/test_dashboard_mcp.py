"""
数据看板 MCP 启停路由测试（2026-11-08 与 TradeX 同步的第二入口）。

覆盖：catalog 数据结构（GROUPS 全集/hidden 反映）+ apply 预设校验 +
tool_count 缓存失效。IO 层（kill/wait）mock，不真杀网关。
"""

import json

import pytest

from tradex.dashboard import __main__ as dash


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """profile 指向 tmp；杀进程/等待 mock。"""
    profile = tmp_path / "mcp_tool_profile.json"
    monkeypatch.setattr(
        "tradex.tools.mcp_profile_io.profile_path", lambda: profile
    )
    monkeypatch.setattr(
        "tradex.tools.mcp_profile_io.kill_gateway", lambda: 1
    )
    monkeypatch.setattr(
        "tradex.tools.mcp_profile_io.wait_gateway",
        lambda expected, deadline_s=45.0: expected,
    )
    monkeypatch.setattr(
        "tradex.tools.mcp_profile_io.gateway_tools", lambda timeout=4.0: 116
    )
    yield


def test_catalog_shape():
    data = dash.get_mcp_catalog_data()
    assert data["total"] == 191
    assert len(data["groups"]) == 26
    assert data["profile"] == "full"  # tmp 无 profile 文件 → full
    assert data["gateway_tools"] == 116
    names = [t["name"] for g in data["groups"] for t in g["tools"]]
    assert len(names) == 191


def test_apply_lean_writes_and_invalidates_cache(monkeypatch):
    monkeypatch.setattr(dash, "_TOOL_COUNT", 190)  # 预置缓存
    out = dash.apply_mcp_preset("lean")
    assert out["preset"] == "lean"
    assert out["enabled"] == 116
    assert dash._TOOL_COUNT is None  # 缓存已失效
    from tradex.tools import mcp_profile_io

    written = json.loads(
        mcp_profile_io.profile_path().read_text(encoding="utf-8")
    )
    assert written["profile"] == "lean"
    assert len(written["hidden_tools"]) == 75  # 2026-11-08 191 工具：get_index_valuation 归低频组，lean 隐藏


def test_apply_full_clears_hidden(monkeypatch):
    dash.apply_mcp_preset("lean")
    out = dash.apply_mcp_preset("full")
    assert out["enabled"] == 191
    from tradex.tools import mcp_profile_io

    written = json.loads(
        mcp_profile_io.profile_path().read_text(encoding="utf-8")
    )
    assert written["hidden_tools"] == []


def test_apply_invalid_preset_raises():
    from tradex.tools.mcp_profile_io import apply_preset_values

    with pytest.raises(ValueError, match="非法预设"):
        apply_preset_values("nope", [], [], 190)
