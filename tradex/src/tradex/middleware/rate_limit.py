"""令牌桶限流中间件（工单 20）。

三层防护：
  - 全局桶：capacity=600，refill_rate=10/s（600/min）
  - 单 IP 桶：capacity=60，refill_rate=1/s（60/min）
  - 单端点桶：capacity=120，refill_rate=2/s（120/min）

阈值可配：
  - TRADEX_RATE_LIMIT_GLOBAL（默认 600）
  - TRADEX_RATE_LIMIT_PER_IP（默认 60）
  - TRADEX_RATE_LIMIT_PER_ENDPOINT（默认 120）

白名单：127.0.0.1 / localhost / [::1] 不限流

超限返回：HTTP 429 + envelope {code: 42901, msg: "rate limit exceeded"}
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# 从 env 读阈值（容量 = 每分钟上限；refill_rate = 每秒补充速率）
_GLOBAL_LIMIT = int(os.environ.get("TRADEX_RATE_LIMIT_GLOBAL", "600"))
_PER_IP_LIMIT = int(os.environ.get("TRADEX_RATE_LIMIT_PER_IP", "60"))
_PER_ENDPOINT_LIMIT = int(os.environ.get("TRADEX_RATE_LIMIT_PER_ENDPOINT", "120"))

# 本机回环白名单
_LOCALHOST = {"127.0.0.1", "localhost", "[::1]", "::1"}


class TokenBucket:
    """令牌桶算法（线程安全）。

    capacity：桶容量（最多累积多少令牌）
    refill_rate：每秒补充多少令牌
    tokens：当前令牌数（初始等于 capacity，让冷启动不被限）
    last_refill：上次补充时间戳
    """

    def __init__(self, capacity: int, refill_rate: float):
        self.capacity = float(capacity)
        self.refill_rate = float(refill_rate)
        self.tokens = float(capacity)
        self.last_refill = time.time()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = time.time()
        elapsed = now - self.last_refill
        new_tokens = elapsed * self.refill_rate
        self.tokens = min(self.capacity, self.tokens + new_tokens)
        self.last_refill = now

    def consume(self, tokens: float = 1.0) -> tuple[bool, float]:
        """尝试消费 N 个令牌。

        Returns:
            (allowed, retry_after_seconds)
            allowed=True 表示成功消费；allowed=False 表示令牌不足，
            retry_after_seconds 给出预估的等待时间。
        """
        with self._lock:
            self._refill()
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True, 0.0
            # 计算还需等多久才有足够令牌
            deficit = tokens - self.tokens
            retry_after = deficit / self.refill_rate if self.refill_rate > 0 else 1.0
            return False, retry_after


class RateLimiter:
    """三层令牌桶限流器（线程安全）。

    维护三个独立桶类别：
    - global_bucket：单例，所有请求共享
    - ip_buckets：dict[client_ip, TokenBucket]
    - endpoint_buckets：dict[(path, method), TokenBucket]
    """

    def __init__(
        self,
        global_limit: int = _GLOBAL_LIMIT,
        per_ip_limit: int = _PER_IP_LIMIT,
        per_endpoint_limit: int = _PER_ENDPOINT_LIMIT,
    ):
        # 容量等于每分钟上限；refill_rate = 上限/60（每秒补充速率）
        self.global_bucket = TokenBucket(capacity=global_limit, refill_rate=global_limit / 60.0)
        self.ip_limit = per_ip_limit
        self.endpoint_limit = per_endpoint_limit
        self._ip_buckets: dict[str, TokenBucket] = {}
        self._endpoint_buckets: dict[tuple[str, str], TokenBucket] = {}
        self._lock = threading.Lock()

    def _get_ip_bucket(self, client_ip: str) -> TokenBucket:
        with self._lock:
            if client_ip not in self._ip_buckets:
                self._ip_buckets[client_ip] = TokenBucket(
                    capacity=self.ip_limit, refill_rate=self.ip_limit / 60.0
                )
            return self._ip_buckets[client_ip]

    def _get_endpoint_bucket(self, path: str, method: str) -> TokenBucket:
        with self._lock:
            key = (path, method)
            if key not in self._endpoint_buckets:
                self._endpoint_buckets[key] = TokenBucket(
                    capacity=self.endpoint_limit, refill_rate=self.endpoint_limit / 60.0
                )
            return self._endpoint_buckets[key]

    def check(self, client_ip: str, path: str, method: str) -> tuple[bool, float, str]:
        """检查请求是否放行（按全局 → 单 IP → 单端点顺序判断）。

        Returns:
            (allowed, retry_after_seconds, failed_layer)
            failed_layer 为空字符串表示成功；否则为 "global" / "per_ip" / "per_endpoint"。
        """
        # 白名单：本机回环不限流
        if client_ip in _LOCALHOST:
            return True, 0.0, ""

        # 三层独立桶，每层都消费 1 个令牌；任一层不足即拒绝
        ok, retry = self.global_bucket.consume()
        if not ok:
            return False, retry, "global"

        ip_bucket = self._get_ip_bucket(client_ip)
        ok, retry = ip_bucket.consume()
        if not ok:
            return False, retry, "per_ip"

        ep_bucket = self._get_endpoint_bucket(path, method)
        ok, retry = ep_bucket.consume()
        if not ok:
            return False, retry, "per_endpoint"

        return True, 0.0, ""


# 全局单例
_limiter: Optional[RateLimiter] = None
_limiter_lock = threading.Lock()


def get_limiter() -> RateLimiter:
    """获取全局限流器单例。"""
    global _limiter
    if _limiter is None:
        with _limiter_lock:
            if _limiter is None:
                _limiter = RateLimiter()
    return _limiter


def reset_limiter() -> None:
    """重置单例（测试用）。"""
    global _limiter
    with _limiter_lock:
        _limiter = None


class RateLimitMiddleware(BaseHTTPMiddleware):
    """限流中间件 —— 拦截 /api/v1/* 请求按三层令牌桶判断。

    白名单：本机回环（127.0.0.1 / localhost / [::1]）不限流。
    超限：返 429 + envelope {code: 42901, msg: "..."}。
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # 只限 /api/v1/* 路径
        if not path.startswith("/api/v1"):
            return await call_next(request)

        client_ip = request.client.host if request.client else ""
        method = request.method

        limiter = get_limiter()
        allowed, retry_after, failed_layer = limiter.check(client_ip, path, method)
        if not allowed:
            # 构造限流响应
            from tradex.api.schemas import ERR_RATE_LIMIT
            retry_hint = f"retry after {retry_after:.1f}s" if retry_after > 0 else "retry later"
            msg = f"rate limit exceeded ({failed_layer}), {retry_hint}"
            return JSONResponse(
                status_code=429,
                content={
                    "code": ERR_RATE_LIMIT,
                    "data": None,
                    "msg": msg,
                    "retry_after": round(retry_after, 2),
                    "layer": failed_layer,
                },
                headers={
                    "Retry-After": str(max(1, int(retry_after))),
                },
            )

        return await call_next(request)


def register_rate_limit_middleware(app) -> None:
    """把 RateLimitMiddleware 挂载到 FastAPI app。"""
    app.add_middleware(RateLimitMiddleware)
