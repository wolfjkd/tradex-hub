"""
Entry point for running the cn-financial-mcp server.

Usage:
    python -m cn_financial_mcp                    # stdio mode (default)
    python -m cn_financial_mcp --http             # HTTP/SSE mode
    python -m cn_financial_mcp --http --port 9000 # HTTP/SSE on custom port

环境变量：
    WS_SERVER_ENABLED=true   启用 WebSocket 推送服务
    WS_PORT=8765             WebSocket 端口
    WS_TOKEN=xxx             WebSocket 认证 token
"""

import argparse
import sys


def _start_ws_server(config):
    """启动 WebSocket 推送服务（独立线程 + 独立事件循环）。

    启动失败不阻止 MCP server 启动（try/except 包裹）。
    """
    import os
    import asyncio
    import threading
    import logging

    logger = logging.getLogger("cn-financial-mcp.ws")
    try:
        _HUB_SRC = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "src")
        )
        if _HUB_SRC not in sys.path:
            sys.path.insert(0, _HUB_SRC)

        from astock_signals.ws_server import get_ws_server

        ws_server = get_ws_server(
            host="127.0.0.1",
            port=config.WS_PORT,
            token=config.WS_TOKEN,
        )

        def _run_ws():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(ws_server.start())
                loop.run_forever()
            except Exception as e:
                logger.warning("WsServer event loop stopped: %s", e)
            finally:
                loop.close()

        ws_thread = threading.Thread(target=_run_ws, daemon=True, name="ws-server")
        ws_thread.start()
        logger.info(
            "WebSocket push service started on 127.0.0.1:%d (auth=%s)",
            config.WS_PORT,
            "required" if config.WS_TOKEN else "disabled",
        )
    except Exception as e:
        logger.warning(
            "WsServer startup failed (MCP server will continue): %s", e
        )


def main():
    parser = argparse.ArgumentParser(
        description="cn-financial-mcp: China Financial Data MCP Server based on AKShare"
    )
    parser.add_argument(
        "--http",
        action="store_true",
        help="Run in HTTP/SSE mode instead of stdio",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for HTTP/SSE mode (default: 8000)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host for HTTP/SSE mode (default: 127.0.0.1)",
    )
    args = parser.parse_args()

    from .server import mcp
    from .config import config

    # 可选：启动 WebSocket 推送服务（WS_SERVER_ENABLED=true 时启用）
    if config.WS_SERVER_ENABLED:
        _start_ws_server(config)

    if args.http:
        mcp._host = args.host
        mcp._port = args.port
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
