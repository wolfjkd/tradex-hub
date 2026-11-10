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
    from tradex.data_sources import akshare_fetchers as akf
    from tradex.utils.cache import cache

    stamp = (akf.datetime.now() - timedelta(days=days_ago)).strftime("%Y%m%d")
    key = f"trade_dates_recent:{stamp}"
    cache.set(key, value, ttl=86400)
    return key


class TestTradeDatesCacheDailyRefresh:
    def teardown_method(self):
        from tradex.utils.cache import cache
        from tradex.data_sources import akshare_fetchers as akf

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
        from tradex.data_sources import akshare_fetchers as akf
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
        from tradex.data_sources import akshare_fetchers as akf
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
        from tradex.data_sources import akshare_fetchers as akf

        today = akf.datetime.now()
        stale_key = _seed(365, [f"{today.year - 1}0601"])
        fake = MagicMock()
        fake.tool_trade_date_hist_sina.return_value = _calendar([today.year])
        with patch.object(akf, "_ak", return_value=fake):
            result = akf._trade_dates_recent()
        assert result == [f"{today.year}0601"]
