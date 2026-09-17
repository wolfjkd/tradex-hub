"""
回归测试：BaseException（pyo3 PanicException 系）穿透防护。

背景（2026-09-18 根因修复）：
eltdx 3.x Rust 内核（pyo3 native）在并发/异常数据下可能 panic，
pyo3 将 panic 转为 PanicException —— 继承 BaseException 而非 Exception。
SmartRouter.route() / _safe_call 原有的 `except Exception` 无法捕获，
异常穿透至 anyio 事件循环顶层，导致 MCP server 进程整体退出
（WorkBuddy 侧表现：MCP error -32000 Connection closed，且不重连 → 频繁断连）。

本测试锁死三层防线：
  L1 SmartRouter.route()  —— 全源保险丝，BaseException 按源失败处理并降级
  L2 eltdx_fetchers 代理  —— native 调用序列化 + BaseException 转 RuntimeError
  L3 _safe_call           —— 组合分析工具双保险
"""

from __future__ import annotations

import threading

import pytest

from astock_signals.smart_router import SmartRouter


class FakePanic(BaseException):
    """模拟 pyo3 PanicException（BaseException 系，except Exception 捕获不到）。"""


def _boom(**kwargs):
    raise FakePanic("simulated rust panic")


def _good(**kwargs):
    return ("OK-DATA",)


# ─────────────────────────────────────────────
# L1: SmartRouter.route()
# ─────────────────────────────────────────────

class TestRouteBaseException:
    def test_baseexception_source_degrades_to_backup(self):
        """BaseException 源必须按失败处理并降级到备份源（修复前：穿透杀进程）。"""
        r = SmartRouter()
        r.register("t_l1", "bad_native", _boom, priority=1)
        r.register("t_l1", "good_backup", _good, priority=2)
        data, src = r.route("t_l1")
        assert data == ("OK-DATA",)
        assert src == "good_backup"

    def test_baseexception_exclusive_raises_runtime_error_not_passthrough(self):
        """独占源 BaseException 必须转为 RuntimeError，不得原样穿透。"""
        r = SmartRouter()
        r.register("t_l1x", "bad_native", _boom, priority=1, exclusive=True)
        with pytest.raises(RuntimeError, match="bad_native"):
            r.route("t_l1x")

    def test_baseexception_all_failed_raises_runtime_error(self):
        """所有源都 BaseException 时，汇总错误必须是 RuntimeError。"""
        r = SmartRouter()
        r.register("t_l1a", "bad1", _boom, priority=1)
        r.register("t_l1a", "bad2", _boom, priority=2)
        with pytest.raises(RuntimeError, match="All sources"):
            r.route("t_l1a")

    def test_keyboardinterrupt_still_reraised(self):
        """KeyboardInterrupt / SystemExit 不得被吞——必须原样重抛。"""
        def ki(**kwargs):
            raise KeyboardInterrupt()

        r = SmartRouter()
        r.register("t_ki", "src", ki, priority=1)
        with pytest.raises(KeyboardInterrupt):
            r.route("t_ki")

    def test_normal_exception_still_degrades(self):
        """普通 Exception 的既有降级行为不受影响。"""
        def normal_fail(**kwargs):
            raise ValueError("ordinary failure")

        r = SmartRouter()
        r.register("t_norm", "bad", normal_fail, priority=1)
        r.register("t_norm", "good", _good, priority=2)
        data, src = r.route("t_norm")
        assert src == "good"


# ─────────────────────────────────────────────
# L2: eltdx_fetchers 代理（序列化 + 异常转换）
# ─────────────────────────────────────────────

