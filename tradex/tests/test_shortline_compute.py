"""工单 H2 测试（一）：四池读数口径（纯函数，不联网）。

所有断言都对着一份手算样本，口径一旦被改就会红。
"""

from __future__ import annotations

import pytest

from tradex.shortline import compute
from tradex.shortline.compute import PoolSnapshot


def _snapshot(missing=()):
    zt = [
        {"code": "600519", "name": "贵州茅台", "consecutive_days": 1, "change_pct": 10.0,
         "latest_price": 1452.0, "deal_amount": 6_752_970_915.0, "turnover_rate": 1.0,
         "sealed_capital": 1_000_000_000, "first_seal_time": "09:35", "break_count": 0,
         "industry": "白酒"},
        {"code": "300750", "name": "宁德时代", "consecutive_days": 2, "change_pct": 20.0,
         "latest_price": 264.06, "deal_amount": 1_840_000_000, "turnover_rate": 2.0,
         "sealed_capital": 500_000_000, "first_seal_time": "10:20", "break_count": 1,
         "industry": "电池"},
        {"code": "002384", "name": "东山精密", "consecutive_days": 3, "change_pct": 10.0,
         "latest_price": 89.1, "deal_amount": 1_596_000_000, "turnover_rate": 3.0,
         "sealed_capital": 200_000_000, "first_seal_time": "13:10", "break_count": 2,
         "industry": "元件"},
    ]
    prev_zt = [
        {"code": "600519", "name": "贵州茅台", "consecutive_days": 1, "change_pct": 5.0},
        {"code": "300750", "name": "宁德时代", "consecutive_days": 1, "change_pct": 2.0},
        {"code": "002384", "name": "东山精密", "consecutive_days": 1, "change_pct": 9.0},
        {"code": "000001", "name": "平安银行", "consecutive_days": 2, "change_pct": -1.0},
        {"code": "601398", "name": "工商银行", "consecutive_days": 3, "change_pct": -3.0},
    ]
    zb = [
        {"code": "600000", "name": "浦发银行", "consecutive_days": 1, "change_pct": 5.0},
        {"code": "000002", "name": "万科A", "consecutive_days": 1, "change_pct": 3.0},
    ]
    dt = [{"code": "600111", "name": "北方稀土", "consecutive_days": 1, "change_pct": -10.0}]
    fields = {
        "zt": ["代码", "名称", "涨跌幅", "最新价", "成交额", "封板资金"],
        "zb": ["代码", "名称", "涨跌幅", "开板次数"],
        "dt": ["代码", "名称", "涨跌幅"],
        "prev_zt": ["代码", "名称", "涨跌幅", "昨日连板数"],
    }
    return PoolSnapshot(
        date="20261105",
        zt=zt,
        zb=[] if "zb" in missing else zb,
        dt=[] if "dt" in missing else dt,
        prev_zt=[] if "prev_zt" in missing else prev_zt,
        fields=fields,
        missing=list(missing),
    )


class TestEmotion:
    def test_four_metrics(self):
        result, text = compute.emotion(_snapshot())
        # 赚钱效应：5 只里 3 只上涨 = 60%
        assert result["money_effect"]["up_ratio"] == 60.0
        assert result["money_effect"]["up_count"] == 3
        # 晋级率：昨日 5 只中 3 只今日仍涨停
        assert result["promoted"] == 3
        assert result["promotion_rate"] == 60.0
        # 连板溢价：连板均 (-1 + -3)/2 = -2；首板均 (5+2+9)/3 = 5.33 → -7.33
        assert result["premium"]["lianban_avg"] == -2.0
        assert result["premium"]["first_avg"] == 5.33
        assert result["premium"]["diff"] == -7.33
        # 梯队 1/2/3 层齐全，无断层
        assert result["ladder_gap"]["max_board"] == 3
        assert result["ladder_gap"]["gaps"] == []

    def test_ladder_gap_detected(self):
        snap = _snapshot()
        snap.zt = [r for r in snap.zt if r["consecutive_days"] != 2]
        result, _ = compute.emotion(snap)
        assert result["ladder_gap"]["gaps"] == [2]

    def test_missing_prev_pool_not_zero(self):
        result, text = compute.emotion(_snapshot(missing=("prev_zt",)))
        assert result["money_effect"]["up_ratio"] is None
        assert result["promotion_rate"] is None
        assert result["premium"] is None
        assert result["missing_reason"]

    def test_promotion_tiers(self):
        result, text = compute.emotion(_snapshot())
        tiers = {t["tier"]: t for t in result["promotion_tiers"]}
        # 手算样本：昨日 3 首板全晋级、1 只 2 板未晋级、1 只 3 板未晋级
        assert tiers["1进2"] == {"tier": "1进2", "base": 3, "promoted": 3, "rate": 100.0}
        assert tiers["2进3"]["base"] == 1
        assert tiers["2进3"]["promoted"] == 0
        assert tiers["2进3"]["rate"] == 0.0
        assert tiers["3板以上"]["base"] == 1
        assert tiers["3板以上"]["promoted"] == 0
        # 对账恒等式：各档加总 = 整体
        assert sum(t["base"] for t in tiers.values()) == 5
        assert sum(t["promoted"] for t in tiers.values()) == 3
        assert "1进2 3/3" in text

    def test_promotion_tiers_missing_prev(self):
        result, _ = compute.emotion(_snapshot(missing=("prev_zt",)))
        assert result["promotion_tiers"] is None

    def test_promotion_tiers_unknown_board(self):
        snap = _snapshot()
        snap.prev_zt.append({"code": "999999", "name": "缺板位", "change_pct": 1.0})
        result, _ = compute.emotion(snap)
        tiers = {t["tier"]: t for t in result["promotion_tiers"]}
        assert "板位未知" in tiers
        assert tiers["板位未知"]["base"] == 1
        # 有缺板位票时恒等式仍成立（不虚增、不丢失）
        assert sum(t["base"] for t in result["promotion_tiers"]) == 6
        assert sum(t["promoted"] for t in result["promotion_tiers"]) == 3


