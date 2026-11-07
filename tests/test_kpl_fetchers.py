"""
开盘啦（KPL）数据源 fetcher 测试（对应交接文档 07 T1' + 09 T3）。

2026-11-07 实测背景：KPL 免鉴权直连，UA 必须安卓 Dalvik；涨停接口
PidType 只收 1~5（0 报 1020），"全量" 由 fetcher 循环 1~5 拼接。

本测试 mock 隔离网络，验证字段映射 / 板位拼接 / 降级纪律；
真实接口冒烟标注 network，单独跑。
"""

import pandas as pd
import pytest
from unittest.mock import MagicMock, patch


class TestNormalizeDay:
    def test_compact_format(self):
        from tradex.data_sources.kpl_fetchers import _normalize_day

        assert _normalize_day("20261106") == "2026-11-06"

    def test_dashed_format_passthrough(self):
        from tradex.data_sources.kpl_fetchers import _normalize_day

        assert _normalize_day("2026-11-06") == "2026-11-06"

    def test_empty_returns_empty_for_realtime(self):
        from tradex.data_sources.kpl_fetchers import _normalize_day

        assert _normalize_day("") == ""
        assert _normalize_day(None) == ""

    def test_invalid_raises(self):
        from tradex.data_sources.kpl_fetchers import _normalize_day

        with pytest.raises(ValueError):
            _normalize_day("2026-11")
        with pytest.raises(ValueError):
            _normalize_day("abcdef01")


class TestRowsToDf:
    def test_position_mapping(self):
        from tradex.data_sources.kpl_fetchers import _rows_to_df

        fields = {0: "code", 2: "amount"}
        df = _rows_to_df([["600000", "ignored", 12345]], fields)
        assert list(df.columns) == ["code", "amount"]
        assert df.iloc[0]["code"] == "600000"
        assert df.iloc[0]["amount"] == 12345

    def test_short_row_safe(self):
        """行长度不足映射位置 → 该字段缺失，不炸。"""
        from tradex.data_sources.kpl_fetchers import _rows_to_df

        fields = {0: "code", 5: "reason"}
        df = _rows_to_df([["600000"]], fields)
        assert df.iloc[0]["code"] == "600000"
        assert "reason" not in df.columns

    def test_empty_rows(self):
        from tradex.data_sources.kpl_fetchers import _rows_to_df

        assert _rows_to_df([], {0: "code"}).empty


class TestKplGet:
    def test_errcode_nonzero_raises(self):
        from tradex.data_sources.kpl_fetchers import _kpl_get

        resp = MagicMock()
        resp.json.return_value = {"errcode": "1020", "errmsg": "参数出错"}
        resp.raise_for_status = MagicMock()
        with patch(
            "tradex.data_sources.kpl_fetchers._kpl_session"
        ) as m_sess:
            m_sess.return_value.get.return_value = resp
            with pytest.raises(RuntimeError, match="1020"):
                _kpl_get("https://x", {"a": "X"})

    def test_errcode_zero_passthrough(self):
        from tradex.data_sources.kpl_fetchers import _kpl_get

        resp = MagicMock()
        resp.json.return_value = {"errcode": "0", "info": [1]}
        resp.raise_for_status = MagicMock()
        with patch(
            "tradex.data_sources.kpl_fetchers._kpl_session"
        ) as m_sess:
            m_sess.return_value.get.return_value = resp
            assert _kpl_get("https://x", {"a": "X"})["info"] == [1]


class TestSessionDirectConnect:
    """直连铁律：KPL 会话必须禁读代理环境变量 + Dalvik UA。"""

    def test_trust_env_and_headers(self):
        from tradex.data_sources.kpl_fetchers import _kpl_session

        session = _kpl_session()
        assert session.trust_env is False
        assert "Dalvik" in session.headers["User-Agent"]


