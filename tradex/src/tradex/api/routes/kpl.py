"""开盘啦（KPL）REST 端点（交接文档 09 票5）。

路径前缀 /api/v1（由 http_server.py 挂载时添加），本路由自带 /kpl 前缀。
业务层 service/kpl_service.py（QI-ARCH-05，2026-11-18 补接缝——原路由越层
直伸手 SmartRouter 违硬约定#9）；错误语义 serve_envelope 唯一口径
（ValueError→400 配 ERR_BAD_REQUEST——原 400 配 ERR_INTERNAL 的漂移一并
归一，见该 A③ 验收测试）。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ...api.schemas import ERR_BAD_REQUEST, Envelope
from ._helpers import serve_envelope
from ...service import kpl_service

router = APIRouter(prefix="/kpl", tags=["kpl"])


def _validate_date(date: str) -> str:
    """交易日参数前置校验：非法直接 400，不进 router（SmartRouter 会把
    ValueError 包装成记账失败，REST 层无法还原 4xx 语义）。"""
    s = str(date or "").strip()
    if not s:
        return ""
    compact = s.replace("-", "")
    if len(compact) != 8 or not compact.isdigit():
        raise HTTPException(
            status_code=400,
            detail=f"非法日期参数：{date!r}（期望 YYYYMMDD 或 YYYY-MM-DD）",
            headers={"X-ErrCode": str(ERR_BAD_REQUEST)},  # QI-ARCH-05：ERR_INTERNAL→ERR_BAD_REQUEST 归一
        )
    return s


@router.get("/limit-up", response_model=Envelope[list])
def limit_up(
    date: str = Query("", description="交易日 YYYYMMDD，空 = 实时"),
    pid_type: int = Query(0, description="板位 1~5；0 = 全部（循环 1~5 拼接）"),
) -> Envelope[list]:
    """开盘啦涨停复盘（KPL 口径：原因/封单/主力/801xxx 板块码/板位）。"""
    date = _validate_date(date)
    return serve_envelope(lambda: kpl_service.limit_up(date=date, pid_type=pid_type))


@router.get("/sentiment", response_model=Envelope[dict])
def sentiment() -> Envelope[dict]:
    """开盘啦市场情绪读数（涨停/跌停/炸板率 + 情绪值/连板高度）。"""
    return serve_envelope(kpl_service.sentiment)


@router.get("/boards", response_model=Envelope[list])
def boards(
    date: str = Query("", description="交易日 YYYYMMDD，空 = 实时"),
) -> Envelope[list]:
    """开盘啦精选板块列表（801xxx 板块码/强度/主力净额）。"""
    date = _validate_date(date)
    return serve_envelope(lambda: kpl_service.boards(date=date))


@router.get("/bidding", response_model=Envelope[list])
def bidding(
    date: str = Query("", description="交易日 YYYYMMDD，空 = 实时"),
) -> Envelope[list]:
    """开盘啦竞价涨停委买额榜（历史保留期短，交易日盘中调用）。"""
    date = _validate_date(date)
    return serve_envelope(lambda: kpl_service.bidding(date=date))
