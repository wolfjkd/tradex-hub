"""扩展数据源测试：龙虎榜扩展族 + 融资融券扩展族 + 大宗交易族（2026-09-25 新增）。

借鉴 chengzuopeng/stock-sdk (ISC license) 的 dragonTiger.ts / margin.ts / blockTrade.ts
全部走 datacenter-web 子域（老板 2026-09-23 批准的 P999 降级源）。

覆盖：
- 字段映射正确性
- 日期归一化（YYYYMMDD / YYYY-MM-DD 都接受）
- 必填参数校验
- 分页安全阀
- 空数据兜底
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _fake_response(records, pages=1):
    resp = MagicMock()
    resp.json.return_value = {
        "result": {"pages": pages, "count": len(records), "data": records}
    }
    resp.raise_for_status.return_value = None
    return resp


def _fake_empty_response():
    resp = MagicMock()
    resp.json.return_value = {"result": None}
    resp.raise_for_status.return_value = None
    return resp


_responses = []


def _em_get_mock(url, params):
    if _responses:
        return _responses.pop(0)
    return _fake_empty_response()


@pytest.fixture(autouse=True)
def _patch_em_get(monkeypatch):
    """patch em_get 避免真实请求；同时记录调用供断言。"""
    from tradex.data_sources import em_client
    calls = []

    def fake_em_get(url, params=None, headers=None, timeout=15, **kwargs):
        calls.append({"url": url, "params": dict(params) if params else {}})
        return _em_get_mock(url, params)

    monkeypatch.setattr(em_client, "em_get", fake_em_get)
    monkeypatch.setattr(em_client, "_test_calls", calls, raising=False)
    yield


@pytest.fixture(autouse=True)
def _clear_responses():
    _responses.clear()
    yield
    _responses.clear()


# ════════════════════════════════════════════════════════════════════
# 龙虎榜扩展族
# ════════════════════════════════════════════════════════════════════

class TestDragonTigerDetail:
    def test_basic_mapping_with_after_change_fields(self):
        from tradex.data_sources import em_client
        _responses.append(_fake_response([{
            "SECURITY_CODE": "000001", "SECURITY_NAME_ABBR": "平安银行",
            "TRADE_DATE": "2026-09-22",
            "CLOSE_PRICE": "11.5", "CHANGE_RATE": "9.95",
            "BILLBOARD_NET_AMT": "100000000", "BILLBOARD_BUY_AMT": "150000000",
            "BILLBOARD_SELL_AMT": "50000000", "BILLBOARD_DEAL_AMT": "200000000",
            "ACCUM_AMOUNT": "5000000000", "DEAL_NET_RATIO": "2.0",
            "DEAL_AMOUNT_RATIO": "4.0", "TURNOVERRATE": "5.5",
            "FREE_MARKET_CAP": "200000000000",
            "EXPLANATION": "日涨幅偏离值达 7%",
            "D1_CLOSE_ADJCHRATE": "5.5", "D2_CLOSE_ADJCHRATE": "8.0",
            "D5_CLOSE_ADJCHRATE": "12.0", "D10_CLOSE_ADJCHRATE": "-3.0",
        }]))
        result = em_client.fetch_dragon_tiger_detail(
            start_date="2026-09-20", end_date="2026-09-25"
        )
        assert len(result) == 1
        r = result[0]
        assert r["code"] == "000001"
        assert r["close"] == 11.5
        assert r["net_buy"] == 100000000.0
        assert r["after_1d"] == 5.5
        assert r["after_5d"] == 12.0
        assert r["after_10d"] == -3.0
        assert "EM_Datacenter" in r["source"]

    def test_filter_uses_iso_dates(self):
        from tradex.data_sources import em_client
        _responses.append(_fake_response([]))
        em_client.fetch_dragon_tiger_detail(
            start_date="20260920", end_date="20260925"
        )
        flt = em_client._test_calls[0]["params"]["filter"]
        assert "2026-09-20" in flt and "2026-09-25" in flt

    def test_empty_returns_empty_list(self):
        from tradex.data_sources import em_client
        _responses.append(_fake_empty_response())
        assert em_client.fetch_dragon_tiger_detail(
            start_date="2026-09-20", end_date="2026-09-25"
        ) == []


class TestDragonTigerStockStats:
    def test_basic_mapping(self):
        from tradex.data_sources import em_client
        _responses.append(_fake_response([{
            "SECURITY_CODE": "600519", "SECURITY_NAME_ABBR": "贵州茅台",
            "LATEST_TDATE": "2026-09-20", "CLOSE_PRICE": "1700",
            "CHANGE_RATE": "5.0", "BILLBOARD_TIMES": "10",
            "BILLBOARD_BUY_AMT": "1000000000", "BILLBOARD_SELL_AMT": "800000000",
            "BILLBOARD_NET_BUY": "200000000", "BILLBOARD_DEAL_AMT": "1800000000",
            "ORG_BUY_TIMES": "5", "ORG_SELL_TIMES": "3",
        }]))
        result = em_client.fetch_dragon_tiger_stock_stats(period="3month")
        assert result[0]["appearances"] == 10
        assert result[0]["total_net"] == 200000000.0

    def test_invalid_period_raises(self):
        from tradex.data_sources import em_client
        with pytest.raises(ValueError, match="period"):
            em_client.fetch_dragon_tiger_stock_stats(period="invalid")

    def test_period_cycle_in_filter(self):
        from tradex.data_sources import em_client
        _responses.append(_fake_response([]))
        em_client.fetch_dragon_tiger_stock_stats(period="1year")
        assert 'STATISTICS_CYCLE="04"' in em_client._test_calls[0]["params"]["filter"]


class TestDragonTigerInstitution:
    def test_basic_mapping(self):
        from tradex.data_sources import em_client
        _responses.append(_fake_response([{
            "SECURITY_CODE": "000001", "SECURITY_NAME_ABBR": "平安银行",
            "TRADE_DATE": "2026-09-22", "CLOSE_PRICE": "11.5",
            "CHANGE_RATE": "9.95", "BUY_TIMES": "3", "SELL_TIMES": "2",
            "BUY_AMT": "50000000", "SELL_AMT": "30000000", "NET_BUY_AMT": "20000000",
        }]))
        result = em_client.fetch_dragon_tiger_institution(
            start_date="2026-09-20", end_date="2026-09-25"
        )
        assert result[0]["buy_org_count"] == 3
        assert result[0]["org_net_amt"] == 20000000.0


class TestDragonTigerSeatDetail:
    def test_basic_buy_sell_merge(self):
        from tradex.data_sources import em_client
        # 买榜和卖榜各占一个响应
        # 上游真实字段是 BUY/SELL/NET（不是 BUY_AMT_REAL/SELL_AMT_REAL/NET_AMT）
        _responses.append(_fake_response([{
            "RANK": "1", "OPERATEDEPT_NAME": "买方营业部A",
            "BUY": "10000000", "SELL": "0",
            "NET": "10000000",
            "TRADE_DATE": "2026-09-22", "CLOSE_PRICE": "11.5",
            "CHANGE_RATE": "9.95", "EXPLANATION": "日涨幅偏离值 7%",
        }]))
        _responses.append(_fake_response([{
            "RANK": "1", "OPERATEDEPT_NAME": "卖方营业部B",
            "BUY": "0", "SELL": "8000000",
            "NET": "-8000000",
            "TRADE_DATE": "2026-09-22", "CLOSE_PRICE": "11.5",
            "CHANGE_RATE": "9.95", "EXPLANATION": "日涨幅偏离值 7%",
        }]))
        result = em_client.fetch_dragon_tiger_seat_detail(
            symbol="600519", date="2026-09-22"
        )
        assert len(result) == 2
        assert result[0]["side"] == "buy"
        assert result[0]["branch_name"] == "买方营业部A"
        assert result[0]["buy_amt"] == 10000000.0
        assert result[0]["net_amt"] == 10000000.0
        assert result[0]["date"] == "2026-09-22"
        assert result[1]["side"] == "sell"

    def test_invalid_symbol_raises(self):
        from tradex.data_sources import em_client
        with pytest.raises(ValueError, match="无法解析"):
            em_client.fetch_dragon_tiger_seat_detail(symbol="abc", date="2026-09-22")

    def test_filter_uses_pure_code_without_trade_date(self):
        """上游不接受组合 filter，必须只用 SECURITY_CODE。"""
        from tradex.data_sources import em_client
        _responses.append(_fake_response([]))
        _responses.append(_fake_response([]))
        em_client.fetch_dragon_tiger_seat_detail(
            symbol="sh600519.SH", date="20260922"
        )
        # 两次调用（买 + 卖）的 filter 都应含 600519 但**不应含** TRADE_DATE
        for call in em_client._test_calls:
            flt = call["params"]["filter"]
            assert "600519" in flt
            assert "TRADE_DATE" not in flt
        # 两次调用（买 + 卖）的 filter 都应含 600519 与归一化日期
        for call in em_client._test_calls:
            flt = call["params"]["filter"]
            assert "600519" in flt
            assert "TRADE_DATE" not in flt


# ════════════════════════════════════════════════════════════════════
# 融资融券扩展族
# ════════════════════════════════════════════════════════════════════

class TestMarginAccountInfo:
    def test_basic_mapping(self):
        from tradex.data_sources import em_client
        _responses.append(_fake_response([{
            "STATISTICS_DATE": "2026-09-24",
            "FIN_BALANCE": "150000000000", "LOAN_BALANCE": "80000000000",
            "FIN_BUY_AMT": "50000000000", "LOAN_SELL_AMT": "30000000000",
            "OPERATE_INVESTOR_NUM": "5000000", "MARGIN_INVESTOR_NUM": "2000000",
            "TOTAL_GUARANTEE": "300000000000", "AVG_GUARANTEE_RATIO": "280.5",
        }]))
        result = em_client.fetch_margin_account_info()
        assert result[0]["fin_balance"] == 1.5e11
        assert result[0]["avg_guarantee_ratio"] == 280.5
        assert result[0]["date"] == "2026-09-24"

    def test_empty_returns_empty(self):
        from tradex.data_sources import em_client
        _responses.append(_fake_empty_response())
        assert em_client.fetch_margin_account_info() == []


class TestMarginTargetList:
    def test_basic_mapping(self):
        from tradex.data_sources import em_client
        _responses.append(_fake_response([{
            "SCODE": "600519", "SECNAME": "贵州茅台",
            "DATE": "2026-09-24", "MARKET": "融资融券_沪证",
            "RZYE": "5000000000", "RZMRE": "1000000000",
            "RZCHE": "800000000", "RZJME": "200000000",
            "RQYE": "200000000", "RQYL": "100000",
            "RQMCL": "50000", "RQJMG": "-5000",
            "RZRQYE": "5200000000",
        }]))
        result = em_client.fetch_margin_target_list()
        r = result[0]
        assert r["code"] == "600519"
        assert r["name"] == "贵州茅台"
        assert r["fin_balance"] == 5e9
        assert r["fin_net_amt"] == 2e8
        assert r["total_balance"] == 5.2e9
        assert r["market"] == "融资融券_沪证"

    def test_date_filter_applied(self):
        from tradex.data_sources import em_client
        _responses.append(_fake_response([]))
        em_client.fetch_margin_target_list(trade_date="20260924")
        flt = em_client._test_calls[0]["params"]["filter"]
        assert "2026-09-24" in flt

    def test_no_filter_when_no_date(self):
        from tradex.data_sources import em_client
        _responses.append(_fake_response([]))
        em_client.fetch_margin_target_list()
        assert "filter" not in em_client._test_calls[0]["params"]


# ════════════════════════════════════════════════════════════════════
# 大宗交易族
# ════════════════════════════════════════════════════════════════════

class TestBlockTradeMarketStat:
    def test_basic_mapping(self):
        from tradex.data_sources import em_client
        _responses.append(_fake_response([{
            "TRADE_DATE": "2026-09-24",
            "SZ_INDEX": "3888.37", "SZ_CHANGE_RATE": "-1.22",
            "BLOCKTRADE_DEAL_AMT": "1087937200",
            "PREMIUM_DEAL_AMT": "66266800", "PREMIUM_RATIO": "6.09",
            "DISCOUNT_DEAL_AMT": "504292800", "DISCOUNT_RATIO": "46.35",
        }]))
        result = em_client.fetch_block_trade_market_stat()
        assert result[0]["total_amount"] == 1087937200.0
        assert result[0]["premium_ratio"] == 6.09
        assert result[0]["sz_index"] == 3888.37


class TestBlockTradeDetail:
    def test_basic_mapping(self):
        from tradex.data_sources import em_client
        _responses.append(_fake_response([{
            "SECURITY_CODE": "000001", "SECURITY_NAME_ABBR": "平安银行",
            "TRADE_DATE": "2026-09-24", "CLOSE_PRICE": "11.5",
            "CHANGE_RATE": "1.5", "DEAL_PRICE": "11.3",
            "DEAL_VOLUME": "1000000", "DEAL_AMT": "11300000",
            "PREMIUM_RATIO": "-1.74", "TURNOVER_RATE": "0.05",
            "BUYER_NAME": "中信证券", "SELLER_NAME": "国泰君安",
        }]))
        result = em_client.fetch_block_trade_detail(
            start_date="2026-09-20", end_date="2026-09-25"
        )
        r = result[0]
        assert r["deal_price"] == 11.3
        assert r["buy_branch"] == "中信证券"
        assert r["sell_branch"] == "国泰君安"

    def test_no_date_filter(self):
        from tradex.data_sources import em_client
        _responses.append(_fake_response([]))
        em_client.fetch_block_trade_detail()
        # 没传日期 → filter_expr 应为 None → 参数里不应有 filter
        assert "filter" not in em_client._test_calls[0]["params"]


class TestBlockTradeDailyStat:
    def test_basic_mapping(self):
        from tradex.data_sources import em_client
        _responses.append(_fake_response([{
            "SECURITY_CODE": "000001", "SECURITY_NAME_ABBR": "平安银行",
            "TRADE_DATE": "2026-09-24", "CHANGE_RATE": "1.5",
            "CLOSE_PRICE": "11.5", "DEAL_NUM": "3",
            "VOLUME": "2600000", "DEAL_AMT": "30000000",
            "AVERAGE_PRICE": "11.54", "PREMIUM_RATIO": "-1.0",
            "PREMIUM_TIMES": "1", "DISCOUNT_TIMES": "2",
            "D1_CLOSE_ADJCHRATE": "0.5", "D5_CLOSE_ADJCHRATE": "1.2",
        }]))
        result = em_client.fetch_block_trade_daily_stat(
            start_date="2026-09-20", end_date="2026-09-25"
        )
        r = result[0]
        assert r["deal_count"] == 3
        assert r["deal_total_amount"] == 3e7
        assert r["deal_total_volume"] == 2600000.0
        assert r["premium_times"] == 1
        assert r["after_5d"] == 1.2


# ════════════════════════════════════════════════════════════════════
# Registry 集成
# ════════════════════════════════════════════════════════════════════

class TestAllNewTypesRegistered:
    """所有新数据类型都已注册到 SmartRouter。"""

    NEW_TYPES = [
        "dt_detail", "dt_stock_stats", "dt_institution",
        "dt_seat_detail",
        "margin_account_info", "margin_target_list",
        "block_trade_market_stat", "block_trade_detail", "block_trade_daily_stat",
    ]

    def test_all_registered_with_em_datacenter(self):
        from tradex.data_sources import register_all_sources, get_router
        register_all_sources()
        r = get_router()
        for t in self.NEW_TYPES:
            assert t in r._sources, f"{t} 未注册"
            sources = r._sources[t]
            assert len(sources) >= 1, f"{t} 没有任何源"
            item = sources[0]
            assert item[0] == "em_datacenter", f"{t} 源名应为 em_datacenter"
            # 2026-09-25 压测零封禁后从 P999 降到 P1 主源（老板拍板）
            assert item[2] == 1, f"{t} priority 应为 1（压测后提到主源），实际 {item[2]}"
            assert callable(item[1]), f"{t} fetch_fn 必须可调用"
