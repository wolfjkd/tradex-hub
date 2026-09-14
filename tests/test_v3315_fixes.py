"""v3.3.15 修复回归测试。

覆盖 4 组修复（全部离线可跑，不真连网）：
  P1-1  _prev_quarter_end 季度末真实日期（Q2/Q3 不再产出 20260631 / 20260931）
  P1-2  8 个 fetcher 静默吞异常 → 上抛（交由 SmartRouter 降级并计健康度）
  P2-1/P2-2  7 个「单源无兜底」数据类型的备源注册与优先级
  P4    备源适配器基本契约（fetch_hot_rank_ths / fetch_industry_comparison_ths）
"""

from datetime import datetime

import pandas as pd
import pytest
from unittest.mock import MagicMock

from tradex.data_sources import akshare_fetchers as akf
from tradex.data_sources.akshare_fetchers import (
    _prev_quarter_end,
    fetch_baidu_economic_calendar,
    fetch_baidu_trade_notify,
    fetch_index_news_sentiment,
    fetch_futures_news,
    fetch_hot_search_baidu,
    fetch_hot_rank_data,
    fetch_xueqiu_hot,
    fetch_fund_hold_data,
    fetch_industry_comparison_ths,
    fetch_hot_rank_ths,
)
from tradex.data_sources import ths_fetchers as ths_mod
from tradex.data_sources.registry import register_all_sources, get_router


# ============================================================
# P1-1: _prev_quarter_end 季度末真实日期
# ============================================================

class TestPrevQuarterEnd:
    """上一季度末必须落在真实存在的日期（6→30, 9→30, 12→31）。"""

    def test_specific_dates(self):
        # (today, expected) — 全部显式传参，不依赖当前系统时间
        cases = [
            (datetime(2026, 9, 14), "20260630"),   # Q3 的上一季
            (datetime(2026, 9, 30), "20260630"),
            (datetime(2026, 10, 1), "20260930"),    # 跨入 Q4
            (datetime(2026, 6, 30), "20260331"),     # Q2 上一季是 Q1
            (datetime(2026, 3, 31), "20251231"),     # 跨年：Q1 上一季是去年 Q4
            (datetime(2026, 1, 1), "20251231"),
            (datetime(2024, 4, 1), "20240331"),      # 闰年 2024
        ]
        for today, expected in cases:
            assert _prev_quarter_end(today) == expected, f"{today} → 期望 {expected}"

    def test_invalid_dates_never_produced(self):
        """关键回归：2026 全年 12 个月每月 15 日调用，结果必须全部合法，
        且永远不等于 20260631 / 20260931 这类不存在的日期。"""
        bad = {"20260631", "20260931"}
        for month in range(1, 13):
            s = _prev_quarter_end(datetime(2026, month, 15))
            # 能解析且不抛异常即合法日期
            dt = datetime.strptime(s, "%Y%m%d")
            assert s not in bad, f"第 {month} 月产出非法日期 {s}"
            assert dt.year == 2026 or dt.year == 2025, f"第 {month} 月年份异常: {s}"

    @pytest.mark.parametrize("year", [2024, 2025, 2026])
    @pytest.mark.parametrize("input_month,expect_month,expect_last", [
        (4, 3, 31),    # 上一季度末 = Q1 末（3月，31天）
        (7, 6, 30),    # 上一季度末 = Q2 末（6月，30天）
        (10, 9, 30),   # 上一季度末 = Q3 末（9月，30天）
        (1, 12, 31),   # 上一季度末 = 去年 Q4 末（12月，31天）
    ])
    def test_quarter_end_month_last_day(self, year, input_month, expect_month, expect_last):
        s = _prev_quarter_end(datetime(year, input_month, 15))
        dt = datetime.strptime(s, "%Y%m%d")
        assert dt.month == expect_month
        assert dt.day == expect_last


