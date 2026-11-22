"""工单 17（QI-STD-26）降级链验证：已注册源断源形态改抛出后，SmartRouter 记账降级实测。

三层断言（mock 优先，rule 4 无网络用例）：
  1. fetcher 层：mock 断源应答（JSONP 解析失败 / 空 items / data:null / 键缺失 /
     凭据缺失）→ fetcher 抛 RuntimeError（不再静默空表）。
  2. 路由层：mock SmartRouter 双源——主源抛出 → 备源接管 + 主源 fail_count 记账。
  3. 信封层：双源全败 → 诚实 RuntimeError 信封（错误清单含两源）。
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from astock_signals.smart_router import SmartRouter
from tradex.data_sources import sina_fetchers


class _FakeResp:
    """curl_cffi 响应桩：按构造参数伪装断源应答。"""

    def __init__(self, text: str = "", payload=None, raw: bytes = b""):
        self.text = text
        self._payload = payload
        self.content = raw

    def raise_for_status(self):
        return None

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


# ============================================================
# 1. fetcher 层：断源形态 → 抛出（QI-STD-26 三处 sina 锚点）
# ============================================================


class TestSinaResearchReportsThrows:
    def test_jsonp_parse_fail_raises(self):
        """票面锚点 :93（取证版）：JSONP 解析失败不再折叠空表。"""
        with patch.object(
            sina_fetchers.curl_requests, "get",
            return_value=_FakeResp(text="<html>blocked</html>"),
        ):
            with pytest.raises(RuntimeError, match="JSONP 解析失败"):
                sina_fetchers.fetch_sina_research_reports(symbol="600519")

    def test_empty_items_raises(self):
        """票面锚点 :97（取证版）：合法 JSONP 但 result.data 空 → 抛出。"""
        payload = {"result": {"data": []}}
        text = "IO.XSRV2.CallbackList['x'](" + __import__("json").dumps(payload) + ")"
        with patch.object(
            sina_fetchers.curl_requests, "get",
            return_value=_FakeResp(text=text, payload=payload),
        ):
            with pytest.raises(RuntimeError, match="空 items"):
                sina_fetchers.fetch_sina_research_reports(symbol="600519")


class TestSinaFundFlowThrows:
    def test_empty_klines_raises_and_falls_back_to_snapshot(self):
        """票面锚点 :264（取证版）：data:null → 抛出 → 新浪快照兜底接管。"""
        with patch.object(
            sina_fetchers.curl_requests, "get",
            return_value=_FakeResp(payload={"data": None}),
        ), patch.object(
            sina_fetchers, "_sina_moneyflow_snapshot",
            return_value=pd.DataFrame([{"日期": "2026-11-21", "主力净流入": 1.0}]),
        ) as m_snap:
            df = sina_fetchers.fetch_sina_fund_flow(symbol="600519")
        assert not df.empty
        m_snap.assert_called_once()

    def test_klines_parse_zero_rows_raises(self):
        """票面锚点 :294（取证版）：klines 有载荷但解析零行 → 抛出（快照也无 → 上抛）。"""
        kline = "1,2,3"  # < 13 字段，全部行被跳过
        with patch.object(
            sina_fetchers.curl_requests, "get",
            return_value=_FakeResp(payload={"data": {"klines": [kline]}}),
        ), patch.object(
            sina_fetchers, "_sina_moneyflow_snapshot",
            side_effect=RuntimeError("snapshot down"),
        ):
            with pytest.raises(RuntimeError, match="解析零行"):
                sina_fetchers.fetch_sina_fund_flow(symbol="600519")

    def test_moneyflow_snapshot_missing_netamount_raises(self):
        """票面锚点 :183（取证版）：快照应答缺 netamount（键缺失）→ 抛出。"""
        with patch.object(
            sina_fetchers.curl_requests, "get",
            return_value=_FakeResp(payload={"other": 1}),
        ):
            with pytest.raises(RuntimeError, match="netamount"):
                sina_fetchers._sina_moneyflow_snapshot("600519")


class TestCredentialMissingThrows:
    def test_wencai_news_missing_api_key_raises(self):
        """凭据缺失 = 源不可用（同 tdx_mcp/tq 先例），不再静默空表。"""
        from tradex.data_sources import wencai_fetchers

        with patch.object(wencai_fetchers, "IWENCAI_API_KEY", ""):
            with pytest.raises(RuntimeError, match="IWENCAI_API_KEY"):
                wencai_fetchers.fetch_wencai_news(keyword="涨停")


# ============================================================
# 2/3. 路由层：记账降级 + 诚实错误信封
# ============================================================


class _AlwaysRaise:
    def __call__(self, **kwargs):
        raise RuntimeError("断源（mock）")


class TestRouterDegradation:
    def _router(self, data_type: str, primary, backup) -> SmartRouter:
        r = SmartRouter()
        r.register(data_type, "primary_mock", primary, 1, False)
        r.register(data_type, "backup_mock", backup, 100, False)
        return r

    def test_primary_raises_backup_takes_over(self):
        """主源断源抛出 → 备源接管 + 主源 fail_count 记账（不再静默空表截断降级链）。"""
        r = self._router("deg_test_a", _AlwaysRaise(), lambda **k: pd.DataFrame([{"v": 1}]))
        data, src = r.route("deg_test_a", timeout=5)
        assert src == "backup_mock"
        assert not data.empty
        report = {x["source"]: x for x in r.get_health_report()}
        assert report["deg_test_a:primary_mock"]["fail_count"] == 1
        assert report["deg_test_a:backup_mock"]["fail_count"] == 0

    def test_all_fail_honest_envelope(self):
        """双源全败 → RuntimeError 信封含两源错误清单（诚实暴露，非假空表）。"""
        r = self._router("deg_test_b", _AlwaysRaise(), _AlwaysRaise())
        with pytest.raises(RuntimeError) as ei:
            r.route("deg_test_b", timeout=5)
        msg = str(ei.value)
        assert "primary_mock" in msg and "backup_mock" in msg
        report = {x["source"]: x for x in r.get_health_report()}
        assert report["deg_test_b:primary_mock"]["fail_count"] >= 1
        assert report["deg_test_b:backup_mock"]["fail_count"] >= 1

    def test_sina_research_registered_and_throws_through_router(self):
        """真实注册面：sina_research 断源形态经全局路由抛出（不再返回空 df 记成功）。"""
        from tradex.data_sources import register_all_sources
        from tradex.data_sources import get_router

        register_all_sources()
        router = get_router()
        with patch.object(
            sina_fetchers.curl_requests, "get",
            return_value=_FakeResp(text="<html>blocked</html>"),
        ):
            # source_name 固定源语义：sina_research 抛出即上抛（不降级）
            with pytest.raises(RuntimeError, match="JSONP 解析失败"):
                router.route(
                    "research_report", source_name="sina_research",
                    symbol="600519", page=1, page_size=20, timeout=5,
                )
        report = {x["source"]: x for x in router.get_health_report()}
        assert report["research_report:sina_research"]["fail_count"] >= 1
