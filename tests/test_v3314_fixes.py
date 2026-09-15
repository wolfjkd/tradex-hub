"""v3.3.14 修复回归测试。

覆盖 4 处修复：
  P1-a  akshare 备源 period 归一化（消除与 eltdx 主源的值域分裂）
  P1-b  NO_PROXY 绕开 Windows 注册表系统代理
  P2    4 个单源类型（company_info/financial_stmt/valuation/industry_data）的独立备源
  P3    _bar_sort_key 异常处理不再静默降级
"""

import datetime
import os
from unittest.mock import MagicMock, patch

import pytest

from tradex.data_sources.akshare_fetchers import (
    _normalize_ak_period,
    fetch_company_info_cninfo,
    fetch_financial_stmt_sina,
    fetch_historical_kline,
    fetch_industry_data_ths,
)
from tradex.data_sources.eltdx_fetchers import _bar_sort_key, fetch_valuation_eltdx


# ============================================================
# P1-a: period 归一化
# ============================================================

class TestAksharePeriodNormalization:
    """akshare 备源必须接受 eltdx 风格周期名。"""

    def test_eltdx_style_to_akshare_style(self):
        assert _normalize_ak_period("day") == "daily"
        assert _normalize_ak_period("week") == "weekly"
        assert _normalize_ak_period("month") == "monthly"

    def test_akshare_style_passthrough(self):
        for v in ("daily", "weekly", "monthly"):
            assert _normalize_ak_period(v) == v

    def test_short_aliases(self):
        assert _normalize_ak_period("d") == "daily"
        assert _normalize_ak_period("w") == "weekly"
        assert _normalize_ak_period("1m") == "monthly"

    def test_case_insensitive_and_strip(self):
        assert _normalize_ak_period("  DAY ") == "daily"

    def test_unknown_value_passthrough(self):
        assert _normalize_ak_period("weird") == "weird"
        assert _normalize_ak_period("") == ""

    def test_fetch_historical_kline_applies_normalization(self):
        """核心回归：fetch_historical_kline 必须把 day 归一成 daily 再传给 akshare。

        修复前直接透传 period='day' → akshare period_dict['day'] KeyError，
        导致 eltdx 主源失败时降级链断裂。
        """
        captured = {}

        def fake_hist(**kwargs):
            captured.update(kwargs)
            return MagicMock()

        with patch("akshare.stock_zh_a_hist", side_effect=fake_hist):
            fetch_historical_kline(code="600000", period="day")
        assert captured["period"] == "daily"

        with patch("akshare.stock_zh_a_hist", side_effect=fake_hist):
            fetch_historical_kline(code="600000", period="weekly")
        assert captured["period"] == "weekly"


# ============================================================
# P1-b: 代理绕开
# ============================================================

class TestProxyBypass:
    """import tradex 后必须彻底绕开系统代理（含注册表代理）。"""

    def test_no_proxy_env_is_set(self):
        import tradex  # noqa: F401  ← 触发 __init__.py
        assert os.environ.get("NO_PROXY") == "*"
        assert os.environ.get("no_proxy") == "*"

    def test_requests_getproxies_bypassed(self):
        """getproxies() 不应再返回注册表里的 http/https 代理。"""
        import tradex  # noqa: F401
        import requests.utils

        proxies = requests.utils.getproxies()
        # 设 NO_PROXY=* 后 getproxies_environment() 非空短路，返回 {'no': '*'}
        assert "http" not in proxies or proxies.get("no") == "*"


# ============================================================
# P2: 独立备源
# ============================================================

@pytest.fixture(scope="class")
def router():
    from tradex.data_sources.registry import register_all_sources
    from astock_signals.smart_router import get_router

    register_all_sources()
    return get_router()


