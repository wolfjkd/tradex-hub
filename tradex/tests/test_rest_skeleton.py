"""工单 01 测试：FastAPI 升级 + api/service 骨架 + 包裹响应中间件。

验证验收标准：
- /health 升级前后行为一致
- /api/v1/ping 返回正确包裹格式
- 异常路径返回包裹式错误（如 /api/v1/nonexistent → code=40401）
- Envelope 模型 + 错误码常量正确
- service/api 骨架目录可导入
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tradex.api.schemas import (
    ERR_BAD_REQUEST,
    ERR_INTERNAL,
    ERR_NOT_FOUND,
    ERR_OK,
    Envelope,
    envelope_err,
    envelope_ok,
)


# ---------- Envelope 模型单测 ----------


class TestEnvelopeModel:
    """Envelope 包裹响应模型。"""

    def test_ok_constructor(self):
        """envelope_ok 构造成功响应。"""
        env = envelope_ok({"ping": True})
        assert env.code == ERR_OK
        assert env.data == {"ping": True}
        assert env.msg == "ok"

    def test_err_constructor(self):
        """envelope_err 构造失败响应（data 恒为 None）。"""
        env = envelope_err(ERR_NOT_FOUND, "resource not found")
        assert env.code == ERR_NOT_FOUND
        assert env.data is None
        assert env.msg == "resource not found"

    def test_error_codes_distinct(self):
        """错误码彼此不重复且非 0。"""
        codes = [ERR_BAD_REQUEST, ERR_NOT_FOUND, ERR_INTERNAL]
        assert len(set(codes)) == len(codes)
        assert all(c != ERR_OK for c in codes)

    def test_envelope_generic_serialization(self):
        """Envelope 泛型序列化为 {code,data,msg} 三键。"""
        env = envelope_ok({"k": 1})
        dumped = env.model_dump()
        assert set(dumped.keys()) == {"code", "data", "msg"}


# ---------- 骨架目录可导入性 ----------


class TestSkeletonImportable:
    """service/ 与 api/ 骨架目录可正常导入。"""

    def test_service_pkg_importable(self):
        """service 包可导入（空骨架）。"""
        import tradex.service  # noqa: F401

    def test_api_pkg_importable(self):
        """api 包可导入。"""
        import tradex.api  # noqa: F401

    def test_api_routes_pkg_importable(self):
        """api.routes 子包可导入，且 router 已定义。"""
        from tradex.api import routes
        assert hasattr(routes, "router")

    def test_schemas_module_importable(self):
        """schemas 模块可导入。"""
        import tradex.api.schemas  # noqa: F401


# ---------- 端点集成测（需要构造最小 app） ----------


def _build_min_app():
    """构造一个最小 FastAPI app 用于测试（不带 MCP 子 app，避免依赖 FastMCP 实例）。

    A⑦ 收敛 2026-11-22：薄壳调基座 _rest_test_base。原手抄为工单 01 时代形态
    （handler 无 X-ErrCode 优先 + middleware 缺 422 msg 分支 + 无类型注解，历史漂移
    ——生产 5 处 route 抛 X-ErrCode headers、middleware 有 422 分支）；本文件断言面
    仅 /ping、/nonexistent、_health，无 422/X-ErrCode 面，收敛零断言变化。
    """
    from tests._rest_test_base import build_min_test_app

    return build_min_test_app()


class TestPingEndpoint:
    """/api/v1/ping 端点行为。"""

    def test_ping_returns_envelope_ok(self):
        """ping 返回 {code:0, data:{pong:true}, msg:'ok'}。"""
        app = _build_min_app()
        client = TestClient(app)
        resp = client.get("/api/v1/ping")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"] == {"pong": True}
        assert body["msg"] == "ok"


class TestErrorEnvelope:
    """异常路径返回包裹式错误。"""

    def test_nonexistent_endpoint_returns_envelope_not_found(self):
        """访问不存在的 /api/v1/* 路径返回 code=40401 包裹格式。"""
        app = _build_min_app()
        client = TestClient(app)
        resp = client.get("/api/v1/nonexistent")
        # FastAPI 对未定义路由抛 HTTPException(404)
        assert resp.status_code == 404
        body = resp.json()
        assert body["code"] == ERR_NOT_FOUND
        assert body["data"] is None
        assert "msg" in body


# ---------- /health 行为一致性 ----------
# 注：/health 由 build_app 构造时挂载，需完整 FastMCP 实例；
# 此处单独测 _health 函数逻辑（不依赖 app 构造），保证返回字段齐全。


class TestHealthFunction:
    """/health 端点函数行为（不依赖完整 app 构造）。"""

    @pytest.mark.asyncio
    async def test_health_returns_expected_fields(self):
        """_health 返回 status/service/version/tools/uptime_seconds 五字段。"""
        from tradex.http_server import _health

        class _DummyRequest:
            class url:
                path = "/health"

        resp = await _health(_DummyRequest())
        import json
        body = json.loads(resp.body)
        assert body["status"] == "ok"
        assert body["service"] == "tradex-mcp"
        assert "version" in body
        assert "tools" in body
        assert "uptime_seconds" in body
