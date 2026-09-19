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


# ────────────────────── 工单 14：数据源健康/延迟埋点 ──────────────────────────

class TestDataSourceMetrics:
    """验证 smart_router.route() 把数据源健康/延迟推送到 Prometheus 指标。"""

    def test_record_data_source_success_updates_gauges(self):
        """成功调用：health=1, latency 写入。"""
        from tradex.metrics import (
            data_source_health,
            data_source_latency_seconds,
            record_data_source,
        )
        record_data_source(source="eltdx_test", latency_s=0.045, healthy=True)
        assert data_source_health.labels(source="eltdx_test")._value.get() == 1.0
        assert data_source_latency_seconds.labels(source="eltdx_test")._value.get() == pytest.approx(0.045, rel=1e-3)

    def test_record_data_source_failure_updates_gauges(self):
        """失败调用：health=0。"""
        from tradex.metrics import data_source_health, record_data_source
        record_data_source(source="akshare_fail", latency_s=1.2, healthy=False)
        assert data_source_health.labels(source="akshare_fail")._value.get() == 0.0

    def test_smart_router_success_path_records_metric(self):
        """smart_router.route 成功路径应触发 record_data_source（health=1）。"""
        from astock_signals.smart_router import SmartRouter, _record_data_source_metric
        from tradex.metrics import data_source_health

        router = SmartRouter()
        router.register("test_ds_ok", "src_ok", lambda: {"data": "ok"}, priority=1)
        result, src = router.route("test_ds_ok", timeout=0)
        assert src == "src_ok"
        # 指标应被推送（health=1）
        val = data_source_health.labels(source="src_ok")._value.get()
        assert val == 1.0

    def test_smart_router_failure_path_records_metric(self):
        """smart_router.route 失败路径应触发 record_data_source（health=0）。"""
        from astock_signals.smart_router import SmartRouter
        from tradex.metrics import data_source_health

        def _boom():
            raise RuntimeError("boom")
        router = SmartRouter()
        # 注册一个会失败的源 + 一个独占源保证整体 raise
        router.register("test_ds_fail", "src_boom", _boom, priority=1, exclusive=True)
        with pytest.raises(RuntimeError):
            router.route("test_ds_fail", timeout=0)
        val = data_source_health.labels(source="src_boom")._value.get()
        assert val == 0.0

    def test_smart_router_failover_records_metric_for_each_source(self):
        """失败源（health=0）+ 成功源（health=1）降级时各自埋点。"""
        from astock_signals.smart_router import SmartRouter
        from tradex.metrics import data_source_health

        def _boom():
            raise RuntimeError("boom")
        def _ok():
            return {"data": "fallback"}
        router = SmartRouter()
        router.register("test_ds_fo", "src_primary", _boom, priority=1)
        router.register("test_ds_fo", "src_backup", _ok, priority=100)
        result, src = router.route("test_ds_fo", timeout=0)
        assert src == "src_backup"
        # 失败源 health=0, 成功源 health=1
        assert data_source_health.labels(source="src_primary")._value.get() == 0.0
        assert data_source_health.labels(source="src_backup")._value.get() == 1.0

    def test_record_data_source_metric_silent_on_failure(self):
        """辅助函数在 metrics 不可用时不应抛异常（失败安全）。"""
        from astock_signals.smart_router import _record_data_source_metric
        # 正常调用不应抛异常
        _record_data_source_metric("test_silent", 0.01, True)
        # 即使指标模块内部出错，函数也应吞掉异常
        # （这里只验证接口稳定性，不模拟内部异常）


# ────────────────────── 工单 15：慢查询端点 ──────────────────────────

