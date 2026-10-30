"""KNOWN-ISSUES-2026-10-25 修复回归测试。

覆盖专项重构 P0 四张工单：
  01 指数代码不再静默错取个股
  02 K 线工具尊重 start_date / end_date
  03 估值指标不再崩溃、不静默返回空值
  04 序列化护栏统一收口

全部为离线单测：SmartRouter 用 monkeypatch 打桩，不打外部接口。
"""

import json
from datetime import date
from unittest.mock import MagicMock

import pandas as pd
import pytest


def _mock_router(df):
    """创建 mock SmartRouter，route() 返回 (df, 'test_source')。"""
    mock = MagicMock()
    mock.route.return_value = (df, "test_source")
    return mock


# ══════════════════════════════════════════════════════════════════
# 04 序列化护栏
# ══════════════════════════════════════════════════════════════════

class TestSerializationGuard:
    """任何工具出口都必须能 json.dumps 成功。"""

    def test_timestamp_becomes_string(self):
        from tradex.utils.formatter import df_to_records

        df = pd.DataFrame([
            {"标题": "a", "发布时间": pd.Timestamp("2026-10-30 19:42:00")},
            {"标题": "b", "发布时间": pd.Timestamp("2026-10-30 19:43:00")},
        ])
        records = df_to_records(df)

        assert all(isinstance(r["发布时间"], str) for r in records)
        # 不抛 TypeError: Object of type Timestamp is not JSON serializable
        json.dumps(records, ensure_ascii=False)

    def test_datetime_date_becomes_string(self):
        from tradex.utils.formatter import df_to_records

        df = pd.DataFrame([{"日期": date(2026, 10, 30), "值": 1.0}])
        records = df_to_records(df)

        assert records[0]["日期"] == "2026-10-30"
        json.dumps(records, ensure_ascii=False)

    def test_nat_and_nan_become_none(self):
        from tradex.utils.formatter import df_to_records

        df = pd.DataFrame([{"日期": pd.NaT, "值": float("nan")}])
        records = df_to_records(df)

        assert records[0]["日期"] is None
        assert records[0]["值"] is None
        # 不允许出现裸 NaN（RFC 8259 非法）
        assert "NaN" not in json.dumps(records, ensure_ascii=False)

    def test_to_json_safe_handles_nested_mixed(self):
        from tradex.utils.formatter import to_json_safe

        payload = {
            "bars": [{"日期": pd.Timestamp("2026-10-30"), "量": 1}],
            "extra": {"when": date(2026, 1, 2)},
            "empty": pd.NaT,
        }
        text = to_json_safe(payload)
        parsed = json.loads(text)

        assert parsed["bars"][0]["日期"].startswith("2026-10-30")
        assert parsed["extra"]["when"] == "2026-01-02"
        assert parsed["empty"] is None

    def test_dict_to_json_uses_safe_path(self):
        from tradex.utils.formatter import dict_to_json

        text = dict_to_json({"ts": pd.Timestamp("2026-10-30 10:00")})
        assert json.loads(text)["ts"].startswith("2026-10-30")

    def test_search_news_records_survive_mixed_sources(self):
        """真实事故复现：#3 期货子源的 Timestamp 与财联社的 str 混列。"""
        from tradex.utils.formatter import df_to_records, to_json_safe

        combined = pd.concat(
            [
                pd.DataFrame([{"标题": "快讯", "发布时间": "19:39:56"}]),
                pd.DataFrame([{"标题": "期货", "发布时间": pd.Timestamp("2026-10-30 19:42")}]),
            ],
            ignore_index=True,
        )
        records = df_to_records(combined)

        # 修复前这里抛 Object of type Timestamp is not JSON serializable
        text = to_json_safe({"news": records})
        assert len(json.loads(text)["news"]) == 2


# ══════════════════════════════════════════════════════════════════
# 01 指数代码路由
# ══════════════════════════════════════════════════════════════════

