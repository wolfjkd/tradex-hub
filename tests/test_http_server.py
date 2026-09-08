"""
HTTP 网关回归测试（v3.3.12 引入）。

覆盖：
  - 网关路由注册：/health、/mcp(Streamable HTTP)、/sse + /messages(legacy SSE) 三组并存
  - /health 健康检查：status/version/tools 字段（进程级轻量探活，不触发网络外呼）

说明：
  - MCP 握手（initialize / SSE endpoint）含长连接会话，TestClient 关闭会死锁，
    已由手工端到端验证覆盖（uvicorn 起服 + 官方 mcp client + curl），此处只锁路由层。
  - 纯本机回环，无真实网络外呼。

运行方式：pytest tests/test_http_server.py -v
"""

import pytest


def _build():
    from tradex.server import mcp
    from tradex.http_server import build_app

    return build_app(mcp)


def test_routes_registered():
    """三组端点并存：/health + Streamable HTTP(/mcp) + legacy SSE(/sse,/messages)。"""
    app = _build()
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/health" in paths
    assert "/mcp" in paths
    assert "/sse" in paths
    assert "/messages" in paths  # SSE 消息回传端点（Mount）


def test_health_ok():
    """/health 健康检查（TestClient 短连接，安全）。"""
    from starlette.testclient import TestClient

    # base_url 用 localhost（本机回环）：mcp SDK transport_security 校验 Host header
    # （防 DNS rebinding），默认 testserver 会被拒（421）。
    app = _build()
    with TestClient(app, base_url="http://localhost:8000") as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "tradex-mcp"
    assert body["version"]  # 非空即满足（版本由 VERSION 单一事实源驱动）
    assert body["tools"] == 129
    assert body["uptime_seconds"] >= 0


# ── Host 校验 / DNS rebinding 防护（v3.3.12 增强）─────────────────────────
# 说明：SDK 的 Host 校验只作用于 /mcp、/sse 等 MCP 子端点（/health 是我们自己的
# 路由不经校验），而 MCP 握手是长连接、TestClient 会死锁 —— 所以白名单的"真实验证"
# 落在 settings 断言层；"421 被拒"是 SDK 内部行为（已在本仓手工 E2E 见过），不重测。

from mcp.server.transport_security import TransportSecuritySettings  # noqa: E402


def _reset_transport_security():
    """每个用例前重置为 SDK 默认，避免 settings 跨用例污染。"""
    from tradex.server import mcp

    mcp.settings.transport_security = TransportSecuritySettings()


def test_parse_allowed_hosts():
    from tradex.http_server import parse_allowed_hosts

    assert parse_allowed_hosts(None) == []
    assert parse_allowed_hosts("") == []
    assert parse_allowed_hosts(" 10.0.0.8 , localhost ,47.102.212.49 ") == [
        "10.0.0.8",
        "localhost",
        "47.102.212.49",
    ]
    assert parse_allowed_hosts("*") == ["*"]


def test_is_allow_any_host():
    from tradex.http_server import is_allow_any_host

    assert is_allow_any_host(["*"]) is True
    assert is_allow_any_host(["*:*"]) is True
    assert is_allow_any_host(["10.0.0.8", "localhost"]) is False


def test_apply_transport_security_empty_keeps_default():
    """allowed_hosts 为空 → 不改动 settings（沿用 SDK 默认仅本机回环）。"""
    from tradex.server import mcp
    from tradex.http_server import apply_transport_security

    _reset_transport_security()
    before = mcp.settings.transport_security
    apply_transport_security(mcp, None)
    assert mcp.settings.transport_security is before


def test_apply_transport_security_whitelist():
    """白名单模式：DNS 防护开启，hosts 含本机回环家族 + 用户项 + 端口通配。

    注：回环家族里的 127.0.0.1 属 SDK Host 校验的 localhost 安全兜底
    （保证配置白名单后本机回环仍可访问），非代理地址，勿删。
    """
    from tradex.server import mcp
    from tradex.http_server import apply_transport_security

    _reset_transport_security()
    apply_transport_security(mcp, ["47.102.212.49"])
    sec = mcp.settings.transport_security
    assert sec.enable_dns_rebinding_protection is True
    for host in (
        "127.0.0.1:*",
        "localhost:*",
        "[::1]:*",
        "47.102.212.49",
        "47.102.212.49:*",
    ):
        assert host in sec.allowed_hosts, f"missing {host} in {sec.allowed_hosts}"
    assert "http://47.102.212.49:*" in sec.allowed_origins


def test_apply_transport_security_star_disables():
    """'*' 模式：关闭 DNS rebinding 防护，全放行（仅限可信内网）。"""
    from tradex.server import mcp
    from tradex.http_server import apply_transport_security

    _reset_transport_security()
    apply_transport_security(mcp, ["*"])
    sec = mcp.settings.transport_security
    assert sec.enable_dns_rebinding_protection is False
    assert sec.allowed_hosts == ["*"]


def test_build_app_applies_allowlist_before_subapps():
    """build_app 带白名单 → settings 在创建子 app 前生效（无需进 lifespan）。

    注：不进 TestClient —— 本模块 mcp 的 session manager 是进程单例，
    lifespan 只能进入一次（多次进入抛 run() can only be called once）。
    """
    from tradex.server import mcp
    from tradex.http_server import build_app

    _reset_transport_security()
    app = build_app(mcp, allowed_hosts=["203.0.113.9"])
    assert mcp.settings.transport_security.enable_dns_rebinding_protection is True
    assert "203.0.113.9:*" in mcp.settings.transport_security.allowed_hosts
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/health" in paths and "/mcp" in paths and "/sse" in paths
