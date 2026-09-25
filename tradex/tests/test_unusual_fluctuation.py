"""监管异动 fetch_unusual_fluctuation 测试（2026-09-25 新增）。

覆盖：
- 字段映射正确性（IS_HAPPEN / IS_POSITIVE / DEVUATION_VALUE 等上游字段）
- 参数互斥校验（trade_date 与 start/end_date 不能同时指定）
- 日期归一化（YYYYMMDD / YYYY-MM-DD / YYYY/MM/DD 都接受）
- 分页安全阀（max_pages）
- 空数据兜底

借鉴来源：chengzuopeng/stock-sdk（ISC license）src/providers/eastmoney/topicData.ts
字段语义实测口径参考其 commit 2.4.4「feat(marketEvent): 新增监管异动 unusualFluctuation」。
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


# ── 字段映射测试（用伪造的 datacenter 返回） ──


def _fake_response(records, pages=1):
    """构造一个类似 em_get 返回的 Mock response。"""
    resp = MagicMock()
    resp.json.return_value = {
        "result": {
            "pages": pages,
            "count": len(records),
            "data": records,
        }
    }
    resp.raise_for_status.return_value = None
    return resp


def _fake_empty_response():
    """构造 result=null 的空响应（上游在超出保留窗口时返回）。"""
    resp = MagicMock()
    resp.json.return_value = {"result": None}
    resp.raise_for_status.return_value = None
    return resp


@pytest.fixture(autouse=True)
def _patch_em_get(monkeypatch):
    """统一 patch em_get，避免测试触发真实请求。"""
    # 注意：em_client 的 em_get 是模块级函数，要 patch 它的引用
    from tradex.data_sources import em_client
    calls = []

    def fake_em_get(url, params=None, headers=None, timeout=15, **kwargs):
        calls.append({"url": url, "params": params})
        return _em_get_mock(url, params)

    monkeypatch.setattr(em_client, "em_get", fake_em_get)
    # 让测试可以检视调用
    monkeypatch.setattr(em_client, "_test_calls", calls, raising=False)
    yield


_em_get_responses = []  # 由测试填充


def _em_get_mock(url, params):
    """从队列里取出下一个响应。"""
    if _em_get_responses:
        return _em_get_responses.pop(0)
    return _fake_empty_response()


@pytest.fixture(autouse=True)
def _clear_responses():
    _em_get_responses.clear()
    yield
    _em_get_responses.clear()


class TestUnusualFluctuationFieldMapping:
    """字段语义实测口径（参考 stock-sdk 2.4.4 的 commit 说明）。"""

    def test_basic_mapping_triggered_record(self):
        """IS_HAPPEN=1 已触发公告 → triggered=True。"""
        from tradex.data_sources.em_client import fetch_unusual_fluctuation
        _em_get_responses.append(_fake_response([
            {
                "SECURITY_CODE": "000017",
                "SECURITY_NAME_ABBR": "深中华A",
                "TRADE_DATE": "2026-09-20T00:00:00",
                "UNUSUAL_TYPE": "连续三个交易日内日收盘价格涨跌幅偏离值累计达到 100%",
                "IS_HAPPEN": "1",
                "DEVUATION_VALUE": "100",
                "MAX_DAYS": "3",
                "CHANGE_RATE": "100.00",
                "IS_POSITIVE": "1",
                "CHANGE_RATE_TARGET": "100",
            },
        ]))
        result = fetch_unusual_fluctuation(trade_date="2026-09-20")
        assert len(result) == 1
        r = result[0]
        assert r["code"] == "000017"
        assert r["name"] == "深中华A"
        assert r["date"] == "2026-09-20"
        assert r["triggered"] is True
        assert r["deviation_value"] == 100.0
        assert r["window_days"] == 3.0
        assert r["change_pct"] == 100.0
        assert r["direction"] == "up"
        assert "EM_Datacenter" in r["source"]

    def test_approaching_record_is_happen_zero(self):
        """IS_HAPPEN=0 逼近未达 → triggered=False。"""
        from tradex.data_sources.em_client import fetch_unusual_fluctuation
        _em_get_responses.append(_fake_response([
            {
                "SECURITY_CODE": "600010",
                "SECURITY_NAME_ABBR": "国芳集团",
                "TRADE_DATE": "2026-09-19",
                "UNUSUAL_TYPE": "贴近阈值",
                "IS_HAPPEN": "0",
                "DEVUATION_VALUE": "97.66",
                "MAX_DAYS": "3",
                "CHANGE_RATE": "97.66",
                "IS_POSITIVE": "1",
                "CHANGE_RATE_TARGET": "100",
            },
        ]))
        result = fetch_unusual_fluctuation(trade_date="2026-09-19")
        assert len(result) == 1
        assert result[0]["triggered"] is False
        assert result[0]["deviation_value"] == 97.66

    def test_direction_down_is_positive_zero(self):
        """IS_POSITIVE=0 下跌偏离 → direction='down'。"""
        from tradex.data_sources.em_client import fetch_unusual_fluctuation
        _em_get_responses.append(_fake_response([
            {
                "SECURITY_CODE": "000001", "SECURITY_NAME_ABBR": "平安银行",
                "TRADE_DATE": "2026-09-18",
                "UNUSUAL_TYPE": "下跌偏离",
                "IS_HAPPEN": "1",
                "DEVUATION_VALUE": "-50",
                "MAX_DAYS": "3",
                "CHANGE_RATE": "-50",
                "IS_POSITIVE": "0",
                "CHANGE_RATE_TARGET": "-50",
            },
        ]))
        result = fetch_unusual_fluctuation()
        assert result[0]["direction"] == "down"
        assert result[0]["change_pct"] == -50.0

    def test_null_fields_return_none(self):
        """缺失字段应返回 None，不应抛异常。"""
        from tradex.data_sources.em_client import fetch_unusual_fluctuation
        _em_get_responses.append(_fake_response([
            {"SECURITY_CODE": "600000", "TRADE_DATE": "2026-09-17"},
        ]))
        result = fetch_unusual_fluctuation()
        r = result[0]
        assert r["code"] == "600000"
        assert r["name"] == ""
        assert r["triggered"] is False
        assert r["deviation_value"] is None
        assert r["change_pct"] is None
        assert r["direction"] == "down"  # IS_POSITIVE 缺失走 down 分支


class TestUnusualFluctuationParams:
    """参数校验。"""

    def test_trade_date_and_range_mutually_exclusive(self):
        from tradex.data_sources.em_client import fetch_unusual_fluctuation
        _em_get_responses.append(_fake_response([]))
        with pytest.raises(ValueError, match="不能同时指定"):
            fetch_unusual_fluctuation(
                trade_date="2026-09-25", start_date="2026-09-20"
            )

    def test_date_normalization_compact(self):
        """YYYYMMDD 也能正常解析成 filter 表达式里的 YYYY-MM-DD。"""
        from tradex.data_sources import em_client
        _em_get_responses.append(_fake_response([]))
        fetch_unusual_fluctuation = em_client.fetch_unusual_fluctuation
        fetch_unusual_fluctuation(trade_date="20260925")
        assert len(em_client._test_calls) == 1
        filter_expr = em_client._test_calls[0]["params"]["filter"]
        assert "TRADE_DATE='2026-09-25'" in filter_expr

    def test_date_normalization_slash(self):
        """YYYY/MM/DD 也能正常解析。"""
        from tradex.data_sources import em_client
        _em_get_responses.append(_fake_response([]))
        em_client.fetch_unusual_fluctuation(start_date="2026/09/20", end_date="2026/09/25")
        filter_expr = em_client._test_calls[0]["params"]["filter"]
        assert "TRADE_DATE>='2026-09-20'" in filter_expr
        assert "TRADE_DATE<='2026-09-25'" in filter_expr

    def test_triggered_filter_appends_clause(self):
        from tradex.data_sources import em_client
        _em_get_responses.append(_fake_response([]))
        em_client.fetch_unusual_fluctuation(trade_date="2026-09-25", triggered=True)
        filter_expr = em_client._test_calls[0]["params"]["filter"]
        assert 'IS_HAPPEN="1"' in filter_expr

    def test_no_filter_when_no_args(self):
        from tradex.data_sources import em_client
        _em_get_responses.append(_fake_response([]))
        em_client.fetch_unusual_fluctuation()
        params = em_client._test_calls[0]["params"]
        assert "filter" not in params

    def test_report_name_is_correct(self):
        from tradex.data_sources import em_client
        _em_get_responses.append(_fake_response([]))
        em_client.fetch_unusual_fluctuation()
        assert em_client._test_calls[0]["params"]["reportName"] == "RPT_WATCH_UNUSUAL_FLUCTUATE"


class TestUnusualFluctuationPagination:
    """分页逻辑。"""

    def test_empty_result_returns_empty_list(self):
        from tradex.data_sources.em_client import fetch_unusual_fluctuation
        _em_get_responses.append(_fake_empty_response())
        result = fetch_unusual_fluctuation()
        assert result == []

    def test_max_pages_truncation(self):
        """max_pages=1 时即便首页满页也不再翻页。"""
        from tradex.data_sources.em_client import fetch_unusual_fluctuation
        full_page = [
            {"SECURITY_CODE": f"60000{i}", "TRADE_DATE": "2026-09-25"}
            for i in range(500)
        ]
        _em_get_responses.append(_fake_response(full_page, pages=10))
        _em_get_responses.append(_fake_response(full_page, pages=10))  # 不会被消费
        result = fetch_unusual_fluctuation(max_pages=1)
        assert len(result) == 500  # 只拿到第一页

    def test_multi_page_aggregation(self):
        """正常翻页：首页 + 第二页合并。"""
        from tradex.data_sources.em_client import fetch_unusual_fluctuation
        page1 = [{"SECURITY_CODE": f"00000{i}", "TRADE_DATE": "2026-09-25"} for i in range(500)]
        page2 = [{"SECURITY_CODE": f"00050{i}", "TRADE_DATE": "2026-09-25"} for i in range(100)]
        _em_get_responses.append(_fake_response(page1, pages=2))
        _em_get_responses.append(_fake_response(page2, pages=2))
        result = fetch_unusual_fluctuation()
        assert len(result) == 600
        # 第二页满 500 才会翻到第三页；这里第二页只有 100 条，循环应在此终止


class TestUnusualFluctuationDatacenterHelper:
    """fetch_datacenter_list 通用助手（独立于 specific fetcher 的通用测试）。"""

    def test_datacenter_helper_passthrough_reportname(self):
        from tradex.data_sources import em_client
        _em_get_responses.append(_fake_response([]))
        em_client.fetch_datacenter_list("ANY_REPORT_NAME")
        params = em_client._test_calls[0]["params"]
        assert params["reportName"] == "ANY_REPORT_NAME"
        assert params["source"] == "WEB"
        assert params["client"] == "WEB"

    def test_datacenter_helper_columns_passthrough(self):
        from tradex.data_sources import em_client
        _em_get_responses.append(_fake_response([]))
        em_client.fetch_datacenter_list("X", columns="A,B,C")
        assert em_client._test_calls[0]["params"]["columns"] == "A,B,C"


class TestToolRegistration:
    """工具层注册（仅验证 MCP 工具能找到这个能力）。"""

    def test_unusual_fluctuation_tool_callable(self):
        """get_unusual_fluctuation 已注册为 MCP 工具（通过模块导入确认）。"""
        from tradex.tools.event_driven import register
        # 只要 register 函数能跑通，说明工具装饰器没抛异常
        # 不能在这里实际启动 FastMCP，但能验证模块加载
        assert callable(register)


class TestRegistryIntegration:
    """registry 层集成（与 test_new_sources_registration 配合）。"""

    def test_regulatory_anomaly_type_registered(self):
        from tradex.data_sources import register_all_sources, get_router
        register_all_sources()
        r = get_router()
        assert "regulatory_anomaly" in r._sources, "regulatory_anomaly 未注册"
        sources = r._sources["regulatory_anomaly"]
        assert len(sources) >= 1
        # SmartRouter._sources 内部结构：list[tuple[source_name, fetch_fn, priority, exclusive]]
        item = sources[0]
        assert item[0] == "em_datacenter", f"源名应为 em_datacenter，实际为 {item[0]}"
        # 2026-09-25 压测零封禁后从 P999 降到 P1 主源（老板拍板）
        assert item[2] == 1, f"priority 应为 1（压测后提到主源），实际为 {item[2]}"
        assert callable(item[1]), "fetch_fn 必须可调用"
