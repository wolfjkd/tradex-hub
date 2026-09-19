"""统一响应包裹模型 + 错误码常量（阶段一工单 01）。

所有 /api/v1/* REST 端点的返回都走 Envelope 包裹：
- 成功：{"code": 0, "data": <业务对象>, "msg": "ok"}
- 失败：{"code": <非 0>, "data": null, "msg": "<错误信息>"}
"""

from __future__ import annotations

from typing import Generic, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


# 错误码规范（详见 spec 第五章 5.1）
ERR_OK = 0
ERR_BAD_REQUEST = 40001          # 参数错误
ERR_NOT_FOUND = 40401            # 资源不存在
ERR_DATA_SOURCE_UNREACHABLE = 50001   # 数据源不可达
ERR_DATA_SOURCE_ABNORMAL = 50002      # 数据源返回异常
ERR_INTERNAL = 50003             # 网关内部错误
ERR_RATE_LIMIT = 42901           # 限流（工单 20）


class Envelope(BaseModel, Generic[T]):
    """统一包裹响应模型。

    用法（FastAPI 端点）::

        from .schemas import Envelope, envelope_ok

        @router.get("/ping")
        def ping() -> Envelope[dict]:
            return envelope_ok({"pong": True})
    """

    code: int = ERR_OK
    data: Optional[T] = None
    msg: str = "ok"


def envelope_ok(data: T) -> Envelope[T]:
    """成功响应的便捷构造器。"""
    return Envelope(code=ERR_OK, data=data, msg="ok")


def envelope_err(code: int, msg: str) -> Envelope[None]:
    """失败响应的便捷构造器（data 恒为 None）。"""
    return Envelope(code=code, data=None, msg=msg)


# HTTP status → 业务 code 映射（供异常处理中间件用）
HTTP_STATUS_TO_CODE = {
    400: ERR_BAD_REQUEST,
    404: ERR_NOT_FOUND,
    500: ERR_INTERNAL,
}
