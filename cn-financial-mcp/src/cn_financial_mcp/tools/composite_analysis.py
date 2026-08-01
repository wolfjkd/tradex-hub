"""
Category 13: Composite Analysis — 组合分析工具 (V2.6.0).

将多个原子工具组合为高级分析流程，一次调用获取完整分析视图。
AI Agent 无需多次调用和组装数据，降低上下文消耗。

设计原则：
  1. 并行获取：asyncio.gather 并行调用各维度数据，降低延迟
  2. 容错降级：单维度失败不影响其他维度，返回 partial 结果
  3. 结构化输出：统一 JSON 格式，包含各维度分析结果和状态

Tools (共 3 个):
  73. analyze_stock_comprehensive  - 个股综合分析（行情+技术+基本面+资金+估值+信号）
  74. analyze_industry_comparison  - 行业对比分析（个股 vs 同行业）
  75. analyze_market_overview      - 市场全景分析（大盘+板块+涨跌停+北向）
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import akshare as ak
from mcp.server.fastmcp import FastMCP

from ..utils.cache import cache, TTL_REALTIME, TTL_DAILY
from ..utils.formatter import dict_to_json, error_response, df_to_json, slim_df
from ..utils.symbol import normalize_symbol

logger = logging.getLogger(__name__)


async def _safe_call(func, *args, **kwargs) -> dict:
    """安全调用函数，捕获异常返回错误信息。

    Args:
        func: 要调用的函数
        *args, **kwargs: 函数参数

    Returns:
        成功返回 {"success": True, "data": result}，
        失败返回 {"success": False, "error": str}
    """
    try:
        result = await func(*args, **kwargs) if asyncio.iscoroutinefunction(func) else func(*args, **kwargs)
        return {"success": True, "data": result}
    except Exception as exc:
        logger.warning("组合分析子调用失败 %s: %s", func.__name__, exc)
        return {"success": False, "error": str(exc)}


def _get_realtime_quote_sync(symbol: str) -> dict:
    """同步获取实时行情（内部函数）。"""
    df = ak.stock_zh_a_spot_em()
    row = df[df["代码"] == symbol]
    if row.empty:
        raise ValueError(f"未找到股票 {symbol} 的实时行情")
    r = row.iloc[0]
    return {
        "code": str(r.get("代码", "")),
        "name": str(r.get("名称", "")),
        "price": float(r.get("最新价", 0)),
        "change_pct": float(r.get("涨跌幅", 0)),
        "change_amount": float(r.get("涨跌额", 0)),
        "volume": float(r.get("成交量", 0)),
        "turnover": float(r.get("成交额", 0)),
        "high": float(r.get("最高", 0)),
        "low": float(r.get("最低", 0)),
        "open": float(r.get("今开", 0)),
        "prev_close": float(r.get("昨收", 0)),
        "turnover_rate": float(r.get("换手率", 0)),
        "pe_ratio": float(r.get("市盈率-动态", 0)),
        "total_market_cap": float(r.get("总市值", 0)),
    }


def _get_company_info_sync(symbol: str) -> dict:
    """同步获取公司基本信息（内部函数）。"""
    df = ak.stock_individual_info_em(symbol=symbol)
    if df is None or df.empty:
        raise ValueError(f"未找到股票 {symbol} 的公司信息")
    info = {}
    for _, row in df.iterrows():
        info[str(row.iloc[0])] = str(row.iloc[1])
    return info


def _get_financial_indicators_sync(symbol: str) -> dict:
    """同步获取财务指标（内部函数）。"""
    df = ak.stock_financial_analysis_indicator(symbol=symbol, start_year="2020")
    if df is None or df.empty:
        raise ValueError(f"未找到股票 {symbol} 的财务指标")
    latest = df.iloc[:4]  # 最近4个报告期
    records = []
    for _, row in latest.iterrows():
        records.append({
            "date": str(row.get("日期", "")),
            "roe": float(row.get("净资产收益率(%)", 0) or 0),
            "net_profit_margin": float(row.get("销售净利率(%)", 0) or 0),
            "gross_margin": float(row.get("销售毛利率(%)", 0) or 0),
            "debt_ratio": float(row.get("资产负债率(%)", 0) or 0),
            "current_ratio": float(row.get("流动比率", 0) or 0),
        })
    return {"indicators": records}


def _get_sector_fund_flow_sync() -> dict:
    """同步获取板块资金流向（内部函数）。"""
    df = ak.stock_sector_fund_flow_rank(indicator="今日", sector_type="行业资金流")
    if df is None or df.empty:
        raise ValueError("未获取到板块资金流向数据")
    top = df.head(10)
    return {
        "top_inflow": df_to_json(slim_df(top, max_rows=5)),
        "top_outflow": df_to_json(slim_df(df.tail(5), max_rows=5)),
    }


def _get_market_overview_sync() -> dict:
    """同步获取大盘总览（内部函数）。"""
    df = ak.stock_zh_index_spot_em(symbol="上证系列指数")
    sh = df[df["代码"] == "000001"] if df is not None and not df.empty else None
    df2 = ak.stock_zh_index_spot_em(symbol="深证系列指数")
    sz = df2[df2["代码"] == "399001"] if df2 is not None and not df2.empty else None
    df3 = ak.stock_zh_index_spot_em(symbol="创业板系列指数")
    cy = df3[df3["代码"] == "399006"] if df3 is not None and not df3.empty else None

    result = {}
    for name, row_data in [("shanghai", sh), ("shenzhen", sz), ("chinext", cy)]:
        if row_data is not None and not row_data.empty:
            r = row_data.iloc[0]
            result[name] = {
                "name": str(r.get("名称", "")),
                "price": float(r.get("最新价", 0)),
                "change_pct": float(r.get("涨跌幅", 0)),
            }
    return result


def _get_limit_up_down_sync() -> dict:
    """同步获取涨跌停统计（内部函数）。"""
    try:
        df_up = ak.stock_zt_pool_em(date="")
        up_count = len(df_up) if df_up is not None else 0
    except Exception:
        up_count = -1
    try:
        df_down = ak.stock_zt_pool_dtgc_em(date="")
        down_count = len(df_down) if df_down is not None else 0
    except Exception:
        down_count = -1
    return {"limit_up": up_count, "limit_down": down_count}


def register(mcp: FastMCP):
    """Register composite analysis tools with the MCP server."""

    @mcp.tool()
    async def analyze_stock_comprehensive(symbol: str) -> str:
        """
        个股综合分析 — 一次调用获取完整分析视图。

        组合以下维度数据：
        - 实时行情（价格、涨跌、成交量、市值、换手率）
        - 公司信息（行业、上市日期、总股本等）
        - 财务指标（ROE、净利率、毛利率、资产负债率，最近4期）
        - 板块资金流向（当日行业资金流入/流出 Top5）

        Args:
            symbol: 6位A股股票代码，如 "600519"（贵州茅台）

        Returns:
            JSON 格式的综合分析结果，包含各维度数据和成功/失败状态。
        """
        symbol = normalize_symbol(symbol)
        cache_key = f"composite:stock:{symbol}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        # 并行获取各维度数据
        quote_task = _safe_call(_get_realtime_quote_sync, symbol)
        company_task = _safe_call(_get_company_info_sync, symbol)
        financial_task = _safe_call(_get_financial_indicators_sync, symbol)
        fund_flow_task = _safe_call(_get_sector_fund_flow_sync)

        quote_result, company_result, financial_result, fund_flow_result = (
            await asyncio.gather(
                quote_task, company_task, financial_task, fund_flow_task
            )
        )

        result = {
            "symbol": symbol,
            "realtime_quote": quote_result,
            "company_info": company_result,
            "financial_indicators": financial_result,
            "sector_fund_flow": fund_flow_result,
        }

        # 统计成功数
        success_count = sum(
            1 for r in [quote_result, company_result, financial_result, fund_flow_result]
            if r.get("success")
        )
        result["summary"] = {
            "total_dimensions": 4,
            "success_dimensions": success_count,
            "status": "complete" if success_count == 4 else "partial",
        }

        output = dict_to_json(result, "stock_comprehensive_analysis")
        cache.set(cache_key, output, TTL_REALTIME)
        return output

    @mcp.tool()
    async def analyze_industry_comparison(symbol: str) -> str:
        """
        行业对比分析 — 个股指标 vs 同行业均值。

        获取个股的行业分类，然后获取同行业所有股票的关键指标，
        计算行业平均值，对比个股在行业中的排名。

        Args:
            symbol: 6位A股股票代码，如 "600519"（贵州茅台）

        Returns:
            JSON 格式的行业对比分析结果。
        """
        symbol = normalize_symbol(symbol)
        cache_key = f"composite:industry:{symbol}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        # Step 1: 获取个股行业信息
        company_result = await _safe_call(_get_company_info_sync, symbol)
        if not company_result.get("success"):
            return error_response(
                f"无法获取公司信息: {company_result.get('error')}",
                "analyze_industry_comparison",
            )

        industry = company_result["data"].get("行业", "")

        # Step 2: 获取行业成分股
        try:
            industry_code = None
            board_df = ak.stock_board_industry_name_em()
            if board_df is not None and not board_df.empty:
                match = board_df[board_df["板块名称"].str.contains(industry, na=False)]
                if not match.empty:
                    industry_code = match.iloc[0].get("板块代码")

            if industry_code is None:
                return error_response(
                    f"未找到行业 '{industry}' 的板块代码",
                    "analyze_industry_comparison",
                )

            # 获取行业成分股
            constituents = ak.stock_board_industry_cons_em(symbol=industry)
            if constituents is None or constituents.empty:
                return error_response(
                    f"行业 '{industry}' 无成分股数据",
                    "analyze_industry_comparison",
                )
        except Exception as exc:
            return error_response(
                f"获取行业数据失败: {exc}",
                "analyze_industry_comparison",
            )

        # Step 3: 计算行业统计
        stats = {
            "industry": industry,
            "constituent_count": len(constituents),
            "stock_rank": None,
        }

        # 尝试计算关键指标的行业排名
        for metric, label in [
            ("涨跌幅", "change_pct"),
            ("换手率", "turnover_rate"),
            ("市盈率-动态", "pe_ratio"),
        ]:
            if metric in constituents.columns:
                col = constituents[metric]
                stock_row = constituents[constituents["代码"] == symbol]
                if not stock_row.empty:
                    stock_val = float(stock_row.iloc[0][metric])
                    rank = int((col > stock_val).sum()) + 1
                    stats[label] = {
                        "stock_value": stock_val,
                        "industry_avg": round(float(col.mean()), 4),
                        "industry_median": round(float(col.median()), 4),
                        "rank": rank,
                        "total": len(constituents),
                    }

        output = dict_to_json(stats, "industry_comparison")
        cache.set(cache_key, output, TTL_DAILY)
        return output

    @mcp.tool()
    async def analyze_market_overview() -> str:
        """
        市场全景分析 — 大盘指数 + 板块资金 + 涨跌停统计。

        一次获取市场全景数据：
        - 三大指数（上证、深证、创业板）实时行情
        - 行业板块资金流向 Top5
        - 涨停/跌停数量统计

        Returns:
            JSON 格式的市场全景分析结果。
        """
        cache_key = "composite:market_overview"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        # 并行获取
        market_task = _safe_call(_get_market_overview_sync)
        fund_flow_task = _safe_call(_get_sector_fund_flow_sync)
        limit_task = _safe_call(_get_limit_up_down_sync)

        market_result, fund_flow_result, limit_result = await asyncio.gather(
            market_task, fund_flow_task, limit_task
        )

        result = {
            "market_indices": market_result,
            "sector_fund_flow": fund_flow_result,
            "limit_up_down": limit_result,
        }

        success_count = sum(
            1 for r in [market_result, fund_flow_result, limit_result]
            if r.get("success")
        )
        result["summary"] = {
            "total_dimensions": 3,
            "success_dimensions": success_count,
            "status": "complete" if success_count == 3 else "partial",
        }

        output = dict_to_json(result, "market_overview")
        cache.set(cache_key, output, TTL_REALTIME)
        return output
