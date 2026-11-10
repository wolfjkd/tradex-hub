"""交易日日历缓存按日刷新测试（2026-11-10 审计 A7）。

背景：sina 日历只含当年（实测 max=2026-12-31），原「永不失效」进程缓存
在跨年后让 _latest_board_date 回溯只试去年日期——复活「东财对旧日期返回
最近池+错标签」污染。修复后缓存结构为 (获取日戳, days)，跨天即重拉。
"""

from datetime import timedelta
from unittest.mock import MagicMock, patch


def _calendar(years: list[int]):
    """构造 sina 日历桩：每年给一个代表交易日（仅验证年份覆盖）。"""
    import pandas as pd

    return pd.DataFrame(
        {"trade_date": pd.to_datetime([f"{y}-06-01" for y in years])}
    )


class TestTradeDatesCacheDailyRefresh:
    def test_same_day_cache_hit(self):
        """当日戳与今天一致：命中缓存，不重拉日历。"""
        from tradex.data_sources import akshare_fetchers as akf

        old = akf._TRADE_DATES_CACHE
        try:
            stamp = akf.datetime.now().strftime("%Y%m%d")
            akf._TRADE_DATES_CACHE = (stamp, ["20261105"])
            fake = MagicMock()
            with patch.object(akf, "_ak", return_value=fake):
                assert akf._trade_dates_recent() == ["20261105"]
            fake.tool_trade_date_hist_sina.assert_not_called()
        finally:
            akf._TRADE_DATES_CACHE = old

    def test_stale_stamp_refetches(self):
        """日戳是昨天：重拉并写入新日戳。"""
        from tradex.data_sources import akshare_fetchers as akf

        old = akf._TRADE_DATES_CACHE
        try:
            stale = (akf.datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
            akf._TRADE_DATES_CACHE = (stale, ["20260101"])
            fake = MagicMock()
            fake.tool_trade_date_hist_sina.return_value = _calendar([2026])
            with patch.object(akf, "_ak", return_value=fake):
                result = akf._trade_dates_recent()
            assert result == ["20260601"]
            assert akf._TRADE_DATES_CACHE[0] == akf.datetime.now().strftime("%Y%m%d")
        finally:
            akf._TRADE_DATES_CACHE = old

    def test_cross_year_refetch_picks_new_year(self):
        """跨年炸弹回归测试：钉住去年日戳的缓存，重拉必须拿到新年日历。"""
        from tradex.data_sources import akshare_fetchers as akf

        old = akf._TRADE_DATES_CACHE
        try:
            today = akf.datetime.now()
            stale = today.replace(year=today.year - 1).strftime("%Y%m%d")
            akf._TRADE_DATES_CACHE = (stale, [f"{today.year - 1}0601"])
            fake = MagicMock()
            fake.tool_trade_date_hist_sina.return_value = _calendar([today.year])
            with patch.object(akf, "_ak", return_value=fake):
                result = akf._trade_dates_recent()
            assert result == [f"{today.year}0601"]
        finally:
            akf._TRADE_DATES_CACHE = old
