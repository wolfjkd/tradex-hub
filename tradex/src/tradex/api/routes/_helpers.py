"""REST 路由错误样板单点（批次C5 收拢，2026-11-11）。

原先各 route 文件各自定义 _validate_symbol / _data_source_error /
_business_error + 每端点一段 try/except 样板（约 91 处），收拢于此：

  - validate_symbol:            6 位数字代码统一校验（400 + ERR_BAD_REQUEST）
  - business_error / data_source_error: 业务级 / 数据源级 HTTPException 构造
  - serve_envelope:             样板执行器（全部异常 → 502，HTTPException 穿透）
  - serve_envelope_400:         样板执行器（ValueError → 400，其余 → 502）

两种执行器对应仓内既有两种语义形态（行为不变收拢）：
  - A 形（financial/company/price/shortline/indicator 等）：ValueError→400
  - B 形（event/industry/macro/diagnostic/industry_news 等）：无 ValueError
    分支，业务级 ValueError 也走 502——历史怪癖，先保留，统一与否待裁决。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import HTTPException

from ..schemas import ERR_BAD_REQUEST, ERR_DATA_SOURCE_UNREACHABLE, Envelope, envelope_ok


def validate_symbol(symbol: str) -> None:
    """统一 symbol 校验：6 位数字。"""
    if not (len(symbol) == 6 and symbol.isdigit()):
        raise HTTPException(
            status_code=400,
            detail=f"symbol 必须是 6 位数字代码，收到: {symbol}",
            headers={"X-ErrCode": str(ERR_BAD_REQUEST)},
        )


def business_error(e: Exception) -> HTTPException:
    """构造业务级异常 HTTPException（400）。"""
    return HTTPException(
        status_code=400, detail=str(e),
        headers={"X-ErrCode": str(ERR_BAD_REQUEST)},
    )


def data_source_error(e: Exception) -> HTTPException:
    """构造数据源异常 HTTPException（502）。"""
    return HTTPException(
        status_code=502, detail=f"数据源不可达: {e}",
        headers={"X-ErrCode": str(ERR_DATA_SOURCE_UNREACHABLE)},
    )


def _serve(build: Callable[[], Any], value_error_400: bool) -> Envelope:
    """样板单点：执行 build → envelope_ok 包装 → 异常转 HTTPException。

    HTTPException 原样穿透（路由自身的 4xx/404 语义不被吞成 502）。
    """
    try:
        return envelope_ok(build())
    except HTTPException:
        raise
    except ValueError as e:
        if value_error_400:
            raise business_error(e)
        raise data_source_error(e)
    except Exception as e:
        raise data_source_error(e)


def serve_envelope(build: Callable[[], Any]) -> Envelope:
    """B 形样板：全部非 HTTPException 异常 → 502。"""
    return _serve(build, value_error_400=False)


def serve_envelope_400(build: Callable[[], Any]) -> Envelope:
    """A 形样板：ValueError → 400，其余非 HTTPException 异常 → 502。"""
    return _serve(build, value_error_400=True)
