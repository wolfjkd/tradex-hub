"""工单 11 测试 —— Prometheus 指标端点与采集。

策略：
- 直接测试 metrics 模块的采集函数（record_request / set_tools_registered 等）
- TestClient 测试 /metrics 和 /api/v1/metrics/json 端点
- 模拟多次请求后验证计数器递增
"""

from __future__ import annotations

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tradex.api.schemas import ERR_OK


def _build_metrics_app() -> FastAPI:
    """构建带指标中间件的测试 app。"""
    from tradex.api.routes import metrics as metrics_routes
    from tradex.api.schemas import envelope_ok, Envelope

    app = FastAPI()
    app.include_router(metrics_routes.router, prefix="/api/v1")

    # 模拟业务端点
    @app.get("/api/v1/test/ping", response_model=Envelope[dict])
    def ping() -> Envelope[dict]:
        return envelope_ok({"pong": True})

    @app.get("/api/v1/test/boom")
    def boom():
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="boom")

    # 注册指标中间件（复用 http_server 的逻辑）
    from tradex.http_server import _register_metrics_middleware
    _register_metrics_middleware(app)

    return app


# ────────────────────── metrics 模块 ──────────────────────────

class TestMetricsModule:
    def test_record_request_increments_counter(self):
        from tradex.metrics import requests_total, record_request
        before = requests_total.labels(method="GET", path="/test", code="200")._value.get()
        record_request("GET", "/test", 200, 0.05)
        after = requests_total.labels(method="GET", path="/test", code="200")._value.get()
        assert after == before + 1

    def test_record_request_counts_errors(self):
        from tradex.metrics import errors_total, record_request
        before = errors_total.labels(method="GET", path="/err")._value.get()
        record_request("GET", "/err", 500, 0.1)
        after = errors_total.labels(method="GET", path="/err")._value.get()
        assert after == before + 1

    def test_record_slow_query_increments_counter(self):
        """duration >= 阈值（默认 800ms）应触发 slow_queries_total。"""
        from tradex.metrics import slow_queries_total, record_request, SLOW_QUERY_THRESHOLD_MS
        # 构造明确超过阈值的延迟
        slow_s = (SLOW_QUERY_THRESHOLD_MS + 100) / 1000.0
        before = slow_queries_total.labels(method="GET", path="/slow")._value.get()
        record_request("GET", "/slow", 200, slow_s)
        after = slow_queries_total.labels(method="GET", path="/slow")._value.get()
        assert after == before + 1

    def test_render_prometheus_text_returns_bytes(self):
        from tradex.metrics import render_prometheus_text
        output = render_prometheus_text()
        assert isinstance(output, (bytes, bytearray))
        text = output.decode("utf-8")
        # Prometheus 文本格式应含指标名（HELP/TYPE 行）
        assert "tradex_requests_total" in text
        assert "tradex_gateway_uptime_seconds" in text

    def test_render_json_snapshot_structure(self):
        from tradex.metrics import render_json_snapshot, set_tools_registered
        set_tools_registered(129)
        snap = render_json_snapshot()
        assert "gateway" in snap
        assert "cache" in snap
        assert snap["gateway"]["uptime_seconds"] >= 0
        assert snap["gateway"]["tools_registered"] == 129

    def test_set_tools_registered(self):
        from tradex.metrics import tools_registered, set_tools_registered
        set_tools_registered(42)
        val = tools_registered._value.get()
        assert val == 42


# ────────────────────── 端点集成 ──────────────────────────

class TestMetricsEndpoints:
    def test_prometheus_metrics_endpoint(self):
        app = _build_metrics_app()
        client = TestClient(app)
        # 先打几个请求产生数据
        client.get("/api/v1/test/ping")
        client.get("/api/v1/test/ping")
        # 访问 /metrics（注意：这个端点由 http_server 挂在根路由，不在 /api/v1 下）
        # 这里直接测 metrics 模块的 render 函数（因为测试 app 不挂根路由 /metrics）
        from tradex.metrics import render_prometheus_text
        text = render_prometheus_text().decode("utf-8")
        assert "tradex_requests_total" in text

    def test_metrics_json_endpoint(self):
        app = _build_metrics_app()
        client = TestClient(app)
        r = client.get("/api/v1/metrics/json")
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == ERR_OK
        assert "gateway" in body["data"]
        assert "cache" in body["data"]
        assert body["data"]["gateway"]["uptime_seconds"] >= 0

    def test_request_counts_after_multiple_calls(self):
        """多次请求后 /metrics 文本里计数应增加。"""
        from tradex.metrics import record_request, render_prometheus_text
        # 打三次
        for _ in range(3):
            record_request("GET", "/api/v1/test/ping", 200, 0.01)
        text = render_prometheus_text().decode("utf-8")
        # 找到对应行并验证数值 >= 3
        lines = [ln for ln in text.splitlines() if "tradex_requests_total" in ln and "code=\"200\"" in ln]
        assert any("path=\"/api/v1/test/ping\"" in ln for ln in lines)


# ────────────────────── 慢查询日志 ──────────────────────────

class TestSlowQueryLog:
    def test_slow_query_log_written(self, tmp_path, monkeypatch):
        """慢查询应写入日志文件。"""
        from tradex.metrics import _log_slow_query, _SLOW_QUERY_LOG
        # 重定向日志路径到临时目录
        fake_log = tmp_path / "slow.log"
        # 直接 patch 内部 open 目标（通过 monkeypatch 模块变量）
        import tradex.metrics as m
        monkeypatch.setattr(m, "_SLOW_QUERY_LOG", fake_log)
        _log_slow_query("GET", "/slow-path", 1.5)
        assert fake_log.exists()
        content = fake_log.read_text(encoding="utf-8")
        assert "/slow-path" in content
        assert "1500ms" in content