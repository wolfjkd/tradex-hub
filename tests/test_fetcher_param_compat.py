"""
fetcher 参数归一化回归测试（v3.1.3）。

背景：SmartRouter.route(**kwargs) 原样转发参数，但不同 fetcher 参数名不一致
（eltdx 用 code=，akshare/http 用 symbol=），导致 eltdx 主源永远失败降级。
v3.1.3 修复：所有 fetcher 同时接受 symbol 和 code，内部归一化。

本测试用 mock 隔离网络，专注验证参数归一化逻辑。
"""

import pytest
from unittest.mock import MagicMock, patch


class TestEltdxFetcherParamCompat:
    """eltdx_fetchers 参数归一化测试。"""

    def test_normalize_symbol_code_returns_code_when_symbol_empty(self):
        from tradex.data_sources.eltdx_fetchers import _normalize_symbol_code
        # code 优先
        result = _normalize_symbol_code(symbol="", code="600519")
        assert "600519" in result

    def test_normalize_symbol_code_returns_symbol_when_code_empty(self):
        from tradex.data_sources.eltdx_fetchers import _normalize_symbol_code
        # symbol 兜底
        result = _normalize_symbol_code(symbol="600519", code="")
        assert "600519" in result

    def test_normalize_symbol_code_code_overrides_symbol(self):
        from tradex.data_sources.eltdx_fetchers import _normalize_symbol_code
        # code 优先级高于 symbol
        result = _normalize_symbol_code(symbol="000001", code="600519")
        assert "600519" in result

    def test_normalize_symbol_code_raises_on_empty(self):
        from tradex.data_sources.eltdx_fetchers import _normalize_symbol_code
        with pytest.raises(RuntimeError, match="stock code is required"):
            _normalize_symbol_code(symbol="", code="")

    def test_fetch_realtime_quote_accepts_symbol(self):
        """关键回归：route('realtime_quote', symbol=...) 必须能路由到 eltdx。"""
        from tradex.data_sources import eltdx_fetchers

        # mock client.get_quote() 返回 QuoteSnapshot（v3.1.4 起用 get_quote 替代 bars.get）
        fake_quote = MagicMock()
        fake_quote.code = "600519"
        fake_quote.last_price = 1350.6
        fake_quote.pre_close_price = 1361.76
        fake_quote.open_price = 1330.03
        fake_quote.high_price = 1355.72
        fake_quote.low_price = 1325.77
        fake_quote.change = -11.16
        fake_quote.change_pct = -0.82
        fake_quote.total_hand = 55127
        fake_quote.amount = 7373462528.0
        fake_quote.inside_dish = 28574
        fake_quote.outer_disc = 26554
        fake_quote.current_hand = 677

        with patch.object(eltdx_fetchers, "_get_client") as mock_client:
            mock_client.return_value.get_quote.return_value = [fake_quote]
            # 用 symbol= 调用（工具层 price_data.py 的调用方式）
            df = eltdx_fetchers.fetch_realtime_quote(symbol="600519")
            assert len(df) == 1
            assert df.iloc[0]["代码"] == "600519"
            assert df.iloc[0]["成交量"] == 55127  # total_hand
            assert df.iloc[0]["涨跌幅"] == -0.82  # change_pct（v3.1.4 新增字段）
            # 验证 get_quote 收到的代码非空
            call_args = mock_client.return_value.get_quote.call_args
            assert call_args[0][0]  # norm_code 非空

    def test_fetch_realtime_quote_accepts_code(self):
        """eltdx_data.py 用 code= 调用，必须保持兼容。"""
        from tradex.data_sources import eltdx_fetchers

        fake_quote = MagicMock()
        fake_quote.code = "600519"
        fake_quote.last_price = 10.0
        fake_quote.pre_close_price = 9.8
        fake_quote.open_price = 9.5
        fake_quote.high_price = 10.5
        fake_quote.low_price = 9.0
        fake_quote.change = 0.2
        fake_quote.change_pct = 2.04
        fake_quote.total_hand = 1000
        fake_quote.amount = 100000.0
        fake_quote.inside_dish = 500
        fake_quote.outer_disc = 500
        fake_quote.current_hand = 10

        with patch.object(eltdx_fetchers, "_get_client") as mock_client:
            mock_client.return_value.get_quote.return_value = [fake_quote]
            df = eltdx_fetchers.fetch_realtime_quote(code="600519")
            assert df.iloc[0]["代码"] == "600519"

    def test_fetch_historical_kline_uses_time_field(self):
        """关键回归：KlineBar 字段映射 date→time, volume→volume_lots。"""
        from tradex.data_sources import eltdx_fetchers

        fake_bar = MagicMock()
        fake_bar.time = "2026-07-31"
        fake_bar.open = 1330.0
        fake_bar.high = 1355.0
        fake_bar.low = 1325.0
        fake_bar.close = 1350.6
        fake_bar.volume_lots = 55127.52
        fake_bar.amount = 7373462528.0
        # 旧字段名（确保不被使用）
        fake_bar.date = None
        fake_bar.volume = None
        fake_result = MagicMock()
        fake_result.bars = [fake_bar]

        with patch.object(eltdx_fetchers, "_get_client") as mock_client:
            mock_client.return_value.bars.get.return_value = fake_result
            df = eltdx_fetchers.fetch_historical_kline(symbol="600519", count=1)
            assert df.iloc[0]["日期"] == "2026-07-31"  # 用 time 字段
            assert df.iloc[0]["成交量"] == 55127.52  # 用 volume_lots 字段

    def test_fetch_historical_kline_accepts_code(self):
        from tradex.data_sources import eltdx_fetchers

        fake_bar = MagicMock()
        fake_bar.time = "2026-07-31"
        fake_bar.open = 10.0
        fake_bar.high = 10.5
        fake_bar.low = 9.5
        fake_bar.close = 10.2
        fake_bar.volume_lots = 1000.0
        fake_bar.amount = 100000.0
        fake_result = MagicMock()
        fake_result.bars = [fake_bar]

        with patch.object(eltdx_fetchers, "_get_client") as mock_client:
            mock_client.return_value.bars.get.return_value = fake_result
            df = eltdx_fetchers.fetch_historical_kline(code="600519", count=1)
            assert len(df) == 1


