"""
Category 3: Financial Statements (V0.2)

Tools:
  9.  get_income_statement      - Quarterly income statement
  10. get_balance_sheet         - Quarterly balance sheet
  11. get_cash_flow_statement   - Quarterly cash flow statement
  12. get_financial_line_item   - Extract specific line items
  13. get_financial_indicators  - Key financial ratios (ROE, margins, etc.)
  14. get_growth_rates          - Revenue/profit growth rates
  15. get_per_share_data        - EPS, BPS, CFPS, etc.
  16. get_segments_revenue      - Revenue breakdown by business segment

Data source routing (via SmartRouter):
  财务报表: akshare financial_stmt (endpoints: profit/balance/cashflow/indicator/segments)

v3.4.0 工单 05：业务逻辑已抽到 service/financial_service.py，本文件保留薄包装
（MCP 工具层），调用 service 并用 json.dumps 转 MCP 协议字符串。
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from ..service import financial_service
from ..utils.formatter import error_response


def register(mcp: FastMCP):
    """Register financial statement tools with the MCP server.

    v3.4.0：业务逻辑在 service/financial_service.py，本函数只做 MCP 薄包装。
    """

    @mcp.tool()
    async def get_income_statement(
        symbol: str,
        num_quarters: int = 8,
    ) -> str:
        """
        获取利润表（按季度）。

        Args:
            symbol: 6位股票代码，如 "600519"
            num_quarters: 返回最近几个季度的数据，默认8个季度（2年）

        Returns:
            利润表数据 (JSON)，包含营业收入、营业成本、毛利润、净利润、
            研发费用、销售费用、管理费用等字段。
        """
        try:
            result = financial_service.get_income_statement(
                symbol=symbol, num_quarters=num_quarters
            )
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(
                f"获取利润表失败 ({symbol}): {e}", "get_income_statement"
            )

    @mcp.tool()
    async def get_balance_sheet(
        symbol: str,
        num_quarters: int = 8,
    ) -> str:
        """
        获取资产负债表（按季度）。

        Args:
            symbol: 6位股票代码，如 "600519"
            num_quarters: 返回最近几个季度的数据，默认8个季度

        Returns:
            资产负债表数据 (JSON)，包含总资产、总负债、股东权益、
            流动资产、非流动资产、存货、应收账款等。
        """
        try:
            result = financial_service.get_balance_sheet(
                symbol=symbol, num_quarters=num_quarters
            )
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(
                f"获取资产负债表失败 ({symbol}): {e}", "get_balance_sheet"
            )

    @mcp.tool()
    async def get_cash_flow_statement(
        symbol: str,
        num_quarters: int = 8,
    ) -> str:
        """
        获取现金流量表（按季度）。

        Args:
            symbol: 6位股票代码，如 "600519"
            num_quarters: 返回最近几个季度的数据，默认8个季度

        Returns:
            现金流量表数据 (JSON)，包含经营活动现金流、投资活动现金流、
            筹资活动现金流、自由现金流等。
        """
        try:
            result = financial_service.get_cash_flow_statement(
                symbol=symbol, num_quarters=num_quarters
            )
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(
                f"获取现金流量表失败 ({symbol}): {e}", "get_cash_flow_statement"
            )

    @mcp.tool()
    async def get_financial_line_item(
        symbol: str,
        item: str,
        num_quarters: int = 8,
    ) -> str:
        """
        从三大财务报表中提取特定财务科目的时间序列数据。

        Args:
            symbol: 6位股票代码，如 "600519"
            item: 要提取的科目名称，如 "营业总收入"、"净利润"、"基本每股收益"、
                  "经营活动产生的现金流量净额"、"总资产" 等。支持模糊匹配。
            num_quarters: 返回最近几个季度的数据，默认8个季度

        Returns:
            该科目的时间序列数据 (JSON)，包含报告期和对应值。
        """
        try:
            result = financial_service.get_financial_line_item(
                symbol=symbol, item=item, num_quarters=num_quarters
            )
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(
                f"获取财务科目失败 ({symbol}, {item}): {e}",
                "get_financial_line_item",
            )

    @mcp.tool()
    async def get_financial_indicators(
        symbol: str,
        num_periods: int = 8,
    ) -> str:
        """
        获取财务分析指标（ROE、毛利率、净利率、资产负债率等）。

        Args:
            symbol: 6位股票代码，如 "600519"
            num_periods: 返回最近几期数据，默认8期

        Returns:
            财务指标数据 (JSON)，包含盈利能力、偿债能力、运营能力、
            成长能力等多维度指标。
        """
        try:
            result = financial_service.get_financial_indicators(
                symbol=symbol, num_periods=num_periods
            )
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(
                f"获取财务指标失败 ({symbol}): {e}", "get_financial_indicators"
            )

    @mcp.tool()
    async def get_growth_rates(
        symbol: str,
        num_periods: int = 8,
    ) -> str:
        """
        获取成长性指标（营收增长率、净利润增长率等）。

        Args:
            symbol: 6位股票代码，如 "600519"
            num_periods: 返回最近几期数据，默认8期

        Returns:
            成长性指标数据 (JSON)，包含各项增长率。
        """
        try:
            result = financial_service.get_growth_rates(
                symbol=symbol, num_periods=num_periods
            )
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(
                f"获取增长指标失败 ({symbol}): {e}", "get_growth_rates"
            )

    @mcp.tool()
    async def get_per_share_data(
        symbol: str,
        num_periods: int = 8,
    ) -> str:
        """
        获取每股指标（每股收益EPS、每股净资产BPS、每股现金流CFPS等）。

        Args:
            symbol: 6位股票代码，如 "600519"
            num_periods: 返回最近几期数据，默认8期

        Returns:
            每股指标数据 (JSON)，包含EPS、BPS、每股经营现金流等。
        """
        try:
            result = financial_service.get_per_share_data(
                symbol=symbol, num_periods=num_periods
            )
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(
                f"获取每股指标失败 ({symbol}): {e}", "get_per_share_data"
            )

    @mcp.tool()
    async def get_segments_revenue(symbol: str) -> str:
        """
        获取公司主营业务构成（按产品/地区分拆营收）。

        Args:
            symbol: 6位股票代码，如 "600519"

        Returns:
            主营构成数据 (JSON)，包含各业务板块的营收、占比、毛利率等。
        """
        try:
            result = financial_service.get_segments_revenue(symbol=symbol)
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return error_response(
                f"获取主营构成失败 ({symbol}): {e}", "get_segments_revenue"
            )
