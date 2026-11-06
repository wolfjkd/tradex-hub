"""短线（shortline）数据产品层。

本包承载「市场级确定性计算」：四池读数、题材事实、收盘定稿落库等。
设计原则（见交接文档 06）：
  - 计算层归 hub，不归 TradeX；
  - 声明式元数据先行，新增端点只改声明；
  - 缺数写 missing_reason，绝不把缺失当 0。
"""

from .meta import (
    CACHE_POLICIES,
    SHORTLINE_ENDPOINTS,
    CacheDecision,
    EndpointMeta,
    cache_key,
    get_endpoint,
    resolve_cache,
    validate_registry,
)

__all__ = [
    "CACHE_POLICIES",
    "SHORTLINE_ENDPOINTS",
    "CacheDecision",
    "EndpointMeta",
    "cache_key",
    "get_endpoint",
    "resolve_cache",
    "validate_registry",
]
