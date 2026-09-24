"""
全球市场新闻工具模块（3 个 MCP 工具）。

Tools:
  - get_wallstreetcn_lives:   华尔街见闻 7×24 全球财经快讯
  - get_macro_calendar:       全球宏观日历（公布值/预期/前值）
  - get_cctv_news:            央视网新闻联播条目 + 文字稿
"""

from __future__ import annotations

import json
import logging

from mcp.server.fastmcp import FastMCP

from ..data_sources import get_router
from ..utils.cache import TTL_DAILY, cache
from ..utils.formatter import error_response
from ..service import global_news_service

logger = logging.getLogger(__name__)

_router = get_router()


def register(mcp: FastMCP):
    """Register global market news tools."""

    @mcp.tool()
    async def get_wallstreetcn_lives(
        channel: str = "global", limit: int = 30, cursor: str = ""
    ) -> str:
        """
        获取华尔街见闻 7×24 全球财经快讯。

        Args:
            channel: 频道过滤，"global"(默认) / "important"(重要) /
                     "a-stock"(A股) / "us-stock"(美股) / "forex"(外汇) / "commodity"(商品)
            limit: 返回条数（最大 100）
            cursor: 翻页游标（首页留空）

        Returns:
            快讯列表 (JSON)，含标题、内容、发布时间、频道、原文链接。
        """
        try:
            result = global_news_service.get_wallstreetcn_lives(
                channel=channel, limit=limit, cursor=cursor
            )
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(
                f"获取华尔街见闻快讯失败: {e}", "get_wallstreetcn_lives"
            )

    @mcp.tool()
    async def get_macro_calendar(
        start_date: str = "",
        end_date: str = "",
        country: str = "",
        min_importance: str = "",
    ) -> str:
        """
        获取全球宏观日历（公布值/预期/前值）。

        Args:
            start_date: 起始日期 YYYY-MM-DD（默认今天）
            end_date: 截止日期 YYYY-MM-DD（默认未来 7 天）
            country: 国家/地区过滤，"中国" / "美国" / "欧元区" / "日本" / ""(全部)
            min_importance: 重要性过滤，"高" / "中" / "低" / ""(全部)

        Returns:
            宏观事件日历 (JSON)，含时间、国家/地区、指标、重要性、公布值、预期值、前值。
        """
        try:
            result = global_news_service.get_macro_calendar(
                start_date=start_date, end_date=end_date,
                country=country, min_importance=min_importance,
            )
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(f"获取宏观日历失败: {e}", "get_macro_calendar")

    @mcp.tool()
    async def get_cctv_news(date: str = "", with_content: bool = False) -> str:
        """
        获取央视新闻联播条目 + 文字稿（政策信号挖掘）。

        当晚约 20:00 后才有当日条目。

        Args:
            date: 日期 YYYY-MM-DD，默认今天
            with_content: 是否获取正文内容（额外请求每条详情页，较慢）

        Returns:
            新闻联播条目列表 (JSON)，含标题、时间、链接，可选正文。
        """
        try:
            result = global_news_service.get_cctv_news(
                date=date, with_content=with_content
            )
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(f"获取新闻联播失败: {e}", "get_cctv_news")
