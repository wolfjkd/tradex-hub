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
import json
import logging
import os
import pkgutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------- 工具可见性 profile
# 2026-11-08 一键启停（老板需求）：config/mcp_tool_profile.json 的 hidden_tools
# 在 FastMCP 注册后整体摘除，server 只暴露启用的工具（WorkBuddy/ZCode 界面数字
# 直接对上）。黑名单语义：不在 hidden 的新工具默认可见，不会悄悄丢。
# 仅影响 MCP 暴露层；REST 与进程内 route（TradeX/短线落库）不经过 FastMCP，无感。
# 文件不入 git（.gitignore），缺失 = full 全量暴露；env MCP_TOOL_PROFILE 可改路径。


def _tool_profile_path() -> Path | None:
    """定位 mcp_tool_profile.json：env 覆盖 → tradex 包向上找项目根 config/。"""
    env = os.environ.get("MCP_TOOL_PROFILE")
    if env:
        return Path(env)
    # registry.py 位于 <root>/tradex/src/tradex/tools/ → parents[4] = 项目根
    # （仓内还有一层 tradex/ 子目录，parents[3] 是它，不是根）
    root = Path(__file__).resolve().parents[4]
    candidate = root / "config" / "mcp_tool_profile.json"
    return candidate if candidate.exists() else None


def _load_hidden_tools() -> tuple[str, list[str]]:
    """读 profile 文件，返回 (profile 名, hidden 列表)。缺失/异常 → ("full", [])。"""
    path = _tool_profile_path()
    if path is None:
        return "full", []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        profile = str(data.get("profile", "custom"))
        hidden = [str(t) for t in (data.get("hidden_tools") or [])]
        return profile, hidden
    except Exception as exc:  # noqa: BLE001 - 配置坏了不能挡启动
        logger.warning("工具可见性 profile 读取失败（按 full 处理）: %s", exc)
        return "full", []


def _apply_tool_visibility(mcp: Any) -> tuple[str, int, int]:
    """按 profile 摘除隐藏工具，返回 (profile, 可见数, 隐藏数)。

    FastMCP 的 _tool_manager._tools 是 name → Tool 的 dict，pop 即从
    tools/list 协议结果中消失（mcp>=1.0,<2 锁定，测试锁行为）。
    """
    profile, hidden = _load_hidden_tools()
    if profile == "full" or not hidden:
        return profile, -1, 0  # full 无条件全量（防御：full 不应带 hidden）
    tools = getattr(getattr(mcp, "_tool_manager", None), "_tools", None)
    if not isinstance(tools, dict):
        logger.warning("FastMCP tool manager 结构异常，跳过可见性过滤")
        return profile, -1, 0
    removed = 0
    for name in hidden:
        if tools.pop(name, None) is not None:
            removed += 1
    logger.info(
        "工具可见性 profile=%s：暴露 %d / 隐藏 %d（名单 %d 项，其中 %d 未命中）",
        profile, len(tools), removed, len(hidden), len(hidden) - removed,
    )
    return profile, len(tools), removed


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
        profile, visible, hidden_n = _apply_tool_visibility(mcp)
        if visible >= 0:
            logger.info(
                "MCP 暴露工具 %d 个（profile=%s，隐藏 %d）——REST/进程内调用不受影响",
                visible, profile, hidden_n,
            )
        return registered