class TestFundHoldDefaultDate:
    """fetch_fund_hold_data 未传 date 时默认走 _prev_quarter_end，日期必须合法。"""

    def test_default_date_is_prev_quarter_end_and_parsable(self, monkeypatch):
        captured = {}

        def fake_stock_report_fund_hold(symbol, date):
            captured["date"] = date
            return pd.DataFrame({"a": [1]})

        fake_ak = MagicMock()
        fake_ak.stock_report_fund_hold.side_effect = fake_stock_report_fund_hold
        monkeypatch.setattr(akf, "_ak", lambda: fake_ak)

        fetch_fund_hold_data()  # 不传 date

        expected = _prev_quarter_end()
        assert captured["date"] == expected
        # 必须能被 strptime 解析（即真实存在的日期）
        datetime.strptime(captured["date"], "%Y%m%d")


# ============================================================
# P1-2: 静默吞异常 → 上抛
# ============================================================

def _patch_ak_raising(monkeypatch, *attrs):
    """monkeypatch akshare_fetchers._ak 返回一个 stub，其 *attrs 各方法抛 RuntimeError。"""
    fake = MagicMock()
    for attr in attrs:
        setattr(fake, attr, MagicMock(side_effect=RuntimeError("upstream down")))
    monkeypatch.setattr(akf, "_ak", lambda: fake)
    return fake


class TestExceptionPropagation:
    """8 个 fetcher 原吞异常（return pd.DataFrame()），现必须向上抛出。"""

    def test_baidu_economic_calendar_raises(self, monkeypatch):
        _patch_ak_raising(monkeypatch, "news_economic_baidu")
        with pytest.raises(RuntimeError):
            fetch_baidu_economic_calendar()

    def test_baidu_trade_notify_raises(self, monkeypatch):
        # 默认 endpoint=suspend → ak.news_trade_notify_suspend_baidu（会走网络的分支）
        _patch_ak_raising(monkeypatch, "news_trade_notify_suspend_baidu")
        with pytest.raises(RuntimeError):
            fetch_baidu_trade_notify(endpoint="suspend")

    def test_index_news_sentiment_raises(self, monkeypatch):
        _patch_ak_raising(monkeypatch, "index_news_sentiment_scope")
        with pytest.raises(RuntimeError):
            fetch_index_news_sentiment()

    def test_futures_news_raises(self, monkeypatch):
        _patch_ak_raising(monkeypatch, "futures_news_shmet")
        with pytest.raises(RuntimeError):
            fetch_futures_news(symbol="全部")

    def test_hot_search_baidu_raises(self, monkeypatch):
        _patch_ak_raising(monkeypatch, "stock_hot_search_baidu")
        with pytest.raises(RuntimeError):
            fetch_hot_search_baidu()

    def test_hot_rank_data_raises(self, monkeypatch):
        # 默认 endpoint=rank → ak.stock_hot_rank_em（会走网络的分支）
        _patch_ak_raising(monkeypatch, "stock_hot_rank_em")
        with pytest.raises(RuntimeError):
            fetch_hot_rank_data(endpoint="rank")

    def test_xueqiu_hot_raises(self, monkeypatch):
        # 默认 endpoint=follow → ak.stock_hot_follow_xq（会走网络的分支）
        _patch_ak_raising(monkeypatch, "stock_hot_follow_xq")
        with pytest.raises(RuntimeError):
            fetch_xueqiu_hot(endpoint="follow")

    def test_fund_hold_data_raises(self, monkeypatch):
        # 默认 endpoint=hold → ak.stock_report_fund_hold（会走网络的分支）
        _patch_ak_raising(monkeypatch, "stock_report_fund_hold")
        with pytest.raises(RuntimeError):
            fetch_fund_hold_data(endpoint="hold")


# ============================================================
# P2-1/P2-2: 备源注册与优先级
# ============================================================

# (data_type, source_name, expected_priority)
NEW_SOURCES = [
    ("industry_comparison", "ths_flow", 200),
    ("baidu_economic_calendar", "akshare_report_time", 100),
    ("baidu_trade_notify", "akshare_tfp", 100),
    ("hot_rank", "ths_hot", 100),
    ("hot_search", "ths_hot", 100),
    ("xueqiu_hot", "ths_hot", 100),
    ("index_news_sentiment", "legu_activity", 100),
]
# 这两个类型刻意保持单源（未过度改动护栏）
SINGLE_SOURCE_TYPES = ["fund_hold", "futures_news"]


