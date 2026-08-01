"""
astock_signals 包导入和版本测试。
"""

import pytest


class TestAstockSignalsInit:
    """astock_signals 包导入测试。"""

    def test_import_version(self):
        import astock_signals
        assert astock_signals.__version__ == "1.1.0"

    def test_import_anti_ban_client(self):
        from astock_signals import em_get, em_datacenter, em_push2
        assert callable(em_get)
        assert callable(em_datacenter)
        assert callable(em_push2)

    def test_import_etf_module(self):
        from astock_signals import get_etf_realtime, get_etf_kline, get_etf_list
        assert callable(get_etf_realtime)
        assert callable(get_etf_kline)
        assert callable(get_etf_list)

    def test_import_cb_module(self):
        from astock_signals import get_cb_realtime, get_cb_value_analysis, get_cb_comparison
        assert callable(get_cb_realtime)
        assert callable(get_cb_value_analysis)
        assert callable(get_cb_comparison)

    def test_import_smart_router(self):
        from astock_signals.smart_router import SmartRouter, get_router
        assert callable(SmartRouter)
        assert callable(get_router)

    def test_import_tick_store(self):
        from astock_signals.tick_store import TickStore, get_tick_store
        assert callable(TickStore)
        assert callable(get_tick_store)

    def test_import_ws_server(self):
        from astock_signals.ws_server import WsServer, get_ws_server
        assert callable(WsServer)
        assert callable(get_ws_server)

    def test_all_exports(self):
        import astock_signals
        exports = astock_signals.__all__
        assert "get_etf_realtime" in exports
        assert "get_cb_realtime" in exports
        assert "get_etf_kline_json" in exports
        assert "get_cb_value_analysis_json" in exports
        assert "get_northbound_flow" in exports
        assert "get_dragon_tiger_board" in exports