class TestIndexCodeRouting:
    """指数必须带前缀路由，个股行为不变。"""

    @pytest.mark.parametrize(
        "raw,expected_code",
        [
            ("sh000001", "sh000001"),
            ("sz399001", "sz399001"),
            ("sz399006", "sz399006"),
            ("sh000300", "sh000300"),
            ("000300", "sh000300"),   # 与个股不撞号的裸指数码
            ("399006", "sz399006"),
        ],
    )
    def test_index_keeps_prefix(self, raw, expected_code):
        from tradex.service.price_service import _resolve_symbol

        code, is_index = _resolve_symbol(raw)
        assert code == expected_code
        assert is_index is True

    @pytest.mark.parametrize(
        "raw,expected_code",
        [("000001", "000001"), ("600170", "600170"), ("sh600519", "600519")],
    )
    def test_stock_still_bare(self, raw, expected_code):
        from tradex.service.price_service import _resolve_symbol

        code, is_index = _resolve_symbol(raw)
        assert code == expected_code
        assert is_index is False

    def test_historical_price_marks_index_and_routes_prefixed(self, monkeypatch):
        from tradex.service import price_service
        from tradex.utils.cache import cache

        cache.clear()
        df = pd.DataFrame([
            {"日期": pd.Timestamp("2026-10-23"), "开盘": 3694.12, "收盘": 3690.48},
            {"日期": pd.Timestamp("2026-10-30"), "开盘": 3671.00, "收盘": 3599.02},
        ])
        router = _mock_router(df)
        monkeypatch.setattr(price_service, "_router", router)

        result = price_service.get_historical_price("sh000001", period="weekly")

        sent = router.route.call_args.kwargs
        assert sent["symbol"] == "sh000001", "指数代码必须带前缀送进路由"
        assert result["is_index"] is True
        assert result["symbol"] == "sh000001"
        assert result["bars"][-1]["收盘"] == 3599.02


# ══════════════════════════════════════════════════════════════════
# 02 K 线日期区间
# ══════════════════════════════════════════════════════════════════

class TestKlineDateRange:
    def test_parse_date_accepts_two_formats(self):
        from tradex.service.price_service import _parse_date

        assert _parse_date("20261030", "d") == date(2026, 10, 30)
        assert _parse_date("2026-10-30", "d") == date(2026, 10, 30)
        assert _parse_date("", "d") is None

    def test_parse_date_rejects_garbage(self):
        from tradex.service.price_service import _parse_date

        with pytest.raises(ValueError):
            _parse_date("2026/10/30", "start_date")

    def test_reversed_range_raises(self):
        from tradex.service.price_service import get_historical_price

        with pytest.raises(ValueError, match="不能晚于"):
            get_historical_price("600170", start_date="20260102", end_date="20260101")

    def test_filter_keeps_only_range(self):
        from tradex.service.price_service import _filter_by_date

        df = pd.DataFrame({
            "日期": pd.to_datetime(["2026-09-01", "2026-10-15", "2026-10-30"]),
            "收盘": [1.0, 2.0, 3.0],
        })
        out = _filter_by_date(df, date(2026, 10, 1), date(2026, 10, 20))

        assert len(out) == 1
        assert out.iloc[0]["收盘"] == 2.0

    def test_start_date_trims_result(self, monkeypatch):
        """端到端：传 start_date 后返回根数与区间都要真实收缩。"""
        from tradex.service import price_service
        from tradex.utils.cache import cache

        cache.clear()
        df = pd.DataFrame({
            "日期": pd.to_datetime(
                ["2026-06-01", "2026-08-01", "2026-10-15", "2026-10-30"]
            ),
            "开盘": [1.0, 2.0, 3.0, 4.0],
            "收盘": [1.1, 2.1, 3.1, 4.1],
        })
        router = _mock_router(df)
        monkeypatch.setattr(price_service, "_router", router)

        result = price_service.get_historical_price("600170", start_date="20261001")

        assert result["bar_count"] == 2
        assert result["bars"][0]["日期"] == "2026-10-15"
        # 必须向数据源多要根数，否则主源的 count=100 覆盖不到目标区间
        assert router.route.call_args.kwargs["count"] > 0

    def test_empty_range_raises_not_silent(self, monkeypatch):
        from tradex.service import price_service
        from tradex.utils.cache import cache

        cache.clear()
        df = pd.DataFrame({
            "日期": pd.to_datetime(["2026-06-01"]),
            "开盘": [1.0],
            "收盘": [1.1],
        })
        monkeypatch.setattr(price_service, "_router", _mock_router(df))

        with pytest.raises(ValueError, match="区间内无 K 线"):
            price_service.get_historical_price("600170", start_date="20261001")


