"""
工具注册中心 — 自动发现与注册。

设计原则：
  1. 自动发现：扫描 tools/ 目录下所有模块，无需手动导入
  2. 注册函数：每个工具模块导出 register(mcp) 函数，在其中用 @mcp.tool() 注册

⚠️ 历史勘误（v3.3.9）：曾提供 @register_tool 装饰器轨把元数据写入
ToolRegistry._tools，但 discover_and_register 不会将其挂到 FastMCP——
按装饰器轨写的新工具会静默消失。2026-09-28 审计清理：该装饰器轨与
元数据查询 API（get_by_category/get_all/get_categories）全库零使用，
已整体删除。新增工具请一律使用 register(mcp) 函数轨：

    # 正确姿势（register 函数轨）
    def register(mcp):
        @mcp.tool()
        async def search_stock(keyword: str) -> str:
            ...
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import Any

logger = logging.getLogger(__name__)


class ToolRegistry:
    """工具注册中心：扫描 tools/ 包并调用各模块的 register(mcp)。"""

    @classmethod
    def auto_discover(cls, tools_package: Any) -> None:
        """自动扫描 tools/ 目录下所有模块。

        导入所有子模块（含 signal_data_* 兼容子模块，触发其副作用/装饰器）。

        Args:
            tools_package: tools 包模块对象
        """
        if not hasattr(tools_package, "__path__"):
            logger.warning("提供的模块不是包: %s", tools_package)
            return

        for _, mod_name, _ in pkgutil.iter_modules(tools_package.__path__):
            full_name = f"{tools_package.__name__}.{mod_name}"
            try:
                importlib.import_module(full_name)
                logger.debug("已加载工具模块: %s", full_name)
            except Exception as exc:
                logger.error("加载工具模块失败 %s: %s", full_name, exc, exc_info=True)

    @classmethod
    def discover_and_register(cls, tools_package: Any, mcp: Any) -> list[str]:
        """自动发现所有工具模块并调用其 register(mcp) 函数。

        Args:
            tools_package: tools 包模块对象
            mcp: FastMCP 实例

        Returns:
            成功注册的模块名列表
        """
        cls.auto_discover(tools_package)

        registered: list[str] = []
        for _, mod_name, _ in pkgutil.iter_modules(tools_package.__path__):
            # v3.0.0: signal_data 已拆分为 signal_data_{base,flow,etf,cb,board} 子模块,
            # 由 signal_data.py 兼容入口统一调用 register,跳过子模块避免重复注册
            if mod_name.startswith("signal_data_"):
                logger.debug("跳过 signal_data 子模块 %s(由 signal_data 入口统一注册)", mod_name)
                continue
            full_name = f"{tools_package.__name__}.{mod_name}"
            try:
                mod = importlib.import_module(full_name)
                if hasattr(mod, "register"):
                    mod.register(mcp)
                    registered.append(mod_name)
                    logger.debug("模块 %s 已通过 register() 注册", mod_name)
            except Exception as exc:
                logger.error(
                    "模块 %s 注册失败: %s", mod_name, exc, exc_info=True
                )

        logger.info("工具自动发现完成，共注册 %d 个模块", len(registered))
        return registered
