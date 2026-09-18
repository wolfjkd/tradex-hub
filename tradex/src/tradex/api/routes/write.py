"""写操作 REST 端点（工单 10）—— 本地文件存储 CRUD。

路径前缀：/api/v1（由 http_server.py 挂载时加上）。

端点：
- POST   /write/strategy              创建量化策略
- GET    /write/strategy/list         列出已保存策略
- GET    /write/strategy/{id}         取单个策略详情
- DELETE /write/strategy/{id}         删除策略
- POST   /write/watchlist             添加/更新自选股
- GET    /write/watchlist/list        列出自选股
- DELETE /write/watchlist/{symbol}    移除自选股

阶段一采用本地 JSON 文件存储（不引入数据库）；路径 data/written/ 不入版本控制。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ...api.schemas import (
    ERR_BAD_REQUEST,
    ERR_NOT_FOUND,
    Envelope,
    envelope_ok,
)
from ...service import write_service

router = APIRouter(prefix="/write", tags=["write"])


# ────────────────────── Pydantic 入参模型 ──────────────────────────

class StrategyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="策略名称")
    content: str = Field(..., min_length=1, description="策略正文（Markdown/代码均可）")
    tags: list[str] | None = Field(None, description="可选标签数组")


class WatchlistAdd(BaseModel):
    symbol: str = Field(..., min_length=6, max_length=6, description="6 位 A 股代码")
    note: str = Field("", max_length=500, description="可选备注")


# ────────────────────── 策略端点 ──────────────────────────

@router.post("/strategy", response_model=Envelope[dict])
def create_strategy(payload: StrategyCreate) -> Envelope[dict]:
    """创建量化策略。"""
    try:
        result = write_service.create_strategy(
            name=payload.name, content=payload.content, tags=payload.tags
        )
        return envelope_ok(result)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"策略保存失败: {e}",
            headers={"X-ErrCode": "50003"},
        )


@router.get("/strategy/list", response_model=Envelope[dict])
def list_strategies() -> Envelope[dict]:
    """列出所有已保存策略（仅元信息，不含 content）。"""
    return envelope_ok(write_service.list_strategies())


@router.get("/strategy/{sid}", response_model=Envelope[dict])
def get_strategy(sid: str) -> Envelope[dict]:
    """取单个策略完整内容。"""
    data = write_service.get_strategy(sid)
    if data is None:
        raise HTTPException(
            status_code=404,
            detail=f"策略 {sid} 不存在",
            headers={"X-ErrCode": str(ERR_NOT_FOUND)},
        )
    return envelope_ok(data)


@router.delete("/strategy/{sid}", response_model=Envelope[dict])
def delete_strategy(sid: str) -> Envelope[dict]:
    """删除策略。"""
    ok = write_service.delete_strategy(sid)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail=f"策略 {sid} 不存在",
            headers={"X-ErrCode": str(ERR_NOT_FOUND)},
        )
    return envelope_ok({"id": sid, "deleted": True})


# ────────────────────── 自选股端点 ──────────────────────────

@router.post("/watchlist", response_model=Envelope[dict])
def add_to_watchlist(payload: WatchlistAdd) -> Envelope[dict]:
    """添加或更新自选股。symbol 已存在则更新 note。"""
    if not payload.symbol.isdigit():
        raise HTTPException(
            status_code=400,
            detail=f"symbol 必须为 6 位数字，收到: {payload.symbol}",
            headers={"X-ErrCode": str(ERR_BAD_REQUEST)},
        )
    try:
        result = write_service.add_to_watchlist(symbol=payload.symbol, note=payload.note)
        return envelope_ok(result)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"自选股保存失败: {e}",
            headers={"X-ErrCode": "50003"},
        )


@router.get("/watchlist/list", response_model=Envelope[dict])
def list_watchlist() -> Envelope[dict]:
    """列出自选股。"""
    return envelope_ok(write_service.list_watchlist())


@router.delete("/watchlist/{symbol}", response_model=Envelope[dict])
def remove_from_watchlist(symbol: str) -> Envelope[dict]:
    """从自选股移除。"""
    result = write_service.remove_from_watchlist(symbol)
    if result["action"] == "not_found":
        raise HTTPException(
            status_code=404,
            detail=f"自选股 {symbol} 不存在",
            headers={"X-ErrCode": str(ERR_NOT_FOUND)},
        )
    return envelope_ok(result)
