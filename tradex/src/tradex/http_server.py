"""
tradex HTTP 网关（v3.3.12 起）。

把 FastMCP 实例包装成单端口多端点的 HTTP 服务，原生支持 MCP 两种远程传输：

- ``GET/POST /mcp``        Streamable HTTP 主端点（MCP 2025 新标准传输，
                          新版 Dify / LangChain / Claude 远程客户端首选）
- ``GET /sse``             legacy SSE 传输端点（旧客户端兼容，MCP 官方已标 deprecated）
- ``POST /messages/``      legacy SSE 的消息回传端点（由 /sse 握手返回）
- ``GET /health``          健康检查（容器化运维 / docker healthcheck / K8s probe）

设计要点：
- **零新增依赖**：基于 mcp SDK（>=1.9）原生 ``streamable_http_app()`` /
  ``sse_app()``，两者返回的 Starlette app 路由天然不冲突（/mcp vs /sse,/messages），
  直接合并路由到统一网关即可，无需 supergateway 等外部转发进程。
- **/health 轻量**：只报进程态 + 版本 + 工具数 + 运行时长，不触发网络探测
  （避免慢数据源拖垮探活，呼应 SmartRouter 健康检测 300s 缓存的既有经验）。
- **Host 校验可配**（v3.3.12+ 增强）：默认沿用 SDK DNS rebinding 防护（仅本机回环），
  绑 0.0.0.0 对外部署时通过 ``allowed_hosts`` / ``MCP_ALLOWED_HOSTS`` 放行；
  含 ``*`` 关闭防护全放行（仅限可信内网）。
- **网络边界**：监听地址（默认 0.0.0.0）与代理无关；数据源流量永远直连，
  代理（本机 127.0.0.1:7897 Clash）仅用于 GitHub push/clone，禁止用作服务/网关地址。
- **stdio 不受影响**：本地 WorkBuddy / Claude Code connector 继续走 stdio。

用法：:

    python -m tradex --http                                            # 默认 0.0.0.0:8000（配合 --allowed-hosts）
    python -m tradex --http --allowed-hosts 47.102.x.x                # 公网白名单（数据源仍直连）
    python -m tradex --http --allowed-hosts '*'                       # 仅可信内网全放行
"""

import logging
import time
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

logger = logging.getLogger(__name__)

_start_time = time.time()
_tools_count: int = 0

# 始终保留的本机回环白名单 —— 属 SDK Host 安全校验的 localhost 家族
# （保证配了公网白名单后本机回环仍可访问），与代理地址无关，勿删除。
_LOCALHOST_ALLOWLIST = ("127.0.0.1", "localhost", "[::1]")


def parse_allowed_hosts(raw: str | None) -> list[str]:
    """解析逗号分隔的 Host 白名单为列表（空串/None → 空列表=沿用 SDK 默认）。"""
    if not raw:
        return []
    return [item.strip() for item in str(raw).split(",") if item.strip()]


def is_allow_any_host(hosts: list[str]) -> bool:
    """白名单含 ``*`` / ``*:*`` 表示允许任意 Host（含 0.0.0.0）。

    FastMCP 的 Host 匹配只支持精确值或 ``host:*`` 端口通配，裸 ``*`` 不会匹配
    ``0.0.0.0:port``，因此允许任意 Host 时必须关闭 DNS rebinding 防护。
    """
    return any(h.strip() in ("*", "*:*") for h in hosts)


def _normalize_host_patterns(hosts: list[str]) -> list[str]:
    """补全 Host 匹配模式：裸 IP/域名同时允许任意端口（追加 ``host:*``）。"""
    patterns: list[str] = []
    seen: set[str] = set()

    def add(item: str) -> None:
        if item and item not in seen:
            seen.add(item)
            patterns.append(item)

    for raw in hosts:
        host = raw.strip()
        if not host:
            continue
        add(host)
        if host.endswith(":*"):
            continue
        if host.startswith("[") and host.endswith("]"):  # IPv6 [::1]
            add(f"{host}:*")
        elif ":" not in host:
            add(f"{host}:*")
    return patterns


def _origins_from_host_patterns(host_patterns: list[str]) -> list[str]:
    """由 Host 白名单推导允许的 http Origin（浏览器跨域场景需要）。"""
    origins: list[str] = []
    seen: set[str] = set()
    for host in host_patterns:
        if host.endswith(":*"):
            origin = f"http://{host[:-2]}:*"
        else:
            origin = f"http://{host}"
        if origin not in seen:
            seen.add(origin)
            origins.append(origin)
    return origins


