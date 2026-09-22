"""
tdx_mcp_fetchers.py - 通达信官方 MCP 数据源 fetch_fn 包装器（v0.1.0-DEV）

============================================================
接入 tradex-hub 多源中台的「平级第一梯队」数据源。

定位（老板 2026-09-21 拍板 · SP-2026-09-21-001）：
  - 与 eltdx 同属 priority=1，互为第一梯队、互为备份。
  - 通过 SmartRouter 健康分动态互备：eltdx 故障时自动切到本源，恢复后自动切回。
  - 认证走独立 env `TDX_MCP_TOKEN`（.env），与 WB connector 解耦，开源可分发。

传输协议：
  官方通达信 MCP 使用标准 MCP streamable-HTTP（JSON-RPC 2.0 over HTTP）。
  本模块实现了一个极简 MCP 客户端，向 `TDX_MCP_ENDPOINT` 发起 tools/list + tools/call，
  调用官方魔供的稳定工具名（tdx_quotes / tdx_kline / tdx_screener / wenda_report_query 等），
  并将响应归一化为 SmartRouter 期望的 dict/list 结构。

铁律（对齐 data_sources/__init__.py）：
  仅本文件允许直接发起对该官方 MCP 的 HTTP 请求。
  所有 L1 工具必须通过 SmartRouter.route() 获取数据，不得直接 import 本模块。
"""

from __future__ import annotations

import json
import logging
import random
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

logger = logging.getLogger("tradex.tdx_mcp")

# 默认官方端点（token 未给时不可用，降级走 eltdx）
_DEFAULT_ENDPOINT = "https://txmcp.tdx.com.cn:3001/txmcp"

# 限流：TDX 官方 MCP 未公开风控阈值，保守起见串行节流。
# 可经 env TDX_MCP_MIN_INTERVAL 覆盖（秒）。
_DEFAULT_MIN_INTERVAL = 0.8
_tdx_last_call = [0.0]
_tdx_throttle_lock = threading.Lock()

# 模块级客户端缓存（token 变更需重载）
_CLIENT: Optional["TDXMCPClient"] = None


class TDXSourceUnavailable(RuntimeError):
    """通达信官方 MCP 不可用（缺 token / 连接失败 / 认证失败）。

    SmartRouter 的 route() 会把它当普通源失败处理：标记健康分、自动切到 eltdx。
    不设置 exclusive，保证「非独占 + 自动降级」。
    """


def _get_env(key: str, default: str = "") -> str:
    """读取 env；未设置时回退默认。config.py 已在 import 时 load_dotenv()。"""
    return __import__("os").getenv(key, default)


@dataclass
class TDXMCPClient:
    """极简 MCP streamable-HTTP 客户端。

    仅实现当前需要的子集：JSON-RPC 2.0 的 initialize / tools/call。
    endpoint 支持 path-only（仅划线基址），wire 协议遵循 MCP spec：
      - POST，headers: Content-Type: application/json, Accept: application/json, text/event-stream
      - 每次请求透传所有 header 行「Authorization: Bearer <token>」
      - 响应 body 可能为单 JSON 或 SSE 流（在此都被解析为 JSON）。
    """

    endpoint: str
    token: str
    session_id: Optional[str] = field(default=None, init=False)
    timeout: float = 15.0

    _client: httpx.Client = field(default=None, init=False, repr=False)

    def __post_init__(self):
        self._client = httpx.Client(timeout=self.timeout)

    @property
    def headers(self) -> dict:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        return headers

    def _post_json(self, payload: dict) -> dict:
        """发 JSON-RPC 请求，解出 result；HTTP/协议错误归为源不可用。"""
        # 限流：串行节流防官方风控；检查-等待-发出在同一把锁内，多线程并发安全。
        min_interval = float(__import__("os").getenv("TDX_MCP_MIN_INTERVAL", _DEFAULT_MIN_INTERVAL))
        with _tdx_throttle_lock:
            wait = min_interval - (time.time() - _tdx_last_call[0])
            if wait > 0:
                time.sleep(wait + random.uniform(0.05, 0.2))
            try:
                resp = self._client.post(self.endpoint, json=payload, headers=self.headers)
                if "Mcp-Session-Id" in resp.headers:
                    self.session_id = resp.headers["Mcp-Session-Id"]
                # httpx.Response.text 是 str；此处读出来交给解析器，
                # 避免把整个 Response 对象当字符串处理。
                data = _parse_mcp_response(resp.text)
            except TDXSourceUnavailable:
                raise
            except Exception as e:  # httpx 网络错误 / 解析错误
                raise TDXSourceUnavailable(f"tdx_mcp 网络错误: {e}") from e
            finally:
                _tdx_last_call[0] = time.time()

        err = data.get("error")
        if err:
            logger.warning("tdx_mcp RPC error: %s", err)
            raise TDXSourceUnavailable(f"tdx_mcp RPC 错误: {err}")
        return data.get("result") or {}

    def call_tool(self, tool_name: str, arguments: dict) -> Any:
        """MCP tools/call。返回工具结果（list[dict]）。"""
        if not tool_name:
            raise TDXSourceUnavailable("tdx_mcp: 空工具名")
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        return self._post_json(payload)


