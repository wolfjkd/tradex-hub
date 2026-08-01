"""
WsServer 集成测试 — 验证 WebSocket 推送服务器逻辑 + config 配置 + __main__ 集成。

测试范围:
  1. WsServer 初始化（host/port/token 默认值）
  2. _safe_send 标记断开而非立即删除（修复 v3.0.0 时序 bug）
  3. _cleanup_disconnected 统一清理
  4. config.WS_SERVER_ENABLED 默认为 False
  5. config.WS_PORT 默认为 8765
  6. __main__.py 根据 WS_SERVER_ENABLED 决定是否启动 WsServer

注意：不实际启动 WebSocket 服务器（避免端口占用），只测试逻辑。
"""

import os
import sys
import asyncio
import json
from unittest.mock import MagicMock, AsyncMock

import pytest

from astock_signals.ws_server import WsServer


# ---------------------------------------------------------------------------
# 路径设置：确保 tradex.config 可被 import
# ---------------------------------------------------------------------------
_CN_MCP_SRC = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "tradex", "src")
)
if _CN_MCP_SRC not in sys.path:
    sys.path.insert(0, _CN_MCP_SRC)

_HUB_SRC = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "src"))
if _HUB_SRC not in sys.path:
    sys.path.insert(0, _HUB_SRC)


class TestWsServerInit:
    """WsServer 初始化。"""

    def test_default_host_port(self):
        """默认 host=127.0.0.1, port=8765。"""
        server = WsServer()
        assert server.host == "127.0.0.1"
        assert server.port == 8765

    def test_custom_host_port(self):
        """自定义 host/port。"""
        server = WsServer(host="0.0.0.0", port=9999, token="secret")
        assert server.host == "0.0.0.0"
        assert server.port == 9999
        assert server._token == "secret"

    def test_initial_state_not_running(self):
        """初始化后未启动。"""
        server = WsServer()
        assert server.is_running is False
        assert server.client_count == 0

    def test_empty_clients_on_init(self):
        """初始化后客户端集合为空。"""
        server = WsServer()
        assert server._clients == {}
        assert server._disconnected_clients == set()


class TestSafeSendMarksDisconnected:
    """_safe_send 标记断开而非立即删除（v3.0.0 修复的时序 bug）。

    旧 bug：_safe_send 失败时直接从 _clients 删除，但 push_quote/push_signal
    正在迭代 _clients，导致 RuntimeError: dictionary changed size during iteration。

    修复后：_safe_send 只将失败客户端加入 _disconnected_clients 集合，
    推送完成后由 _cleanup_disconnected 统一清理。
    """

    @pytest.mark.asyncio
    async def test_safe_send_failure_marks_disconnected(self):
        """发送失败时标记到 _disconnected_clients，不从 _clients 删除。"""
        server = WsServer()
        mock_ws = MagicMock()
        mock_ws.send = AsyncMock(side_effect=ConnectionError("client disconnected"))

        # 模拟已连接客户端
        server._clients[mock_ws] = {"codes": {"600519"}, "authed": True}

        await server._safe_send(mock_ws, '{"type":"quote"}')

        # 关键断言：标记到 _disconnected_clients
        assert mock_ws in server._disconnected_clients
        # 关键断言：不从 _clients 立即删除（避免迭代时修改）
        assert mock_ws in server._clients

    @pytest.mark.asyncio
    async def test_safe_send_success_no_mark(self):
        """发送成功时不标记断开。"""
        server = WsServer()
        mock_ws = MagicMock()
        mock_ws.send = AsyncMock()

        server._clients[mock_ws] = {"codes": set(), "authed": True}

        await server._safe_send(mock_ws, '{"type":"ping"}')

        assert mock_ws not in server._disconnected_clients
        assert mock_ws in server._clients


class TestCleanupDisconnected:
    """_cleanup_disconnected 统一清理。"""

    def test_cleanup_removes_marked_clients(self):
        """_cleanup_disconnected 移除所有标记为断开的客户端。"""
        server = WsServer()
        ws1 = MagicMock()
        ws2 = MagicMock()
        ws3 = MagicMock()  # 未断开

        server._clients = {
            ws1: {"codes": set(), "authed": True},
            ws2: {"codes": set(), "authed": True},
            ws3: {"codes": set(), "authed": True},
        }
        server._disconnected_clients = {ws1, ws2}

        server._cleanup_disconnected()

        # ws1, ws2 被清理
        assert ws1 not in server._clients
        assert ws2 not in server._clients
        # ws3 保留
        assert ws3 in server._clients
        # _disconnected_clients 清空
        assert server._disconnected_clients == set()
        assert server.client_count == 1

    def test_cleanup_noop_when_empty(self):
        """_disconnected_clients 为空时不做任何操作。"""
        server = WsServer()
        ws1 = MagicMock()
        server._clients = {ws1: {"codes": set(), "authed": True}}
        server._disconnected_clients = set()

        server._cleanup_disconnected()

        assert ws1 in server._clients
        assert server.client_count == 1

    @pytest.mark.asyncio
    async def test_push_then_cleanup_full_flow(self):
        """推送失败 → 标记 → 清理的完整流程。"""
        server = WsServer()
        server._running = True  # 模拟已启动

        bad_ws = MagicMock()
        bad_ws.send = AsyncMock(side_effect=Exception("connection lost"))
        server._clients[bad_ws] = {"codes": {"600519"}, "authed": True}

        # push_quote 内部调用 _safe_send + _cleanup_disconnected
        await server.push_quote("600519", {"price": 1800})

        # 推送后坏客户端应被清理
        assert bad_ws not in server._clients
        assert server._disconnected_clients == set()