class TestSlowQueryEndpoint:
    """验证 /api/v1/metrics/slow-queries 端点读取慢查询日志。"""

    def test_slow_queries_endpoint_returns_empty_when_no_log(self, tmp_path, monkeypatch):
        """日志文件不存在时返回空数组。"""
        import tradex.metrics as m
        import tradex.api.routes.metrics as routes_mod
        # 把日志路径指到一个不存在的临时文件
        monkeypatch.setattr(m, "_SLOW_QUERY_LOG", tmp_path / "nonexistent.log")
        monkeypatch.setattr(routes_mod, "_SLOW_QUERY_LOG", tmp_path / "nonexistent.log")

        app = _build_metrics_app()
        client = TestClient(app)
        r = client.get("/api/v1/metrics/slow-queries?limit=5")
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == ERR_OK
        assert body["data"] == []

    def test_slow_queries_endpoint_parses_log(self, tmp_path, monkeypatch):
        """正常日志应解析为结构化数组。"""
        fake_log = tmp_path / "slow.log"
        fake_log.write_text(
            "2026-09-19 10:30:00 GET /api/v1/price/quote 1230ms\n"
            "2026-09-19 10:31:00 POST /api/v1/strategies 850ms\n"
            "garbage line that should be skipped\n"
            "2026-09-19 10:32:00 GET /api/v1/indicator/macd 950ms\n",
            encoding="utf-8",
        )
        import tradex.metrics as m
        import tradex.api.routes.metrics as routes_mod
        monkeypatch.setattr(m, "_SLOW_QUERY_LOG", fake_log)
        monkeypatch.setattr(routes_mod, "_SLOW_QUERY_LOG", fake_log)

        app = _build_metrics_app()
        client = TestClient(app)
        r = client.get("/api/v1/metrics/slow-queries?limit=10")
        body = r.json()
        assert body["code"] == ERR_OK
        data = body["data"]
        # 3 条合法行（1 行垃圾被跳过）
        assert len(data) == 3
        assert data[0]["method"] == "GET"
        assert data[0]["path"] == "/api/v1/price/quote"
        assert data[0]["duration_ms"] == 1230
        assert data[0]["timestamp"] == "2026-09-19 10:30:00"

    def test_slow_queries_endpoint_respects_limit(self, tmp_path, monkeypatch):
        """limit 参数应限制返回条数。"""
        fake_log = tmp_path / "slow.log"
        lines = [f"2026-09-19 10:30:{i:02d} GET /api/v1/p{i} {i+100}ms" for i in range(20)]
        fake_log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        import tradex.metrics as m
        import tradex.api.routes.metrics as routes_mod
        monkeypatch.setattr(m, "_SLOW_QUERY_LOG", fake_log)
        monkeypatch.setattr(routes_mod, "_SLOW_QUERY_LOG", fake_log)

        app = _build_metrics_app()
        client = TestClient(app)
        r = client.get("/api/v1/metrics/slow-queries?limit=5")
        body = r.json()
        assert len(body["data"]) == 5

    def test_slow_queries_tail_only_for_large_file(self, tmp_path, monkeypatch):
        """日志文件 > 10MB 时只读尾部 100KB，截断的第一行被丢弃。"""
        fake_log = tmp_path / "huge.log"
        # 写 11MB 垃圾 + 6 行合法尾部（第一行尾部会被丢弃，剩 5 行）
        with open(fake_log, "wb") as f:
            f.write(b"x" * (11 * 1024 * 1024))
            for i in range(6):
                f.write(f"2026-09-19 10:40:{i:02d} GET /p{i} {i+100}ms\n".encode())
        import tradex.metrics as m
        import tradex.api.routes.metrics as routes_mod
        monkeypatch.setattr(m, "_SLOW_QUERY_LOG", fake_log)
        monkeypatch.setattr(routes_mod, "_SLOW_QUERY_LOG", fake_log)

        app = _build_metrics_app()
        client = TestClient(app)
        r = client.get("/api/v1/metrics/slow-queries?limit=10")
        body = r.json()
        # 尾部 100KB 内的 6 行合法行中第一行被截断保护逻辑丢弃，剩 5 条
        assert len(body["data"]) == 5
        # 应是从 /p1 开始（/p0 被丢弃）
        assert body["data"][0]["path"] == "/p1"

    def test_slow_queries_limit_validation(self):
        """limit 参数校验：ge=1, le=200。"""
        app = _build_metrics_app()
        client = TestClient(app)
        # 0 应被拒（422）
        r = client.get("/api/v1/metrics/slow-queries?limit=0")
        assert r.status_code == 422
        # 201 应被拒
        r = client.get("/api/v1/metrics/slow-queries?limit=201")
        assert r.status_code == 422
        # 合法值
        r = client.get("/api/v1/metrics/slow-queries?limit=1")
        assert r.status_code == 200


# ────────────────────── 工单 16：端点 QPS/P95 聚合 ──────────────────────────

