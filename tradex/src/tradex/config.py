"""
统一配置管理 — 支持环境变量覆盖，零配置可运行。

设计原则：
  1. 零配置可运行：所有配置有默认值，不配置 .env 也能启动
  2. 环境变量覆盖：通过 .env 文件或环境变量覆盖默认值
  3. 集中管理：所有配置项集中在此文件，便于维护和查找

Usage:
    from .config import config

    timeout = config.AKSHARE_TIMEOUT
    port = config.MCP_PORT
"""

from __future__ import annotations

import os
from typing import Any

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # python-dotenv 未安装时忽略，直接读取环境变量
    pass


def _get_env(key: str, default: Any, cast: type = str) -> Any:
    """从环境变量读取配置值，支持类型转换。

    Args:
        key: 环境变量名
        default: 默认值
        cast: 目标类型（str/int/float/bool）

    Returns:
        转换后的配置值
    """
    value = os.getenv(key)
    if value is None:
        return default

    if cast is bool:
        return value.lower() in ("1", "true", "yes", "on")
    if cast is int:
        try:
            return int(value)
        except ValueError:
            return default
    if cast is float:
        try:
            return float(value)
        except ValueError:
            return default
    return value


class Config:
    """全局配置。

    所有配置项有默认值，可通过环境变量或 .env 文件覆盖。
    """

    # ── 数据源 ──────────────────────────────────────────────
    AKSHARE_TIMEOUT: int = _get_env("AKSHARE_TIMEOUT", 30, int)
    """AKShare 请求超时时间（秒）"""

    TENCENT_TIMEOUT: int = _get_env("TENCENT_TIMEOUT", 10, int)
    """腾讯行情接口超时时间（秒）"""

    ELTDX_SERVER: str = _get_env("ELTDX_SERVER", "auto")
    """通达信服务器地址，auto 表示自动选择最优"""

    # ── 智能路由 ────────────────────────────────────────────
    ROUTER_HEALTH_CHECK_INTERVAL: int = _get_env("ROUTER_HEALTH_CHECK_INTERVAL", 60, int)
    """健康检查间隔（秒）"""

    ROUTER_MIN_SCORE: float = _get_env("ROUTER_MIN_SCORE", 20.0, float)
    """数据源最低健康评分，低于此值不再选中"""

    ROUTER_RECOVERY_AMOUNT: float = _get_env("ROUTER_RECOVERY_AMOUNT", 10.0, float)
    """定时恢复评分的增量"""

    # ── MCP 服务 ────────────────────────────────────────────
    MCP_TRANSPORT: str = _get_env("MCP_TRANSPORT", "stdio")
    """MCP 传输模式：stdio | sse | http"""

    MCP_HOST: str = _get_env("MCP_HOST", "127.0.0.1")
    """MCP HTTP/SSE 模式监听地址。默认 127.0.0.1 仅本地访问，外网部署需显式设置 MCP_HOST=0.0.0.0"""

    MCP_PORT: int = _get_env("MCP_PORT", 8000, int)
    """MCP HTTP/SSE 模式监听端口"""

    # ── WebSocket 推送服务 ──────────────────────────────────
    WS_SERVER_ENABLED: bool = _get_env("WS_SERVER_ENABLED", "false").lower() == "true"
    """是否启用 WebSocket 实时推送服务（默认关闭）"""

    WS_PORT: int = int(_get_env("WS_PORT", "8765"))
    """WebSocket 服务监听端口"""

    WS_TOKEN: str = _get_env("WS_TOKEN", "")
    """WebSocket 客户端认证 token（空字符串表示不要求认证）"""

    # ── 缓存 ────────────────────────────────────────────────
    CACHE_MAX_SIZE: int = _get_env("CACHE_MAX_SIZE", 5000, int)
    """内存缓存最大条目数，0 表示无限"""

    CACHE_FILE_DIR: str = _get_env("CACHE_FILE_DIR", ".cache")
    """文件缓存目录路径"""

    CACHE_FILE_ENABLED: bool = _get_env("CACHE_FILE_ENABLED", True, bool)
    """是否启用文件缓存（长 TTL 数据持久化）"""

    # ── 技术分析 ────────────────────────────────────────────
    INDICATOR_LOOKBACK_DAYS: int = _get_env("INDICATOR_LOOKBACK_DAYS", 400, int)
    """技术指标计算回溯天数"""

    CHIP_DISTRIBUTION_BINS: int = _get_env("CHIP_DISTRIBUTION_BINS", 50, int)
    """筹码分布直方图分箱数"""

    # ── 日志 ────────────────────────────────────────────────
    LOG_LEVEL: str = _get_env("LOG_LEVEL", "INFO")
    """日志级别：DEBUG | INFO | WARNING | ERROR"""

    LOG_DIR: str = _get_env("LOG_DIR", "logs")
    """日志文件目录"""


# 全局配置单例
config = Config()
