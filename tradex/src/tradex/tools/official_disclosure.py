"""境外官方公告 MCP 工具（OFFSRC-00 P01，2026-11-27）。

Tools:
  - get_official_disclosures - 境外官方机构公告（Fed/SEC/FTSE/MSCI/HKEX/恒生，一手官方）

Data source routing (via SmartRouter):
  official_disclosure: official_direct(priority=1)——聚合分发模式，
  fetcher 内部按 source 参数分发（fed 首发打样，其余源按 OFFSRC-00 工单序接入）。
"""

from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP

from ..service import official_disclosure_service
from ._mcp_serve import mcp_serve

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def get_official_disclosures(
        source: str = "",
        doc_type: str = "",
        limit: int = 30,
        identifier: str = "",
        form_type: str = "",
    ) -> str:
        """
        获取境外官方机构一手公告（OFFSRC-00 专项）。

        当前已接入源：fed（美联储新闻稿 RSS）、sec_edgar（SEC EDGAR 中概股披露，
        官方 JSON API）。FTSE Russell / MSCI / HKEXnews / 恒生 按 OFFSRC-00
        工单序 P03-P05 逐个接入。

        Args:
            source: 源 key，如 "fed" / "sec_edgar"。留空 = 聚合全部已接入源（单源
                失败自动降级并在 failed_sources 中如实标注）。
            doc_type: 文档类型过滤：index_review（指数调整）/ filing（监管申报）/
                press_release（新闻稿）/ macro_release（宏观发布）。留空返回全部。
            limit: 每源最多返回条数，默认 30。
            identifier: 仅 sec_edgar 消费——ticker（如 BABA/PDD）或 10 位内 CIK；
                留空 = 聚合默认中概观察清单 10 只（BABA/PDD/JD/LI/NIO/BIDU/NTES/
                TCOM/BEKE/ZTO）。其余源忽略。
            form_type: 仅 sec_edgar 消费——SEC 文书类型过滤（10-K/10-Q/8-K/20-F/6-K），
                留空全部。其余源忽略。

        Returns:
            JSON：disclosures 列表（title/summary/url/publish_time_utc/publish_time_cn
            双标时区/source_grade 来源等级/raw_json 原始载荷）、failed_sources 降级
            记录、count。
        """
        return mcp_serve(
            "get_official_disclosures",
            lambda: official_disclosure_service.get_official_disclosures(
                source=source, doc_type=doc_type, limit=limit,
                identifier=identifier, form_type=form_type,
            ),
            f"获取境外官方公告失败 (source={source!r})",
            value_error_detail=f"参数错误 (source={source!r})",
        )

    @mcp.tool()
    async def get_official_sources() -> str:
        """
        列出已接入的境外官方公告源清单（OFFSRC-00 专项）。

        Returns:
            JSON：sources 列表（source key + description + status）、count。
        """
        return mcp_serve(
            "get_official_sources",
            official_disclosure_service.get_official_sources,
            "获取境外官方源清单失败",
        )
