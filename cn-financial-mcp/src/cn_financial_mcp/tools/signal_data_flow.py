"""
Signal Data — 资金流类子模块 (signal_data_flow)。

原 signal_data.py 拆分自 v3.0.0，本子模块承载资金流类信号工具：
北向资金、个股资金流、龙虎榜、行业横向对比。

TradingAgents-astock 移植层（V0.7 4 个工具）。
函数名带 _signal 后缀以避免与 market/industry 模块同名冲突。

Tools (共 4 个):
  get_northbound_flow_signal     - 北向资金流向（同花顺 hsgtApi，astock_signals）
  get_fund_flow_signal           - 个股资金流向（东财 push2，astock_signals）
  get_dragon_tiger_signal        - 龙虎榜席位明细（东财 datacenter，astock_signals）
  get_industry_comparison_signal - 行业横向对比排名（东财 push2，astock_signals）
"""

from __future__ import annotations

import os
import sys
import logging
import threading
from datetime import datetime, timedelta

from mcp.server.fastmcp import FastMCP

from ..utils.cache import TTL_DAILY, TTL_REALTIME, cache
from ..utils.formatter import error_response, dict_to_json
from ..utils.symbol import normalize_symbol, get_exchange

# Import astock_signals modules from Hub src/
_HUB_SRC = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "src")
)
if _HUB_SRC not in sys.path:
    sys.path.insert(0, _HUB_SRC)

from astock_signals import (  # noqa: E402
    get_northbound_flow_json,
    get_fund_flow_json,
    get_dragon_tiger_board_json,
    get_industry_comparison_json,
)
from astock_signals.smart_router import get_router  # noqa: E402

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# 模块级 SmartRouter 实例（全局单例，与 diagnostics 共享健康数据）
# 注册东财(em_push2/em_datacenter) + AKShare 两个数据源，东财优先
# ──────────────────────────────────────────────────────────────
_router = get_router()

# 东财源最近一次错误（全源失败时返回原东财错误，不抛新异常）
_em_last_error: dict[str, str] = {}
_em_error_lock = threading.Lock()


def _set_em_error(data_type: str, error: str) -> None:
    with _em_error_lock:
        if error:
            _em_last_error[data_type] = error
        else:
            _em_last_error.pop(data_type, None)


def _get_em_error(data_type: str) -> str:
    with _em_error_lock:
        return _em_last_error.pop(data_type, "东财接口失败")


# ── 东财源包装器：空数据/异常时抛 RuntimeError 触发 SmartRouter 降级 ──

def _em_fund_flow(code: str, curr_date: str = "", include_history: bool = True) -> dict:
    result = get_fund_flow_json(code, curr_date, include_history)
    if result.get("error") or (not result.get("realtime") and not result.get("history")):
        err = result.get("error", "东财返回空数据")
        _set_em_error("fund_flow", err)
        raise RuntimeError(err)
    _set_em_error("fund_flow", "")
    return result


def _em_dragon_tiger(code: str, trade_date: str = "", look_back_days: int = 30) -> dict:
    result = get_dragon_tiger_board_json(code, trade_date, look_back_days)
    has_data = (
        result.get("appearances")
        or result.get("latest_seats", {}).get("buy")
        or result.get("latest_seats", {}).get("sell")
        or result.get("institutional")
    )
    if not has_data:
        err = result.get("error_appearances") or result.get("error_seats") or "东财返回空数据"
        _set_em_error("dragon_tiger", err)
        raise RuntimeError(err)
    _set_em_error("dragon_tiger", "")
    return result


def _em_industry_comparison(code: str = "", trade_date: str = "", top_n: int = 20) -> dict:
    result = get_industry_comparison_json(code, trade_date, top_n)
    if result.get("error") or not result.get("industries"):
        err = result.get("error", "东财返回空数据")
        _set_em_error("industry_comparison", err)
        raise RuntimeError(err)
    _set_em_error("industry_comparison", "")
    return result


# ── AKShare 备用源包装器：返回与东财源相同的 dict 结构 ──

def _akshare_fund_flow(code: str, curr_date: str = "", include_history: bool = True) -> dict:
    import akshare as ak

    if not curr_date:
        curr_date = datetime.now().strftime("%Y-%m-%d")
    result: dict = {
        "symbol": code,
        "source": "AKShare stock_individual_fund_flow",
        "date": curr_date,
        "realtime": [],
        "history": [],
        "signal": "neutral",
    }
    market = get_exchange(code)  # 'sh' / 'sz' / 'bj'
    df = ak.stock_individual_fund_flow(stock=code, market=market)
    if df is None or df.empty:
        raise RuntimeError("AKShare 资金流数据为空")
    for _, row in df.iterrows():
        entry = {
            "date": str(row.get("日期", "")),
            "main_net": float(row.get("主力净流入-净额", 0) or 0),
            "small": float(row.get("小单净流入-净额", 0) or 0),
            "mid": float(row.get("中单净流入-净额", 0) or 0),
            "large": float(row.get("大单净流入-净额", 0) or 0),
            "super_large": float(row.get("超大单净流入-净额", 0) or 0),
        }
        result["history"].append(entry)
    if result["history"]:
        last = result["history"][-1]
        if last["main_net"] > 0:
            result["signal"] = "bullish_inflow"
        elif last["main_net"] < 0:
            result["signal"] = "bearish_outflow"
    return result