# ══════════════════════════════════════════════════════════════════
# 03 估值指标
# ══════════════════════════════════════════════════════════════════

class TestValuationMetrics:
    def test_rejects_unrelated_two_column_structure(self):
        """eltdx 备源那种 (num, total_num) 不得被当成估值表。"""
        from tradex.tools.valuation import _pick_date_and_value

        df = pd.DataFrame([{"num": "1", "total_num": "2"}])
        assert _pick_date_and_value(df) == (None, None)

    def test_rejects_multi_value_columns(self):
        from tradex.tools.valuation import _pick_date_and_value

        df = pd.DataFrame([{"date": "2026-10-30", "a": 1, "b": 2}])
        assert _pick_date_and_value(df) == (None, None)

    def test_accepts_regular_structure(self):
        from tradex.tools.valuation import _pick_date_and_value

        df = pd.DataFrame([{"date": pd.Timestamp("2026-10-30"), "value": 12.5}])
        assert _pick_date_and_value(df) == ("date", "value")

    def test_supported_indicators_exclude_pushi(self):
        """市销率不在百度支持集内——请求它就是崩溃起点。"""
        from tradex.tools.valuation import _BAIDU_INDICATORS

        assert "市销率(TTM)" not in _BAIDU_INDICATORS
        assert "市盈率(TTM)" in _BAIDU_INDICATORS
        assert "市净率" in _BAIDU_INDICATORS

    async def test_merge_no_longer_crashes(self, monkeypatch):
        """模拟真实事故：多指标日期类型差异不再导致排序崩溃。"""
        from tradex.tools import valuation
        from tradex.utils.cache import cache
        from mcp.server.fastmcp import FastMCP

        cache.clear()
        frames = {
            "总市值": pd.DataFrame([
                {"date": date(2026, 10, 29), "value": 100.0},
                {"date": date(2026, 10, 30), "value": 101.0},
            ]),
            "市盈率(TTM)": pd.DataFrame([
                {"date": "2026-10-29", "value": 8.0},      # 字符串日期
                {"date": "2026-10-30", "value": 8.1},
            ]),
        }

        class _Router:
            def route(self, route_type, **kwargs):
                ind = kwargs.get("indicator")
                if ind in frames:
                    return frames[ind], "akshare"
                raise RuntimeError(f"no data for {ind}")

        monkeypatch.setattr(valuation, "_router", _Router())

        mcp = FastMCP("test-valuation")
        valuation.register(mcp)
        tool = mcp._tool_manager._tools["get_valuation_metrics"]

        text = await tool.fn(symbol="600170", num_periods=10)
        parsed = json.loads(text)

        assert isinstance(parsed, list)
        assert len(parsed) == 2
        assert parsed[0]["date"] == "2026-10-30"   # 降序
        assert parsed[0]["总市值"] == 101.0


# ══════════════════════════════════════════════════════════════════
# 11 财务指标「最近 N 期」
# ══════════════════════════════════════════════════════════════════

class TestFinancialPeriodOrder:
    def test_returns_latest_not_earliest(self):
        """数据源按报告期升序，head(n) 拿到的是三十年前的数据。"""
        from tradex.service.financial_service import _latest_periods

        df = pd.DataFrame({
            "日期": pd.to_datetime([f"{y}-12-31" for y in range(2015, 2025)]),
            "净资产收益率(%)": list(range(10)),
        })
        out = _latest_periods(df, 2)

        assert len(out) == 2
        assert out.iloc[0]["日期"].year == 2024   # 最新在前
        assert out.iloc[1]["日期"].year == 2023

    def test_zero_periods_returns_all_desc(self):
        from tradex.service.financial_service import _latest_periods

        df = pd.DataFrame({
            "日期": pd.to_datetime(["2023-12-31", "2024-12-31"]),
            "值": [1, 2],
        })
        out = _latest_periods(df, 0)

        assert len(out) == 2
        assert out.iloc[0]["日期"].year == 2024

    def test_without_date_column_falls_back(self):
        from tradex.service.financial_service import _latest_periods

        df = pd.DataFrame({"值": [1, 2, 3]})
        out = _latest_periods(df, 2)

        assert len(out) == 2


