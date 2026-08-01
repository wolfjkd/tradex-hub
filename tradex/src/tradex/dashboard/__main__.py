"""tradex 数据源看板 - 轻量 HTTP 服务。

启动：python -m tradex.dashboard
默认端口 8765（环境变量 TRADEX_DASHBOARD_PORT 可配置）

路由：
  GET /                → HTML 看板页面（单页应用，CSS/JS 全内联）
  GET /api/dashboard   → 看板数据 JSON（与 MCP 工具 get_data_source_dashboard 结构一致）
"""

from __future__ import annotations

import asyncio
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

_HTML_CACHE: str | None = None
_TOOL_COUNT: int | None = None


def _get_html() -> str:
    """读取并缓存 index.html（与本文件同目录）。"""
    global _HTML_CACHE
    if _HTML_CACHE is None:
        html_path = Path(__file__).parent / "index.html"
        _HTML_CACHE = html_path.read_text(encoding="utf-8")
    return _HTML_CACHE


def _get_tool_count() -> int:
    """获取 MCP 工具总数（首次调用后缓存，工具数启动后不变）。"""
    global _TOOL_COUNT
    if _TOOL_COUNT is None:
        try:
            from tradex.server import mcp

            _TOOL_COUNT = len(asyncio.run(mcp.list_tools()))
        except Exception:
            _TOOL_COUNT = 0
    return _TOOL_COUNT


def get_dashboard_data() -> dict:
    """获取看板数据（复用 diagnostics.build_dashboard_data 逻辑）。"""
    # 确保数据源已注册（幂等）
    try:
        from tradex.data_sources import register_all_sources

        register_all_sources()
    except Exception:
        pass
    from tradex.tools.diagnostics import build_dashboard_data

    return build_dashboard_data(tool_count=_get_tool_count())


class DashboardHandler(BaseHTTPRequestHandler):
    """看板 HTTP 请求处理器。"""

    def do_GET(self):  # noqa: N802 - stdlib 接口命名
        if self.path == "/api/dashboard":
            self._handle_api()
        elif self.path in ("/", "/index.html"):
            self._handle_html()
        else:
            self.send_error(404)

    def _handle_html(self):
        try:
            body = _get_html().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def _handle_api(self):
        try:
            data = get_dashboard_data()
            self._send_json(200, data)
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A002 - stdlib 签名
        # 静默默认日志，避免刷屏
        pass


def main():
    port = int(os.environ.get("TRADEX_DASHBOARD_PORT", "8765"))
    server = HTTPServer(("127.0.0.1", port), DashboardHandler)
    print(f"tradex 数据源看板启动: http://127.0.0.1:{port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n看板已停止")
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
