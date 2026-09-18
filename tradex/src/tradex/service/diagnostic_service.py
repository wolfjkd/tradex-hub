"""诊断/分析类 service —— 综合诊断、市场全景、技术分析。

对应 MCP 工具：
  - analyze_stock_comprehensive (composite_analysis.py)
  - analyze_market_overview     (composite_analysis.py)
  - analyze_technical           (analysis_engine.py)

设计说明（工单 09 决策）：
  这三个分析函数都是「组合器/编排器」——业务逻辑深嵌于 tools 模块内部
  （依赖 _safe_call、_get_*_sync、_load_ohlcv、AnalysisEngine 等辅助）。
  抽离整套逻辑代价高且易引入回归。故采取「薄 service 层」策略：
  service 函数复用 tools 模块顶层的辅助函数（非闭包内），保证 MCP 与 REST
  走同一执行路径，契约一致性天然成立。MCP 工具本身不动（零回归风险）。

返回 dict；MCP 与 REST 的序列化差异（json str vs envelope）由各自调用方处理。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ..utils.cache import cache, TTL_REALTIME, TTL_DAILY
from ..utils.symbol import normalize_symbol

logger = logging.getLogger(__name__)


def _err_dict(message: str, tool_name: str = "") -> dict:
    """service 层错误返回 dict（区别于 formatter.error_response 的 JSON 字符串）。

    REST 端点和 service 内部都用 dict 传递错误；MCP 工具层若需 JSON 字符串可另行序列化。
    """
    return {"success": False, "error": message, "tool": tool_name}


async def analyze_stock_comprehensive(symbol: str) -> dict:
    """个股综合分析 —— 行情 / 公司 / 财务 / 板块资金 4 维度并行获取。

    复用 composite_analysis 模块顶层的辅助函数（_safe_call / _get_*_sync）。
    返回 dict，结构与 MCP 工具 analyze_stock_comprehensive 内部 result 完全一致。
    """
    from ..tools.composite_analysis import (
        _safe_call,
        _get_realtime_quote_sync,
        _get_company_info_sync,
        _get_financial_indicators_sync,
        _get_sector_fund_flow_sync,
    )

    symbol = normalize_symbol(symbol)
    cache_key = f"composite:stock:{symbol}"
    cached = cache.get(cache_key)
    if cached is not None and isinstance(cached, dict):
        return cached

    quote_task = _safe_call(_get_realtime_quote_sync, symbol)
    company_task = _safe_call(_get_company_info_sync, symbol)
    financial_task = _safe_call(_get_financial_indicators_sync, symbol)
    fund_flow_task = _safe_call(_get_sector_fund_flow_sync)

    quote_result, company_result, financial_result, fund_flow_result = (
        await asyncio.gather(
            quote_task, company_task, financial_task, fund_flow_task
        )
    )

    result: dict[str, Any] = {
        "symbol": symbol,
        "realtime_quote": quote_result,
        "company_info": company_result,
        "financial_indicators": financial_result,
        "sector_fund_flow": fund_flow_result,
    }
    success_count = sum(
        1 for r in [quote_result, company_result, financial_result, fund_flow_result]
        if isinstance(r, dict) and r.get("success")
    )
    result["summary"] = {
        "total_dimensions": 4,
        "success_dimensions": success_count,
        "status": "complete" if success_count == 4 else "partial",
    }

    cache.set(cache_key, result, TTL_REALTIME)
    return result


async def analyze_market_overview() -> dict:
    """市场全景分析 —— 大盘指数 / 板块资金 / 涨跌停 3 维度并行获取。

    返回 dict，结构与 MCP 工具 analyze_market_overview 内部 result 完全一致。
    """
    from ..tools.composite_analysis import (
        _safe_call,
        _get_market_overview_sync,
        _get_sector_fund_flow_sync,
        _get_limit_up_down_sync,
    )

    cache_key = "composite:market_overview"
    cached = cache.get(cache_key)
    if cached is not None and isinstance(cached, dict):
        return cached

    market_task = _safe_call(_get_market_overview_sync)
    fund_flow_task = _safe_call(_get_sector_fund_flow_sync)
    limit_task = _safe_call(_get_limit_up_down_sync)

    market_result, fund_flow_result, limit_result = await asyncio.gather(
        market_task, fund_flow_task, limit_task
    )

    result: dict[str, Any] = {
        "market_indices": market_result,
        "sector_fund_flow": fund_flow_result,
        "limit_up_down": limit_result,
    }
    success_count = sum(
        1 for r in [market_result, fund_flow_result, limit_result]
        if isinstance(r, dict) and r.get("success")
    )
    result["summary"] = {
        "total_dimensions": 3,
        "success_dimensions": success_count,
        "status": "complete" if success_count == 3 else "partial",
    }

    cache.set(cache_key, result, TTL_REALTIME)
    return result


def analyze_technical(symbol: str, look_back_days: int = 30) -> dict:
    """5 维度技术分析（均线 / 趋势 / 量价 / 筹码 / 形态）。

    同步函数：直接复用 analysis_engine._load_ohlcv + AnalysisEngine。
    返回 dict，结构与 MCP 工具 analyze_technical 的输出（去 JSON 化后）一致。
    """
    from ..tools.analysis_engine import _load_ohlcv, AnalysisEngine

    symbol = normalize_symbol(symbol)
    if look_back_days <= 0:
        return _err_dict(
            "参数错误: look_back_days 必须为正整数",
            "analyze_technical",
        )

    cache_key = f"analyze_technical:{symbol}:{look_back_days}"
    cached = cache.get(cache_key)
    if cached is not None and isinstance(cached, dict):
        return cached

    try:
        df = _load_ohlcv(symbol, look_back_days)
        if df is None or df.empty:
            return _err_dict(
                f"无法获取 {symbol} 的 OHLCV 数据",
                "analyze_technical",
            )
        engine = AnalysisEngine(df, symbol=symbol)
        result = engine.analyze_all()
        if isinstance(result.get("data_points"), int):
            result["data_points"] = min(result["data_points"], look_back_days)
        cache.set(cache_key, result, TTL_DAILY)
        return result
    except Exception as e:
        logger.warning("service.analyze_technical 失败 %s: %s", symbol, e)
        return _err_dict(f"技术分析失败: {e}", "analyze_technical")