# ══════════════════════════════════════════════════════════════════
# 05 交易日历备源
# ══════════════════════════════════════════════════════════════════

class TestTradingCalendarFallback:
    def test_builds_month_from_sina(self):
        """深交所接口 404 后，sina 清单要能独立撑起整月日历。"""
        from unittest.mock import patch

        from tradex.data_sources.akshare_fetchers import fetch_trading_calendar

        sina = pd.DataFrame({
            "trade_date": pd.to_datetime(
                ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08",
                 "2026-01-09", "2026-01-30"]
            )
        })
        with patch("akshare.tool_trade_date_hist_sina", return_value=sina):
            df = fetch_trading_calendar(year=2026, month=1)

        assert len(df) == 31                      # 整月每一天都在
        assert list(df.columns) == ["日期", "是否交易日", "节假日"]
        marked = set(df[df["是否交易日"] == "是"]["日期"])
        assert marked == {
            "2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08",
            "2026-01-09", "2026-01-30",
        }
        # 周末要标出来，别让调用方以为是休市日
        weekend = df[df["日期"] == "2026-01-03"].iloc[0]
        assert weekend["是否交易日"] == "否"
        assert weekend["节假日"] == "周末"
        # 元旦假期是工作日但非交易日 → 标休市
        holiday = df[df["日期"] == "2026-01-01"].iloc[0]
        assert holiday["是否交易日"] == "否"
        assert holiday["节假日"] == "休市"

    def test_month_beyond_coverage_raises(self):
        """sina 清单没覆盖到的月份必须报错，不能返回一张全「否」的假日历。"""
        from unittest.mock import patch

        from tradex.data_sources.akshare_fetchers import fetch_trading_calendar

        sina = pd.DataFrame({"trade_date": pd.to_datetime(["2026-01-05"])})
        with patch("akshare.tool_trade_date_hist_sina", return_value=sina):
            with pytest.raises(RuntimeError, match="仅覆盖到"):
                fetch_trading_calendar(year=2026, month=6)

    def test_empty_source_raises(self):
        from unittest.mock import patch

        from tradex.data_sources.akshare_fetchers import fetch_trading_calendar

        with patch("akshare.tool_trade_date_hist_sina", return_value=pd.DataFrame()):
            with pytest.raises(RuntimeError, match="返回空"):
                fetch_trading_calendar(year=2026, month=1)


# ══════════════════════════════════════════════════════════════════
# 06 打板情绪 schema
# ══════════════════════════════════════════════════════════════════

