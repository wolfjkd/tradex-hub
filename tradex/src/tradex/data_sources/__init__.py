"""
数据源 fetch_fn 层 — 集中包装 akshare/eltdx/astock_signals/HTTP 数据源。

铁律：仅本包内文件允许 `import akshare` / `from eltdx import` / `from astock_signals import`。
所有 L1 工具必须通过 SmartRouter.route() 获取数据，不得直接 import 数据源。

子模块：
  - akshare_fetchers:           AKShare 数据源 fetch_fn 包装器
  - eltdx_fetchers:             eltdx 通达信协议 fetch_fn 包装器
  - http_fetchers:              HTTP 直连数据源（腾讯行情等）
  - astock_signals_fetchers:    astock_signals 函数 fetch_fn 包装器
  - registry:                   register_all_sources() — 注册 25 个数据类型到 SmartRouter

Usage:
    from ..data_sources import register_all_sources, get_router
    register_all_sources()          # 在 server.py 启动时调用一次
    router = get_router()           # 获取全局 SmartRouter 单例
    data, source = router.route("realtime_quote", symbol="600519")
"""

from __future__ import annotations

from astock_signals.smart_router import get_router

from .registry import register_all_sources

__all__ = ["register_all_sources", "get_router"]
