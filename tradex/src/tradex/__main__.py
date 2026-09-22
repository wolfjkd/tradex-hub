"""
Entry point for running the tradex server.

Usage:
    python -m tradex                    # stdio mode (default)
    python -m tradex --http             # HTTP gateway: Streamable HTTP + legacy SSE + /health
    python -m tradex --http --port 9000 # HTTP gateway on custom port

HTTP gateway 端点 (v3.3.12+)：
    POST /mcp      Streamable HTTP 主端点 (Dify/LangChain 新版首选)
    GET  /sse      legacy SSE 端点 (旧客户端兼容)
    GET  /health   健康检查 (docker healthcheck)

Host 校验 (v3.3.12+)：
    默认仅允许本机回环访问（SDK DNS rebinding 防护，伪造 Host 返回 421）。
    监听默认 0.0.0.0（云/容器形态，与代理无关；数据源流量永远直连，代理仅供 GitHub）。
    对外部署用 --allowed-hosts 或 MCP_ALLOWED_HOSTS 放行；'*' 关闭防护全放行（仅限可信内网）。

环境变量：
    MCP_HOST=0.0.0.0             HTTP 网关监听地址（--host 覆盖）
    MCP_PORT=8000                HTTP 网关监听端口（--port 覆盖）
    MCP_ALLOWED_HOSTS=           逗号分隔 Host 白名单 / * 全放行（--allowed-hosts 覆盖）
    WS_SERVER_ENABLED=true       启用 WebSocket 推送服务
    WS_PORT=8765                 WebSocket 端口
    WS_TOKEN=xxx                 WebSocket 认证 token
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

    logger = logging.getLogger("tradex.ws")
    try:

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
        description="tradex: China Financial Data MCP Server based on AKShare"
    )
    parser.add_argument(
        "--http",
        action="store_true",
        help="Run in HTTP gateway mode (Streamable HTTP /mcp + legacy SSE + /health)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port for HTTP gateway (default: MCP_PORT or 8000)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="Host for HTTP gateway (default: MCP_HOST or 0.0.0.0)",
    )
    parser.add_argument(
        "--allowed-hosts",
        type=str,
        default=None,
        help=(
            "Comma-separated Host allowlist, or '*' to allow any Host by disabling "
            "DNS rebinding protection (default: MCP_ALLOWED_HOSTS)"
        ),
    )
    args = parser.parse_args()

    from .server import mcp
    from .config import config

    # 可选：启动 WebSocket 推送服务（WS_SERVER_ENABLED=true 时启用）
    if config.WS_SERVER_ENABLED:
        _start_ws_server(config)

    if args.http:
        # v3.3.12+: 统一 HTTP 网关（/mcp + /sse + /health），原生支持免 supergateway。
        # host/port 优先级：CLI 显式值 > MCP_HOST/MCP_PORT 环境变量 > 默认值。
        from .http_server import run as run_http_gateway, parse_allowed_hosts

        host = args.host if args.host is not None else config.MCP_HOST
        port = args.port if args.port is not None else config.MCP_PORT
        allowed = (
            args.allowed_hosts
            if args.allowed_hosts is not None
            else config.MCP_ALLOWED_HOSTS
        )
        run_http_gateway(mcp, host=host, port=port, allowed_hosts=parse_allowed_hosts(allowed))
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
