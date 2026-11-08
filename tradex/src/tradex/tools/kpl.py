"""开盘啦（KPL）数据源 MCP 工具（交接文档 07 T3 / 09 票5）。

KPL 短线特色口径：涨停复盘（含 KPL 涨停原因 / 封单 / 801xxx 板块码 /
板位梯队）、市场情绪读数、精选板块强度、竞价涨停委买额。
数据层见 data_sources/kpl_fetchers.py（2026-11-07 六接口实测）。
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..data_sources import get_router
from ..utils.cache import TTL_DAILY, TTL_REALTIME, cache
from ..utils.formatter import dict_to_json, df_to_json, error_response

_router = get_router()


def register(mcp: FastMCP):
    """注册 KPL 工具。"""

    @mcp.tool()
    async def get_kpl_limit_up(date: str = "", pid_type: int = 0) -> str:
        """
        获取开盘啦涨停复盘（KPL 口径：涨停原因/封单/主力/801xxx 板块码/板位）。

        与东财涨停池互补：KPL 自带题材归因（reason）、实际流通/换手、
        概念板块码（801xxx）与该板块涨停家数。免鉴权直连。

        Args:
            date: 交易日 YYYYMMDD 或 YYYY-MM-DD；空 = 实时（最近交易日/盘中）。
            pid_type: 板位 1~5（1 首板 … 5 更高连板）；0 = 全部（循环 1~5 拼接）。

        Returns:
            涨停列表 JSON：code/name/limit_up_time/reason/seal_amount/
            max_seal_amount/main_net_inflow/turnover/board_tags/
            actual_circulation/actual_turnover_rate/amplitude/kpl_board_code/
            board_limit_up_count/ladder（板位）。
        """
        cache_key = f"kpl_limit_up:{date}:{pid_type}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            df, _src = _router.route("kpl_limit_up", date=date, pid_type=pid_type)
            if df is None or df.empty:
                return df_to_json(df)
            result = df_to_json(df, max_rows=200)
            ttl = TTL_DAILY if date else TTL_REALTIME
            cache.set(cache_key, result, ttl)
            return result
        except Exception as e:
            return error_response(f"获取KPL涨停复盘失败: {e}", "get_kpl_limit_up")

    @mcp.tool()
    async def get_kpl_sentiment() -> str:
        """
        获取开盘啦市场情绪读数（涨停/跌停/炸板率 + KPL 情绪值/连板高度）。

        返回 limit_up / limit_down / zhaban / zhaban_rate（RiseFallAnalysis）
        与 strength（KPL 情绪指标 0-100）/ ladder_height（连板高度）。
        数值与 hub 东财涨停池口径可对账（2026-11-06 双源一致：32 家）。

        Returns:
            情绪读数 JSON dict。
        """
        cache_key = "kpl_sentiment"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            payload, _src = _router.route("kpl_sentiment")
            result = dict_to_json(payload)
            cache.set(cache_key, result, TTL_REALTIME)
            return result
        except Exception as e:
            return error_response(f"获取KPL情绪读数失败: {e}", "get_kpl_sentiment")

    @mcp.tool()
    async def get_kpl_boards(date: str = "") -> str:
        """
        获取开盘啦精选板块列表（801xxx 板块码/强度/涨幅/主力净额）。

        KPL 板块强度（strength）是开盘啦特色短线口径；ZSType=7 精选板块
        实测混有少量非 801 代码行（指数类），消费方需按 kpl_board_code 过滤。

        Args:
            date: 交易日 YYYYMMDD；空 = 实时。

        Returns:
            板块列表 JSON：kpl_board_code/name/strength/pct_change/
            main_net_inflow/turnover/vol_ratio/market_cap 等。
        """
        cache_key = f"kpl_boards:{date}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            df, _src = _router.route("kpl_boards", date=date)
            if df is None or df.empty:
                return df_to_json(df)
            result = df_to_json(df, max_rows=100)
            ttl = TTL_DAILY if date else TTL_REALTIME
            cache.set(cache_key, result, ttl)
            return result
        except Exception as e:
            return error_response(f"获取KPL精选板块失败: {e}", "get_kpl_boards")

    @mcp.tool()
    async def get_kpl_bidding(date: str = "") -> str:
        """
        获取开盘啦竞价涨停委买额榜（9:15-9:25 竞价口径）。

        ⚠️ 历史数据保留期极短（实测次日已查不到），交易日盘中调用价值最高。
        返回竞价涨幅/委买额/竞价净额/竞价换手/连板标签（如「6天4板」）。

        Args:
            date: 交易日 YYYYMMDD；空 = 实时。

        Returns:
            竞价列表 JSON：code/name/bid_buy_amount/bid_pct_change/
            bid_net_amount/bid_turnover/ladder_tag 等。
        """
        cache_key = f"kpl_bidding:{date}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            df, _src = _router.route("kpl_bidding", date=date)
            if df is None or df.empty:
                return df_to_json(df)
            result = df_to_json(df, max_rows=100)
            ttl = TTL_DAILY if date else TTL_REALTIME
            cache.set(cache_key, result, ttl)
            return result
        except Exception as e:
            return error_response(f"获取KPL竞价榜失败: {e}", "get_kpl_bidding")
