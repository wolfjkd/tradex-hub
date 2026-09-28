"""
老模块（V0.1/V0.2）测试 — 覆盖导入、签名、基础逻辑。

这些模块深度依赖网络请求，这里用可mock的部分来拉覆盖率。
"""

import pytest
import pandas as pd
from unittest.mock import patch, MagicMock


class TestLockupModule:
    """限售解禁模块测试。"""

    @patch("astock_signals.lockup.em_datacenter")
    def test_get_lockup_expiry_returns_str(self, mock_dc):
        mock_dc.return_value = [
            {"FREE_DATE": "2026-07-01", "LIFT_NUM": 1000000, "LIFT_MARKET_CAP": 5000.0}
        ]
        from astock_signals.lockup import get_lockup_expiry
        result = get_lockup_expiry("600519", "2026-06-24", 90)
        assert "600519" in result

    @patch("astock_signals.lockup.em_datacenter")
    def test_get_lockup_expiry_json(self, mock_dc):
        mock_dc.return_value = []
        from astock_signals.lockup import get_lockup_expiry_json
        result = get_lockup_expiry_json("600519", "2026-06-24", 90)
        assert isinstance(result, dict)
        # lockup uses 'ticker' or 'symbol' as key depending on version
        has_key = any(k in result for k in ("symbol", "ticker", "code", "data", "records", "history"))
        assert has_key, f"Unexpected keys: {list(result.keys())}"


class TestIndicatorsModule:
    """技术指标模块测试。"""

    def test_get_supported_indicators(self):
        from astock_signals.indicators import get_supported_indicators
        indicators = get_supported_indicators()
        assert isinstance(indicators, list)
        assert "macd" in indicators
        assert "rsi" in indicators
        assert len(indicators) >= 10

    def test_get_indicator_description(self):
        from astock_signals.indicators import get_indicator_description
        for ind in ["macd", "rsi", "boll", "atr", "mfi"]:
            desc = get_indicator_description(ind)
            assert isinstance(desc, str)
            assert len(desc) > 0

    def test_get_indicator_description_unknown(self):
        from astock_signals.indicators import get_indicator_description
        desc = get_indicator_description("unknown_indicator")
        assert isinstance(desc, str)


class TestNorthboundModule:
    """北向资金模块测试（仅测导入）。"""

    def test_import(self):
        from astock_signals.northbound import get_northbound_flow, get_northbound_flow_json
        assert callable(get_northbound_flow)
        assert callable(get_northbound_flow_json)


class TestAntiBanClient:
    """防封客户端基础测试。"""

    def test_set_min_interval(self):
        from astock_signals.anti_ban_client import set_min_interval
        set_min_interval(2.0)
        set_min_interval(0.5)

    def test_em_reset_session(self):
        from astock_signals.anti_ban_client import em_reset_session
        em_reset_session()

    def test_imports(self):
        from astock_signals.anti_ban_client import (
            em_get, em_datacenter, em_push2,
            em_push2_fund_flow, em_push2his_fund_flow,
        )
        assert callable(em_get)
        assert callable(em_datacenter)
        assert callable(em_push2)
        assert callable(em_push2_fund_flow)
        assert callable(em_push2his_fund_flow)


class TestHotMoneyModule:
    """涨停归因模块测试（仅测导入）。"""

    def test_import(self):
        from astock_signals.hot_money import get_hot_stocks, get_hot_stocks_json
        assert callable(get_hot_stocks)
        assert callable(get_hot_stocks_json)
