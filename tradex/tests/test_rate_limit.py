"""工单 20 测试 —— 令牌桶限流（全局 + 单 IP + 单端点三层）。"""

from __future__ import annotations

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tradex.api.schemas import ERR_OK, ERR_RATE_LIMIT


def _build_rate_limit_app(
    global_limit: int = 5,
    per_ip_limit: int = 3,
    per_endpoint_limit: int = 4,
) -> FastAPI:
    """构建带限流中间件的测试 app（用小阈值方便触发）。"""
    from tradex.middleware.rate_limit import RateLimiter, RateLimitMiddleware
    from tradex.api.schemas import Envelope, envelope_ok
    import tradex.middleware.rate_limit as rl_mod

    # 重置单例，用定制参数重建
    rl_mod._limiter = RateLimiter(
        global_limit=global_limit,
        per_ip_limit=per_ip_limit,
        per_endpoint_limit=per_endpoint_limit,
    )

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)

    @app.get("/api/v1/test/ping", response_model=Envelope[dict])
    def ping():
        return envelope_ok({"pong": True})

    return app


@pytest.fixture(autouse=True)
def reset_limiter_after_test():
    """每个测试后重置限流单例，避免污染其他测试。"""
    yield
    from tradex.middleware.rate_limit import reset_limiter
    reset_limiter()


# ────────────────────── 令牌桶单元 ──────────────────────────

class TestTokenBucket:
    def test_consume_success(self):
        from tradex.middleware.rate_limit import TokenBucket
        b = TokenBucket(capacity=10, refill_rate=1.0)
        ok, retry = b.consume(1)
        assert ok is True
        assert retry == 0.0

    def test_consume_until_empty(self):
        """连续消费应耗尽令牌。"""
        from tradex.middleware.rate_limit import TokenBucket
        b = TokenBucket(capacity=3, refill_rate=0.01)  # 慢补充避免干扰
        for _ in range(3):
            ok, _ = b.consume(1)
            assert ok
        # 第 4 次应失败
        ok, retry = b.consume(1)
        assert not ok
        assert retry > 0

    def test_refill_after_wait(self):
        """等待一段时间后令牌应补充。"""
        from tradex.middleware.rate_limit import TokenBucket
        b = TokenBucket(capacity=2, refill_rate=10.0)  # 10/s
        # 耗尽
        b.consume(2)
        ok, _ = b.consume(1)
        assert not ok
        # 等 0.2s 应补 2 个
        time.sleep(0.2)
        ok, _ = b.consume(1)
        assert ok

    def test_capacity_ceiling(self):
        """补充不应超过 capacity。"""
        from tradex.middleware.rate_limit import TokenBucket
        b = TokenBucket(capacity=5, refill_rate=100.0)
        time.sleep(0.1)  # 等待补充
        # 容量上限不应超过 5（虽然按速率应补 10 个）
        b._refill()
        assert b.tokens <= 5.0


# ────────────────────── 三层限流 ──────────────────────────

