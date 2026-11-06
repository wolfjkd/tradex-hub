"""短线元数据 MCP 工具（工单 H1）。

本模块只暴露「元数据读取」入口；读数与落库工具随后续工单追加到同一模块。
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..shortline.catalog import build_catalog
from ..utils.formatter import dict_to_json, error_response


def register(mcp: FastMCP):
    """注册短线元数据工具。"""

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