def _parse_mcp_response(text: str) -> dict:
    """解析 MCP 响应：兼容纯 JSON 与 SSE 事件流（data: {...} 行）。

    MCP 返回既可能是单块 JSON，也可能是 text/event-stream。
    """
    text = (text or "").strip()
    if not text:
        raise TDXSourceUnavailable("tdx_mcp: 空响应")
    if text.startswith("{"):
        return json.loads(text)
    # SSE：取所有 "data: {...}" 的最后一个完整 JSON
    import re
    chunks = re.findall(r'data:\s*(\{.*?\})\s*(?:\n|$)', text, re.S)
    for chunk in reversed(chunks):
        try:
            return json.loads(chunk)
        except Exception:
            continue
    # 最后兜底：整段按 JSON 解析
    return json.loads(text)


def _get_client() -> TDXMCPClient:
    """惰性构建客户端。token 缺省时抛 TDXSourceUnavailable（降级）。"""
    global _CLIENT
    token = _get_env("TDX_MCP_TOKEN")
    if not token:
        raise TDXSourceUnavailable("TDX_MCP_TOKEN 未配置，tdx_mcp 数据源不可用（已降级 eltdx）")
    if _CLIENT is None:
        endpoint = _get_env("TDX_MCP_ENDPOINT", _DEFAULT_ENDPOINT)
        _CLIENT = TDXMCPClient(endpoint=endpoint, token=token)
    return _CLIENT


def _normalize_symbol_code(symbol: str = "", code: str = "") -> str:
    """归一化 symbol/code：SmartRouter 路由时两者可能混用，统一取非空者。"""
    return symbol or code or ""


# ============================================================================
# 供 SmartRouter 注册的 fetch_fn（统一签名：兼容 symbol/code）
# ============================================================================

def fetch_realtime_quote(code: str = "", symbol: str = "", **kwargs) -> Any:
    """实时行情（平级第一梯队，与 eltdx 互为备份）。调用官方 tdx_quotes。"""
    cli = _get_client()
    norm = _normalize_symbol_code(symbol, code)
    if not norm:
        raise TDXSourceUnavailable("tdx_mcp: 缺少证券代码")
    result = cli.call_tool("tdx_quotes", {"codes": [norm]})
    return result


def fetch_historical_kline(code: str = "", symbol: str = "", period: str = "day", count: int = 120, **kwargs) -> Any:
    """历史 K 线（与 eltdx 互备）。官方 tdx_kline。"""
    cli = _get_client()
    norm = _normalize_symbol_code(symbol, code)
    if not norm:
        raise TDXSourceUnavailable("tdx_mcp: 缺少代码")
    result = cli.call_tool(
        "tdx_kline",
        {"code": norm, "period": period, "count": count},
    )
    return result


def fetch_research_report(code: str = "", symbol: str = "", keyword: str = "", limit: int = 20, **kwargs) -> Any:
    """券商研报（纯增量类型）：调用 wenda_report_query。"""
    cli = _get_client()
    norm = _normalize_symbol_code(symbol, code)
    args: dict = {"limit": limit}
    if norm:
        args["code"] = norm
    if keyword:
        args["keyword"] = keyword
    return cli.call_tool("wenda_report_query", args)


def fetch_macro_data(indicator: str = "CPI", **kwargs) -> Any:
    """宏观数据（增强）：调用 wenda_macro_query。"""
    cli = _get_client()
    return cli.call_tool("wenda_macro_query", {"indicator": indicator})


def fetch_screener(query: str = "", limit: int = 20, **kwargs) -> Any:
    """自然语言条件选股（纯增量独立工具）：调用官方 tdx_screener。"""
    cli = _get_client()
    if not query:
        raise TDXSourceUnavailable("tdx_mcp: screener 缺 query")
    return cli.call_tool("tdx_screener", {"query": query, "limit": limit})


# 供 registry 导入的命名空间（对齐 eltdx/akshare 惯例）
fetch_functions = {
    "realtime_quote": fetch_realtime_quote,
    "historical_kline": fetch_historical_kline,
    "research_report": fetch_research_report,
    "macro_data": fetch_macro_data,
    "screener": fetch_screener,
}