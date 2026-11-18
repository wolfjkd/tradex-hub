"""fetch_global_index_spot 频控代码化测试（QI-STD-95，2026-11-18 质检整改）。

原契约仅 docstring（「调用方必须做 ≥60s 级缓存」）无代码约束——现模块级
最小间隔 60s 节流（间隔不足自动补眠），空态 None → 空 DataFrame 对齐
AGENTS.md rule 5 书面豁免口径。
"""
from unittest.mock import MagicMock, patch

import pandas as pd

from tradex.data_sources import akshare_fetchers as akf


def _fake_df() -> pd.DataFrame:
    return pd.DataFrame({"名称": ["KOSPI"], "最新价": [5290.53]})


class TestGlobalIndexSpotThrottle:
    def test_first_call_no_sleep(self):
        """首次调用（间隔远大于 60s）：不补眠直接取数。"""
        akf._last_global_index_call = 0.0
        fake_time = MagicMock()
        fake_time.monotonic.side_effect = [1000.0, 1000.0]
        with patch.object(akf, "time", fake_time), patch.object(akf, "_ak") as mock_ak:
            mock_ak.return_value.index_global_spot_em.return_value = _fake_df()
            df = akf.fetch_global_index_spot()
        fake_time.sleep.assert_not_called()
        assert not df.empty

    def test_rapid_second_call_sleeps_gap(self):
        """间隔不足（距上次 10s < 60s）：补眠 50s 后再取（频控契约代码化）。"""
        akf._last_global_index_call = 1000.0
        fake_time = MagicMock()
        fake_time.monotonic.side_effect = [1010.0, 1070.0]
        with patch.object(akf, "time", fake_time), patch.object(akf, "_ak") as mock_ak:
            mock_ak.return_value.index_global_spot_em.return_value = _fake_df()
            akf.fetch_global_index_spot()
        fake_time.sleep.assert_called_once_with(50.0)

    def test_none_yields_empty_frame_with_waiver_comment(self):
        """None → 空 DataFrame（诚实空态）；豁免口径注释 grep 验收见台账回写。"""
        akf._last_global_index_call = 0.0
        fake_time = MagicMock()
        fake_time.monotonic.side_effect = [2000.0, 2000.0]
        with patch.object(akf, "time", fake_time), patch.object(akf, "_ak") as mock_ak:
            mock_ak.return_value.index_global_spot_em.return_value = None
            df = akf.fetch_global_index_spot()
        assert isinstance(df, pd.DataFrame)
        assert df.empty
