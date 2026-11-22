"""QI-ARCH-14 票 13 编排上收行为锁定 + MCP/REST 双出口对拍（2026-11-22）。

三段编排搬进 service 后的语义保真锁定：
- market_capitalization：双 Tier 降级对象缓存（dict/DataFrame 判型出口），
  None 不缓存（原兜底 error_response 不入缓存等价）
- stock_list：df 对象缓存 + 出口 df_to_json(max_rows) 截断重放
- financial_calendar：date_cols 关键词猜测过滤编排随迁 + 空 df 缓存/None
  早退两态保真
- MCP/REST 双出口对拍：get_realtime_quote 同缓存键共享（route 一次）、
  market_capitalization MCP 出口与 service 对象一致

路由与缓存实例全部 monkeypatch 隔离，不触网。
"""

import asyncio
import json
from types import SimpleNamespace

import pandas as pd

from tradex.utils.cache import TwoLevelCache


def _fresh_cache(monkeypatch, module, tmp_path) -> TwoLevelCache:
    """给目标模块换上独立缓存实例（隔离全局单例，无文件层）。"""
    c = TwoLevelCache(cache_dir=str(tmp_path / "c"), file_enabled=False)
    monkeypatch.setattr(module, "cache", c)
    return c


def _run(coro):
    return asyncio.run(coro)


# ---------- market_capitalization ----------


class TestMarketCapitalization:
    """双 Tier 降级编排：对象缓存 + None 不缓存 + 判型出口。"""

    def _tool(self):
        from tradex.tools import price_data

        return price_data

    def test_tier1_hit_caches_dict(self, monkeypatch, tmp_path):
        from tradex.service import price_service

        svc = price_service
        tool = self._tool()
        _fresh_cache(monkeypatch, svc, tmp_path)
        calls = []

        def fake_route(cmd, **kwargs):
            calls.append(cmd)
            if cmd == "company_info":
                return (
                    pd.DataFrame([["总市值", "100亿"], ["名称", "贵州茅台"]]),
                    "fake_src",
                )
            return (pd.DataFrame(), "fake_src")

        monkeypatch.setattr(svc, "_router", SimpleNamespace(route=fake_route))

        out = _run(tool.get_market_capitalization("600519"))
        # Tier1 命中 → dict_to_json(info) 等价串
        assert out == json.dumps(
            {"总市值": "100亿", "名称": "贵州茅台"}, ensure_ascii=False
        )
        # 缓存对象是 dict（非串），第二次调用命中缓存不重复取数
        assert isinstance(svc.cache.get("market_cap:600519"), dict)
        _run(tool.get_market_capitalization("600519"))
        assert calls.count("company_info") == 1

    def test_tier2_fallback_caches_dataframe(self, monkeypatch, tmp_path):
        from tradex.service import price_service
        from tradex.utils.formatter import df_to_json

        svc = price_service
        tool = self._tool()
        _fresh_cache(monkeypatch, svc, tmp_path)

        quote_df = pd.DataFrame(
            [{"代码": "600519", "名称": "贵州茅台", "最新价": 1.0, "总市值": 100.0,
              "其他列": "x"}]
        )

        def fake_route(cmd, **kwargs):
            if cmd == "company_info":
                raise RuntimeError("tier1 down")
            return (quote_df, "fake_src")

        monkeypatch.setattr(svc, "_router", SimpleNamespace(route=fake_route))

        obj = svc.get_market_capitalization("600519")
        assert isinstance(obj, pd.DataFrame)  # Tier2 命中返回 DataFrame 对象
        out = _run(tool.get_market_capitalization("600519"))
        # 判型出口：DataFrame → df_to_json（available_cols 过滤掉「其他列」）
        assert json.loads(out)[0]["代码"] == "600519"
        assert "其他列" not in json.loads(out)[0]
        assert json.loads(out) == json.loads(df_to_json(obj))
        # 命中重放等价（df_to_json 确定性）
        out2 = _run(tool.get_market_capitalization("600519"))
        assert out2 == out

    def test_all_fail_not_cached(self, monkeypatch, tmp_path):
        from tradex.service import price_service

        svc = price_service
        tool = self._tool()
        c = _fresh_cache(monkeypatch, svc, tmp_path)
        calls = []

        def fake_route(cmd, **kwargs):
            calls.append(cmd)
            if cmd == "company_info":
                raise RuntimeError("down")
            return (None, "fake_src")  # 行情空

        monkeypatch.setattr(svc, "_router", SimpleNamespace(route=fake_route))

        out = _run(tool.get_market_capitalization("600519"))
        assert json.loads(out)["error"] is True
        assert "所有数据源均不可用" in json.loads(out)["message"]
        # None 不缓存，两次调用都重算（原态失败不冻结等价）
        assert c.get("market_cap:600519") is None
        _run(tool.get_market_capitalization("600519"))
        assert len(calls) == 4  # 2 次 × (Tier1 + Tier2)