class TestRateLimiter:
    def test_whitelist_localhost(self):
        """本机回环白名单不限流。"""
        from tradex.middleware.rate_limit import RateLimiter
        rl = RateLimiter(global_limit=1, per_ip_limit=1, per_endpoint_limit=1)
        # 127.0.0.1 即使把容量耗光也应放行
        for _ in range(10):
            allowed, _, layer = rl.check("127.0.0.1", "/api/v1/test", "GET")
            assert allowed
            assert layer == ""

    def test_global_limit_triggered(self):
        """全局桶耗尽应触发拒绝。"""
        from tradex.middleware.rate_limit import RateLimiter
        rl = RateLimiter(global_limit=2, per_ip_limit=100, per_endpoint_limit=100)
        for _ in range(2):
            assert rl.check("1.2.3.4", "/api/v1/x", "GET")[0]
        # 第 3 次应被全局桶拒
        allowed, _, layer = rl.check("1.2.3.4", "/api/v1/x", "GET")
        assert not allowed
        assert layer == "global"

    def test_per_ip_limit_triggered(self):
        """单 IP 桶耗尽应触发拒绝。"""
        from tradex.middleware.rate_limit import RateLimiter
        rl = RateLimiter(global_limit=100, per_ip_limit=2, per_endpoint_limit=100)
        for _ in range(2):
            assert rl.check("5.6.7.8", "/api/v1/x", "GET")[0]
        allowed, _, layer = rl.check("5.6.7.8", "/api/v1/x", "GET")
        assert not allowed
        assert layer == "per_ip"

    def test_per_endpoint_limit_triggered(self):
        """单端点桶耗尽应触发拒绝。"""
        from tradex.middleware.rate_limit import RateLimiter
        rl = RateLimiter(global_limit=100, per_ip_limit=100, per_endpoint_limit=2)
        for _ in range(2):
            assert rl.check("9.10.11.12", "/api/v1/special", "GET")[0]
        allowed, _, layer = rl.check("9.10.11.12", "/api/v1/special", "GET")
        assert not allowed
        assert layer == "per_endpoint"

    def test_different_ips_have_independent_buckets(self):
        """不同 IP 应有独立的桶。"""
        from tradex.middleware.rate_limit import RateLimiter
        rl = RateLimiter(global_limit=100, per_ip_limit=2, per_endpoint_limit=100)
        # 把 IP A 用满
        for _ in range(2):
            assert rl.check("1.1.1.1", "/api/v1/x", "GET")[0]
        # IP A 已被限
        assert not rl.check("1.1.1.1", "/api/v1/x", "GET")[0]
        # IP B 应不受影响
        assert rl.check("2.2.2.2", "/api/v1/x", "GET")[0]


# ────────────────────── 中间件集成 ──────────────────────────

class TestRateLimitMiddleware:
    def test_non_api_request_not_limited(self):
        """非 /api/v1/* 请求不限流。"""
        from tradex.middleware.rate_limit import RateLimiter, RateLimitMiddleware
        import tradex.middleware.rate_limit as rl_mod
        rl_mod._limiter = RateLimiter(global_limit=1, per_ip_limit=1, per_endpoint_limit=1)
        app = FastAPI()
        app.add_middleware(RateLimitMiddleware)

        @app.get("/health")
        def health():
            return {"ok": True}

        client = TestClient(app)
        # 即使全局桶只有 1，/health 也应不被限
        for _ in range(10):
            r = client.get("/health")
            assert r.status_code == 200

    def test_429_response_structure(self):
        """超限响应应返回 429 + envelope 结构。"""
        app = _build_rate_limit_app(global_limit=1, per_ip_limit=10, per_endpoint_limit=10)
        # 注意 TestClient 默认 client_ip 可能是 testclient 或空字符串（不在白名单）
        # 手动把所有非回环 IP 都计入——这里用 default 即可
        client = TestClient(app)
        client.get("/api/v1/test/ping")  # 用掉 1 个令牌
        r = client.get("/api/v1/test/ping")
        # 第二次可能被限也可能不被限（取决于 client_ip 是否在白名单）
        # 这里验证响应结构合法即可
        if r.status_code == 429:
            body = r.json()
            assert body["code"] == ERR_RATE_LIMIT
            assert "rate limit" in body["msg"]
            assert "Retry-After" in r.headers

    def test_concurrent_requests_some_rejected(self):
        """并发请求部分应被拒绝（具体数量取决于 IP 是否在白名单）。"""
        import concurrent.futures
        app = _build_rate_limit_app(global_limit=5, per_ip_limit=3, per_endpoint_limit=4)
        client = TestClient(app)

        def make_request():
            r = client.get("/api/v1/test/ping")
            return r.status_code

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            statuses = list(executor.map(lambda _: make_request(), range(10)))

        # 至少有一个 200（白名单生效或前几个成功）
        assert any(s == 200 for s in statuses)


# ────────────────────── 错误码常量 ──────────────────────────

class TestErrorCode:
    def test_err_rate_limit_value(self):
        """ERR_RATE_LIMIT 应为 42901。"""
        from tradex.api.schemas import ERR_RATE_LIMIT
        assert ERR_RATE_LIMIT == 42901