class TestDaily:
    def test_daily_readings(self):
        result, _ = compute.daily(_snapshot())
        assert result["limit_up_count"] == 3
        assert result["max_board"] == 3
        assert result["broken_count"] == 2
        assert result["break_rate"] == 40.0  # 2 / (3+2) * 100
        assert result["prev_zt_median"] == 2.0  # [5,2,9,-1,-3] 中位
        assert result["first_to_second"] == {"prev_first": 3, "advanced": 3, "ratio": 100.0}

    def test_missing_zb(self):
        result, _ = compute.daily(_snapshot(missing=("zb",)))
        assert result["broken_count"] is None
        assert result["break_rate"] is None
        assert "zb" in "".join(result["missing_reason"])


class TestSettled:
    def test_sorted_and_stats(self):
        result, text = compute.settled(_snapshot())
        assert result["count"] == 5
        assert [s["code"] for s in result["stocks"]] == [
            "002384", "600519", "300750", "000001", "601398",
        ]
        assert result["stats"] == {"up": 3, "down": 2, "median": 2.0}

    def test_missing_prev(self):
        result, text = compute.settled(_snapshot(missing=("prev_zt",)))
        assert result["count"] == 0
        assert result["stocks"] == []
        assert result["missing_reason"]
        assert "—" in text


class TestLive:
    def test_counts_and_seal_rate(self):
        result, _ = compute.live(_snapshot())
        assert result["limit_up"] == 3
        assert result["broken"] == 2
        assert result["limit_down"] == 1
        assert result["seal_rate"] == 60.0
        assert result["first_to_second"]["ratio"] == 100.0


class TestLadder:
    def test_levels_desc(self):
        result, _ = compute.ladder(_snapshot())
        assert [lv["level"] for lv in result["levels"]] == [3, 2, 1]
        assert result["levels"][0]["count"] == 1
        assert result["levels"][2]["count"] == 3

    def test_missing_prev(self):
        result, _ = compute.ladder(_snapshot(missing=("prev_zt",)))
        assert result["levels"] == []


class TestBoardLadder:
    def test_missed_fate(self):
        result, _ = compute.board_ladder(_snapshot())
        assert [lv["level"] for lv in result["levels"]] == [3, 2, 1]
        missed = {(m["code"], m["fate"]) for m in result["missed"]}
        assert ("000001", "走弱") in missed   # 昨 2 板，今日 -1%
        assert ("601398", "走弱") in missed   # 昨 3 板，今日 -3%
        assert len(result["missed"]) == 2

    def test_no_missed_when_all_promote(self):
        snap = _snapshot()
        snap.prev_zt = [r for r in snap.prev_zt if r["code"] in {"600519", "300750", "002384"}]
        result, _ = compute.board_ladder(snap)
        assert result["missed"] == []


class TestStructure:
    def test_board_ratios_and_fields(self):
        result, _ = compute.structure(_snapshot())
        assert result["limit_up_count"] == 3
        assert result["boards"]["主板"]["count"] == 2
        assert result["boards"]["主板"]["ratio"] == 66.67
        assert result["boards"]["创业板"]["count"] == 1
        assert result["streak"]["first_board"] == 1
        assert result["streak"]["lianban"] == 2
        assert result["upstream_fields"]["zt"][0] == "代码"
        assert result["missing_reason"] is None

    def test_missing_pool_reported(self):
        result, _ = compute.structure(_snapshot(missing=("dt",)))
        assert result["missing_reason"]


class TestCycle:
    def test_without_history_marks_missing(self):
        result, text = compute.cycle(_snapshot(), days=5, history=None)
        assert result["missing_reason"]
        assert result["window_days"] == 1
        assert result["metrics"]["limit_up_count"]["value"] == 3

    def test_percentile_with_history(self):
        history = [
            {"date": "20261030", "limit_up_count": 10, "max_board": 2, "break_rate": 20.0},
            {"date": "20261102", "limit_up_count": 20, "max_board": 4, "break_rate": 30.0},
            {"date": "20261103", "limit_up_count": 30, "max_board": 5, "break_rate": 40.0},
        ]
        result, _ = compute.cycle(_snapshot(), days=5, history=history)
        assert result["window_days"] == 4
        # 今日涨停 3 低于窗口内全部 3 个历史值 → 1/4 = 25%
        assert result["metrics"]["limit_up_count"]["percentile"] == 25.0
        assert result["composite_percentile"] is not None

    def test_missing_dates_reported(self):
        result, _ = compute.cycle(_snapshot(), days=5, history=[], missing_dates=["20261104"])
        assert result["missing_dates"] == ["20261104"]
        assert any("窗口缺" in item for item in result["missing_reason"])
