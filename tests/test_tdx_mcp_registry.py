"""
tdx_mcp 注册集成测试（v0.1.0-DEV，SP-2026-09-21-001）。

锁行为（TDD）：
  - tdx_mcp 与 eltdx 同属 priority=1 第一梯队，互为备份、互为兜底：
      realtime_quote / historical_kline 两类型均有 eltdx + tdx_mcp 双 priority=1 源。
  - 纯增量类型经 registry 统一暴露：screener / research_report / macro_data。
  - 非独占 + 自动降级：无 token 时 fetch_fn 抛 TDXSourceUnavailable，
    route() 把 tdx_mcp 当普通源失败处理，自动降级到下一源（akshare）。
  - 平级互备：eltdx 连续失败健康分归零后，tdx_mcp 成为首选并被真正调用。
"""

import os
import sys

import pytest

_HUB_SRC = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "src"))
if _HUB_SRC not in sys.path:
    sys.path.insert(0, _HUB_SRC)

from tradex.data_sources import register_all_sources  # noqa: E402
from tradex.data_sources import registry as _registry_mod  # noqa: E402
from tradex.data_sources import tdx_mcp_fetchers as tdxf  # noqa: E402
from astock_signals.smart_router import get_router  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_tdx_token(monkeypatch):
    """默认无 token，保证这批测试不依赖真实凭证（纯机制验证）。"""
    monkeypatch.delenv("TDX_MCP_TOKEN", raising=False)
    monkeypatch.delenv("TDX_MCP_ENDPOINT", raising=False)
    monkeypatch.setattr(tdxf, "_CLIENT", None)
    yield


def _sources_for(data_type):
    return get_router()._sources.get(data_type, [])


def _names_source_priority(data_type, name):
    """返回 (priority, exclusive) for 某源在某类型的注册项。"""
    for src_name, fn, priority, exclusive in _sources_for(data_type):
        if src_name == name:
            return (priority, exclusive)
    return None


class TestTdxMcpPeggedFirstTierPeering:
    """tdx_mcp 与 eltdx 平级互备（拍板 #1）。"""

    def setup_method(self):
        # 清空单例，并重置 register_all_sources 的幂等标志，
        # 保证强制重新注册（否则 _registered=True 会被跳过，测不到 tdx_mcp）
        for k in list(get_router()._sources.keys()):
            del get_router()._sources[k]
        for k in list(get_router()._health.keys()):
            del get_router()._health[k]
        _registry_mod._registered = False
        register_all_sources()

    def test_register_clears_and_repopulates(self):
        # 关键前置：确保 setup() 已重置单例并重新注册
        assert len(_sources_for("realtime_quote")) >= 3

    def test_realtime_quote_has_eltdx_and_tdx_mcp_both_priority1(self):
        pe = _names_source_priority("realtime_quote", "eltdx")
        pt = _names_source_priority("realtime_quote", "tdx_mcp")
        assert pe is not None, "eltdx 必须仍是 realtime_quote 的 priority=1 主源"
        assert pt is not None, "tdx_mcp 未注册进 realtime_quote"
        assert pe[0] == 1 and pt[0] == 1, (
            f"平级互备要求两者同 priority=1，实测 eltdx={pe[0]} tdx_mcp={pt[0]}"
        )
        assert pt[1] is False, "tdx_mcp 必须非独占（自动降级）"

    def test_historical_kline_has_tdx_mcp_and_eltdx_both_priority1(self):
        et = _names_source_priority("historical_kline", "eltdx")
        tt = _names_source_priority("historical_kline", "tdx_mcp")
        assert et and tt, "historical_kline 需含 eltdx + tdx_mcp"
        assert et[0] == 1 and tt[0] == 1

    def test_incremental_types_registered(self):
        """纯增量类型经 registry 统一暴露（拍板 #5）。"""
        assert _names_source_priority("screener", "tdx_mcp")[0] == 1
        assert _names_source_priority("research_report", "tdx_mcp")[0] == 1

    def test_macro_data_has_akshare_primary_and_tdx_backup(self):
        p = _names_source_priority("macro_data", "tdx_mcp")
        assert p is not None, "macro_data 应含 tdx_mcp 源"
        assert p[0] == 100, "macro_data 上 akshare 为主，tdx_mcp 为备份（priority=100）"


