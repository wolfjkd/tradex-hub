"""
工具注册中心 — 支持自动发现和元数据管理。

设计原则：
  1. 自动发现：扫描 tools/ 目录下所有模块，无需手动导入
  2. 双轨制：装饰器注册和 register(mcp) 函数注册共存
  3. 元数据管理：每个工具有分类、描述等元信息，支持按分类查询

Usage:
    # 方式一：装饰器注册（新工具推荐）
    from .registry import register_tool, ToolRegistry

    @register_tool("L1-数据获取", "搜索A股股票")
    async def search_stock(keyword: str) -> str:
        ...

    # 方式二：register函数注册（现有工具兼容）
    def register(mcp):
        @mcp.tool()
        async def search_stock(keyword: str) -> str:
            ...

    # 自动发现所有工具模块
    ToolRegistry.auto_discover(importlib.import_module("tradex.tools"))

    # 按分类查询工具
    tools = ToolRegistry.get_by_category("L1-数据获取")
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class ToolMeta:
    """工具元数据。

    Attributes:
        name: 工具名称（函数名）
        category: 工具分类（L1-数据获取 / L2-计算引擎 / L3-决策支持 / 系统诊断）
        description: 工具描述
        handler: 工具处理函数
    """

    name: str
    category: str
    description: str
    handler: Callable[..., Any]


class ToolRegistry:
    """工具注册中心。

    管理所有通过装饰器注册的工具元数据，支持自动发现和分类查询。
    与现有的 register(mcp) 函数模式共存，不影响向后兼容性。
    """

    _tools: dict[str, ToolMeta] = {}

    @classmethod
    def register(
        cls,
        category: str,
        description: str,
        name: Optional[str] = None,
    ) -> Callable:
        """装饰器：注册工具元数据。

        Args:
            category: 工具分类（L1-数据获取 / L2-计算引擎 / L3-决策支持 / 系统诊断）
            description: 工具描述
            name: 工具名称，默认使用函数名

        Returns:
            装饰器函数
        """

        def decorator(func: Callable) -> Callable:
            tool_name = name or func.__name__
            cls._tools[tool_name] = ToolMeta(
                name=tool_name,
                category=category,
                description=description,
                handler=func,
            )
            logger.debug("工具已注册: %s [%s]", tool_name, category)
            return func

        return decorator

    @classmethod
    def auto_discover(cls, tools_package: Any) -> None:
        """自动扫描 tools/ 目录下所有模块。

        导入所有子模块，触发装饰器注册和 register(mcp) 函数收集。

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

        兼容现有的 register(mcp) 函数模式，同时收集装饰器注册的元数据。

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

    @classmethod
    def get_by_category(cls, category: str) -> list[ToolMeta]:
        """按分类获取工具列表。

        Args:
            category: 工具分类

        Returns:
            该分类下所有工具的元数据列表
        """
        return [t for t in cls._tools.values() if t.category == category]

    @classmethod
    def get_all(cls) -> list[ToolMeta]:
        """获取所有已注册工具。

        Returns:
            所有工具元数据列表
        """
        return list(cls._tools.values())

    @classmethod
    def get_categories(cls) -> list[str]:
        """获取所有工具分类。

        Returns:
            去重后的分类列表
        """
        return list({t.category for t in cls._tools.values()})

    @classmethod
    def clear(cls) -> None:
        """清空注册表（主要用于测试）。"""
        cls._tools.clear()


# 便捷别名
register_tool = ToolRegistry.register
