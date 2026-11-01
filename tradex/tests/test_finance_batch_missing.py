"""工单 05（2026-11-01）测试：批量财务查询的缺失代码策略。

eltdx 3.3.x 批量接口默认 on_missing="raise"，个别代码在主站无数据会让
整批失败。fetch_finance_batch 改用 on_missing="skip"：缺失码跳过 +
WARNING 留痕，其余照常返回；全批无数据仍显式报错。
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from tradex.data_sources import eltdx_fetchers as ef


def _record(code: str, net_profit: float = 1.0) -> SimpleNamespace:
    return SimpleNamespace(
        full_code=code,
        total_shares=1_000_000,
        circulating_shares=800_000,
        total_assets_yuan=9_999.0,
        net_profit_yuan=net_profit,
        eps_raw=0.5,
        industry_raw="测试行业",
        ipo_date="19900101",
    )


class _FakeCorporate:
    """模拟 eltdx corporate.finance_batch（on_missing="skip" 语义）。"""

    def __init__(self, records_by_call):
        self.records_by_call = records_by_call
        self.calls = []

    def finance_batch(self, codes, on_missing="raise"):
        self.calls.append({"codes": list(codes), "on_missing": on_missing})
        assert on_missing == "skip", "必须以 skip 策略调用，否则整批会因缺失失败"
        return SimpleNamespace(records=tuple(self.records_by_call))


class _FakeClient:
    def __init__(self, corporate):
        self.corporate = corporate


@pytest.fixture
def patch_client(monkeypatch):
    def _patch(records):
        corporate = _FakeCorporate(records)
        monkeypatch.setattr(ef, "_get_client", lambda: _FakeClient(corporate))
        return corporate

    return _patch


class TestFinanceBatchMissingPolicy:
    """三场景：全部有效 / 部分缺失 / 全部缺失。"""

    def test_all_valid(self, patch_client):
        records = [_record("600170.SH"), _record("000001.SZ"), _record("601868.SH")]
        corporate = patch_client(records)
        df = ef.fetch_finance_batch("600170,000001,601868")
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 3
        # 必须以 skip 策略下发
        assert corporate.calls[0]["on_missing"] == "skip"

    def test_partial_missing_returns_rest(self, patch_client):
        # 请求 3 只，主站只回 2 只（如 000001 停牌无数据）
        records = [_record("600170.SH"), _record("601868.SH")]
        patch_client(records)
        df = ef.fetch_finance_batch("600170,000001,601868")
        assert len(df) == 2
        assert not df.empty
        # 返回行带「代码」列，调用方可与请求列表 diff 出谁缺了
        assert set(df["代码"]) == {"600170.SH", "601868.SH"}

    def test_all_missing_raises(self, patch_client):
        patch_client([])
        with pytest.raises(RuntimeError, match="no data for all"):
            ef.fetch_finance_batch("600170,000001")

    def test_partial_missing_logs_warning(self, patch_client, caplog):
        import logging

        # 请求 2 只只回 1 只：返回有效部分 + WARNING 留痕缺失码
        records = [_record("600170.SH")]
        patch_client(records)
        with caplog.at_level(logging.WARNING, logger="tradex.eltdx"):
            df = ef.fetch_finance_batch("600170,000001")
        assert len(df) == 1
        assert any("missing" in r.getMessage() for r in caplog.records)
