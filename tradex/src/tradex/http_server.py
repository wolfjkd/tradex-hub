"""
tradex HTTP 网关（v3.3.12 起，v3.4.0 阶段一工单 01 加入 REST 层）。

把 FastMCP 实例包装成单端口多端点的 HTTP 服务：

- ``GET/POST /mcp``        Streamable HTTP 主端点（MCP 2025 新标准传输，
                          新版 Dify / LangChain / Claude 远程客户端首选）
- ``GET /sse``             legacy SSE 传输端点（旧客户端兼容，MCP 官方已标 deprecated）
- ``POST /messages/``      legacy SSE 的消息回传端点（由 /sse 握手返回）
- ``GET /health``          健康检查（容器化运维 / docker healthcheck / K8s probe）
- ``GET /api/v1/*``        REST 端点（v3.4.0 阶段一工单 01 起，双协议 MCP+REST 并存）
- ``GET /docs``            FastAPI 自动生成的 OpenAPI 文档（含 /api/v1/* 端点）

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

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.applications import Starlette
from starlette.routing import Mount, Route

# 阶段一工单 01：REST 层骨架
from tradex.api import routes as rest_routes
from tradex.api.schemas import (
    ERR_BAD_REQUEST,
    ERR_DATA_SOURCE_UNREACHABLE,
    ERR_INTERNAL,
    ERR_NOT_FOUND,
    envelope_err,
)

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
    """健康检查：轻量探活，不触发任何数据源网络请求。

    Args:
        request: 兼容 Starlette/FastAPI 的 Request 对象（未使用，但签名需要）。
    """
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


async def _prometheus_metrics(request):
    """Prometheus 文本格式指标端点（工单 11）。

    Prometheus 标准约定路径为 /metrics（不带 /api/v1 前缀）。
    返回 Content-Type: text/plain; version=0.0.4。
    """
    from fastapi.responses import PlainTextResponse
    from tradex.metrics import render_prometheus_text

    return PlainTextResponse(
        render_prometheus_text(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


async def _dashboard_page(request):
    """监控看板 HTML 页（工单 12）。"""
    from fastapi.responses import HTMLResponse
    from tradex.api.routes.dashboard import _DASHBOARD_HTML

    return HTMLResponse(_DASHBOARD_HTML)


def _register_exception_handlers(app: FastAPI) -> None:
    """注册统一异常处理 + 响应包裹中间件（阶段一工单 01）。

    作用范围：仅 /api/* 路径；MCP/health 端点保持原行为。

    两层保障：
    1) HTTPException handler：捕获端点内主动抛出的 HTTPException（如 400/404）
    2) Response 包裹中间件：捕获未匹配路由的 404、以及任何非 200 响应，
       对 /api/* 路径统一转成 {code,data,msg} 包裹格式
    """
    from fastapi.responses import Response as FastAPIResponse

    @app.exception_handler(HTTPException)
    async def _http_exc_handler(request: Request, exc: HTTPException) -> JSONResponse:
        path = request.url.path
        if not path.startswith("/api/"):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        code_map = {
            400: ERR_BAD_REQUEST,
            404: ERR_NOT_FOUND,
            422: ERR_BAD_REQUEST,
            500: ERR_INTERNAL,
            502: ERR_DATA_SOURCE_UNREACHABLE,
        }
        code = code_map.get(exc.status_code, ERR_INTERNAL)
        return JSONResponse(
            envelope_err(code, str(exc.detail)).model_dump(),
            status_code=exc.status_code,
        )

    @app.exception_handler(Exception)
    async def _unhandled_exc_handler(request: Request, exc: Exception) -> JSONResponse:
        path = request.url.path
        if not path.startswith("/api/"):
            return JSONResponse({"detail": "Internal Server Error"}, status_code=500)
        logger.exception("Unhandled exception on %s: %s", path, exc)
        return JSONResponse(
            envelope_err(ERR_INTERNAL, "internal error").model_dump(),
            status_code=500,
        )

    # 响应包裹中间件：处理 Starlette 默认 404（未匹配路由）等情况
    @app.middleware("http")
    async def _envelope_non_200_for_api(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        # 仅对 /api/* 路径且状态码非 200 时包裹；成功路径由端点自己返回 Envelope
        if path.startswith("/api/") and response.status_code != 200:
            # 读原 body 并判断是否已是包裹格式（避免重复包裹）
            import json
            try:
                body_bytes = b""
                async for chunk in response.body_iterator:
                    body_bytes += chunk
                try:
                    body = json.loads(body_bytes)
                except Exception:
                    body = {"raw": body_bytes.decode(errors="replace")}
                # 已是包裹格式（含 code 键）则原样返回
                if isinstance(body, dict) and "code" in body:
                    return JSONResponse(body, status_code=response.status_code)
                # 未包裹：按状态码映射并包裹
                # 422 = FastAPI Query/Pydantic 校验失败 → 归入参数错误 40001
                # 502 = 端点内抛 HTTPException(502) 表示数据源不可达 → 50001（由 handler 处理，
                #       但若端点直接返回 502 response 则由此处兜底）
                code_map = {
                    400: ERR_BAD_REQUEST,
                    404: ERR_NOT_FOUND,
                    422: ERR_BAD_REQUEST,
                    500: ERR_INTERNAL,
                    502: ERR_DATA_SOURCE_UNREACHABLE,
                }
                code = code_map.get(response.status_code, ERR_INTERNAL)
                # 422 FastAPI 返回 body 是 {"detail":[{...校验错误列表...}]}，序列化成简洁 msg
                if response.status_code == 422 and isinstance(body, dict):
                    import json as _json
                    msg = _json.dumps(body.get("detail", "validation error"), ensure_ascii=False)
                else:
                    msg = body.get("detail") if isinstance(body, dict) else str(body)
                return JSONResponse(
                    envelope_err(code, str(msg or "error")).model_dump(),
                    status_code=response.status_code,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("envelope middleware error: %s", exc)
                return response
        return response


def build_app(mcp, allowed_hosts: list[str] | None = None) -> FastAPI:
    """构造统一 HTTP 网关：FastAPI 外层 + /health + /mcp + /sse + /api/v1/* REST。

    架构（阶段一工单 01）：
    - 最外层：FastAPI（Starlette 超集，零风险升级）
    - /health：轻量健康检查（行为不变）
    - /mcp, /sse, /messages：MCP 子 app 路由（来自 streamable_http_app/sse_app，
      直接合并到 FastAPI 的 routes 列表，行为与原 Starlette 一致）
    - /api/v1/*：REST 层（工单 01 只挂 ping，后续工单填充业务端点）
    - 异常处理：/api/* 路径的 HTTPException 转成 {code,data,msg} 包裹格式

    Args:
        mcp: FastMCP 实例（129 工具已注册）
        allowed_hosts: Host 校验白名单（见 apply_transport_security）。
    """
    apply_transport_security(mcp, allowed_hosts)

    @asynccontextmanager
    async def lifespan(app):
        # 必须嵌套执行 SDK 子 app 的进程级 lifespan：
        # streamable_http_app / sse_app 各自的 lifespan 会初始化共享 anyio task group，
        # 否则 handle_request 抛 "Task group is not initialized"。
        async with http_app.router.lifespan_context(app):
            async with sse_app.router.lifespan_context(app):
                global _tools_count
                _tools_count = await _count_tools(mcp)
                logger.info("tradex HTTP gateway ready: tools=%d", _tools_count)
                yield

    http_app = mcp.streamable_http_app()  # Streamable HTTP（主端点 /mcp）
    sse_app = mcp.sse_app()  # legacy SSE（/sse + /messages）

    # 1) 原有路由（/health + /metrics + /dashboard + MCP 子 app 路由）保持不变
    routes: list = [
        Route("/health", _health, methods=["GET"]),
        Route("/metrics", _prometheus_metrics, methods=["GET"]),
        Route("/dashboard", _dashboard_page, methods=["GET"]),
    ]
    routes.extend(http_app.routes)
    routes.extend(sse_app.routes)

    # 2) FastAPI 作为最外层（接受 routes 参数，行为与 Starlette 一致）
    app = FastAPI(routes=routes, lifespan=lifespan)

    # 3) 挂载 REST 路由（/api/v1/* 下聚合所有业务端点）
    app.include_router(rest_routes.router, prefix="/api/v1")

    # 4) 注册统一异常处理器（仅 /api/* 路径包裹，其他路径保持原行为）
    _register_exception_handlers(app)

    # 5) Prometheus 指标采集中间件（工单 11）—— 必须在异常处理器之后注册
    _register_metrics_middleware(app)

    return app


def _register_metrics_middleware(app: FastAPI) -> None:
    """注册请求指标采集中间件（工单 11）。

    自动记录：
    - requests_total（含 method/path/code 标签）
    - request_duration_seconds（Histogram）
    - errors_total（status >= 400）
    - slow_queries_total（超过阈值的请求）
    - gateway_uptime_seconds（每次请求时刷新）
    """
    from tradex.metrics import (
        record_request, update_uptime, set_tools_registered,
    )

    # 启动后定期同步工具数到指标（在第一个请求时设置）
    _tools_synced = {"done": False}

    @app.middleware("http")
    async def _collect_metrics(request: Request, call_next):
        # 启动后第一次请求同步工具数
        if not _tools_synced["done"]:
            set_tools_registered(_tools_count)
            _tools_synced["done"] = True
        update_uptime()

        start = time.time()
        response = await call_next(request)
        duration = time.time() - start

        # 归一化路径（把 /api/v1/price/quote 的查询参数等剥离，便于聚合）
        path = request.url.path
        method = request.method
        try:
            record_request(method, path, response.status_code, duration)
        except Exception as exc:  # noqa: BLE001
            logger.debug("metrics collect failed: %s", exc)
        return response


def run(
    mcp,
    host: str = "0.0.0.0",
    port: int = 8000,
    allowed_hosts: list[str] | None = None,
) -> None:
    """用 uvicorn 启动 HTTP 网关（阻塞调用）。

    网关架构（阶段一工单 01 起）：
    - 最外层 FastAPI：/health + /mcp + /sse + /api/v1/* REST
    - 129 MCP 工具通过 /mcp 端点对外（行为不变）
    - REST 端点通过 /api/v1/* 对外（工单 01 起逐步填充）

    Args:
        host: 监听地址，默认 0.0.0.0（云/容器形态；与代理无关，数据源仍直连）。
            仅本机调试可传 "localhost"。
        port: 端口，默认 8000。
        allowed_hosts: 透传 build_app（见 apply_transport_security）。
    """
    import uvicorn

    app = build_app(mcp, allowed_hosts=allowed_hosts)
    uvicorn.run(app, host=host, port=port, log_level="info")
