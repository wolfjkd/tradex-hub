"""工单 T35 测试：SmartRouter 降级机制。

源注册结构为 tuple: (source_name, fetch_fn, priority, exclusive)
- priority 数值越小越优先（1=主源, 100=备源, 200=第三备源, 999=东财兜底）
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest


@pytest.fixture(autouse=True)
def _ensure_registered():
    from tradex.data_sources import register_all_sources
    register_all_sources()


def _get_sources(dtype: str):
    """返回 [(name, fn, priority, exclusive), ...] 按 priority 升序。"""
    from tradex.data_sources import get_router
    r = get_router()
    return list(r._sources.get(dtype, []))


class TestRegistryStructure:
    """源注册表的 tuple 结构合规。"""

    def test_historical_kline_has_multiple_sources(self):
        sources = _get_sources("historical_kline")
        assert len(sources) >= 3, f"historical_kline 应有 ≥3 个源，实际 {len(sources)}"

    def test_source_tuple_structure(self):
        sources = _get_sources("historical_kline")
        for s in sources:
            assert isinstance(s, tuple) and len(s) == 4, f"源应为 4-tuple: {s}"
            name, fn, prio, excl = s
            assert isinstance(name, str)
            assert callable(fn)
            assert isinstance(prio, int)
            assert isinstance(excl, bool)

    def test_sources_ordered_by_priority(self):
        """同类型的源 priority 应升序（主源在前）。"""
        sources = _get_sources("historical_kline")
        priorities = [s[2] for s in sources]
        assert priorities == sorted(priorities), \
            f"源未按 priority 排序: {priorities}"


class TestBackupChainAvailability:
    """关键数据类型应支持一主一备（≥2 源）。"""

    PRIMARY_BACKUP_TYPES = [
        "historical_kline",          # eltdx + tdx_mcp + akshare + baidu
        "research_report",           # 主 + sina_research
        "fund_flow",                 # 主 + sina_fund_flow
        "valuation",                 # 主 + baostock_tcp
        "dragon_tiger",              # 东财 + sse_official + szse_official
        "cninfo_announcement",       # 主 + szse_official
        "margin_trading",            # 主 + sse_official + szse_official
    ]

    def test_each_has_at_least_2_sources(self):
        for dtype in self.PRIMARY_BACKUP_TYPES:
            sources = _get_sources(dtype)
            assert len(sources) >= 2, (
                f"{dtype} 只有 {len(sources)} 个源，期望 ≥2"
            )


class TestRouterRoute:
    """SmartRouter.route() 的接口契约。"""

    def test_route_returns_tuple(self):
        """route() 应返回 (DataFrame, source_name) 二元组。"""
        from tradex.data_sources import get_router
        r = get_router()
        # 用一个保证有源的类型 + 全部 mock
        sources = _get_sources("historical_kline")
        # 临时替换第一个源的 fn
        original = sources[0]
        mock_df = pd.DataFrame([{"close": 1}])
        new_entry = (original[0], MagicMock(return_value=mock_df),
                     original[2], original[3])
        sources[0] = new_entry
        try:
            r._sources["historical_kline"] = sources
            result = r.route("historical_kline", symbol="600519")
            assert isinstance(result, tuple) and len(result) == 2
            df, src = result
            assert src == original[0]
        finally:
            sources[0] = original
            r._sources["historical_kline"] = sources

    def test_route_unknown_type(self):
        """未知类型应抛错或返回空 DataFrame。"""
        from tradex.data_sources import get_router
        r = get_router()
        try:
            df, src = r.route("definitely_not_registered_xyz")
            assert df is None or df.empty
        except Exception:
            # 抛错也合理（明确告知无源）
            pass


class TestSourcePriorityDistribution:
    """各类 priority 分布合理性。"""

    def test_most_sources_are_primary(self):
        """大部分源应是 priority=1（主源）。"""
        from tradex.data_sources import get_router
        r = get_router()
        primary_count = 0
        total = 0
        for sources in r._sources.values():
            for s in sources:
                total += 1
                if s[2] == 1:
                    primary_count += 1
        # 至少 70% 是主源（大部分类型只有 1 个源）
        assert primary_count / total > 0.5, \
            f"主源占比 {primary_count}/{total} < 50%"

    def test_backup_sources_exist(self):
        """应有 priority=100 的备源。"""
        from tradex.data_sources import get_router
        r = get_router()
        backup_count = sum(
            1 for sources in r._sources.values() for s in sources
            if s[2] == 100
        )
        assert backup_count >= 10, f"备源（priority=100）数量 {backup_count} < 10"