class TestFetchKplLimitUp:
    def _payload(self, code="600000", reason="AI应用"):
        return {
            "errcode": "0",
            "info": [[[code, "某股", 0, "", 1793928608, reason,
                       62382832, 248228992, 32498232, 42571898, -10073666,
                       55070285, "AI应用、算力", 2868089937, 20.11,
                       1, 1, 2.04, "", "801511", 3]]],
        }

    def test_realtime_single_ladder(self):
        from tradex.data_sources.kpl_fetchers import fetch_kpl_limit_up

        with patch(
            "tradex.data_sources.kpl_fetchers._kpl_get",
            return_value=self._payload(),
        ) as m_get:
            df = fetch_kpl_limit_up(pid_type=1)  # 空 date → 实时；单板位 1 次请求
        assert m_get.call_count == 1
        assert df.iloc[0]["ladder"] == 1
        assert df.iloc[0]["code"] == "600000"
        assert df.iloc[0]["kpl_board_code"] == "801511"
        assert df.iloc[0]["reason"] == "AI应用"
        args = m_get.call_args
        assert args[0][0].startswith("https://apphwhq")  # 实时走 apphwhq

    def test_realtime_default_all_ladders(self):
        """默认 pid_type=0 = 全量（循环 1~5，5 次请求）。"""
        from tradex.data_sources.kpl_fetchers import fetch_kpl_limit_up

        with patch(
            "tradex.data_sources.kpl_fetchers._kpl_get",
            return_value=self._payload(),
        ) as m_get:
            fetch_kpl_limit_up()
        assert m_get.call_count == 5

    def test_history_uses_apphis_and_day(self):
        from tradex.data_sources.kpl_fetchers import fetch_kpl_limit_up

        with patch(
            "tradex.data_sources.kpl_fetchers._kpl_get",
            return_value=self._payload(),
        ) as m_get:
            fetch_kpl_limit_up(date="20261106", pid_type=2)
        args = m_get.call_args
        assert args[0][0].startswith("https://apphis")  # 历史走 apphis
        assert args[0][1]["Day"] == "2026-11-06"
        assert args[0][1]["PidType"] == "2"
        assert args[0][1]["c"] == "HisHomeDingPan"

    def test_pid_type_zero_loops_five(self):
        """pid_type=0 → 循环 PidType 1~5 拼接（含空板位过滤）。"""
        from tradex.data_sources.kpl_fetchers import fetch_kpl_limit_up

        payloads = [self._payload(code=f"60000{i}") for i in range(5)]
        payloads[3] = {"errcode": "0", "info": [[]]}  # 4 板无数据
        with patch(
            "tradex.data_sources.kpl_fetchers._kpl_get",
            side_effect=payloads,
        ) as m_get:
            df = fetch_kpl_limit_up(date="20261106")
        assert m_get.call_count == 5
        assert sorted(df["ladder"].tolist()) == [1, 2, 3, 5]

    def test_all_empty_returns_empty_df(self):
        from tradex.data_sources.kpl_fetchers import fetch_kpl_limit_up

        with patch(
            "tradex.data_sources.kpl_fetchers._kpl_get",
            return_value={"errcode": "0", "info": [[]]},
        ):
            df = fetch_kpl_limit_up(date="20261106")
        assert df.empty


class TestFetchKplSentiment:
    def test_full_parse(self):
        from tradex.data_sources.kpl_fetchers import fetch_kpl_sentiment

        rise = {"errcode": "0",
                "info": [[32, 15, 30, 8, 30.4348, 14, "2026-11-06"]]}
        stat = {"errcode": "0", "info": [
            {"ztjs": "32", "Day": "2026-11-06", "df_num": "6",
             "strong": "34", "lbgd": "5"}]}
        with patch(
            "tradex.data_sources.kpl_fetchers._kpl_get",
            side_effect=[rise, stat],
        ):
            out = fetch_kpl_sentiment()
        assert out["limit_up"] == 32
        assert out["zhaban_rate"] == 30.4348
        assert out["strength"] == "34"
        assert out["ladder_height"] == "5"

    def test_stat_failure_tolerated(self):
        """ChangeStatistics 失败不拖垮 RiseFallAnalysis 主读数。"""
        from tradex.data_sources.kpl_fetchers import fetch_kpl_sentiment

        rise = {"errcode": "0",
                "info": [[32, 15, 30, 8, 30.4348, 14, "2026-11-06"]]}
        with patch(
            "tradex.data_sources.kpl_fetchers._kpl_get",
            side_effect=[rise, RuntimeError("情绪指标挂了")],
        ):
            out = fetch_kpl_sentiment()
        assert out["limit_up"] == 32
        assert "strength_error" in out

    def test_empty_info_raises(self):
        from tradex.data_sources.kpl_fetchers import fetch_kpl_sentiment

        with patch(
            "tradex.data_sources.kpl_fetchers._kpl_get",
            side_effect=[{"errcode": "0", "info": []},
                         {"errcode": "0", "info": []}],
        ):
            with pytest.raises(RuntimeError, match="结构异常"):
                fetch_kpl_sentiment()


