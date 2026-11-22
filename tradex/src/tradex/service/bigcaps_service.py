"""大市值名单 service（工单 H4）。

MCP 工具与 REST 路由共用同一份业务逻辑：
  - 取数走 SmartRouter（新浪主源 → 东财快照兜底）
  - 缓存按元数据策略（hourly），不在函数里写死 TTL
  - 返回统一信封：as_of / source / threshold_yi / count / stocks / unpriced
"""

from __future__ import annotations

import logging

from ..data_sources import get_router
from ..shortline.meta import cache_key, get_endpoint, resolve_cache
from ..utils.cache import cache

logger = logging.getLogger(__name__)

_router = get_router()

ENDPOINT_ID = "shortline.bigcaps"
_COMPLIANCE = "cn-public"


def get_bigcaps(min_mktcap_yi: float = 500, limit: int = 0) -> dict:
    """取大市值名单。

    Args:
        min_mktcap_yi: 总市值门槛（亿元），默认 500。
        limit: 只返回前 N 只（0 = 全部）。

    Raises:
        RuntimeError: 数据源不可达或返回结构异常（由调用方转成错误响应）。
    """
    threshold_yi = float(min_mktcap_yi or 0)
    meta = get_endpoint(ENDPOINT_ID)
    decision = resolve_cache(meta.cache_policy, partial=False)
    key = cache_key(ENDPOINT_ID, threshold=threshold_yi)

    def _factory():
        payload, source = _router.route("bigcaps", min_mktcap_yi=threshold_yi, timeout=25)
        if not isinstance(payload, dict) or not isinstance(payload.get("stocks"), list):
            raise RuntimeError(f"bigcaps 数据源返回结构异常（source={source}）")

        return {
            "endpoint": ENDPOINT_ID,
            "as_of": payload.get("as_of"),
            "source": payload.get("source") or source,
            "source_route": source,
            "source_note": payload.get("source_note", ""),
            "compliance": _COMPLIANCE,
            "threshold_yi": payload.get("threshold_yi", threshold_yi),
            "count": len(payload["stocks"]),
            "stocks": payload["stocks"],
            "unpriced": payload.get("unpriced", []),
            "cache_hit": False,
            "cache": {
                "policy": meta.cache_policy,
                "ttl_seconds": decision.ttl_seconds,
            },
        }

    out: dict = {}
    result = cache.get_or_set(
        key,
        _factory,
        decision.ttl_seconds,
        store=lambda v: (decision.enabled, decision.ttl_seconds),  # 原样：decision.enabled 才落缓存
        out=out,
    )
    # 浅拷贝后改写：_apply_limit 只重赋值 stocks/returned 键，缓存对象不被污染
    # （原 dict(cached) 同款防御；get_or_set 直存 factory 产物，拷贝职责移到调用侧）
    result = dict(result)
    result["cache_hit"] = bool(out.get("cache_hit"))
    return _apply_limit(result, limit)


def _apply_limit(result: dict, limit: int) -> dict:
    """按 limit 截断返回名单（count 始终是全量命中数）。"""
    try:
        n = int(limit or 0)
    except (TypeError, ValueError):
        n = 0
    stocks = result["stocks"]
    if n > 0 and len(stocks) > n:
        result["stocks"] = stocks[:n]
    result["returned"] = len(result["stocks"])
    return result