class TestGuardedClient:
    def test_panic_converted_to_runtime_error(self):
        """native 方法 panic（BaseException）必须被代理转为 RuntimeError。"""
        from tradex.data_sources.eltdx_fetchers import _NativePanicShield

        class FakeNativeAPI:
            def series(self, code):
                raise FakePanic("rust panic in native call")

        class FakeClient:
            auctions = FakeNativeAPI()

        guarded = _NativePanicShield(FakeClient())
        with pytest.raises(RuntimeError, match="series"):
            guarded.auctions.series("sh600519")

    def test_keyboardinterrupt_reraised_through_shield(self):
        """代理不得吞 KeyboardInterrupt。"""
        from tradex.data_sources.eltdx_fetchers import _NativePanicShield

        class FakeAPI:
            def call(self):
                raise KeyboardInterrupt()

        class FakeClient:
            api = FakeAPI()

        guarded = _NativePanicShield(FakeClient())
        with pytest.raises(KeyboardInterrupt):
            guarded.api.call()

    def test_scalar_attributes_returned_as_is(self):
        """标量/数据属性必须原样返回，不得被包成代理对象（int 比较等语义保持）。"""
        from tradex.data_sources.eltdx_fetchers import _NativePanicShield

        class FakeClient:
            pool_size = 1
            heartbeat_interval = 30.0
            name = "tdx"

        guarded = _NativePanicShield(FakeClient())
        assert guarded.pool_size == 1 and isinstance(guarded.pool_size, int)
        assert guarded.heartbeat_interval == 30.0
        assert guarded.name == "tdx"

    def test_concurrent_calls_serialized(self):
        """并发调用必须被互斥锁序列化（消除 native 并发竞争触发条件）。"""
        from tradex.data_sources.eltdx_fetchers import _NativePanicShield

        state = {"in_call": 0, "max_concurrent": 0}
        lock = threading.Lock()

        class FakeAPI:
            def call(self, i):
                with lock:
                    state["in_call"] += 1
                    state["max_concurrent"] = max(
                        state["max_concurrent"], state["in_call"]
                    )
                try:
                    import time
                    time.sleep(0.02)
                    return i
                finally:
                    with lock:
                        state["in_call"] -= 1

        class FakeClient:
            api = FakeAPI()

        guarded = _NativePanicShield(FakeClient())
        threads = [
            threading.Thread(target=guarded.api.call, args=(i,)) for i in range(8)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert state["max_concurrent"] == 1, (
            f"native 调用未被序列化: max_concurrent={state['max_concurrent']}"
        )


# ─────────────────────────────────────────────
# CancelledError 语义（规格轴审查发现：不得吞协程取消）
# ─────────────────────────────────────────────

class TestCancelledErrorPassthrough:
    def test_route_reraises_cancelled_error(self):
        """route() 不得吞 asyncio.CancelledError（3.8+ 属 BaseException）。"""
        import asyncio

        def cancelled(**kwargs):
            raise asyncio.CancelledError()

        r = SmartRouter()
        r.register("t_cancel", "src", cancelled, priority=1)
        with pytest.raises(asyncio.CancelledError):
            r.route("t_cancel")

    @pytest.mark.asyncio
    async def test_safe_call_reraises_cancelled_error(self):
        """_safe_call 不得吞 CancelledError——吞掉会让超时/断开取消失效。"""
        import asyncio
        from tradex.tools.composite_analysis import _safe_call

        def cancelled():
            raise asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            await _safe_call(cancelled)


# ─────────────────────────────────────────────
# eltdx_stream 常驻流 client（第二裸 client 穿透路径）
# ─────────────────────────────────────────────

class TestStreamClientShielded:
    def test_stream_start_failure_with_panic_returns_false(self):
        """stream start() 在 connect 期 native panic 时必须返回 False，不得穿透。"""
        from tradex.data_sources import eltdx_stream

        manager = eltdx_stream.EltdxStreamManager()

        class PanicClient:
            @classmethod
            def from_hosts(cls, **kwargs):
                raise FakePanic("rust panic during connect")

        import eltdx
        orig = getattr(eltdx, "TdxClient", None)
        eltdx.TdxClient = PanicClient
        try:
            ok = manager.start()
        finally:
            if orig is not None:
                eltdx.TdxClient = orig
        assert ok is False
        assert manager._client is None


# ─────────────────────────────────────────────
# L3: _safe_call（组合分析双保险）
# ─────────────────────────────────────────────

class TestSafeCallBaseException:
    @pytest.mark.asyncio
    async def test_baseexception_returns_error_dict(self):
        """_safe_call 必须把 BaseException 兜成 error 返回，不得穿透到事件循环。"""
        from tradex.tools.composite_analysis import _safe_call

        def boom():
            raise FakePanic("rust panic")

        result = await _safe_call(boom)
        assert result["success"] is False
        assert "rust panic" in result["error"]

    @pytest.mark.asyncio
    async def test_normal_exception_still_handled(self):
        """普通异常路径不受影响。"""
        from tradex.tools.composite_analysis import _safe_call

        def fail():
            raise ValueError("ordinary")

        result = await _safe_call(fail)
        assert result["success"] is False
        assert "ordinary" in result["error"]