# ---------- stock_list ----------


class TestStockList:
    """过滤编排：df 对象缓存 + 出口截断重放 + 空态不缓存。"""

    def _tool(self):
        from tradex.tools import price_data

        return price_data

    def test_filter_and_row_cap(self, monkeypatch, tmp_path):
        from tradex.service import price_service

        svc = price_service
        tool = self._tool()
        _fresh_cache(monkeypatch, svc, tmp_path)
        calls = []

        def fake_route(cmd, **kwargs):
            calls.append(cmd)
            rows = [
                {"代码": f"{600000 + i}", "名称": f"股{i}", "总市值": (500 - i) * 1e8}
                for i in range(6)
            ]
            return (pd.DataFrame(rows), "fake_src")

        monkeypatch.setattr(svc, "_router", SimpleNamespace(route=fake_route))

        out = _run(tool.get_stock_list(min_market_cap=100, max_results=2))
        data = json.loads(out)
        # 市值过滤（>=100亿）+ 降序 + 截断 2 条
        assert len(data) == 2
        assert data[0]["总市值"] == 500e8
        assert data[1]["总市值"] == 499e8
        # 缓存的是 df 对象（未截断），命中重放等价
        assert isinstance(svc.cache.get("stock_list:100:2"), pd.DataFrame)
        out2 = _run(tool.get_stock_list(min_market_cap=100, max_results=2))
        assert out2 == out
        assert len(calls) == 1

    def test_empty_not_cached(self, monkeypatch, tmp_path):
        from tradex.service import price_service

        svc = price_service
        tool = self._tool()
        c = _fresh_cache(monkeypatch, svc, tmp_path)
        calls = []

        def fake_route(cmd, **kwargs):
            calls.append(cmd)
            return (None, "fake_src")

        monkeypatch.setattr(svc, "_router", SimpleNamespace(route=fake_route))

        out = _run(tool.get_stock_list())
        assert json.loads(out)["error"] is True
        assert c.get("stock_list:0:50") is None
        _run(tool.get_stock_list())
        assert len(calls) == 2  # 空态重算


# ---------- financial_calendar ----------


class TestFinancialCalendar:
    """date_cols 关键词猜测过滤编排随迁 + 空 df 缓存 / None 早退两态保真。"""

    def _tool(self):
        from tradex.tools import news_events

        return news_events

    def test_no_date_concat_and_slim(self, monkeypatch, tmp_path):
        from tradex.service import news_service

        svc = news_service
        tool = self._tool()
        _fresh_cache(monkeypatch, svc, tmp_path)

        df1 = pd.DataFrame([["600519", "2026-04-25", "年报"]], columns=["代码", "预约披露时间", "报告类型"])
        df2 = pd.DataFrame([["GDP", "2026-04-20"]], columns=["指标", "日期"])

        def fake_route(cmd, **kwargs):
            if cmd == "news_data":
                return (df1, "src1")
            if cmd == "baidu_economic_calendar":
                return (df2, "src2")
            return (None, "src")

        monkeypatch.setattr(svc, "_router", SimpleNamespace(route=fake_route))

        combined = svc.get_financial_calendar()
        assert isinstance(combined, pd.DataFrame)
        assert len(combined) == 2
        out = _run(tool.get_financial_calendar())
        assert len(json.loads(out)) == 2

    def test_date_filter_matches_disclosure_col(self, monkeypatch, tmp_path):
        """date_cols 关键词列（预约披露时间）匹配 YYYY-MM-DD 过滤。"""
        from tradex.service import news_service

        svc = news_service
        tool = self._tool()
        _fresh_cache(monkeypatch, svc, tmp_path)

        df1 = pd.DataFrame([
            ["600519", "2026-04-25", "年报"],
            ["000001", "2025-04-25", "年报"],
        ], columns=["代码", "预约披露时间", "报告类型"])

        def fake_route(cmd, **kwargs):
            if cmd == "news_data":
                return (df1, "src1")
            if cmd == "baidu_economic_calendar":
                return (None, "src2")
            return (None, "src")

        monkeypatch.setattr(svc, "_router", SimpleNamespace(route=fake_route))

        combined = svc.get_financial_calendar("20260425")
        # 只留 2026-04-25 一行（先猜 YYYY-MM-DD 命中）
        assert len(combined) == 1
        assert combined.iloc[0]["代码"] == "600519"
        out = _run(tool.get_financial_calendar("20260425"))
        assert len(json.loads(out)) == 1

    def test_date_filter_regex_fallback_and_drop(self, monkeypatch, tmp_path):
        """date_cols 无匹配 → 全列正则兜底；仍无匹配 → 丢弃该源（空 df 缓存）。"""
        from tradex.service import news_service

        svc = news_service
        tool = self._tool()
        c = _fresh_cache(monkeypatch, svc, tmp_path)

        # 无任何含「日期/披露/时间」等关键词列的源，值用 YYYYMMDD 原始格式
        df1 = pd.DataFrame([["600519", "20260425"]], columns=["代码", "备注"])

        def fake_route(cmd, **kwargs):
            if cmd == "news_data":
                return (df1, "src1")
            if cmd == "baidu_economic_calendar":
                return (None, "src2")
            return (None, "src")

        monkeypatch.setattr(svc, "_router", SimpleNamespace(route=fake_route))

        # date_fmt=2026-04-25 全列不命中 → 该源丢弃 → combined 空 df（原态走 set 缓存）
        combined = svc.get_financial_calendar("20260425")
        assert isinstance(combined, pd.DataFrame)
        assert combined.empty
        # 空 df 对象入缓存（非 None），与原态「过滤后空走 set」一致
        assert isinstance(c.get("fin_calendar:20260425"), pd.DataFrame)
        out = _run(tool.get_financial_calendar("20260425"))
        assert json.loads(out) == []

    def test_both_sources_empty_not_cached(self, monkeypatch, tmp_path):
        from tradex.service import news_service

        svc = news_service
        tool = self._tool()
        c = _fresh_cache(monkeypatch, svc, tmp_path)
        calls = []

        def fake_route(cmd, **kwargs):
            calls.append(cmd)
            return (None, "src")

        monkeypatch.setattr(svc, "_router", SimpleNamespace(route=fake_route))

        out = _run(tool.get_financial_calendar())
        # None 不缓存 → 工具体重建空态串（原态早退先于 set 等价）
        assert json.loads(out) == []
        assert c.get("fin_calendar:") is None
        _run(tool.get_financial_calendar())
        assert len(calls) == 4  # 2 次 × 双源