def _akshare_dragon_tiger(code: str, trade_date: str = "", look_back_days: int = 30) -> dict:
    import akshare as ak

    if not trade_date:
        trade_date = datetime.now().strftime("%Y-%m-%d")
    end_dt = datetime.strptime(trade_date, "%Y-%m-%d")
    start_dt = end_dt - timedelta(days=look_back_days)
    result: dict = {
        "symbol": code,
        "source": "AKShare stock_lhb_detail_em",
        "trade_date": trade_date,
        "look_back_days": look_back_days,
        "appearances": [],
        "latest_seats": {"buy": [], "sell": []},
        "institutional": None,
    }
    df = ak.stock_lhb_detail_em(
        start_date=start_dt.strftime("%Y%m%d"),
        end_date=end_dt.strftime("%Y%m%d"),
    )
    if df is None or df.empty:
        raise RuntimeError("AKShare 龙虎榜数据为空")
    code_col = "代码" if "代码" in df.columns else df.columns[1]
    filtered = df[df[code_col].astype(str).str.zfill(6) == code]
    if filtered.empty:
        raise RuntimeError(f"AKShare 龙虎榜无 {code} 上榜记录")
    for _, row in filtered.iterrows():
        result["appearances"].append({
            "date": str(row.get("上榜日", "")),
            "reason": str(row.get("解读", "")),
            "net_buy_wan": round(float(row.get("龙虎榜净买额", 0) or 0) / 10000, 1),
            "turnover_pct": round(float(row.get("换手率", 0) or 0), 2),
        })
    return result


def _akshare_industry_comparison(code: str = "", trade_date: str = "", top_n: int = 20) -> dict:
    import akshare as ak

    if not trade_date:
        trade_date = datetime.now().strftime("%Y-%m-%d")
    result: dict = {
        "source": "AKShare stock_sector_fund_flow_rank",
        "date": trade_date,
        "code": code or None,
        "industries": [],
    }
    df = ak.stock_sector_fund_flow_rank(indicator="今日", sector_type="行业资金流")
    if df is None or df.empty:
        raise RuntimeError("AKShare 行业资金流数据为空")
    for i, (_, row) in enumerate(df.iterrows()):
        if i >= top_n:
            break
        result["industries"].append({
            "rank": i + 1,
            "name": str(row.get("板块", "")),
            "change_pct": float(row.get("涨跌幅", 0) or 0),
            "up_count": 0,
            "down_count": 0,
            "leader": str(row.get("领涨股票", "")),
        })
    return result


# 注册数据源：东财(priority=1, 优先) + AKShare(priority=100, 备用)
_router.register("fund_flow", "em_push2", _em_fund_flow, priority=1)
_router.register("fund_flow", "akshare", _akshare_fund_flow, priority=100)
_router.register("dragon_tiger", "em_datacenter", _em_dragon_tiger, priority=1)
_router.register("dragon_tiger", "akshare", _akshare_dragon_tiger, priority=100)
_router.register("industry_comparison", "em_push2", _em_industry_comparison, priority=1)
_router.register("industry_comparison", "akshare", _akshare_industry_comparison, priority=100)