def apply_transport_security(mcp, allowed_hosts: list[str] | None = None) -> None:
    """配置 mcp SDK 的 Host/Origin 校验（DNS rebinding 防护）。

    - ``allowed_hosts`` 为空/None → 不改动，沿用 SDK 默认（仅 localhost，最安全）
    - 含 ``*`` → 关闭防护、全放行（仅限可信内网；绑 0.0.0.0 时 ``*`` 才真正可访问）
    - 其它 → 白名单 = localhost 三件套 + 用户列表，自动补 ``host:*`` 端口通配与
      http Origin（enable_dns_rebinding_protection 保持开启）
    """
    extra = [h for h in (allowed_hosts or []) if h]
    if not extra:
        return
    try:
        from mcp.server.transport_security import TransportSecuritySettings
    except ImportError:  # 极老 SDK 无此模块：保持默认
        logger.warning("TransportSecuritySettings unavailable, skip host allowlist")
        return

    settings = getattr(mcp, "settings", None)
    if settings is None:
        return

    if is_allow_any_host(extra):
        settings.transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
            allowed_hosts=["*"],
            allowed_origins=["*"],
        )
        logger.warning("MCP host check DISABLED (allow any host) — 仅限可信内网使用")
    else:
        patterns = _normalize_host_patterns([*_LOCALHOST_ALLOWLIST, *extra])
        settings.transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=patterns,
            allowed_origins=_origins_from_host_patterns(patterns),
        )
    logger.info(
        "MCP host allowlist set: dns_rebinding=%s hosts=%s",
        settings.transport_security.enable_dns_rebinding_protection,
        settings.transport_security.allowed_hosts,
    )


async def _count_tools(mcp) -> int:
    """统计已注册工具数（FastMCP 公开 API list_tools，async 返回 list）。"""
    try:
        tools = await mcp.list_tools()
        return len(tools)
    except Exception as exc:  # noqa: BLE001
        logger.debug("count tools failed: %s", exc)
        return 0


async def _health(request) -> JSONResponse:
    """健康检查：轻量探活，不触发任何数据源网络请求。"""
    from tradex import __version__

    return JSONResponse(
        {
            "status": "ok",
            "service": "tradex-mcp",
            "version": __version__,
            "tools": _tools_count,
            "uptime_seconds": round(time.time() - _start_time, 1),
        }
    )


def build_app(mcp, allowed_hosts: list[str] | None = None) -> Starlette:
    """构造统一 HTTP 网关：/health + Streamable HTTP(/mcp) + legacy SSE(/sse,/messages)。

    子 app 的 Route/Mount 对象直接复用（各自闭包绑定对应 transport 的 session 管理），
    合并进外层 Starlette 即可单端口共存。

    Args:
        mcp: FastMCP 实例（129 工具已注册）
        allowed_hosts: Host 校验白名单（见 apply_transport_security），
            None/空=沿用 SDK 默认仅 localhost。必须在调用子 app 前配置，
            因为 streamable_http_app()/sse_app() 创建时会读取 transport_security。
    """
    apply_transport_security(mcp, allowed_hosts)

    @asynccontextmanager
    async def lifespan(app):
        # 必须嵌套执行 SDK 子 app 的进程级 lifespan：
        # streamable_http_app / sse_app 各自的 lifespan 会初始化共享 anyio task group，
        # 否则 handle_request 抛 "Task group is not initialized"。
        # tradex.server 的 FastMCP user lifespan 由 SDK 按会话自动触发，无需在此重复。
        async with http_app.router.lifespan_context(app):
            async with sse_app.router.lifespan_context(app):
                global _tools_count
                _tools_count = await _count_tools(mcp)
                logger.info("tradex HTTP gateway ready: tools=%d", _tools_count)
                yield

    http_app = mcp.streamable_http_app()  # Streamable HTTP（主端点 /mcp）
    sse_app = mcp.sse_app()  # legacy SSE（/sse + /messages）

    routes = [Route("/health", _health, methods=["GET"])]
    routes.extend(http_app.routes)
    routes.extend(sse_app.routes)

    return Starlette(routes=routes, lifespan=lifespan)


def run(
    mcp,
    host: str = "0.0.0.0",
    port: int = 8000,
    allowed_hosts: list[str] | None = None,
) -> None:
    """用 uvicorn 启动 HTTP 网关（阻塞调用）。

    Args:
        host: 监听地址，默认 0.0.0.0（云/容器形态；与代理无关，数据源仍直连）。
            仅本机调试可传 "localhost"。
        allowed_hosts: 透传 build_app（见 apply_transport_security）。
    """
    import uvicorn

    app = build_app(mcp, allowed_hosts=allowed_hosts)
    uvicorn.run(app, host=host, port=port, log_level="info")
