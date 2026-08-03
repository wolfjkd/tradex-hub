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
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..data_sources import get_router
from ..utils.cache import TTL_DAILY, cache
from ..utils.formatter import df_to_json, error_response, slim_df

_router = get_router()


def register(mcp: FastMCP):
    """Register industry sector tools with the MCP server."""

    @mcp.tool()
    async def get_industry_list() -> str:
        """
        获取行业板块列表。

        Returns:
            行业板块列表 (JSON)，包含板块名称、涨跌幅、总市值、
            换手率、领涨股等信息。
        """
        cache_key = "industry_list"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        # Primary: 东方财富, Fallback: 同花顺
        for ep in ["board_industry_name_em", "board_industry_name_ths"]:
            try:
                df, _src = _router.route("industry_data", endpoint=ep)
                if df is not None and not df.empty:
                    result = df_to_json(df)
                    cache.set(cache_key, result, TTL_DAILY)
                    return result
            except Exception:
                continue

        return error_response(
            "获取行业板块列表失败: 所有数据源均不可用", "get_industry_list"
        )

    @mcp.tool()
    async def get_industry_stocks(industry: str) -> str:
        """
        获取指定行业板块的成分股列表。

        Args:
            industry: 行业板块名称，如 "白酒"、"银行"、"半导体"、"新能源车"

        Returns:
            该行业所有成分股 (JSON)，包含代码、名称、最新价、涨跌幅、
            市盈率、市净率等。
        """
        cache_key = f"industry_stocks:{industry}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            df, _src = _router.route(
                "industry_data", endpoint="board_industry_cons_em", industry=industry
            )
            df = slim_df(df)
            result = df_to_json(df)
            cache.set(cache_key, result, TTL_DAILY)
            return result
        except Exception as e:
            return error_response(
                f"获取行业成分股失败 ({industry}): {e}", "get_industry_stocks"
            )

    @mcp.tool()
    async def get_concept_list() -> str:
        """
        获取概念板块列表。

        概念板块如：华为概念、ChatGPT、锂电池、芯片、光伏等。

        Returns:
            概念板块列表 (JSON)，包含板块名称、涨跌幅、总市值、
            换手率、领涨股等信息。
        """
        cache_key = "concept_list"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        # Primary: 东方财富, Fallback: 同花顺
        for ep in ["board_concept_name_em", "board_concept_name_ths"]:
            try:
                df, _src = _router.route("industry_data", endpoint=ep)
                if df is not None and not df.empty:
                    result = df_to_json(df)
                    cache.set(cache_key, result, TTL_DAILY)
                    return result
            except Exception:
                continue

        return error_response(
            "获取概念板块列表失败: 所有数据源均不可用", "get_concept_list"
        )

    @mcp.tool()
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
        cache_key = f"sector_fund_flow:{sector_type}:{indicator}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            # Primary: 东方财富资金流向排名
            df = None
            try:
                df, _src = _router.route(
                    "industry_data",
                    endpoint="sector_fund_flow_rank",
                    sector_type=sector_type,
                    indicator=indicator,
                )
            except Exception:
                pass

            if df is None or df.empty:
                # Fallback: 新浪板块行情（不含资金流明细，但提供板块涨跌/成交额/涨跌停数）
                try:
                    import akshare as ak
                    sina_df = ak.stock_sector_spot()
                    if sina_df is not None and not sina_df.empty:
                        # 保留所有可用字段，映射中文名
                        _col_map = {
                            "板块": "板块", "涨跌幅": "涨跌幅", "涨跌额": "涨跌额",
                            "总成交额": "总成交额", "总成交量": "总成交量",
                            "公司家数": "公司家数", "平均价格": "平均价格",
                        }
                        keep = [c for c in _col_map if c in sina_df.columns]
                        df = sina_df[keep].rename(columns={k: v for k, v in _col_map.items() if k in keep})
                        df["数据源"] = "新浪财经（备源-无资金流明细）"
                        df["说明"] = "主源东方财富资金流向排名不可用，新浪备源仅提供板块涨跌和成交额"
                except Exception:
                    pass

            if df is None or df.empty:
                return df_to_json(pd.DataFrame([{
                    "提示": f"板块资金流向暂不可用 ({sector_type})",
                    "说明": "东方财富数据源连接失败，新浪备源不可用",
                }]))
            # 直接返回原始数据，保留所有字段
            result = df_to_json(df, max_rows=30)
            cache.set(cache_key, result, TTL_DAILY)
            return result
        except Exception as e:
            return error_response(
                f"获取板块资金流向失败 ({sector_type}): {e}",
                "get_sector_fund_flow",
            )

    @mcp.tool()
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
        cache_key = f"industry_pe:{industry}:{start_date}:{end_date}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            df, _src = _router.route(
                "industry_data",
                endpoint="board_industry_hist_em",
                industry=industry,
                period="日k",
                start_date=start_date,
                end_date=end_date,
            )
            result = df_to_json(df, max_rows=250)
            cache.set(cache_key, result, TTL_DAILY)
            return result
        except Exception as e:
            return error_response(
                f"获取行业历史行情失败 ({industry}): {e}", "get_industry_pe"
            )
