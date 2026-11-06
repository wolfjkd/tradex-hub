"""短线元数据 MCP 工具（工单 H1）。

本模块只暴露「元数据读取」入口；读数与落库工具随后续工单追加到同一模块。
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..service.bigcaps_service import get_bigcaps
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
