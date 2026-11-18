"""
Category 5: Industry & Sector Data (V0.3)

Tools:
  21. get_industry_list    - List all industry sectors
  22. get_industry_stocks  - Get stocks in a specific industry
  23. get_concept_list     - List all concept/theme sectors
  24. get_sector_fund_flow - Sector-level fund flow ranking
  25. get_industry_pe      - Industry historical PE valuation

Data source routing (via SmartRouter):
  行业数据: akshare industry_data (endpoints: board_industry_name_em/board_industry_name_ths/
           board_industry_cons_em/board_concept_name_em/board_concept_name_ths/
           sector_fund_flow_rank/board_industry_hist_em)

v3.4.0 工单 07：业务逻辑已抽到 service/industry_service.py，本文件保留薄包装。
"""

from __future__ import annotations


from mcp.server.fastmcp import FastMCP

from ._mcp_serve import mcp_serve
from ..service import industry_service


# （QI-ARCH-02 全量上提，2026-11-19：5 个工具体模块级化 + mcp_serve 出口
# 收拢——service 薄包装同构形态。）


async def get_industry_list() -> str:
    """
    获取行业板块列表。

    Returns:
        行业板块列表 (JSON)，包含板块名称、涨跌幅、总市值、
        换手率、领涨股等信息。
    """
    return mcp_serve(
        "get_industry_list",
        industry_service.get_industry_list,
        "获取行业板块列表失败",
    )


async def get_industry_stocks(industry: str) -> str:
    """
    获取指定行业板块的成分股列表。

    Args:
        industry: 行业板块名称，如 "白酒"、"银行"、"半导体"、"新能源车"

    Returns:
        该行业所有成分股 (JSON)，包含代码、名称、最新价、涨跌幅、
        市盈率、市净率等。
    """
    return mcp_serve(
        "get_industry_stocks",
        lambda: industry_service.get_industry_stocks(industry=industry),
        f"获取行业成分股失败 ({industry})",
    )


async def get_concept_list() -> str:
    """
    获取概念板块列表。

    概念板块如：华为概念、ChatGPT、锂电池、芯片、光伏等。

    Returns:
        概念板块列表 (JSON)，包含板块名称、涨跌幅、总市值、
        换手率、领涨股等信息。
    """
    return mcp_serve(
        "get_concept_list",
        industry_service.get_concept_list,
        "获取概念板块列表失败",
    )


async def get_sector_fund_flow(
    sector_type: str = "行业资金流",
    indicator: str = "今日",
) -> str:
    """
    获取板块资金流向排名。

    Args:
        sector_type: 资金流类型，可选：
            "行业资金流" - 行业板块资金流向
            "概念资金流" - 概念板块资金流向
            "地域资金流" - 地域板块资金流向
        indicator: 时间维度，可选："今日"、"5日"、"10日"，默认 "今日"

    Returns:
        板块资金流向排名 (JSON)，包含板块名称、今日主力净流入、
        今日超大单净流入、今日大单净流入等。
    """
    return mcp_serve(
        "get_sector_fund_flow",
        lambda: industry_service.get_sector_fund_flow(sector_type=sector_type, indicator=indicator),
        f"获取板块资金流向失败 ({sector_type})",
    )


async def get_industry_pe(
    industry: str,
    start_date: str = "",
    end_date: str = "",
) -> str:
    """
    获取行业板块历史行情数据（可用于计算行业PE估值趋势）。

    Args:
        industry: 行业板块名称，如 "白酒"、"银行"
        start_date: 开始日期，格式 "YYYYMMDD"，如 "20240101"
        end_date: 结束日期，格式 "YYYYMMDD"

    Returns:
        行业板块历史行情 (JSON)，包含日期、开盘价、收盘价、最高价、
        最低价、成交量、成交额、振幅、涨跌幅等。
    """
    return mcp_serve(
        "get_industry_pe",
        lambda: industry_service.get_industry_pe(industry=industry, start_date=start_date, end_date=end_date),
        f"获取行业历史行情失败 ({industry})",
    )


def register(mcp: FastMCP):
    """Register industry sector tools with the MCP server.

    v3.4.0：业务逻辑在 service/industry_service.py；QI-ARCH-02 全量上提
    （2026-11-19）：5 工具体模块级，引用注册。"""
    for _fn in (
        get_industry_list,
        get_industry_stocks,
        get_concept_list,
        get_sector_fund_flow,
        get_industry_pe,
    ):
        mcp.tool()(_fn)
