"""
WebSocket 实时推送服务器。

用途：
- 实时行情推送（tick/quote 变动）
- 异动信号推送（涨停/跌停/大单/北向异动）
- 客户端按股票代码订阅

设计原则：
- 轻量级，基于 websockets 库
- JSON 格式消息
- 心跳保活（30秒间隔）
- 支持多客户端并发连接
- 默认绑定 127.0.0.1（仅本地访问）
- 可选 token 认证

依赖：pip install websockets（可选，不强制）
"""

from __future__ import annotations

import os
import json
import time
import asyncio
import logging
from typing import Optional, Set
from datetime import datetime

logger = logging.getLogger(__name__)


class WsServer:
    """WebSocket 实时推送服务器。

    Usage:
        server = WsServer(host="127.0.0.1", port=8765, token="my_secret")
        # 在异步上下文中：
        await server.start()
        await server.push_quote("600519", {"price": 1800, "change_pct": 1.5})
        # 客户端连接后发送 {"action":"auth","token":"my_secret"} 进行认证
        # 认证后发送 {"action":"subscribe","codes":["600519","000001"]}
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8765,
        token: str = "",
    ):
        self.host = host
        self.port = port
        self._token = token or os.environ.get("WS_TOKEN", "")
        self._clients: dict = {}  # websocket -> {"codes": set, "authed": bool}
        self._disconnected_clients: set = set()  # 已断开但未清理的客户端
        self._server = None
        self._running = False
        self._loop = None  # 运行 WsServer 的事件循环（跨线程推送用）

    async def start(self):
        """启动 WebSocket 服务器。"""
        try:
            import websockets
        except ImportError:
            logger.error("websockets not installed. Run: pip install websockets")
            raise

        self._loop = asyncio.get_running_loop()
        self._server = await websockets.serve(
            self._handler, self.host, self.port
        )
        self._running = True
        logger.info("WebSocket server started on ws://%s:%d (auth=%s)",
                     self.host, self.port, "required" if self._token else "disabled")

    async def stop(self):
        """停止 WebSocket 服务器。"""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._running = False
            logger.info("WebSocket server stopped")

    async def _handler(self, websocket, path=None):
        """处理单个客户端连接。"""
        self._clients[websocket] = {"codes": set(), "authed": not self._token}
        logger.info("Client connected: %s (auth=%s)",
                     websocket.remote_address, self._clients[websocket]["authed"])
        try:
            async for raw_msg in websocket:
                try:
                    msg = json.loads(raw_msg)
                    action = msg.get("action", "")

                    # 认证检查（仅在设置了 token 时要求）
                    if self._token and not self._clients[websocket]["authed"]:
                        if action == "auth" and msg.get("token") == self._token:
                            self._clients[websocket]["authed"] = True
                            await websocket.send(json.dumps({
                                "type": "auth", "status": "ok"
                            }))
                        else:
                            await websocket.send(json.dumps({
                                "type": "error", "message": "Authentication required"
                            }))
                        continue

                    if action == "auth":
                        # 已认证状态重复 auth
                        await websocket.send(json.dumps({
                            "type": "auth", "status": "already_authenticated"
                        }))

                    elif action == "subscribe":
                        codes = msg.get("codes", [])
                        self._clients[websocket]["codes"].update(codes)
                        await websocket.send(json.dumps({
                            "type": "subscribed",
                            "codes": list(self._clients[websocket]["codes"]),
                        }))

                    elif action == "unsubscribe":
                        codes = msg.get("codes", [])
                        self._clients[websocket]["codes"] -= set(codes)
                        await websocket.send(json.dumps({
                            "type": "unsubscribed",
                            "codes": list(self._clients[websocket]["codes"]),
                        }))

                    elif action == "ping":
                        await websocket.send(json.dumps({"type": "pong"}))

                    elif action == "status":
                        await websocket.send(json.dumps({
                            "type": "status",
                            "connected_clients": len(self._clients),
                            "subscriptions": list(self._clients[websocket]["codes"]),
                        }))

                except json.JSONDecodeError:
                    await websocket.send(json.dumps({
                        "type": "error", "message": "Invalid JSON"
                    }))

        except Exception as e:
            logger.debug("Client disconnected: %s", e)
        finally:
            self._clients.pop(websocket, None)

    def _get_subscribed_clients(self, code: str) -> list:
        """获取订阅了指定代码且已认证的客户端列表。"""
        return [
            ws for ws, info in self._clients.items()
            if info["authed"] and (code in info["codes"] or "*" in info["codes"])
        ]

    async def push_quote(self, code: str, data: dict):
        """推送行情数据到订阅了该代码的所有客户端。"""
        if not self._running:
            return

        msg = json.dumps({
            "type": "quote",
            "code": code,
            "data": data,
            "timestamp": datetime.now().isoformat(),
        }, ensure_ascii=False)

        targets = self._get_subscribed_clients(code)
        if targets:
            await asyncio.gather(
                *[self._safe_send(ws, msg) for ws in targets],
                return_exceptions=True,
            )
        self._cleanup_disconnected()

    async def push_signal(self, signal_type: str, data: dict):
        """推送异动信号到所有已认证客户端（全局广播）。"""
        if not self._running:
            return

        msg = json.dumps({
            "type": "signal",
            "signal_type": signal_type,
            "data": data,
            "timestamp": datetime.now().isoformat(),
        }, ensure_ascii=False)

        targets = [ws for ws, info in self._clients.items() if info["authed"]]
        if targets:
            await asyncio.gather(
                *[self._safe_send(ws, msg) for ws in targets],
                return_exceptions=True,
            )
        self._cleanup_disconnected()

    async def push_tick(self, code: str, tick_data: dict):
        """推送 tick 数据到订阅了该代码的所有客户端。"""
        if not self._running:
            return

        msg = json.dumps({
            "type": "tick",
            "code": code,
            "data": tick_data,
            "timestamp": datetime.now().isoformat(),
        }, ensure_ascii=False)

        targets = self._get_subscribed_clients(code)
        if targets:
            await asyncio.gather(
                *[self._safe_send(ws, msg) for ws in targets],
                return_exceptions=True,
            )
        self._cleanup_disconnected()

    async def _safe_send(self, ws, msg: str):
        """安全发送消息（异常时标记为已断开，不立即移除）。"""
        try:
            await ws.send(msg)
        except Exception as e:
            logger.debug("safe_send failed, marking client disconnected: %s", e)
            self._disconnected_clients.add(ws)

    def _cleanup_disconnected(self):
        """统一清理已断开的客户端（在推送方法结束后调用）。"""
        if not self._disconnected_clients:
            return
        for ws in self._disconnected_clients:
            self._clients.pop(ws, None)
        self._disconnected_clients.clear()

    @property
    def client_count(self) -> int:
        return len(self._clients)

    @property
    def is_running(self) -> bool:
        return self._running


# 全局单例
_global_ws: WsServer | None = None


def get_ws_server(host: str = "127.0.0.1", port: int = 8765, token: str = "") -> WsServer:
    global _global_ws
    if _global_ws is None:
        _global_ws = WsServer(host, port, token)
    return _global_ws