class TestIndependentBackupSources:
    """4 个原单源类型必须有非东财的独立备源。"""

    EXPECTED = [
        ("company_info", "cninfo"),
        ("financial_stmt", "sina"),
        ("valuation", "eltdx"),
        ("industry_data", "ths"),
    ]

    def test_backup_sources_registered(self, router):
        for data_type, source in self.EXPECTED:
            names = {n for (n, _fn, _p, _e) in router._sources.get(data_type, [])}
            assert source in names, f"{data_type} 缺少备源 {source}"
            assert "akshare" in names, f"{data_type} 主源丢失"

    def test_backup_priority_is_lower_than_primary(self, router):
        for data_type, source in self.EXPECTED:
            prios = {n: p for (n, _fn, p, _e) in router._sources.get(data_type, [])}
            assert prios[source] > prios["akshare"], f"{data_type} 备源优先级未低于主源"

    def test_registry_total_source_count(self, router):
        """数据源总数快照：v3.3.14 补 4 备源后为 94，v3.3.15 再补 7 备源后为 101，
        其后 fund_hold 由单源升为双源（em_zlsj_direct + akshare）→ 102。"""
        # 基线演进：90（v3.3.13） → 94（v3.3.14 新增 4 备源）
        #           → 101（v3.3.15 新增 7 备源：industry_comparison/ths_flow、
        #             baidu_economic_calendar、baidu_trade_notify、
        #             hot_rank/hot_search/xueqiu_hot 共用 ths_hot、index_news_sentiment）
        #           → 102（fund_hold 补直取主源 em_zlsj_direct，修复 akshare 列错位）
        assert len(router.get_registry_report()) == 102

    def test_unsupported_endpoint_raises(self):
        """备源只覆盖部分 endpoint，其余必须显式报错而非静默返回空。"""
        with pytest.raises(ValueError):
            fetch_company_info_cninfo(endpoint="code_name", symbol="600000")
        with pytest.raises(ValueError):
            fetch_financial_stmt_sina(endpoint="indicator", symbol="600000")
        with pytest.raises(ValueError):
            fetch_industry_data_ths(endpoint="sector_fund_flow_rank")
        with pytest.raises(ValueError):
            fetch_valuation_eltdx(endpoint="dividend_detail", code="600000")

    @pytest.mark.parametrize("code,expected", [
        ("600000", "600000"),
        ("sh600000", "600000"),
        ("SZ000001", "000001"),
    ])
    def test_code_normalization_helpers(self, code, expected):
        from tradex.data_sources.akshare_fetchers import _code6

        assert _code6(code) == expected


# ============================================================
# P3: _bar_sort_key 异常处理
# ============================================================

class TestBarSortKey:
    """取不到时间的 bar 必须排到末尾并告警，不能静默排到最前污染首行。"""

    class _Bar:
        def __init__(self, t):
            self.time = t

    def test_normal_datetime(self):
        dt = datetime.datetime(2026, 9, 14, 15, 0, 0)
        assert _bar_sort_key(self._Bar(dt)) == dt.timestamp()

    def test_none_time_goes_last(self):
        assert _bar_sort_key(self._Bar(None)) == float("inf")

    def test_invalid_time_goes_last(self):
        assert _bar_sort_key(self._Bar("not-a-datetime")) == float("inf")

    def test_logs_warning_instead_of_silent(self, caplog):
        import logging

        with caplog.at_level(logging.WARNING, logger="tradex.eltdx"):
            _bar_sort_key(self._Bar(None))
        assert any("时间字段无法解析" in r.message for r in caplog.records)

    def test_sorting_keeps_valid_bars_first(self):
        """回归：修复前异常 bar 会被排到最前（0.0），现在必须排到最后。"""
        bars = [
            self._Bar(None),
            self._Bar(datetime.datetime(2026, 1, 1)),
            self._Bar(datetime.datetime(2026, 2, 1)),
        ]
        ordered = sorted(bars, key=_bar_sort_key)
        assert ordered[0].time == datetime.datetime(2026, 1, 1)
        assert ordered[-1].time is None