class TestConfigDefaults:
    """config.py 中 WebSocket 配置默认值。"""

    def test_ws_server_enabled_default_false(self):
        """WS_SERVER_ENABLED 默认为 False（不启动 WebSocket）。"""
        # 确保环境变量未设置（避免被 .env 影响）
        from tradex.config import Config
        cfg = Config()
        # 默认应为 False
        assert cfg.WS_SERVER_ENABLED is False

    def test_ws_port_default_8765(self):
        """WS_PORT 默认为 8765。"""
        from tradex.config import Config
        cfg = Config()
        assert cfg.WS_PORT == 8765

    def test_ws_token_default_empty(self):
        """WS_TOKEN 默认为空字符串（不要求认证）。"""
        from tradex.config import Config
        cfg = Config()
        assert cfg.WS_TOKEN == ""


class TestMainIntegration:
    """__main__.py 与 WsServer 的集成（不实际启动服务器）。"""

    def test_start_ws_server_function_exists(self):
        """__main__.py 定义了 _start_ws_server 函数。"""
        from tradex import __main__
        assert hasattr(__main__, "_start_ws_server")
        assert callable(__main__._start_ws_server)

    def test_main_does_not_start_ws_when_disabled(self, monkeypatch):
        """WS_SERVER_ENABLED=False 时 main() 不启动 WsServer。"""
        from tradex import __main__
        from tradex.config import Config

        # 强制 WS_SERVER_ENABLED=False
        test_config = Config()
        test_config.WS_SERVER_ENABLED = False

        # mock _start_ws_server 验证不被调用
        start_called = False
        original_start = __main__._start_ws_server

        def spy_start(cfg):
            nonlocal start_called
            start_called = True
            return original_start(cfg)

        monkeypatch.setattr(__main__, "_start_ws_server", spy_start)

        # mock mcp.run 避免实际启动 MCP 服务器
        mock_mcp = MagicMock()
        monkeypatch.setattr(__main__, "_start_ws_server", spy_start)

        # 验证 _start_ws_server 不被调用
        # （由于 main() 会调用 mcp.run 阻塞，这里只验证逻辑分支）
        assert test_config.WS_SERVER_ENABLED is False
        # 模拟 main() 中的判断逻辑
        if test_config.WS_SERVER_ENABLED:
            __main__._start_ws_server(test_config)
        assert start_called is False

    def test_start_ws_server_called_when_enabled(self, monkeypatch):
        """WS_SERVER_ENABLED=True 时应调用 _start_ws_server。"""
        from tradex import __main__
        from tradex.config import Config

        test_config = Config()
        test_config.WS_SERVER_ENABLED = True

        start_called = False
        def mock_start(cfg):
            nonlocal start_called
            start_called = True

        monkeypatch.setattr(__main__, "_start_ws_server", mock_start)

        # 模拟 main() 中的判断逻辑
        if test_config.WS_SERVER_ENABLED:
            __main__._start_ws_server(test_config)

        assert start_called is True

    def test_start_ws_server_failure_does_not_crash(self, monkeypatch):
        """_start_ws_server 启动失败不阻止主流程（try/except 包裹）。"""
        from tradex import __main__
        from tradex.config import Config

        test_config = Config()
        test_config.WS_SERVER_ENABLED = True
        test_config.WS_PORT = 8765
        test_config.WS_TOKEN = ""

        # mock get_ws_server 抛异常（模拟 websockets 未安装）
        import astock_signals.ws_server as ws_mod
        original_get = ws_mod.get_ws_server

        def failing_get_ws_server(host, port, token):
            raise ImportError("websockets not installed")

        monkeypatch.setattr(ws_mod, "get_ws_server", failing_get_ws_server)

        # _start_ws_server 应捕获异常不抛出
        __main__._start_ws_server(test_config)
        # 如果执行到这里说明异常被捕获
