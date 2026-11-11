"""REST 路由错误样板单点（批次C5 收拢 → 批次BCD 裁决统一，2026-11-11）。

原先各 route 文件各自定义 _validate_symbol / _data_source_error /
_business_error + 每端点一段 try/except 样板（约 91 处），收拢于此：

  - validate_symbol:   6 位数字代码统一校验（400 + ERR_BAD_REQUEST）
  - business_error / data_source_error: 业务级 / 数据源级 HTTPException 构造
  - serve_envelope:    样板执行器（**唯一语义**：ValueError → 400，
                       其余非 HTTPException 异常 → 502，HTTPException 穿透）

语义沿革：收拢时仓内存在两种形态——A 形（ValueError→400）与 B 形（无
ValueError 分支、业务级也走 502 的历史怪癖），当时为「行为不变收拢」双入口
保留；**2026-11-11 老板拍板「统一」**，B 形怪癖废除，全仓单一语义（本文件
serve_envelope），历史差异见 [[15-v3.9.4-审计批次BCD施工交接文档]]。
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


def serve_envelope(build: Callable[[], Any]) -> Envelope:
    """样板单点（统一语义，2026-11-11 拍板）：执行 build → envelope_ok 包装。

    - HTTPException 原样穿透（路由自身的 4xx/404 语义不被吞成 502）；
    - ValueError → 400（业务级，如「数据为空」「未找到代码」）；
    - 其余异常 → 502（数据源不可达）。
    """
    try:
        return envelope_ok(build())
    except HTTPException:
        raise
    except ValueError as e:
        raise business_error(e)
    except Exception as e:
        raise data_source_error(e)
