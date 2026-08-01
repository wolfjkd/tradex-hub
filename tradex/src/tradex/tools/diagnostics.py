"""
MCP 诊断工具模块 — 暴露数据源健康状态、工具清单、缓存统计与系统健康检查。

提供 4 个诊断工具：
  1. get_data_source_health — 各数据源健康状态（评分/成功率/延迟/连续失败）
  2. list_all_tools         — 所有注册工具的分类清单
  3. get_cache_stats        — 两级缓存统计信息
  4. health_check           — 系统整体健康检查（组合以上三项 + akshare 连通性）

设计原则：
  - 只读诊断，不修改任何状态
  - 单项失败不拖垮整体检查，逐项 try/except
  - SmartRouter / akshare 等可选依赖不可用时降级返回基础信息
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..utils.formatter import dict_to_json, error_response
from ..utils.cache import cache
from .registry import ToolRegistry


def _get_router():
    """获取共享的 SmartRouter 单例（与 signal_data_flow 共享健康数据）。

    优先从 astock_signals 导入（由 signal_data_flow 设置 sys.path），
    回退到 src.astock_signals 路径。不可用时返回 None。
    """
    try:
        from astock_signals.smart_router import get_router
        return get_router()
    except ImportError:
        try:
            from src.astock_signals.smart_router import get_router
            return get_router()
        except ImportError:
            return None


def _ts_to_iso(ts) -> str:
    """Unix 时间戳转 ISO 格式字符串（0/None 表示无记录）。"""
    if not ts:
        return ""
    from datetime import datetime
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError):
        return ""


def register(mcp: FastMCP):
    """向 MCP server 注册诊断工具。"""

    @mcp.tool()
    async def get_data_source_health() -> str:
        """
        返回各数据源的健康状态。

        通过 SmartRouter 获取每个数据源的健康评分、成功率、平均延迟、
        连续失败次数、最近失败时间与是否健康标记。SmartRouter 不可用时返回基础信息。

        Returns:
            数据源健康状态 (JSON)，包含 status、count 与 data_sources 列表，
            每个数据源含 name、score、success_rate、avg_latency_ms、
            consecutive_fails、last_fail_time、is_healthy。
        """
        try:
            router = _get_router()
            if router is None:
                return dict_to_json(
                    {
                        "status": "unavailable",
                        "message": "SmartRouter 未安装或不可用，无法获取数据源健康状态",
                        "count": 0,
                        "data_sources": [],
                    }
                )
            report = router.get_health_report()
            sources = [
                {
                    "name": item.get("source"),
                    "score": item.get("score"),
                    "success_rate": item.get("success_rate"),
                    "avg_latency_ms": item.get("avg_latency_ms"),
                    "total_calls": item.get("total_calls"),
                    "fail_count": item.get("fail_count"),
                    "consecutive_fails": item.get("consecutive_fails"),
                    "last_fail_time": _ts_to_iso(item.get("last_fail_ts")),
                    "last_success_time": _ts_to_iso(item.get("last_success_ts")),
                    "is_healthy": item.get("is_healthy"),
                }
                for item in report
            ]
            return dict_to_json(
                {
                    "status": "ok",
                    "count": len(sources),
                    "data_sources": sources,
                }
            )
        except Exception as e:
            return error_response(
                f"获取数据源健康状态失败: {e}", "get_data_source_health"
            )

    @mcp.tool()
    async def list_all_tools() -> str:
        """
        返回所有注册工具的分类清单。

        从 ToolRegistry 读取通过装饰器注册的工具元数据，按分类分组返回。
        每个工具包含 name、category、description。

        Returns:
            工具分类清单 (JSON)，包含 status、total 与 categories 字典，
            categories 按分类名分组，每组为工具列表。
            若无装饰器注册的工具，返回提示信息。
        """
        try:
            tools = ToolRegistry.get_all()
            if not tools:
                return dict_to_json(
                    {
                        "status": "empty",
                        "message": "暂无通过装饰器注册的工具，工具可能通过 register(mcp) 方式注册",
                        "total": 0,
                        "categories": {},
                    }
                )

            categories: dict[str, list[dict]] = {}
            for tool in tools:
                categories.setdefault(tool.category, []).append(
                    {
                        "name": tool.name,
                        "category": tool.category,
                        "description": tool.description,
                    }
                )
            return dict_to_json(
                {
                    "status": "ok",
                    "total": len(tools),
                    "categories": categories,
                }
            )
        except Exception as e:
            return error_response(f"获取工具清单失败: {e}", "list_all_tools")

    @mcp.tool()
    async def get_cache_stats() -> str:
        """
        返回两级缓存（内存 + 文件）的统计信息。

        Returns:
            缓存统计 (JSON)，包含 size、max_size、hits、misses、hit_rate、
            file_size、file_enabled。
        """
        try:
            stats = cache.stats
            return dict_to_json(
                {
                    "size": stats.get("size", 0),
                    "max_size": stats.get("max_size", 0),
                    "hits": stats.get("hits", 0),
                    "misses": stats.get("misses", 0),
                    "hit_rate": stats.get("hit_rate", 0.0),
                    "file_size": stats.get("file_size", 0),
                    "file_enabled": stats.get("file_enabled", False),
                }
            )
        except Exception as e:
            return error_response(f"获取缓存统计失败: {e}", "get_cache_stats")

    @mcp.tool()
    async def health_check() -> str:
        """
        系统健康检查。

        组合数据源健康、工具清单、缓存统计三项，并增加 akshare 连通性测试，
        返回整体状态（healthy / degraded / unhealthy）：
          - unhealthy: akshare 不可用（核心数据源缺失）
          - degraded:  akshare 可用但存在其他异常（SmartRouter 不可用、
                       缓存/工具获取失败或存在不健康数据源）
          - healthy:   全部正常

        Returns:
            系统健康检查结果 (JSON)，包含 status、issues、akshare、
            data_sources、tools、cache。
        """
        result: dict = {
            "status": "healthy",
            "issues": [],
            "akshare": {},
            "data_sources": {},
            "tools": {},
            "cache": {},
        }
        issues: list[str] = []

        # akshare 连通性测试（核心依赖，不可用即为 unhealthy）
        try:
            import akshare

            result["akshare"] = {
                "available": True,
                "version": getattr(akshare, "__version__", "unknown"),
            }
        except Exception as e:
            result["akshare"] = {"available": False, "error": str(e)}
            issues.append("akshare 不可用")

        # 数据源健康
        try:
            router = _get_router()
            if router is None:
                result["data_sources"] = {
                    "available": False,
                    "message": "SmartRouter 未安装或不可用",
                }
                issues.append("SmartRouter 不可用")
            else:
                report = router.get_health_report()
                sources = [
                    {
                        "name": item.get("source"),
                        "score": item.get("score"),
                        "success_rate": item.get("success_rate"),
                        "avg_latency_ms": item.get("avg_latency_ms"),
                        "consecutive_fails": item.get("consecutive_fails"),
                        "is_healthy": item.get("is_healthy"),
                    }
                    for item in report
                ]
                unhealthy = [s for s in sources if not s.get("is_healthy")]
                result["data_sources"] = {
                    "available": True,
                    "count": len(sources),
                    "unhealthy_count": len(unhealthy),
                }
                if unhealthy:
                    issues.append(f"{len(unhealthy)} 个数据源不健康")
        except Exception as e:
            result["data_sources"] = {"available": False, "error": str(e)}
            issues.append("数据源健康检查失败")

        # 工具清单
        try:
            tools = ToolRegistry.get_all()
            result["tools"] = {"available": True, "total": len(tools)}
            if not tools:
                issues.append("无装饰器注册工具")
        except Exception as e:
            result["tools"] = {"available": False, "error": str(e)}
            issues.append("工具清单获取失败")

        # 缓存统计
        try:
            stats = cache.stats
            result["cache"] = {
                "available": True,
                "size": stats.get("size", 0),
                "max_size": stats.get("max_size", 0),
                "hits": stats.get("hits", 0),
                "misses": stats.get("misses", 0),
                "hit_rate": stats.get("hit_rate", 0.0),
                "file_size": stats.get("file_size", 0),
                "file_enabled": stats.get("file_enabled", False),
            }
        except Exception as e:
            result["cache"] = {"available": False, "error": str(e)}
            issues.append("缓存统计获取失败")

        # 整体状态判定
        if not result["akshare"].get("available"):
            result["status"] = "unhealthy"
        elif issues:
            result["status"] = "degraded"
        else:
            result["status"] = "healthy"

        result["issues"] = issues
        return dict_to_json(result)
