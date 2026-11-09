"""
短线落库封板时间链路测试（2026-11-08 票B）。

覆盖：
  - _prev_trading_day（前一交易日，含跨月）
  - ensure_prev_zt_seal_times（prev_zt 池注入昨日首封/末封，失败只记原因）
  - _latest_board_date_with_rows 交易日过滤（2026-11-08 日期污染修复）
  - _stock_brief 携带 last_seal_time
"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


def _fake_ak():
    ak = MagicMock()
    ak.tool_trade_date_hist_sina.return_value = pd.DataFrame(
        {"trade_date": pd.to_datetime(
            ["2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06",
             "2026-11-09", "2026-11-10", "2026-11-30", "2026-12-01"]
        )}
    )
    return ak


class TestPrevTradingDay:
    def test_normal(self):
        from tradex.service import shortline_service as svc

        with patch("tradex.data_sources.akshare_fetchers._ak", return_value=_fake_ak()):
            assert svc._prev_trading_day("20261106") == "20261105"

    def test_cross_month(self):
        from tradex.service import shortline_service as svc

        with patch("tradex.data_sources.akshare_fetchers._ak", return_value=_fake_ak()):
            assert svc._prev_trading_day("20261201") == "20261130"

    def test_no_prior_raises(self):
        from tradex.service import shortline_service as svc

        with patch("tradex.data_sources.akshare_fetchers._ak", return_value=_fake_ak()):
            with pytest.raises(ValueError, match="之前"):
                svc._prev_trading_day("20260101")


class TestLatestBoardDate:
    def test_skips_non_trade_days(self):
        """固定「今天=2026-11-08 周日」：即使东财对周日返回数据，也必须落到 20261106。

        原实现依赖真实运行日（datetime.now），2026-11-09 周一后必挂——
        patch akf.datetime 与运行日解耦（同 TradeX 0be6b58 修 test_etf_scan 的口径）。"""
        from datetime import datetime as _real_dt

        from tradex.data_sources import akshare_fetchers as akf

        class _FixedDT(_real_dt):
            @classmethod
            def now(cls, tz=None):  # noqa: ARG003 - 兼容签名
                return _real_dt(2026, 11, 8, 10, 0, 0)  # 周日

        fake_ak = _fake_ak()
        # 模拟东财新行为：非交易日 date 也返回最近交易日数据（不空）
        fake_ak.stock_zt_pool_em.return_value = pd.DataFrame(
            {"代码": ["600000"], "名称": ["假数据"]}
        )
        with patch.object(akf, "_ak", return_value=fake_ak), patch.object(
            akf, "_TRADE_DATES_CACHE", []
        ):
            # 强制重建缓存（用假日历），并把「今天」钉在周日
            with patch("tradex.data_sources.akshare_fetchers._TRADE_DATES_CACHE", []), \
                 patch.object(akf, "datetime", _FixedDT):
                date_str, rows = akf._latest_board_date_with_rows()
        assert date_str == "20261106", f"应落在最近交易日，实得 {date_str}"
        assert rows

    def test_cache_reuse(self):
        from tradex.data_sources import akshare_fetchers as akf

        old = akf._TRADE_DATES_CACHE
        try:
            akf._TRADE_DATES_CACHE = ["20261105", "20261106"]
            fake_ak = _fake_ak()
            fake_ak.stock_zt_pool_em.return_value = pd.DataFrame(
                {"代码": ["600000"], "名称": ["A"]}
            )
            with patch.object(akf, "_ak", return_value=fake_ak):
                date_str, _ = akf._latest_board_date_with_rows()
            # 缓存命中不拉日历表（_ak() 本身只是拿模块引用，不发请求）
            fake_ak.tool_trade_date_hist_sina.assert_not_called()
            assert date_str == "20261106"
        finally:
            akf._TRADE_DATES_CACHE = old


class TestEnrichPrevZtSealTimes:
    def _snapshot(self):
        from tradex.shortline.compute import PoolSnapshot

        return PoolSnapshot(
            date="20261106",
            zt=[{"code": "600000", "name": "A"}],
            prev_zt=[
                {"code": "600000", "name": "A", "change_pct": 2.0},
                {"code": "000001", "name": "B", "change_pct": -1.0},
            ],
        )

    def test_inject(self):
        from tradex.service import shortline_service as svc

        snap = self._snapshot()
        zt_payload = {
            "data": [
                {"code": "600000", "first_seal_time": "093805", "last_seal_time": "095408"},
            ]
        }
        with patch.object(svc, "_prev_trading_day", return_value="20261105"), patch.object(
            svc._router, "route", return_value=(zt_payload, "akshare_em")
        ):
            svc.ensure_prev_zt_seal_times(snap)
        assert snap.prev_zt[0]["last_seal_time"] == "095408"
        assert snap.prev_zt[0]["first_seal_time"] == "093805"
        assert not snap.prev_zt[1].get("last_seal_time")  # 无交集不注入
        assert not snap.missing  # 不影响 partial 判定

    def test_failure_only_records_reason(self):
        from tradex.service import shortline_service as svc

        snap = self._snapshot()
        with patch.object(svc, "_prev_trading_day", side_effect=ValueError("日历炸了")):
            svc.ensure_prev_zt_seal_times(snap)
        assert "prev_zt_seal_times" in snap.reasons
        assert not snap.missing

    def test_noop_without_prev_zt(self):
        from tradex.service import shortline_service as svc

        snap = self._snapshot()
        snap.prev_zt = []
        with patch.object(svc, "_prev_trading_day") as mocked:
            svc.ensure_prev_zt_seal_times(snap)
        mocked.assert_not_called()


class TestStockBrief:
    def test_has_last_seal_time(self):
        from tradex.shortline.compute import _stock_brief

        brief = _stock_brief(
            {"code": "600000", "name": "A", "first_seal_time": "093805", "last_seal_time": "095408"}
        )
        assert brief["last_seal_time"] == "095408"
        assert brief["first_seal_time"] == "093805"