def _source_priority(router, data_type, name):
    for (n, _fn, p, _e) in router._sources.get(data_type, []):
        if n == name:
            return p
    raise AssertionError(f"{data_type}:{name} 未在注册表中找到")


class TestBackupSourceRegistration:
    """v3.3.15 补的 7 个备源必须就位，且总注册数 94→101。"""

    @pytest.fixture(scope="class")
    def router(self):
        register_all_sources()  # 幂等，可安全多次调用
        return get_router()

    def test_total_data_types(self, router):
        # 数据类型数不变（仍 78 个）
        assert len(router._sources) == 78

    def test_total_registrations(self, router):
        # 总注册数 94 → 101（新增 7 个备源）
        assert sum(len(v) for v in router._sources.values()) == 101

    def test_new_sources_registered_with_priority(self, router):
        for data_type, name, prio in NEW_SOURCES:
            names = {n for (n, _fn, _p, _e) in router._sources.get(data_type, [])}
            assert name in names, f"{data_type} 缺少备源 {name}"
            assert _source_priority(router, data_type, name) == prio

    def test_backup_has_at_least_two_sources(self, router):
        for data_type, _name, _prio in NEW_SOURCES:
            sources = router._sources.get(data_type, [])
            assert len(sources) >= 2, f"{data_type} 源数量应 >= 2，实际 {len(sources)}"

    def test_fund_hold_and_futures_news_remain_single(self, router):
        for dt in SINGLE_SOURCE_TYPES:
            assert len(router._sources.get(dt, [])) == 1, f"{dt} 应仍为单源"


# ============================================================
# P4: 备源适配器基本契约
# ============================================================

class TestBackupAdapterContracts:
    """fetch_hot_rank_ths / fetch_industry_comparison_ths 的契约。"""

    def test_hot_rank_ths_unsupported_endpoint_raises(self):
        # 个股维度 endpoint 同花顺热榜无法替代 → 必须抛错（源码为 ValueError）
        for bad in ("detail", "realtime", "keyword", "latest", "relate"):
            with pytest.raises(ValueError):
                fetch_hot_rank_ths(endpoint=bad)

    def test_hot_rank_ths_supported_endpoint_returns_df(self, monkeypatch):
        # 支持的 endpoint 经 ths_fetchers.fetch_ths_hot_list 拿全市场榜
        df = pd.DataFrame({"排名": [1], "代码": ["600000"], "名称": ["浦发银行"]})
        monkeypatch.setattr(ths_mod, "fetch_ths_hot_list", lambda period: df)
        result = fetch_hot_rank_ths(endpoint="rank")
        assert isinstance(result, pd.DataFrame)
        assert not result.empty

    def test_industry_comparison_ths_structure(self, monkeypatch):
        df = pd.DataFrame({
            "行业": ["银行", "半导体"],
            "行业-涨跌幅": [1.5, -0.8],
            "领涨股": ["工商银行", "中芯国际"],
        })
        fake_ak = MagicMock()
        fake_ak.stock_fund_flow_industry.return_value = df
        monkeypatch.setattr(akf, "_ak", lambda: fake_ak)

        result = fetch_industry_comparison_ths()
        assert set(["source", "date", "code", "industries"]).issubset(result.keys())
        assert isinstance(result["industries"], list)
        assert len(result["industries"]) >= 1
        first = result["industries"][0]
        assert set(
            ["rank", "name", "change_pct", "up_count", "down_count", "leader"]
        ).issubset(first.keys())

    def test_industry_comparison_ths_empty_raises(self, monkeypatch):
        fake_ak = MagicMock()
        fake_ak.stock_fund_flow_industry.return_value = pd.DataFrame()
        monkeypatch.setattr(akf, "_ak", lambda: fake_ak)
        with pytest.raises(RuntimeError):
            fetch_industry_comparison_ths()
