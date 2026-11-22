"""A⑤ composite route 收敛行为锁定 + 双出口对拍（QI-ARCH-14 票 13，2026-11-22）。

composite_analysis._get_realtime_quote_sync 改调 price_service.get_realtime_quote
（裁决③缓存语义统一，三层单实现）：
- 英文键维度映射保真（下游可见形状不变）
- quote 维度与 MCP/REST 出口共享 realtime_quote:{symbol} TTL_REALTIME 缓存
- ValueError 语义不变（_safe_call 捕获转维度失败 dict）

路由与缓存实例全部 monkeypatch 隔离，不触网。
"""

import asyncio
import json
from types import SimpleNamespace

import pandas as pd

from tradex.utils.cache import TwoLevelCache


def _fresh_cache(monkeypatch, module, tmp_path) -> TwoLevelCache:
    """给目标模块换上独立缓存实例（隔离全局单例，无文件层）。"""
    c = TwoLevelCache(cache_dir=str(tmp_path / "c"), file_enabled=False)
    monkeypatch.setattr(module, "cache", c)
    return c


def _quote_df() -> pd.DataFrame:
    return pd.DataFrame(
        [{
            "代码": "600519", "名称": "贵州茅台", "最新价": 1500.0,
            "涨跌幅": 1.2, "涨跌额": 17.8, "成交量": 30000.0, "成交额": 4.5e7,
            "最高": 1510.0, "最低": 1480.0, "今开": 1490.0, "昨收": 1482.2,
            "换手率": 0.5, "市盈率-动态": 25.0, "总市值": 1.8e12,
        }]
    )


class TestA5CompositeRoute:
    def test_field_mapping_faithful(self, monkeypatch, tmp_path):
        """英文键维度映射：service quote → composite 维度 dict，形状与原实现一致。"""
        from tradex.service import price_service
        from tradex.tools.composite_analysis import _get_realtime_quote_sync

        svc = price_service
        _fresh_cache(monkeypatch, svc, tmp_path)

        def fake_route(cmd, **kwargs):
            if kwargs.get("source_name") == "tencent_http":
                return (pd.DataFrame(), "tencent")  # 估值补取空 → None 字段
            return (_quote_df(), "fake_src")

        monkeypatch.setattr(svc, "_router", SimpleNamespace(route=fake_route))

        dim = _get_realtime_quote_sync("600519")
        assert dim["code"] == "600519"
        assert dim["name"] == "贵州茅台"
        assert dim["price"] == 1500.0
        assert dim["change_pct"] == 1.2
        assert dim["pe_ratio"] == 25.0
        assert dim["total_market_cap"] == 1.8e12
        # 输出键集合固定（下游可见形状）
        assert set(dim.keys()) == {
            "code", "name", "price", "change_pct", "change_amount", "volume",
            "turnover", "high", "low", "open", "prev_close", "turnover_rate",
            "pe_ratio", "total_market_cap",
        }

    def test_missing_fields_fallback_zero(self, monkeypatch, tmp_path):
        """缺失字段 or-0 兜底（原态同型：r.get(key, 0) or 0）。"""
        from tradex.service import price_service
        from tradex.tools.composite_analysis import _get_realtime_quote_sync

        svc = price_service
        _fresh_cache(monkeypatch, svc, tmp_path)

        def fake_route(cmd, **kwargs):
            if kwargs.get("source_name") == "tencent_http":
                return (pd.DataFrame(), "tencent")
            return (pd.DataFrame([{"代码": "600519", "名称": "x", "最新价": 1.0}]), "src")

        monkeypatch.setattr(svc, "_router", SimpleNamespace(route=fake_route))

        dim = _get_realtime_quote_sync("600519")
        assert dim["price"] == 1.0
        assert dim["change_pct"] == 0.0
        assert dim["total_market_cap"] == 0.0

    def test_valueerror_propagates_to_safe_call(self, monkeypatch, tmp_path):
        """行情未找到：service ValueError → _safe_call 转维度失败（原态同语义）。"""
        from tradex.service import price_service
        from tradex.tools.composite_analysis import _safe_call, _get_realtime_quote_sync

        svc = price_service
        _fresh_cache(monkeypatch, svc, tmp_path)

        def fake_route(cmd, **kwargs):
            return (None, "src")  # 数据源空 → service raise ValueError

        monkeypatch.setattr(svc, "_router", SimpleNamespace(route=fake_route))

        result = asyncio.run(_safe_call(_get_realtime_quote_sync, "600519"))
        assert result["success"] is False
        # 文案为 service 层 ValueError 原文（空数据态文案与原 composite 直查
        # 实现不同——A⑤ 已书面化漂移：形状不变、文本微调）
        assert "获取实时行情失败 (600519): 数据源返回空数据" in result["error"]

    def test_dual_exit_share_cache(self, monkeypatch, tmp_path):
        """对拍：MCP 出口与 composite quote 维度共享同一缓存条目（route 不重复）。"""
        from tradex.service import price_service
        from tradex.tools import price_data
        from tradex.tools.composite_analysis import _get_realtime_quote_sync

        svc = price_service
        _fresh_cache(monkeypatch, svc, tmp_path)
        calls = []

        def fake_route(cmd, **kwargs):
            calls.append(cmd)
            if kwargs.get("source_name") == "tencent_http":
                return (pd.DataFrame(), "tencent")
            return (_quote_df(), "fake_src")

        monkeypatch.setattr(svc, "_router", SimpleNamespace(route=fake_route))

        mcp_out = json.loads(asyncio.run(price_data.get_realtime_quote("600519")))
        assert len(calls) == 2  # 主行情 + 首次估值补取

        dim = _get_realtime_quote_sync("600519")
        # composite 维度复用 realtime_quote:{symbol} 缓存：route 总数不变
        assert len(calls) == 2
        # 双出口数据一致（对拍：service quote 原始值 = composite 映射值）
        assert dim["price"] == float(mcp_out["quote"]["最新价"])
        assert dim["code"] == mcp_out["quote"]["代码"]
        # 三出口同一缓存键
        assert svc.cache.get("realtime_quote:600519") is not None