def register(mcp: FastMCP):
    """Register signal data flow tools with the MCP server."""

    # ----------------------------------------------------------------
    # V0.7: 4 tools from astock_signals (northbound/fund_flow/
    #       dragon_tiger/industry) — TradingAgents-astock 移植
    # 函数名带 _signal 后缀以避免与 market/industry 模块同名冲突
    # ----------------------------------------------------------------

    @mcp.tool()
    async def get_northbound_flow_signal(
        curr_date: str = "",
        include_history: bool = False,
    ) -> str:
        """
        获取北向资金流向（沪深股通）。

        数据源：同花顺 hsgtApi，提供实时分钟级沪股通+深股通累计净买入。
        附带本地缓存的历史每日收盘数据（最多20个交易日）。

        Args:
            curr_date: 日期 YYYY-MM-DD，空字符串默认今天。
            include_history: 是否包含历史每日数据（最近20个交易日）。

        Returns:
            北向资金数据 (JSON)，含实时数据点、收盘净流入、多空信号、历史数据。
        """
        cache_key = f"northbound:{curr_date or 'today'}:{include_history}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            result = get_northbound_flow_json(curr_date, include_history)
            output = dict_to_json(result)
            if result.get("realtime"):
                cache.set(cache_key, output, TTL_REALTIME)
            return output
        except Exception as e:
            return error_response(
                f"获取北向资金数据失败: {e}", "get_northbound_flow_signal"
            )

    @mcp.tool()
    async def get_fund_flow_signal(
        symbol: str,
        curr_date: str = "",
        include_history: bool = True,
    ) -> str:
        """
        获取个股资金流向（主力/大单/中单/小单/超大单净流入）。

        数据源：东财 push2（实时分钟级）+ push2his（历史日线20天）。
        可作为 AKShare 版 get_money_flow 的备用数据源。

        Args:
            symbol: 6位股票代码，如 "600519"。
            curr_date: 日期 YYYY-MM-DD，空字符串默认今天。
            include_history: 是否包含历史每日资金流（最近20个交易日）。

        Returns:
            资金流向数据 (JSON)，含实时分钟级数据、历史日线、多空信号。
        """
        symbol = normalize_symbol(symbol)
        cache_key = f"fund_flow_signal:{symbol}:{curr_date or 'today'}:{include_history}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            # SmartRouter 智能路由：东财 em_push2 优先，失败降级 AKShare
            result, _source = _router.route(
                "fund_flow",
                code=symbol,
                curr_date=curr_date,
                include_history=include_history,
            )
            output = dict_to_json(result)
            if result.get("realtime"):
                cache.set(cache_key, output, TTL_REALTIME)
            return output
        except RuntimeError:
            # 所有数据源失败，返回原东财接口的错误（不抛新异常）
            em_err = _get_em_error("fund_flow")
            return error_response(
                f"获取个股资金流向失败: {em_err}", "get_fund_flow_signal"
            )
        except Exception as e:
            return error_response(
                f"获取个股资金流向失败: {e}", "get_fund_flow_signal"
            )

    @mcp.tool()
    async def get_dragon_tiger_signal(
        symbol: str,
        trade_date: str = "",
        look_back_days: int = 30,
    ) -> str:
        """
        获取个股龙虎榜数据（上榜记录 + 买卖席位 + 机构动向）。

        数据源：东财 datacenter-web（直连，不依赖 AKShare）。
        可作为 AKShare 版 get_dragon_tiger 的备用数据源。

        Args:
            symbol: 6位股票代码，如 "000858"。
            trade_date: 参考日期 YYYY-MM-DD，空字符串默认今天。
            look_back_days: 向前查询天数，默认30天。

        Returns:
            龙虎榜数据 (JSON)，含上榜记录、买卖席位TOP5、机构动向。
        """
        symbol = normalize_symbol(symbol)
        cache_key = f"dragon_tiger_signal:{symbol}:{trade_date or 'today'}:{look_back_days}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            # SmartRouter 智能路由：东财 em_datacenter 优先，失败降级 AKShare
            result, _source = _router.route(
                "dragon_tiger",
                code=symbol,
                trade_date=trade_date,
                look_back_days=look_back_days,
            )
            output = dict_to_json(result)
            cache.set(cache_key, output, TTL_DAILY)
            return output
        except RuntimeError:
            # 所有数据源失败，返回原东财接口的错误（不抛新异常）
            em_err = _get_em_error("dragon_tiger")
            return error_response(
                f"获取龙虎榜数据失败: {em_err}", "get_dragon_tiger_signal"
            )
        except Exception as e:
            return error_response(
                f"获取龙虎榜数据失败: {e}", "get_dragon_tiger_signal"
            )

    @mcp.tool()
    async def get_industry_comparison_signal(
        symbol: str = "",
        trade_date: str = "",
        top_n: int = 20,
    ) -> str:
        """
        获取行业横向对比排名（全行业涨跌幅/上涨下跌家数/领涨股）。

        数据源：东财 push2 行业板块排名（直连，不依赖 AKShare）。

        Args:
            symbol: 6位股票代码（可选，用于定位所属行业）。
            trade_date: 日期 YYYY-MM-DD，空字符串默认今天。
            top_n: 显示前/后N个行业，默认20。

        Returns:
            行业排名数据 (JSON)，含行业名称/涨跌幅/上涨下跌家数/领涨股。
        """
        if symbol:
            symbol = normalize_symbol(symbol)
        cache_key = f"industry_cmp:{symbol or 'all'}:{trade_date or 'today'}:{top_n}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            # SmartRouter 智能路由：东财 em_push2 优先，失败降级 AKShare
            result, _source = _router.route(
                "industry_comparison",
                code=symbol,
                trade_date=trade_date,
                top_n=top_n,
            )
            output = dict_to_json(result)
            if result.get("industries"):
                cache.set(cache_key, output, TTL_DAILY)
            return output
        except RuntimeError:
            # 所有数据源失败，返回原东财接口的错误（不抛新异常）
            em_err = _get_em_error("industry_comparison")
            return error_response(
                f"获取行业对比数据失败: {em_err}", "get_industry_comparison_signal"
            )
        except Exception as e:
            return error_response(
                f"获取行业对比数据失败: {e}", "get_industry_comparison_signal"
            )