class TestAkshareFetcherParamCompat:
    """akshare_fetchers 参数归一化测试。"""

    def test_fetch_historical_kline_accepts_code(self):
        """关键回归：route('historical_kline', code=...) 必须能路由到 akshare。"""
        from tradex.data_sources import akshare_fetchers

        fake_df = MagicMock()
        fake_df.empty = False
        with patch.object(akshare_fetchers, "_ak") as mock_ak:
            mock_ak.return_value.stock_zh_a_hist.return_value = fake_df
            # 用 code= 调用（eltdx_data.py 的调用方式）
            result = akshare_fetchers.fetch_historical_kline(code="600519")
            # 验证 akshare 收到的 symbol 是 600519
            call_kwargs = mock_ak.return_value.stock_zh_a_hist.call_args[1]
            assert call_kwargs["symbol"] == "600519"

    def test_fetch_historical_kline_symbol_overrides_code(self):
        from tradex.data_sources import akshare_fetchers

        fake_df = MagicMock()
        fake_df.empty = False
        with patch.object(akshare_fetchers, "_ak") as mock_ak:
            mock_ak.return_value.stock_zh_a_hist.return_value = fake_df
            akshare_fetchers.fetch_historical_kline(symbol="600519", code="000001")
            call_kwargs = mock_ak.return_value.stock_zh_a_hist.call_args[1]
            assert call_kwargs["symbol"] == "600519"


class TestHttpFetcherParamCompat:
    """http_fetchers 参数归一化测试。"""

    def test_fetch_realtime_quote_tencent_accepts_code(self):
        """关键回归：route('realtime_quote', code=...) 必须能路由到 tencent。"""
        from tradex.data_sources import http_fetchers

        # 构造 60 个元素的 vals 列表
        fake_vals = ["", "贵州茅台", "1", "1350.6"] + ["0"] * 56
        with patch.object(http_fetchers, "_tencent_quote_vals", return_value=fake_vals):
            df = http_fetchers.fetch_realtime_quote_tencent(code="sh600519")
            assert df.iloc[0]["代码"] == "sh600519"