# ---------- MCP/REST 双出口对拍 ----------


class TestDualExitParity:
    """MCP 工具体与 REST 出口行为一致（含缓存语义统一后共享同一缓存条目）。"""

    def test_realtime_quote_mcp_rest_share_cache(self, monkeypatch, tmp_path):
        from fastapi.testclient import TestClient

        from tradex.service import price_service
        from tradex.tools import price_data

        svc = price_service
        _fresh_cache(monkeypatch, svc, tmp_path)
        calls = []

        quote_df = pd.DataFrame(
            [{"代码": "600519", "名称": "贵州茅台", "最新价": 1500.0, "涨跌幅": 1.2}]
        )

        def fake_route(cmd, **kwargs):
            calls.append(cmd)
            return (quote_df, "fake_src")

        monkeypatch.setattr(svc, "_router", SimpleNamespace(route=fake_route))

        # MCP 出口
        mcp_out = json.loads(_run(price_data.get_realtime_quote("600519")))
        # 首次调用 route 2 次：主行情 1 + 估值补取（腾讯，缺市盈率/市净率触发）1
        assert len(calls) == 2
        # REST 出口（build_min_test_app 挂全量 REST 路由）
        from tests._rest_test_base import build_min_test_app

        client = TestClient(build_min_test_app())
        rest_body = client.get("/api/v1/price/quote?symbol=600519").json()
        assert rest_body["code"] == 0
        # 双出口 quote 数据一致
        assert mcp_out["quote"] == rest_body["data"]["quote"]
        # 同缓存键共享：REST 调用后 route 总数不变（主行情/估值补取键均命中）
        assert len(calls) == 2

    def test_market_cap_mcp_exit_matches_service_object(self, monkeypatch, tmp_path):
        """MCP 出口串 = service 对象出口判型重序列化（薄包装忠实性）。"""
        from tradex.service import price_service
        from tradex.tools import price_data

        svc = price_service
        tool = price_data
        _fresh_cache(monkeypatch, svc, tmp_path)

        def fake_route(cmd, **kwargs):
            if cmd == "company_info":
                return (
                    pd.DataFrame([["总市值", "100亿"], ["流通市值", "80亿"]]),
                    "fake_src",
                )
            return (pd.DataFrame(), "fake_src")

        monkeypatch.setattr(svc, "_router", SimpleNamespace(route=fake_route))

        obj = svc.get_market_capitalization("600519")
        mcp_out = json.loads(_run(tool.get_market_capitalization("600519")))
        # 工具体薄包装：dict_to_json(service 对象) 一致
        assert mcp_out == {"总市值": "100亿", "流通市值": "80亿"}
        assert obj == {"总市值": "100亿", "流通市值": "80亿"}
