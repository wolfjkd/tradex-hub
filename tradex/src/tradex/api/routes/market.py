"""行情/资金类 REST 端点（工单 02）。

路径前缀：/api/v1（由 http_server.py 挂载时加上）。

端点：
- GET /market/overview          A股主要指数实时快照
- GET /market/global            全球市场行情（可选 category 过滤）
- GET /market/limit-up-down     涨跌停池（direction=涨停|跌停）
- GET /market/dragon-tiger      龙虎榜（可选 num_days）

工单 03 会在此文件追加资金类端点（fund/flow、fund/northbound）。

抽 service + 挂路由的标准步骤（供后续模块复制）：
1) 在 service/<domain>_service.py 写纯函数（返回 dict，异常向上抛）
2) 在 tools/<domain>.py 的 @mcp.tool() 改为薄包装（调 service + json.dumps）
3) 在 api/routes/<domain>.py 挂 FastAPI 路由（调 service + 包 Envelope）
4) 写测试（service 单测 + api 集成测 + MCP 回归验证）
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ...api.schemas import (
    ERR_BAD_REQUEST,
    ERR_DATA_SOURCE_UNREACHABLE,
    Envelope,
    envelope_ok,
)
from ...service import market_service

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/overview", response_model=Envelope[dict])
def overview() -> Envelope[dict]:
    """A股主要指数实时行情快照。"""
    try:
        return envelope_ok(market_service.get_market_overview())
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"数据源不可达: {e}",
            headers={"X-ErrCode": str(ERR_DATA_SOURCE_UNREACHABLE)},
        )


@router.get("/global", response_model=Envelope[dict])
def global_quote(category: str = Query("", description="可选分类过滤：美股指数/热门美股/亚太指数/韩股/外汇")) -> Envelope[dict]:
    """全球市场行情快照。"""
    try:
        return envelope_ok(market_service.get_global_market_quote(category=category))
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"数据源不可达: {e}",
            headers={"X-ErrCode": str(ERR_DATA_SOURCE_UNREACHABLE)},
        )


@router.get("/limit-up-down", response_model=Envelope[dict])
def limit_up_down(
    direction: str = Query("涨停", description="涨停 或 跌停"),
) -> Envelope[dict]:
    """当日涨停板或跌停板股票池。"""
    if direction not in ("涨停", "跌停"):
        raise HTTPException(
            status_code=400,
            detail="direction 只能是 '涨停' 或 '跌停'",
            headers={"X-ErrCode": str(ERR_BAD_REQUEST)},
        )
    try:
        return envelope_ok(market_service.get_limit_up_down(direction=direction))
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"数据源不可达: {e}",
            headers={"X-ErrCode": str(ERR_DATA_SOURCE_UNREACHABLE)},
        )


@router.get("/dragon-tiger", response_model=Envelope[dict])
def dragon_tiger(
    num_days: int = Query(5, ge=1, le=60, description="最近几个交易日，默认 5"),
) -> Envelope[dict]:
    """龙虎榜数据（机构和游资活跃买卖记录）。"""
    try:
        return envelope_ok(market_service.get_dragon_tiger(num_days=num_days))
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"数据源不可达: {e}",
            headers={"X-ErrCode": str(ERR_DATA_SOURCE_UNREACHABLE)},
        )
