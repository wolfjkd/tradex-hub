"""交易日日历缓存按日刷新测试（2026-11-10 审计 A7 → 批次C4 并入统一边界）。

背景：sina 日历只含当年（实测 max=2026-12-31），原「永不失效」进程缓存
在跨年后让 _latest_board_date 回溯只试去年日期——复活「东财对旧日期返回
最近池+错标签」污染。批次A 改 (获取日戳, days) 手工日戳；批次C4 并入
get_or_set 统一序列化边界：键含获取日期，跨天（含跨年）即自然换键重拉，
TTL 到当日午夜（进程内最多一日一拉，与批次A API 成本口径等价）。
"""

from datetime import timedelta
from unittest.mock import MagicMock, patch


def _calendar(years: list[int]):
    """构造 sina 日历桩：每年给一个代表交易日（仅验证年份覆盖）。"""
    import pandas as pd

    return pd.DataFrame(
        {"trade_date": pd.to_datetime([f"{y}-06-01" for y in years])}
    )


def _seed(days_ago: int, value: list[str]) -> str:
    """向共享缓存植入 N 天前的键，返回该键。"""
    from tradex.data_sources import akshare_pools as akf  # 真身随 A⑨ 迁 pools
    from tradex.utils.cache import cache

    stamp = (akf.datetime.now() - timedelta(days=days_ago)).strftime("%Y%m%d")
    key = f"trade_dates_recent:{stamp}"
    cache.set(key, value, ttl=86400)
    return key


class TestTradeDatesCacheDailyRefresh:
    def teardown_method(self):
        from tradex.utils.cache import cache
        from tradex.data_sources import akshare_pools as akf  # 真身随 A⑨ 迁 pools

        today = akf.datetime.now().strftime("%Y%m%d")
        cache.invalidate(f"trade_dates_recent:{today}")
        cache.invalidate(
            f"trade_dates_recent:{(akf.datetime.now() - timedelta(days=1)).strftime('%Y%m%d')}"
        )
        cache.invalidate(
            f"trade_dates_recent:{(akf.datetime.now() - timedelta(days=365)).strftime('%Y%m%d')}"
        )

    def test_same_day_cache_hit(self):
        """当日键已存在：命中缓存，不重拉日历。"""
        from tradex.data_sources import akshare_pools as akf  # 真身随 A⑨ 迁 pools
        from tradex.utils.cache import cache

        today = akf.datetime.now().strftime("%Y%m%d")
        key = f"trade_dates_recent:{today}"
        cache.set(key, ["20261105"], ttl=86400)
        fake = MagicMock()
        with patch.object(akf, "_ak", return_value=fake):
            assert akf._trade_dates_recent() == ["20261105"]
        fake.tool_trade_date_hist_sina.assert_not_called()

    def test_stale_stamp_refetches(self):
        """只有昨日键：换键重拉并写入今日键。"""
        from tradex.data_sources import akshare_pools as akf  # 真身随 A⑨ 迁 pools
        from tradex.utils.cache import cache

        stale_key = _seed(1, ["20260101"])
        fake = MagicMock()
        fake.tool_trade_date_hist_sina.return_value = _calendar([2026])
        with patch.object(akf, "_ak", return_value=fake):
            result = akf._trade_dates_recent()
        assert result == ["20260601"]
        today = akf.datetime.now().strftime("%Y%m%d")
        assert cache.get(f"trade_dates_recent:{today}") == ["20260601"]
        assert stale_key != f"trade_dates_recent:{today}"

    def test_cross_year_refetch_picks_new_year(self):
        """跨年炸弹回归测试：钉住去年键的缓存，重拉必须拿到新年日历。"""
        from tradex.data_sources import akshare_pools as akf  # 真身随 A⑨ 迁 pools

        today = akf.datetime.now()
        stale_key = _seed(365, [f"{today.year - 1}0601"])
        fake = MagicMock()
        fake.tool_trade_date_hist_sina.return_value = _calendar([today.year])
        with patch.object(akf, "_ak", return_value=fake):
            result = akf._trade_dates_recent()
        assert result == [f"{today.year}0601"]


class TestPrevTradingDayConsolidated:
    """QI-STD-98（2026-11-18 收拢）：shortline_service._prev_trading_day 原与
    akshare_fetchers._trade_dates_recent 两套并行日历缓存——收拢单点改调
    _trade_dates_recent（get_or_set 统一边界），双消费路径共用同一份实现。"""

    def test_prev_trading_day_uses_consolidated_cache(self, monkeypatch):
        import tradex.data_sources.akshare_fetchers as akf

        from tradex.service.shortline_service import _prev_trading_day

        called = []

        def fake_recent():
            called.append(1)
            return ["20261102", "20261103", "20261104"]

        monkeypatch.setattr(akf, "_trade_dates_recent", fake_recent)
        assert _prev_trading_day("2026-11-04") == "20261103"
        assert called, "必须走收拢单点 _trade_dates_recent，不再自建缓存"

    def test_prev_trading_day_no_prior_raises(self, monkeypatch):
        import tradex.data_sources.akshare_fetchers as akf

        from tradex.service.shortline_service import _prev_trading_day

        monkeypatch.setattr(
            akf, "_trade_dates_recent", lambda: ["20261102", "20261103"]
        )
        import pytest as _pytest

        with _pytest.raises(ValueError, match="交易日历无 20200101 之前的记录"):
            _prev_trading_day("20200101")
