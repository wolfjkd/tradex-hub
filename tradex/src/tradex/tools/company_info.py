"""
Category 1: Company Information & Search (V0.1)

Tools:
  1. search_stock       - Search A-share stocks by name or code
  2. get_company_info   - Get company basic info (industry, market cap, shares)
  3. get_company_profile - Get company business description & revenue breakdown
  4. get_competitors    - Get peer companies in the same industry

Data source routing (via SmartRouter):
  公司信息: akshare company_info (endpoints: code_name/individual_info/profile/industry_cons)

v3.4.0 工单 05：业务逻辑已抽到 service/company_service.py，本文件保留薄包装
（MCP 工具层），调用 service 并用 json.dumps 转 MCP 协议字符串。
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from ..service import company_service
from ..utils.formatter import error_response


def register(mcp: FastMCP):
    """Register company information tools with the MCP server.

    v3.4.0：业务逻辑在 service/company_service.py，本函数只做 MCP 薄包装。
    """

    @mcp.tool()
    async def search_stock(keyword: str) -> str:
        """
        搜索A股股票，支持名称或代码模糊匹配。

        Args:
            keyword: 搜索关键词，可以是股票名称（如"贵州茅台"）或代码（如"600519"）

        Returns:
            匹配的股票列表 (JSON)，包含代码(code)和名称(name)字段，最多返回20条。
        """
        try:
            result = company_service.search_stock(keyword=keyword)
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(f"搜索股票失败: {e}", "search_stock")

    @mcp.tool()
    async def get_company_info(symbol: str) -> str:
        """
        获取A股公司基本信息，包括行业、市值、股本等。

        Args:
            symbol: 6位股票代码，如 "000001"（平安银行）、"600519"（贵州茅台）

        Returns:
            公司基本信息 (JSON)，包含总市值、流通市值、行业、上市日期等。
        """
        try:
            result = company_service.get_company_info(symbol=symbol)
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(
                f"获取公司信息失败 ({symbol}): {e}", "get_company_info"
            )

    @mcp.tool()
    async def get_company_profile(symbol: str) -> str:
        """
        获取公司主营业务构成和业务描述。

        Args:
            symbol: 6位股票代码，如 "000001"（平安银行）

        Returns:
            公司主营业务构成 (JSON)，包含各业务的营收占比、毛利率等。
        """
        try:
            result = company_service.get_company_profile(symbol=symbol)
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(
                f"获取公司主营构成失败 ({symbol}): {e}", "get_company_profile"
            )

    @mcp.tool()
    async def get_competitors(
        symbol: str, industry: str = ""
    ) -> str:
        """
        获取同行业公司列表（竞争对手/可比公司）。

        先根据股票代码查找所属行业板块，然后返回该板块的所有成分股。
        也可以直接传入行业名称来查询。

        Args:
            symbol: 6位股票代码，如 "600519"。如果同时提供了 industry 参数则忽略此参数。
            industry: 行业板块名称，如 "白酒"、"银行"。如果为空则自动从 symbol 推断。

        Returns:
            同行业公司列表 (JSON)，包含代码、名称、最新价、涨跌幅等。
        """
        try:
            result = company_service.get_competitors(symbol=symbol, industry=industry)
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(
                f"获取竞争对手列表失败 ({symbol}, {industry}): {e}",
                "get_competitors",
            )
