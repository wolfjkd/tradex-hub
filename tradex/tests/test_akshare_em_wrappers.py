"""akshare_em 包装层测试（2026-09-25 新增）。

老板拍板："AKshare 更新过后，可能东财源有改善。我们就用 akshare 中集成的
东财源，不自己独立开发东财源的接口了。"

验证：
- 8 个 akshare 包装函数（_em 后缀）字段对齐主源 em_datacenter
- 注册关系：em_datacenter priority=1 主源 + akshare_em priority=100 备源
- dt_branch_rank 由 akshare_em 独占（主源 em_datacenter 无对应 report）
- 参数透传（start_date/end_date 兼容 YYYY-MM-DD / YYYYMMDD / None）
- 空数据抛 RuntimeError 而不是静默吞错
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pandas as pd
import pytest


# ============================================================
# 字段对齐主源测试（不真实联网，mock akshare 返回）
# ============================================================

_FAKE_LHB_DETAIL = pd.DataFrame([
    {
        "序号": 1, "代码": "000002", "名称": "万科A",
        "上榜日": "2026-09-22", "解读": "主力做T",
        "收盘价": 3.81, "涨跌幅": 4.38,
        "龙虎榜净买额": 1.2e8, "龙虎榜买入额": 1.0e9, "龙虎榜卖出额": 9.4e8,
        "龙虎榜成交额": 2.0e9, "市场总成交额": 7.4e9,
        "净买额占总成交比": 1.68, "成交额占总成交比": 27.0,
        "换手率": 8.4, "流通市值": 3.7e10,
        "上榜原因": "日涨幅偏离值达7%", "上榜后1日": 2.9, "上榜后2日": -1.3,
        "上榜后5日": None, "上榜后10日": None,
    }
])


class TestDtDetailEm:
    """dt_detail akshare 包装层字段映射。"""

    def test_field_alignment_with_primary(self):
        from tradex.data_sources.akshare_fetchers import fetch_dt_detail_em
        with patch("akshare.stock_lhb_detail_em", return_value=_FAKE_LHB_DETAIL):
            result = fetch_dt_detail_em(start_date="2026-09-20", end_date="2026-09-24")
        assert len(result) == 1
        row = result[0]
        # 字段对齐主源 em_datacenter.fetch_dragon_tiger_detail
        expected_keys = {
            "code", "name", "date", "close", "change_pct",
            "net_buy", "buy_amt", "sell_amt", "deal_amt", "total_amount",
            "net_buy_ratio", "deal_amount_ratio", "turnover_rate",
            "float_market_value", "reason",
            "after_1d", "after_2d", "after_5d", "after_10d",
            "source",
        }
        assert set(row.keys()) == expected_keys, f"字段不一致: 缺 {expected_keys - set(row.keys())}"
        assert row["code"] == "000002"
        assert row["name"] == "万科A"
        assert row["source"] == "AKShare_stock_lhb_detail_em"
        # None 值应转 0.0
        assert row["after_5d"] == 0.0
        assert row["after_10d"] == 0.0

    def test_empty_raises(self):
        from tradex.data_sources.akshare_fetchers import fetch_dt_detail_em
        with patch("akshare.stock_lhb_detail_em", return_value=pd.DataFrame()):
            with pytest.raises(RuntimeError, match="返回空"):
                fetch_dt_detail_em(start_date="2026-09-20", end_date="2026-09-24")


# ============================================================
# 注册关系测试
# ============================================================

@pytest.fixture(autouse=True)
def _ensure_registered():
    from tradex.data_sources import register_all_sources
    register_all_sources()


class TestAkshareEmRegistration:
    """akshare_em 备源注册关系。"""

    @pytest.mark.parametrize("data_type", [
        "dt_detail", "dt_stock_stats", "dt_institution",
        "margin_account_info",
        "block_trade_market_stat", "block_trade_detail", "block_trade_daily_stat",
    ])
    def test_dual_source_registered(self, data_type):
        """这些类型应有 em_datacenter(pri=1) + akshare_em(pri=100) 两个源。"""
        from tradex.data_sources import get_router
        r = get_router()
        sources = r._sources.get(data_type, [])
        src_names = [s[0] for s in sources]
        assert "em_datacenter" in src_names, f"{data_type} 缺 em_datacenter 主源"
        assert "akshare_em" in src_names, f"{data_type} 缺 akshare_em 备源"

    @pytest.mark.parametrize("data_type", [
        "dt_detail", "dt_stock_stats", "dt_institution",
        "margin_account_info",
        "block_trade_market_stat", "block_trade_detail", "block_trade_daily_stat",
    ])
    def test_primary_priority_is_1(self, data_type):
        """em_datacenter 主源 priority=1。"""
        from tradex.data_sources import get_router
        r = get_router()
        sources = r._sources.get(data_type, [])
        em = [s for s in sources if s[0] == "em_datacenter"]
        assert em, f"{data_type} 缺 em_datacenter"
        assert em[0][2] == 1, f"{data_type} em_datacenter 优先级应为 1，实际 {em[0][2]}"

    @pytest.mark.parametrize("data_type", [
        "dt_detail", "dt_stock_stats", "dt_institution",
        "margin_account_info",
        "block_trade_market_stat", "block_trade_detail", "block_trade_daily_stat",
    ])
    def test_backup_priority_is_100(self, data_type):
        """akshare_em 备源 priority=100。"""
        from tradex.data_sources import get_router
        r = get_router()
        sources = r._sources.get(data_type, [])
        ak = [s for s in sources if s[0] == "akshare_em"]
        assert ak, f"{data_type} 缺 akshare_em"
        assert ak[0][2] == 100, f"{data_type} akshare_em 优先级应为 100，实际 {ak[0][2]}"

    def test_dt_branch_rank_akshare_em_exclusive_primary(self):
        """dt_branch_rank 只由 akshare_em 提供（主源 em_datacenter 无对应 report）。"""
        from tradex.data_sources import get_router
        r = get_router()
        sources = r._sources.get("dt_branch_rank", [])
        src_names = [s[0] for s in sources]
        assert "akshare_em" in src_names, "dt_branch_rank 应有 akshare_em 源"
        assert "em_datacenter" not in src_names, "dt_branch_rank 不应有 em_datacenter 源"
        # akshare_em 应是 priority=1（独占主源）
        ak = [s for s in sources if s[0] == "akshare_em"]
        assert ak[0][2] == 1, f"dt_branch_rank akshare_em 优先级应为 1，实际 {ak[0][2]}"

    def test_dt_seat_detail_no_akshare_em(self):
        """dt_seat_detail 不应有 akshare_em（akshare 无对应包装）。"""
        from tradex.data_sources import get_router
        r = get_router()
        sources = r._sources.get("dt_seat_detail", [])
        src_names = [s[0] for s in sources]
        assert "akshare_em" not in src_names
        assert "em_datacenter" in src_names

    def test_margin_target_list_no_akshare_em(self):
        """margin_target_list 不应有 akshare_em。"""
        from tradex.data_sources import get_router
        r = get_router()
        sources = r._sources.get("margin_target_list", [])
        src_names = [s[0] for s in sources]
        assert "akshare_em" not in src_names
        assert "em_datacenter" in src_names


# ============================================================
# 参数透传测试
# ============================================================

class TestDateParamPassthrough:
    """日期参数兼容 YYYY-MM-DD / YYYYMMDD / None。"""

    def test_normalize_yyyymmdd(self):
        from tradex.data_sources.akshare_fetchers import _ak_date_range_kwargs
        s, e = _ak_date_range_kwargs("20260920", "20260924")
        assert s == "20260920"
        assert e == "20260924"

    def test_normalize_yyyy_dash_mm_dd(self):
        from tradex.data_sources.akshare_fetchers import _ak_date_range_kwargs
        s, e = _ak_date_range_kwargs("2026-09-20", "2026-09-24")
        assert s == "20260920"
        assert e == "20260924"

    def test_none_uses_default(self):
        from tradex.data_sources.akshare_fetchers import _ak_date_range_kwargs
        s, e = _ak_date_range_kwargs(None, None, default_days=5)
        # end 应是今天，start 应是 5 天前
        from datetime import datetime, timedelta
        expected_e = datetime.now().strftime("%Y%m%d")
        expected_s = (datetime.now() - timedelta(days=5)).strftime("%Y%m%d")
        assert e == expected_e
        assert s == expected_s


# ============================================================
# dt_branch_rank 字段测试
# ============================================================

_FAKE_YYBPH = pd.DataFrame([{
    "序号": 1, "营业部名称": "机构专用",
    "上榜后1天-买入次数": 325, "上榜后1天-平均涨幅": 0.19, "上榜后1天-上涨概率": 46.5,
    "上榜后2天-买入次数": 313, "上榜后2天-平均涨幅": 0.03, "上榜后2天-上涨概率": 44.1,
    "上榜后3天-买入次数": 301, "上榜后3天-平均涨幅": -0.52, "上榜后3天-上涨概率": 40.2,
    "上榜后5天-买入次数": 276, "上榜后5天-平均涨幅": -1.63, "上榜后5天-上涨概率": 39.1,
    "上榜后10天-买入次数": 194, "上榜后10天-平均涨幅": -5.60, "上榜后10天-上涨概率": 27.8,
}])


class TestDtBranchRankEm:
    """dt_branch_rank akshare 包装层字段映射。"""

    def test_field_alignment(self):
        from tradex.data_sources.akshare_fetchers import fetch_dt_branch_rank_em
        with patch("akshare.stock_lhb_yybph_em", return_value=_FAKE_YYBPH):
            result = fetch_dt_branch_rank_em(period="1month")
        assert len(result) == 1
        row = result[0]
        assert row["branch_name"] == "机构专用"
        assert row["buy_count_1d"] == 325
        assert row["avg_change_1d"] == 0.19
        assert row["win_rate_1d"] == 46.5
        assert row["source"] == "AKShare_stock_lhb_yybph_em"

    def test_invalid_period_raises(self):
        from tradex.data_sources.akshare_fetchers import fetch_dt_branch_rank_em
        with pytest.raises(ValueError, match="period 必须是"):
            fetch_dt_branch_rank_em(period="invalid")

    def test_empty_raises(self):
        from tradex.data_sources.akshare_fetchers import fetch_dt_branch_rank_em
        with patch("akshare.stock_lhb_yybph_em", return_value=pd.DataFrame()):
            with pytest.raises(RuntimeError, match="返回空"):
                fetch_dt_branch_rank_em(period="1month")


# ============================================================
# 涨停板池 fetch_limit_up_board_em 测试（2026-09-26 新增）
# ============================================================

_FAKE_ZT_POOL = pd.DataFrame([
    {
        "序号": 1, "代码": "000498", "名称": "山东路桥",
        "涨跌幅": 9.92, "最新价": 5.65, "成交额": 314302752,
        "流通市值": 8188814951.35, "总市值": 8771297480.80,
        "换手率": 3.84, "封板资金": 59982095,
        "首次封板时间": "092500", "最后封板时间": "093136",
        "炸板次数": 1, "涨停统计": "1/1", "连板数": 1, "所属行业": "基础建设",
    },
    {
        "序号": 2, "代码": "001234", "名称": "泰慕士",
        "涨跌幅": 10.01, "最新价": 35.4, "成交额": 80434535,
        "流通市值": 3240569100.0, "总市值": 3844071840.0,
        "换手率": 2.48, "封板资金": 360840625,
        "首次封板时间": "092500", "最后封板时间": "092500",
        "炸板次数": 0, "涨停统计": "4/4", "连板数": 4, "所属行业": "服装家纺",
    },
])


class TestLimitUpBoardEm:
    """limit_up_board akshare 包装层测试 —— 修复整类型失效后的回归保障。"""

    def test_field_alignment(self):
        """字段映射齐全且类型正确。"""
        from tradex.data_sources.akshare_fetchers import fetch_limit_up_board_em
        with patch("akshare.stock_zt_pool_em", return_value=_FAKE_ZT_POOL):
            result = fetch_limit_up_board_em(date="20260925")
        assert len(result) == 2
        row = result[0]
        # 核心字段断言
        assert row["code"] == "000498"
        assert row["name"] == "山东路桥"
        assert row["change_pct"] == 9.92
        assert row["latest_price"] == 5.65
        assert row["sealed_capital"] == 59982095
        assert row["consecutive_days"] == 1
        assert row["break_count"] == 1
        assert row["industry"] == "基础建设"
        assert row["source"] == "AKShare_stock_zt_pool_em"
        # 类型断言
        assert isinstance(row["change_pct"], float)
        assert isinstance(row["consecutive_days"], int)
        assert isinstance(row["break_count"], int)

    def test_consecutive_days_preserved(self):
        """连板数字段直接来自 akshare（原 SPEC 假设需推断，实测纠正）。"""
        from tradex.data_sources.akshare_fetchers import fetch_limit_up_board_em
        with patch("akshare.stock_zt_pool_em", return_value=_FAKE_ZT_POOL):
            result = fetch_limit_up_board_em(date="20260925")
        # 第二条是 4 连板
        assert result[1]["consecutive_days"] == 4
        assert result[1]["limit_up_stats"] == "4/4"

    def test_code_zero_padded(self):
        """代码补 0 到 6 位（akshare 可能返回 5 位代码）。"""
        from tradex.data_sources.akshare_fetchers import fetch_limit_up_board_em
        df = pd.DataFrame([{"代码": "1234", "名称": "X", "涨跌幅": 0,
                            "最新价": 0, "成交额": 0, "流通市值": 0, "总市值": 0,
                            "换手率": 0, "封板资金": 0, "首次封板时间": "", "最后封板时间": "",
                            "炸板次数": 0, "涨停统计": "", "连板数": 1, "所属行业": ""}])
        with patch("akshare.stock_zt_pool_em", return_value=df):
            result = fetch_limit_up_board_em(date="20260925")
        assert result[0]["code"] == "001234"  # 补 0 到 6 位

    def test_empty_raises_runtime_error(self):
        """空数据不静默吞错，抛 RuntimeError。"""
        from tradex.data_sources.akshare_fetchers import fetch_limit_up_board_em
        with patch("akshare.stock_zt_pool_em", return_value=pd.DataFrame()):
            with pytest.raises(RuntimeError, match="返回空"):
                fetch_limit_up_board_em(date="20260925")

    def test_none_raises_runtime_error(self):
        """akshare 返回 None 同样抛 RuntimeError。"""
        from tradex.data_sources.akshare_fetchers import fetch_limit_up_board_em
        with patch("akshare.stock_zt_pool_em", return_value=None):
            with pytest.raises(RuntimeError, match="返回空"):
                fetch_limit_up_board_em(date="20260925")

    def test_missing_date_raises_value_error(self):
        """date 必填，缺失抛 ValueError。"""
        from tradex.data_sources.akshare_fetchers import fetch_limit_up_board_em
        with pytest.raises(ValueError, match="必须传 date"):
            fetch_limit_up_board_em(date="")

    def test_invalid_date_format_raises_value_error(self):
        """日期格式错误抛 ValueError（YYYYMMDD 8 位数字，去横杠后）。
        
        注意：YYYY-MM-DD 横杠格式是被允许的（自动归一化），不抛错；
        这里只测真正非法的格式。
        """
        from tradex.data_sources.akshare_fetchers import fetch_limit_up_board_em
        for bad in ["2026092", "abc12345", "2026092X", "2026"]:
            with pytest.raises(ValueError, match="date 参数格式错误"):
                fetch_limit_up_board_em(date=bad)

    def test_date_dash_normalized(self):
        """支持 YYYY-MM-DD 输入（自动去掉横杠）。"""
        from tradex.data_sources.akshare_fetchers import fetch_limit_up_board_em
        with patch("akshare.stock_zt_pool_em", return_value=_FAKE_ZT_POOL) as mock_fn:
            fetch_limit_up_board_em(date="2026-09-25")
            # akshare 应被以归一化的 8 位数字调用
            call_args = mock_fn.call_args
            assert call_args.kwargs.get("date") == "20260925" or call_args.args[0] == "20260925"


class TestLimitUpBoardRegistration:
    """limit_up_board 注册关系 —— 必须命中 akshare_em 主源。"""

    def test_route_hits_akshare_em(self):
        """router.route('limit_up_board') 应返回非空数据 + 命中 akshare_em。"""
        from tradex.data_sources.registry import register_all_sources, get_router
        register_all_sources()
        router = get_router()
        with patch("akshare.stock_zt_pool_em", return_value=_FAKE_ZT_POOL):
            data, source = router.route("limit_up_board", date="20260925")
        assert source == "akshare_em"
        assert len(data) == 2
        assert data[0]["code"] == "000498"
