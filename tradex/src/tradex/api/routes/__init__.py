"""REST 路由子包（阶段一工单 01 建立）。

每个业务领域一个文件：
- market.py    /api/v1/market/* + /api/v1/fund/*
- price.py     /api/v1/price/*
- company.py   /api/v1/company/*
- financial.py /api/v1/financial/*
- news.py      /api/v1/news/*
- industry.py  /api/v1/industry/*
- indicator.py /api/v1/indicator/*
- diagnostic.py /api/v1/diagnostic/*
- write.py     /api/v1/write/*
- metrics.py   /api/v1/metrics/* + /metrics
- dashboard.py /dashboard

聚合模式：本模块对外暴露一个聚合 router，把各子路由文件 include 进来。
各子路由文件自带 prefix（如 /market），http_server.py 挂载时统一加 /api/v1。
工单 01 只建最小验证端点（ping，无 prefix），其余端点由后续工单填充。
"""

from __future__ import annotations

from fastapi import APIRouter

from ..schemas import Envelope, envelope_ok

# 聚合 router（供 http_server.include_router 使用）
router = APIRouter()


@router.get("/ping", response_model=Envelope[dict])
def ping() -> Envelope[dict]:
    """最小验证端点（工单 01）：证明骨架贯通 + 包裹格式正确。"""
    return envelope_ok({"pong": True})


# ---------- 子路由聚合（各工单按序 include） ----------

# 工单 02：行情类端点（/market/* 含 overview/global/limit-up-down/dragon-tiger）
from . import market as _market_routes  # noqa: E402

router.include_router(_market_routes.router)

# 工单 03：资金类端点（/fund/* 含 flow/northbound；service 函数仍在 market_service）
from . import fund as _fund_routes  # noqa: E402

router.include_router(_fund_routes.router)

# 工单 04：价格/K 线端点（/price/* 含 quote/kline/intraday；service 在 price_service）
from . import price as _price_routes  # noqa: E402

router.include_router(_price_routes.router)

# 工单 05：公司基本信息端点（/company/* 含 search/info/profile/competitors）
from . import company as _company_routes  # noqa: E402

router.include_router(_company_routes.router)

# 工单 05：财务报表/指标端点（/financial/* 含 income/balance/cashflow/line-item/indicators/growth/per-share/segments）
from . import financial as _financial_routes  # noqa: E402

router.include_router(_financial_routes.router)

# 工单 06：新闻/公告端点（/news/* 含 stock/announcements/search）
from . import news as _news_routes  # noqa: E402

router.include_router(_news_routes.router)

# 工单 07：板块/行业端点（/industry/* 含 list/stocks/concepts/fund-flow/pe）
from . import industry as _industry_routes  # noqa: E402

router.include_router(_industry_routes.router)

# 工单 08：技术指标端点（/indicator/* 含 macd/kdj/rsi/boll）
from . import indicator as _indicator_routes  # noqa: E402

router.include_router(_indicator_routes.router)

# 工单 09：诊断/分析端点（/diagnostic/* 含 stock/market/technical）
from . import diagnostic as _diagnostic_routes  # noqa: E402

router.include_router(_diagnostic_routes.router)

# 工单 10：写操作端点（/write/* 含 strategy CRUD + watchlist CRUD）
from . import write as _write_routes  # noqa: E402

router.include_router(_write_routes.router)

# 工单 11：指标端点（/metrics/json；注意 /metrics 文本格式由 http_server.py 直接挂载）
from . import metrics as _metrics_routes  # noqa: E402

router.include_router(_metrics_routes.router)

# 工单 19：访问日志查询端点（/access-log）
from . import access_log as _access_log_routes  # noqa: E402

router.include_router(_access_log_routes.router)