class TestAstockSignalsFetcherParamCompat:
    """astock_signals_fetchers 参数归一化测试。"""

    def test_fetch_fund_flow_em_accepts_symbol(self):
        """关键回归：route('fund_flow', symbol=...) 必须能路由到 em 主源。"""
        from tradex.data_sources import astock_signals_fetchers

        with patch.object(astock_signals_fetchers, "_as") as mock_as:
            mock_as.return_value.get_fund_flow_json.return_value = {
                "realtime": {"data": 1},
                "history": [],
            }
            # 用 symbol= 调用
            astock_signals_fetchers.fetch_fund_flow_em(symbol="600519")
            # 验证 get_fund_flow_json 收到的 code 是 600519
            call_args = mock_as.return_value.get_fund_flow_json.call_args[0]
            assert call_args[0] == "600519"

    def test_fetch_dragon_tiger_em_accepts_symbol(self):
        from tradex.data_sources import astock_signals_fetchers

        with patch.object(astock_signals_fetchers, "_as") as mock_as:
            mock_as.return_value.get_dragon_tiger_board_json.return_value = {
                "appearances": [{"date": "2026-07-31"}],
                "latest_seats": {"buy": [], "sell": []},
                "institutional": [],
            }
            astock_signals_fetchers.fetch_dragon_tiger_em(symbol="600519")
            call_args = mock_as.return_value.get_dragon_tiger_board_json.call_args[0]
            assert call_args[0] == "600519"

    def test_fetch_etf_data_accepts_code(self):
        from tradex.data_sources import astock_signals_fetchers

        with patch.object(astock_signals_fetchers, "_as") as mock_as:
            mock_as.return_value.get_etf_kline_json.return_value = {"data": []}
            astock_signals_fetchers.fetch_etf_data(code="510300")
            call_args = mock_as.return_value.get_etf_kline_json.call_args[0]
            assert call_args[0] == "510300"

    def test_fetch_hot_money_accepts_symbol(self):
        from tradex.data_sources import astock_signals_fetchers

        with patch.object(astock_signals_fetchers, "_as") as mock_as:
            mock_as.return_value.get_limit_up_insight.return_value = {"data": []}
            astock_signals_fetchers.fetch_hot_money(symbol="600519")
            call_args = mock_as.return_value.get_limit_up_insight.call_args[0]
            assert call_args[0] == "600519"


class TestSmartRouterParamRouting:
    """SmartRouter 端到端参数路由测试（mock fetch_fn）。"""

    def test_route_passes_symbol_to_fetcher_accepting_code(self):
        """关键回归：route(symbol=...) 能调用接受 code= 的 fetcher。

        这是 v3.1.2 之前的 P0 bug：eltdx fetcher 只接受 code=，
        route 传 symbol= 导致 eltdx 主源永远失败。
        """
        from astock_signals.smart_router import SmartRouter

        router = SmartRouter()

        # 模拟一个 fetcher，签名同时接受 symbol 和 code
        def fake_fetcher(symbol="", code="", **kwargs):
            code = code or symbol
            if not code:
                raise RuntimeError("empty code")
            return {"code": code}

        router.register(
            data_type="test_routing",
            source_name="test_source",
            fetch_fn=fake_fetcher,
            priority=100,
        )
        # route 传 symbol=，fetcher 必须能正确解析
        data, src = router.route("test_routing", symbol="600519")
        assert data["code"] == "600519"
        assert src == "test_source"

    def test_route_fallback_when_symbol_only_fetcher_fails(self):
        """route 传 code= 时，symbol-only fetcher 应失败，降级到兼容 fetcher。"""
        from astock_signals.smart_router import SmartRouter

        router = SmartRouter()

        # 主源：只接受 symbol（模拟旧 eltdx_fetchers 行为）
        def legacy_fetcher(symbol="", **kwargs):
            if not symbol:
                raise RuntimeError("legacy: empty symbol")
            return {"src": "legacy"}

        # 备源：同时接受 symbol 和 code
        def compat_fetcher(symbol="", code="", **kwargs):
            sym = symbol or code
            if not sym:
                raise RuntimeError("compat: empty")
            return {"src": "compat", "code": sym}

        router.register("test_fb", "legacy", legacy_fetcher, priority=100)
        router.register("test_fb", "compat", compat_fetcher, priority=200)

        # route 传 code=，主源失败（无 symbol），降级到备源
        data, src = router.route("test_fb", code="600519")
        assert src == "compat"
        assert data["code"] == "600519"
