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
    get_facts,
    get_firstboard,
    get_ladder,
    get_live,
    get_settled,
    get_structure,
    get_theme_rotation,
    get_themes,
)
from ..service.turnover_service import get_turnover_top
from ..shortline import drift, store
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

    # ---------------- H6：题材 / 首板 / 盘面事实 / 题材轮动 ----------------

    @mcp.tool()
    async def get_shortline_themes(date: str = "") -> str:
        """
        获取题材事件树（涨停原因归组）。

        问财优先，缺 key / 失败自动切同花顺涨停归因，并标 reason_source。
        产出：事件（整条原因归组）+ 关键词热度 + 未归因名单。

        Args:
            date: 交易日 YYYYMMDD，默认最近有数据的交易日。

        Returns:
            题材 JSON（reason_source / events / keywords / unattributed / missing_reason）。
        """
        try:
            return dict_to_json(get_themes(date=date))
        except Exception as e:
            return error_response(f"获取题材事件树失败: {e}", "get_shortline_themes")

    @mcp.tool()
    async def get_shortline_firstboard(date: str = "") -> str:
        """
        获取首板名单：按首次封板时间升序，反包票单标。

        Args:
            date: 交易日 YYYYMMDD，默认最近有数据的交易日。

        Returns:
            名单 JSON（count / stocks / reversal_count）。
        """
        try:
            return dict_to_json(get_firstboard(date=date))
        except Exception as e:
            return error_response(f"获取首板名单失败: {e}", "get_shortline_firstboard")

    @mcp.tool()
    async def get_shortline_facts(date: str = "") -> str:
        """
        获取盘面事实：封板质量 / 亏钱效应 / 强势股反馈矩阵。

        Args:
            date: 交易日 YYYYMMDD，默认最近有数据的交易日。

        Returns:
            事实 JSON（seal_quality / losing_effect / feedback_matrix / missing_reason）。
        """
        try:
            return dict_to_json(get_facts(date=date))
        except Exception as e:
            return error_response(f"获取盘面事实失败: {e}", "get_shortline_facts")

    @mcp.tool()
    async def get_shortline_theme_rotation(days: int = 5, date: str = "") -> str:
        """
        获取题材轮动：近 N 日各题材只数 / 名次 / 连续天数 / 回流。

        历史来自收盘定稿落库；缺天显示「—」，不当 0。

        Args:
            days: 窗口天数（2~60），默认 5。
            date: 交易日 YYYYMMDD，默认最近有数据的交易日。

        Returns:
            轮动 JSON（days / rows（含 counts/display/ranks/streak/is_returning）/ missing_dates）。
        """
        try:
            return dict_to_json(get_theme_rotation(days=days, date=date))
        except Exception as e:
            return error_response(f"获取题材轮动失败: {e}", "get_shortline_theme_rotation")

    # ---------------- H3：收盘定稿落库 + 历史回读 ----------------

    @mcp.tool()
    async def shortline_close_fetch(date: str = "", force: bool = False) -> str:
        """
        收盘定稿取数并落库（幂等）。由 TradeX scheduler 在 15:35 调用。

        把当日四池读数（情绪/每日/昨日表现/梯队/天梯/结构）按日期落本机，
        对抗东财四池约一个月保留期。同一日重复调用不重复写；partial 不会覆盖 final。

        Args:
            date: 交易日 YYYYMMDD，默认今天。
            force: 强制重算（仍拒绝 partial 覆盖 final）。

        Returns:
            落库结果 JSON（date / status / written / reason / schema_version / missing_reasons）。
        """
        try:
            return dict_to_json(store.close_fetch(date=date, force=force))
        except Exception as e:
            return error_response(f"收盘落库失败: {e}", "shortline_close_fetch")

    @mcp.tool()
    async def get_shortline_history(date: str = "", days: int = 5) -> str:
        """
        读取短线收盘定稿历史（已落库的全部交易日）。

        Args:
            date: 截止日期 YYYYMMDD，默认今天。
            days: 最近 N 条落库记录，默认 5。

        Returns:
            历史 JSON（count / dates / records / missing_dates / schema_version）。
        """
        try:
            return dict_to_json(store.history(days=days, date=date))
        except Exception as e:
            return error_response(f"读取收盘历史失败: {e}", "get_shortline_history")

    # ---------------- H7：数据源韧性 ----------------

    @mcp.tool()
    async def get_shortline_field_drift(date: str = "", lookback: int = 10) -> str:
        """
        获取四池字段漂移报告（区分「真 0」与「字段变了」）。

        比对当前与上一份落库快照的四池上游字段清单：新增/消失列、语义字段别名缺口、
        可疑 0 清单；结果同时进入数据源健康看板。

        Args:
            date: 截止日期 YYYYMMDD，默认今天。
            lookback: 往回找参考快照的最大记录数，默认 10。

        Returns:
            漂移 JSON（drift / added / removed / alias_gaps / zero_suspects / alerts）。
        """
        try:
            return dict_to_json(drift.field_drift(date=date, lookback=lookback))
        except Exception as e:
            return error_response(f"获取字段漂移报告失败: {e}", "get_shortline_field_drift")
