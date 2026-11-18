"""
tdx_tq 决策支持工具（L3 决策支持层）— SP-2026-10-13-001。

本模块是通达信 TQ 本地源（HTTP 127.0.0.1:17709）的「决策支持」暴露层。
只暴露 tq 独占增量能力（其余源均无），与 eltdx/tdx_mcp 互备的 realtime_quote
不在此重复包装（对外入口仍是 price_data，路由自动选源）：

  - get_l2_stats    : 当日 L2 统计（逐笔委托数/逐笔成交数/买撤单额/卖撤单额）
  - run_tdx_formula : 通达信内置公式批量计算（公式生态桥）

实现约定（对齐 tools/tdx_mcp.py）：
  - register(mcp) 函数轨 + @mcp.tool() 注册（tools 包自动发现）。
  - 数据一律经 get_router().route() 获取，不直接 import tq_fetchers（铁律）。
  - 源不可用（通达信客户端没开）时 route 内部消化，返回 error_response 兜底。
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..data_sources import get_router
from ..utils.cache import TTL_DAILY, TTL_REALTIME, cache
from ..utils.formatter import df_to_json, dict_to_json, error_response

_router = get_router()


def _route_to_json(data_type: str, tool_name: str, ttl: int, cache_key: str, **kwargs) -> str:
    """「route → JSON → 缓存 → 失败兜底」骨架（对齐 tdx_mcp._router_route_cached）。"""
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        data, _src = _router.route(data_type, **kwargs)
        if hasattr(data, "to_dict") or hasattr(data, "iloc"):  # DataFrame/Series
            out = df_to_json(data)
        else:
            out = dict_to_json(data)
        cache.set(cache_key, out, ttl)
        return out
    except Exception as e:  # noqa: BLE001 —— 源不可用统一兜底，不外泄
        return error_response(f"获取 {data_type} 数据失败: {e}", tool_name)


# （QI-ARCH-02 全量上提，2026-11-19：2 个工具体模块级化——_route_to_json
# 模块级骨架本身即「route→JSON→缓存→兜底」出口单点，保持调用不强套
# mcp_serve，避免双出口单点并存。）


async def get_l2_stats(code: str) -> str:
    """
    当日 L2 统计查询（通达信 TQ 本地源，独占数据）。
    返回逐笔委托数/逐笔成交数/买撤单额/卖撤单额四项当日累计，
    供撤单动力学、盘口博弈分析。需本机通达信客户端运行中。

    Args:
        code: 6位股票代码，如 "600170"，支持带后缀 "600170.SH"。

    Returns:
        JSON：{"代码", "L2OrderNum", "L2TicNum", "BCancel", "SCancel"}。
    """
    code = (code or "").strip()
    return _route_to_json("l2_stats", "get_l2_stats", TTL_REALTIME,
                          f"tq_l2:{code}", code=code)


async def run_tdx_formula(formula: str, codes: str,
                          return_count: int = 1, period: str = "1d") -> str:
    """
    通达信内置公式批量计算（TQ 本地源公式生态桥）。
    支持通达信客户端可用的任意内置指标（MA/MACD/KDJ/BOLL 等），
    批量执行后返回各票各输出线的数值序列。需本机通达信客户端运行中。

    Args:
        formula: 通达信公式名，如 "MA"/"MACD"/"KDJ"（注意：L2 系公式取决于客户端环境）。
        codes: 逗号分隔的股票代码，如 "600170,601868"。
        return_count: 每票返回的序列长度（默认 1，取最新）。
        period: K线周期（默认 "1d"，支持 1m/5m/15m/30m/1h/1d/1w 等）。

    Returns:
        JSON：{"<code>": {"<输出线>": [值, ...]}, ...}。
    """
    formula = (formula or "").strip()
    stock_list = [c.strip() for c in (codes or "").split(",") if c.strip()]
    return_count = max(1, min(int(return_count), 100))
    return _route_to_json("tdx_formula", "run_tdx_formula", TTL_DAILY,
                          f"tq_formula:{formula}:{codes}:{return_count}:{period}",
                          formula=formula, stock_list=stock_list,
                          return_count=return_count, stock_period=period)


def register(mcp: FastMCP):
    """注册通达信 TQ 本地源工具。

    QI-ARCH-02 全量上提（2026-11-19）：2 工具体模块级，引用注册。"""
    for _fn in (
        get_l2_stats,
        run_tdx_formula,
    ):
        mcp.tool()(_fn)
