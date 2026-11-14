# -*- coding: utf-8 -*-
"""大智慧365 本地 WS fetcher 测试（协议来源：dzh-queue 破译 + 2026-11-14 IX*.index 新破译）"""

import pytest

from tradex.data_sources.dzh_fetchers import _parse_dyna, fetch_dzh_index_quote

# IXKS11 真实捕获帧（2026-11-14 WS 实测）
_HEAD = ["obj", "time", "avgvolume", "lastclose", "open", "high", "low", "new", "volume", "amount"]
_ROW = ["IXKS11.index", "1794580340", "0.000000", "5342.729980", "5452.410156",
        "5504.439941", "5259.089844", "5290.529785", "237339.000000", "0.000000"]


class TestParseDyna:
    def test_point_and_lastclose(self):
        q = _parse_dyna(_HEAD, _ROW)
        assert q["point"] == pytest.approx(5290.529785)
        assert q["lastclose"] == pytest.approx(5342.729980)

    def test_pct_cross_checked_with_em(self):
        # pct 与东财全球指数表交叉验证一致（-0.98%）
        q = _parse_dyna(_HEAD, _ROW)
        assert q["pct"] == pytest.approx(-0.98)

    def test_global_index_amount_zero(self):
        # 全球指数无成交额 → amount=0（前端隐藏成交额行，不编造）
        q = _parse_dyna(_HEAD, _ROW)
        assert q["amount"] == 0.0

    def test_missing_fields_tolerated(self):
        q = _parse_dyna(["obj", "new"], ["IXKS11.index", "5100.0"])
        assert q["point"] == 5100.0
        assert q["pct"] is None  # 无 lastclose 不算 pct（不编造）