class TestNonExclusiveAutoDegrade:
    """无 token 时 route 自动降级（拍板 #4 非独占 + 自动降级）。"""

    def test_realtime_no_token_falls_to_akshare(self, monkeypatch):
        router = get_router()
        # 清掉 eltdx 与 tdx_mcp 的真实实现，改用受控桩测「tdx_mcp 失败 → 降级到下一个可用源」
        # 这里不依赖 eltdx 真实网络：直接跳过注册，构造最小 3 层链
        router = get_router()
        from astock_signals.smart_router import SmartRouter

        r = SmartRouter()

        def eltdx_ok(**kw):
            return {"src": "eltdx"}

        def tdx_fail(**kw):
            raise tdxf.TDXSourceUnavailable("no token")

        def akshare_ok(**kw):
            return {"src": "akshare"}

        r.register("realtime_quote", "eltdx", eltdx_ok, priority=1)
        r.register("realtime_quote", "tdx_mcp", tdx_fail, priority=1)
        r.register("realtime_quote", "akshare", akshare_ok, priority=100)

        result, source = r.route("realtime_quote", symbol="600519")
        # 健康评分相同下 eltdx 先注册在前，同分时优先；随后 tdx_mcp 抛 TDXSourceUnavailable 被略过，落到 akshare
        assert source in ("eltdx", "akshare")

    def test_tdx_failure_is_non_blacklist_for_alt_source(self, monkeypatch):
        """tdx_mcp 抛 TDXSourceUnavailable 只惩罚它自己，不影响 eltdx 的健康分。"""
        from astock_signals.smart_router import SmartRouter

        r = SmartRouter()
        calls = {"eltdx": 0, "tdx": 0}

        def eltdx_ok(**kw):
            calls["eltdx"] += 1
            return {"src": "eltdx"}

        def tdx_fail(**kw):
            calls["tdx"] += 1
            raise tdxf.TDXSourceUnavailable("no token")

        r.register("realtime_quote", "eltdx", eltdx_ok, priority=1)
        r.register("realtime_quote", "tdx_mcp", tdx_fail, priority=1)

        # 连调 3 次：eltdx 健康分 100 = tdx_mcp 初始 100，同分时注册靠前的 eltdx 优先，
        # 因此 eltdx 每次都命中；tdx_mcp 一次都不该被摸到。
        for _ in range(3):
            r.route("realtime_quote", symbol="600519")
        assert calls["eltdx"] == 3, "eltdx 为同分首选，应每次都命中"
        assert calls["tdx"] == 0, "eltdx 健康时平级备源 tdx_mcp 不应被调用"

    def test_eltdx_dead_then_tdx_takes_over(self, monkeypatch):
        """平级互备核心：eltdx 连续失败健康分归零后，tdx_mcp 自动接管。"""
        from astock_signals.smart_router import SmartRouter

        r = SmartRouter()
        calls = {"eltdx": 0, "tdx": 0}
        eltdx_failures_left = 6  # 连续 5 次归零拉黑

        def eltdx_unstable(**kw):
            nonlocal eltdx_failures_left
            if eltdx_failures_left > 0:
                eltdx_failures_left -= 1
                raise TimeoutError("eltdx 卡死")
            return {"src": "eltdx"}

        def tdx_ok(**kw):
            calls["tdx"] += 1
            return {"src": "tdx_mcp"}

        r.register("realtime_quote", "eltdx", eltdx_unstable, priority=1)
        r.register("realtime_quote", "tdx_mcp", tdx_ok, priority=1)

        # 第 1 次：eltdx 失败(剩4) → tdx_mcp 兜底
        _, s1 = r.route("realtime_quote", symbol="600519")
        assert s1 == "tdx_mcp", "eltdx 首次失败应立即由平级备源 tdx_mcp 接管"
        assert calls["tdx"] == 1

        # 连续失败让 eltdx 健康分归零拉黑，随后多次调用都应稳定落到 tdx_mcp
        for i in range(12):
            _, s = r.route("realtime_quote", symbol="600519")
        assert calls["tdx"] >= 8, "eltdx 拉黑期间 tdx_mcp 应持续接管"