"""
官方宏观数据工具模块（2 个 MCP 工具）。

Tools:
  - get_pmi:                   PMI（统计局）
  - get_bond_yield_curve:      国债/信用债收益率曲线（中债）

数据源全部官方一手，与 akshare 上游独立。

2026-09-28 死源剥离（老板拍板）：get_social_financing（人行 404）/
get_repo_fixing_rate + get_lpr_history（货币网静态 json 404）已随死源移除。
"""

from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP

from ._mcp_serve import mcp_serve
from ..service import macro_service

logger = logging.getLogger(__name__)


# （QI-ARCH-02 全量上提，2026-11-19：4 个工具体模块级化 + mcp_serve 出口
# 收拢——service 薄包装同构形态。）


async def get_pmi() -> str:
    """
    获取 PMI 数据（国家统计局，制造业 + 非制造业）。

    Returns:
        PMI 历史数据 (JSON)。
    """
    return mcp_serve(
        "get_pmi",
        macro_service.get_pmi,
        "获取 PMI 数据失败",
    )


async def get_bond_yield_curve_official(curve: str = "国债") -> str:
    """
    获取国债/信用债收益率曲线（中债官方一手，3月~30年）。

    与现有 get_bond_yield_curve 不同：本工具走中债官网一手数据，
    支持国债 / 商业银行AAA / 中短票AAA 三种曲线。

    Args:
        curve: 曲线类型，"国债" / "商业银行AAA" / "中短票AAA"

    Returns:
        收益率曲线 (JSON)，含期限、收益率(%)。
    """
    return mcp_serve(
        "get_bond_yield_curve_official",
        lambda: macro_service.get_bond_yield_curve(curve=curve),
        "获取收益率曲线失败",
    )


async def get_index_valuation(index_code: str = "000300") -> str:
    """
    获取中证指数官方估值（PE + 股息率，中证官网一手文件，日度更新）。

    Args:
        index_code: 指数代码，默认 000300 沪深300

    Returns:
        估值序列 (JSON)，含日期、市盈率1(总股本)/市盈率2(计算用股本)、
        股息率1(总股本)/股息率2(计算用股本)，最新日期在前。
    """
    return mcp_serve(
        "get_index_valuation",
        lambda: macro_service.get_index_valuation(index_code=index_code),
        "获取指数估值失败",
    )


async def get_index_constituents(index_code: str = "000300") -> str:
    """
    获取中证指数官方成分股名单（中证官网一手文件，日度更新）。

    仅覆盖中证系指数（000300 沪深300 / 000905 中证500 / 980017 等
    中证公司发布代码）；国证系（399 开头，如 399006 创业板指）无
    cons 文件，请求会返回错误。

    Args:
        index_code: 指数代码，默认 000300 沪深300

    Returns:
        成分名单 (JSON)，含日期、成分券代码（6 位补零）、成分券名称、
        交易所，按代码升序。
    """
    return mcp_serve(
        "get_index_constituents",
        lambda: macro_service.get_index_constituents(index_code=index_code),
        "获取指数成分股失败",
    )


def register(mcp: FastMCP):
    """Register macro official tools.

    QI-ARCH-02 全量上提（2026-11-19）：4 工具体模块级，引用注册。"""
    for _fn in (
        get_pmi,
        get_bond_yield_curve_official,
        get_index_valuation,
        get_index_constituents,
    ):
        mcp.tool()(_fn)
