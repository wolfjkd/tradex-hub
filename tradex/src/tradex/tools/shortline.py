"""短线元数据 MCP 工具（工单 H1）。

本模块只暴露「元数据读取」入口；读数与落库工具随后续工单追加到同一模块。
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..service.bigcaps_service import get_bigcaps
from ..service.shortline_service import (
    get_board_ladder,
    get_cycle,
    get_daily,
    get_emotion,
    get_ladder,
    get_live,
    get_settled,
    get_structure,
)
from ..service.turnover_service import get_turnover_top
from ..shortline.catalog import build_catalog
from ..utils.formatter import dict_to_json, error_response


def register(mcp: FastMCP):
    """注册短线工具。"""

    @mcp.tool()
    async def get_shortline_catalog() -> str:
        """
        获取短线端点目录（声明式元数据）。

        返回每个短线端点的 id / 标题 / 口径 / 参数 / 缓存策略 / 适用阶段 /
        合规分级 / 计算函数 / 产出字段 / MCP 工具名 / REST 路径 / 实现状态。

        Returns:
            CATALOG JSON（含 schema_version、cache_policies、endpoints、validation）。
        """
        try:
            return dict_to_json(build_catalog())
        except Exception as e:
            return error_response(f"获取短线端点目录失败: {e}", "get_shortline_catalog")

    @mcp.tool()
    async def get_shortline_bigcaps(min_mktcap_yi: float = 500, limit: int = 0) -> str:
        """
        获取大市值名单（总市值 ≥ 门槛的 A 股）。

        主源新浪 bigcaps，失败自动切东财全市场快照；缓存 1 小时。
        停牌或缺市值的票不丢整只——停牌票标 suspended，缺市值票进 unpriced 并写 reason。

        Args:
            min_mktcap_yi: 总市值门槛（亿元），默认 500。
            limit: 只返回前 N 只，0 = 全部。

        Returns:
            名单 JSON（as_of / source / threshold_yi / count / stocks / unpriced / source_note）。
        """
        try:
            return dict_to_json(get_bigcaps(min_mktcap_yi=min_mktcap_yi, limit=limit))
        except Exception as e:
            return error_response(f"获取大市值名单失败: {e}", "get_shortline_bigcaps")

    @mcp.tool()
    async def get_shortline_turnover_top(
        date: str = "", limit: int = 20, kind: str = "auto"
    ) -> str:
        """
        获取全市场成交额榜（通达信盘后包主源，实时榜降级）。

        收盘后（通常 17:00 后）官网发布盘后包，解析全市场日线含成交额；
        包未发布或下载失败时自动降级为实时成交额榜，并标 kind=realtime「此刻榜」。

        Args:
            date: 交易日 YYYYMMDD，默认今天。
            limit: 返回前 N 只（上限 500），默认 20。
            kind: auto（默认）/ history（历史优先）/ realtime（直接实时榜）。

        Returns:
            榜单 JSON（kind / date / as_of / source / stocks / degradation）。
        """
        try:
            return dict_to_json(
                get_turnover_top(date=date, limit=limit, kind=kind)
            )
        except Exception as e:
            return error_response(f"获取成交额榜失败: {e}", "get_shortline_turnover_top")

    # ---------------- H2：四池基础读数（8 个） ----------------

    @mcp.tool()
    async def get_shortline_emotion(date: str = "") -> str:
        """
        获取短线情绪四项：赚钱效应 / 晋级率 / 连板溢价 / 梯队断层。

        Args:
            date: 交易日 YYYYMMDD，默认最近有数据的交易日。

        Returns:
            读数 JSON（result + text + computation + partial + missing_reason）。
        """
        try:
            return dict_to_json(get_emotion(date=date))
        except Exception as e:
            return error_response(f"获取情绪四项失败: {e}", "get_shortline_emotion")

    @mcp.tool()
    async def get_shortline_cycle(days: int = 5, date: str = "") -> str:
        """
        获取短线情绪周期：近 N 日涨停数 / 最高板 / 炸板率的窗口分位。

        窗口来自收盘定稿落库；缺天不给 0，写 missing_dates。历史未积累时只含今日。

        Args:
            days: 窗口天数（2~60），默认 5。
            date: 交易日 YYYYMMDD，默认最近有数据的交易日。

        Returns:
            周期 JSON（result + text + computation + partial + missing_reason）。
        """
        try:
            return dict_to_json(get_cycle(days=days, date=date))
        except Exception as e:
            return error_response(f"获取情绪周期失败: {e}", "get_shortline_cycle")

    @mcp.tool()
    async def get_shortline_daily(date: str = "") -> str:
        """
        获取短线每日读数：涨停数 / 最高板 / 炸板率 / 昨日涨停今日中位 / 1进2。

        Args:
            date: 交易日 YYYYMMDD，默认最近有数据的交易日。

        Returns:
            读数 JSON（result + text + computation + partial + missing_reason）。
        """
        try:
            return dict_to_json(get_daily(date=date))
        except Exception as e:
            return error_response(f"获取每日读数失败: {e}", "get_shortline_daily")

    @mcp.tool()
    async def get_shortline_settled(date: str = "") -> str:
        """
        获取昨日涨停股当日表现明细（涨停样本原料）。

        Args:
            date: 交易日 YYYYMMDD，默认最近有数据的交易日。

        Returns:
            明细 JSON（count / stocks / stats / missing_reason）。
        """
        try:
            return dict_to_json(get_settled(date=date))
        except Exception as e:
            return error_response(f"获取昨日涨停表现失败: {e}", "get_shortline_settled")

    @mcp.tool()
    async def get_shortline_live() -> str:
        """
        获取盘中情绪：此刻涨停 / 炸板 / 跌停家数、封板率、1进2。

        永远是「此刻」快照（partial），最多缓存 15 秒。

        Returns:
            盘中读数 JSON（result + text + computation + partial）。
        """
        try:
            return dict_to_json(get_live())
        except Exception as e:
            return error_response(f"获取盘中情绪失败: {e}", "get_shortline_live")

    @mcp.tool()
    async def get_shortline_ladder(date: str = "") -> str:
        """
        获取昨日梯队：昨日全部涨停股按连板数分组排列。

        Args:
            date: 交易日 YYYYMMDD，默认最近有数据的交易日。

        Returns:
            梯队 JSON（levels / stocks / missing_reason）。
        """
        try:
            return dict_to_json(get_ladder(date=date))
        except Exception as e:
            return error_response(f"获取昨日梯队失败: {e}", "get_shortline_ladder")

    @mcp.tool()
    async def get_shortline_board_ladder(date: str = "") -> str:
        """
        获取连板天梯：今日各连板高度名单 + 低一层没接上的票去向。

        Args:
            date: 交易日 YYYYMMDD，默认最近有数据的交易日。

        Returns:
            天梯 JSON（levels / missed / missing_reason）。
        """
        try:
            return dict_to_json(get_board_ladder(date=date))
        except Exception as e:
            return error_response(f"获取连板天梯失败: {e}", "get_shortline_board_ladder")

    @mcp.tool()
    async def get_shortline_structure(date: str = "") -> str:
        """
        获取涨停结构（板块/ST/首板占比）+ 四池上游字段清单（防假断点）。

        Args:
            date: 交易日 YYYYMMDD，默认最近有数据的交易日。

        Returns:
            结构 JSON（structure 各项 / upstream_fields / missing_reason）。
        """
        try:
            return dict_to_json(get_structure(date=date))
        except Exception as e:
            return error_response(f"获取涨停结构失败: {e}", "get_shortline_structure")