class TestBoardSentiment:
    def _rows(self, codes, days=1, pct=10.0, industry="银行"):
        return [
            {"code": c, "name": c, "change_pct": pct, "latest_price": 10.0,
             "deal_amount": 0, "float_mv": 0, "total_mv": 0, "turnover_rate": 0,
             "sealed_capital": 0, "first_seal_time": "", "last_seal_time": "",
             "break_count": 0, "limit_up_stats": "", "consecutive_days": days,
             "industry": industry, "source": "test"}
            for c in codes
        ]

    def test_envelope_has_data_key(self, monkeypatch):
        """工具层读 result['data']，fetcher 必须给信封而不是裸 list。"""
        from tradex.data_sources import akshare_fetchers as akf

        monkeypatch.setattr(
            akf, "_fetch_pool_rows", lambda bt, d: self._rows(["000001", "000002"])
        )
        out = akf.fetch_limit_up_board(board_type="zt", date="20261030")

        assert out["board_type"] == "zt"
        assert out["date"] == "20261030"
        assert out["count"] == 2
        assert out["data"][0]["code"] == "000001"

    def test_sentiment_computes_rates(self, monkeypatch):
        from tradex.data_sources import akshare_fetchers as akf

        pools = {
            "zt": self._rows(["000001", "000002", "000003"], days=2),
            "zb": self._rows(["000004"]),
            "dt": self._rows(["000005"]),
            "prev_zt": self._rows(["000001", "000009"], days=1, pct=-2.0),
        }
        monkeypatch.setattr(akf, "_fetch_pool_rows", lambda bt, d: pools[bt])
        out = akf.fetch_board_sentiment(date="20261030")

        assert out["涨停数"] == 3
        assert out["炸板数"] == 1
        assert out["跌停数"] == 1
        assert out["炸板率(%)"] == 25.0            # 1/(3+1)
        assert out["连板梯队"] == {"2连板": 3}
        assert out["最高连板"] == 2
        assert out["晋级数"] == 1                  # 000001 晋级
        assert out["晋级率(%)"] == 50.0            # 1/2
        assert out["平均溢价(%)"] == -2.0
        assert out["missing_pools"] == []

    def test_aux_pool_failure_degrades_not_fatal(self, monkeypatch):
        """辅助池挂了要降级并标注，不能把整条情绪链路拖死。"""
        from tradex.data_sources import akshare_fetchers as akf

        def fake(bt, d):
            if bt == "zt":
                return self._rows(["000001"])
            raise RuntimeError("boom")

        monkeypatch.setattr(akf, "_fetch_pool_rows", fake)
        out = akf.fetch_board_sentiment(date="20261030")

        assert out["涨停数"] == 1
        assert set(out["missing_pools"]) == {"zb", "dt", "prev_zt"}
        assert out["炸板率(%)"] is None            # 缺数据标 null，不填 0 冒充

    def test_empty_zt_pool_raises(self, monkeypatch):
        from tradex.data_sources import akshare_fetchers as akf

        monkeypatch.setattr(akf, "_fetch_pool_rows", lambda bt, d: [])
        with pytest.raises(RuntimeError, match="涨停池为空"):
            akf.fetch_board_sentiment(date="20261030")

    def test_unknown_board_type_raises(self):
        from tradex.data_sources import akshare_fetchers as akf

        with pytest.raises(ValueError, match="未知 board_type"):
            akf.fetch_limit_up_board(board_type="xxx", date="20261030")


# ══════════════════════════════════════════════════════════════════
# 10 新闻聚合瘦身
# ══════════════════════════════════════════════════════════════════

class TestNewsAggregationSlim:
    def test_output_has_exactly_five_fields(self):
        from tradex.service.news_service import _unify_news_record

        raw = {
            "标题": "某标题", "内容": "正文", "文章来源": "财联社",
            "新闻链接": "https://x", "发布日期": "2026-10-30",
            "发布时间": "19:39:56",
            # 源表其余几十列
            "停牌时间": None, "复牌时间": None, "综合热度": None,
        }
        out = _unify_news_record(raw)

        assert list(out) == ["标题", "时间", "来源", "链接", "摘要"]
        assert out["时间"] == "2026-10-30 19:39:56"

    def test_aliases_cover_sina_shape(self):
        """新浪源把标题放在「新闻标题」、时间放在「发布时间」。"""
        from tradex.service.news_service import _unify_news_record

        out = _unify_news_record({
            "标题": None, "新闻标题": "工行房贷贴息",
            "新闻链接": "https://a", "发布时间": "2026-10-30 19:42",
        })

        assert out["标题"] == "工行房贷贴息"
        assert out["链接"] == "https://a"
        assert out["时间"] == "2026-10-30 19:42"

    def test_iso_timestamp_normalized(self):
        from tradex.service.news_service import _unify_news_record

        out = _unify_news_record({"内容": "x", "发布时间": "2026-10-30T20:32:31+08:00"})
        assert out["时间"] == "2026-10-30 20:32:31"

    def test_source_tag_fills_missing_source_field(self):
        from tradex.service.news_service import _SOURCE_TAG_COL, _unify_news_record

        out = _unify_news_record({"标题": "x", _SOURCE_TAG_COL: "cls_telegraph"})
        assert out["来源"] == "cls_telegraph"

    def test_nan_strings_become_empty(self):
        from tradex.service.news_service import _unify_news_record

        out = _unify_news_record({"标题": "nan", "内容": None})
        assert out["标题"] == ""
        assert out["摘要"] == ""