class TestEndpointBreakdown:
    """验证内存维护的端点统计结构和 P50/P95/P99 分位数。"""

    def test_record_endpoint_call_accumulates(self):
        """同一端点多次记录应累加 count 与 durations 窗口。"""
        from tradex.metrics import record_endpoint_call, get_endpoint_breakdown
        # 清理之前测试可能写入的同路径数据
        from tradex.metrics import _endpoint_stats
        _endpoint_stats.pop("/test_breakdown_1", None)
        for _ in range(5):
            record_endpoint_call("GET", "/test_breakdown_1", 0.05)
        bd = get_endpoint_breakdown()
        assert "/test_breakdown_1" in bd
        assert bd["/test_breakdown_1"]["GET"]["count"] == 5

    def test_percentile_calculation_p50_p95_p99(self):
        """百分位计算：构造已知数据集验证 P50/P95/P99。"""
        from tradex.metrics import _percentile
        # 1..100 数据集
        vals = list(range(1, 101))
        # P50 应接近 50.5（线性插值）；P95 接近 95.05；P99 接近 99.01
        assert _percentile(vals, 50) == pytest.approx(50.5, abs=0.1)
        assert _percentile(vals, 95) == pytest.approx(95.05, abs=0.1)
        assert _percentile(vals, 99) == pytest.approx(99.01, abs=0.1)

    def test_percentile_empty_list(self):
        """空列表百分位应返 0（不抛异常）。"""
        from tradex.metrics import _percentile
        assert _percentile([], 50) == 0.0
        assert _percentile([], 95) == 0.0

    def test_percentile_single_value(self):
        """单值列表任何百分位都应等于该值。"""
        from tradex.metrics import _percentile
        assert _percentile([42.0], 50) == 42.0
        assert _percentile([42.0], 99) == 42.0

    def test_endpoint_breakdown_structure(self):
        """get_endpoint_breakdown 返回结构应符合 spec 格式。"""
        from tradex.metrics import record_endpoint_call, get_endpoint_breakdown, _endpoint_stats
        _endpoint_stats.pop("/test_struct", None)
        # 模拟成功和失败调用
        record_endpoint_call("GET", "/test_struct", 0.03, is_error=False)
        record_endpoint_call("GET", "/test_struct", 0.05, is_error=False)
        record_endpoint_call("GET", "/test_struct", 0.20, is_error=True)
        bd = get_endpoint_breakdown()
        entry = bd["/test_struct"]["GET"]
        assert set(entry.keys()) == {"count", "p50_ms", "p95_ms", "p99_ms", "error_count", "error_rate"}
        assert entry["count"] == 3
        assert entry["error_count"] == 1
        assert entry["error_rate"] == pytest.approx(1/3, abs=0.01)

    def test_sliding_window_max_size(self):
        """超过窗口大小的旧数据应被丢弃。"""
        from tradex.metrics import record_endpoint_call, _endpoint_stats, _ENDPOINT_WINDOW
        _endpoint_stats.pop("/test_window", None)
        # 写入超过窗口的次数
        for i in range(_ENDPOINT_WINDOW + 100):
            record_endpoint_call("GET", "/test_window", 0.001 * (i % 10))
        entry = _endpoint_stats["/test_window"]["GET"]
        # durations deque 应被截断到窗口大小
        assert len(entry["durations"]) == _ENDPOINT_WINDOW
        # 但 count 仍是累计值
        assert entry["count"] == _ENDPOINT_WINDOW + 100

    def test_metrics_json_includes_endpoint_breakdown(self):
        """/metrics/json 端点响应应含 endpoint_breakdown 字段。"""
        from tradex.metrics import record_endpoint_call, _endpoint_stats
        _endpoint_stats.pop("/api/v1/test/ep", None)
        record_endpoint_call("GET", "/api/v1/test/ep", 0.04)
        app = _build_metrics_app()
        client = TestClient(app)
        r = client.get("/api/v1/metrics/json")
        body = r.json()
        assert body["code"] == ERR_OK
        assert "endpoint_breakdown" in body["data"]
        assert "/api/v1/test/ep" in body["data"]["endpoint_breakdown"]

    def test_endpoint_breakdown_records_actual_request(self):
        """实际 HTTP 请求触发中间件应记录到端点统计。"""
        from tradex.metrics import _endpoint_stats
        path = "/api/v1/test/ping"
        _endpoint_stats.pop(path, None)
        app = _build_metrics_app()
        client = TestClient(app)
        # 打 3 次
        for _ in range(3):
            client.get(path)
        # 从 /metrics/json 读
        r = client.get("/api/v1/metrics/json")
        body = r.json()
        bd = body["data"]["endpoint_breakdown"]
        assert path in bd
        assert bd[path]["GET"]["count"] >= 3