class TestFetchKplBoards:
    def test_boards_parse(self):
        from tradex.data_sources.kpl_fetchers import fetch_kpl_boards

        payload = {"errcode": "0", "list": [
            ["801070", "光伏", 3680, -1.626, 1.329, 275769881690,
             -857440117, 19458115865, -20315555982, 1.056,
             946019453484, 0, -123, 800000000000, -100],
        ]}
        with patch(
            "tradex.data_sources.kpl_fetchers._kpl_get",
            return_value=payload,
        ) as m_get:
            df = fetch_kpl_boards()
        assert df.iloc[0]["kpl_board_code"] == "801070"
        assert df.iloc[0]["strength"] == 3680
        args = m_get.call_args
        assert args[0][1]["c"] == "ZhiShuRanking"  # 07 交接踩坑：不是 HomeDingPan


class TestFetchKplBidding:
    def test_empty_history_returns_empty(self):
        """历史竞价数据保留期短：info=[] 返回空表不抛错。"""
        from tradex.data_sources.kpl_fetchers import fetch_kpl_bidding

        with patch(
            "tradex.data_sources.kpl_fetchers._kpl_get",
            return_value={"errcode": "0", "info": [], "day": "2026-11-06"},
        ):
            assert fetch_kpl_bidding(date="20261106").empty

    def test_bidding_parse(self):
        from tradex.data_sources.kpl_fetchers import fetch_kpl_bidding

        payload = {"errcode": "0", "info": [
            ["002969", "嘉美包装", 6.07, 9.96, 1381972304, 9.96,
             2222228, 0.16, 4058402, 37199550, 4058402,
             "实控人变更、酿酒", 2547574181, 12878114, 17454281,
             -4576167, "6天4板"],
        ]}
        with patch(
            "tradex.data_sources.kpl_fetchers._kpl_get",
            return_value=payload,
        ):
            df = fetch_kpl_bidding()
        assert df.iloc[0]["code"] == "002969"
        assert df.iloc[0]["bid_buy_amount"] == 1381972304
        assert df.iloc[0]["ladder_tag"] == "6天4板"


@pytest.mark.network
class TestKplNetworkSmoke:
    """真实联网冒烟（pytest -m network 单独跑）。"""

    def test_real_limit_up_history(self):
        from tradex.data_sources.kpl_fetchers import fetch_kpl_limit_up

        df = fetch_kpl_limit_up(date="20261106")
        assert not df.empty
        assert "code" in df.columns and "reason" in df.columns
        # 与 hub 东财口径对账：2026-11-06 涨停 32 家
        assert len(df) >= 25

    def test_real_sentiment(self):
        from tradex.data_sources.kpl_fetchers import fetch_kpl_sentiment

        out = fetch_kpl_sentiment()
        assert out.get("limit_up") == 32  # 2026-11-06 与东财口径一致

    def test_real_boards(self):
        from tradex.data_sources.kpl_fetchers import fetch_kpl_boards

        df = fetch_kpl_boards()
        assert not df.empty
        codes = df["kpl_board_code"].astype(str)
        # 2026-11-07 实测口径：ZSType=7 精选板块混有非 801 代码行（指数类），
        # 断言「存在 801 概念板块」而非「全部为 801」
        assert codes.str.startswith("801").any()
