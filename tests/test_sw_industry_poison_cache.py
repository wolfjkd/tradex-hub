"""QI-STD-27 锁定测试：sw_industry 下载失败不得毒缓存进模块全局。

票面（老板 2026-11-23 拍板修复）：`sw_industry_fetchers._load_history`
下载失败原把空 df 写进模块全局 `_history_df`（`_history_df = pd.DataFrame()`）
——一次失败进程内永久假空不可自愈（fetch_sw_industry_as_of 断源、
fetch_sw_industry_history 假空成功记账）。修法：失败路径不写入缓存，
保持 None 让下次调用重试下载；成功路径语义原样不动。

契约保持：失败调用返回值仍为空 df（不抛异常）——只改缓存行为，
不改返回值契约（fetch_sw_industry_history「失败时返回空 DataFrame」
docstring 契约与 fetch_sw_industry_as_of 的 RuntimeError 空态信封
均不受影响）。
"""

from __future__ import annotations

import pandas as pd

from tradex.data_sources import sw_industry_fetchers as mod


class _FakeResp:
    content = b"stub-xls-bytes"

    def raise_for_status(self) -> None:
        pass


def test_download_failure_does_not_poison_cache(monkeypatch):
    """失败不写全局（保持 None）+ 下次调用重试下载（红→绿：原态两断言均红）。"""
    monkeypatch.setattr(mod, "_history_df", None)  # 冷态（teardown 还原实况值）
    calls = []

    def fake_get(*_a, **_k):
        calls.append(1)
        raise RuntimeError("模拟下载失败（QI-STD-27 测试）")

    monkeypatch.setattr(mod.curl_requests, "get", fake_get)

    df1 = mod._load_history()
    assert df1.empty, "契约保持：失败返回空 df，不抛异常"
    assert mod._history_df is None, (
        "QI-STD-27: 失败不得把空 df 写进模块全局 _history_df（毒缓存）"
    )

    df2 = mod._load_history()
    assert df2.empty, "重试仍失败：仍返回空 df"
    assert len(calls) == 2, (
        "失败后再次调用应重试下载；原态毒缓存使第二次直接假空命中（不重试）"
    )


def test_download_failure_then_success_recovers(monkeypatch):
    """失败→重试成功：毒缓存修复后进程内可自愈。"""
    monkeypatch.setattr(mod, "_history_df", None)
    state = {"fail": True}

    def fake_get(*_a, **_k):
        if state["fail"]:
            raise RuntimeError("模拟首次失败")
        return _FakeResp()

    monkeypatch.setattr(mod.curl_requests, "get", fake_get)
    stub_df = pd.DataFrame({"股票代码": ["600170"], "行业名称": ["建筑施工"]})
    monkeypatch.setattr(mod.pd, "read_excel", lambda *_a, **_k: stub_df.copy())

    assert mod._load_history().empty, "首次失败返回空 df"
    state["fail"] = False
    df = mod._load_history()
    assert not df.empty, "失败不入缓存 → 下次调用重试成功（进程内自愈）"
    assert mod._history_df is not None and not mod._history_df.empty


def test_success_still_caches_and_reuses(monkeypatch):
    """成功路径语义不动：正常入缓存，第二次调用走缓存不重下。"""
    monkeypatch.setattr(mod, "_history_df", None)
    calls = []

    def fake_get(*_a, **_k):
        calls.append(1)
        return _FakeResp()

    monkeypatch.setattr(mod.curl_requests, "get", fake_get)
    stub_df = pd.DataFrame({"股票代码": ["600170"], "行业名称": ["建筑施工"]})
    monkeypatch.setattr(mod.pd, "read_excel", lambda *_a, **_k: stub_df.copy())

    df1 = mod._load_history()
    assert not df1.empty and len(df1) == 1, "成功正常返回数据"
    assert mod._history_df is not None, "成功正常入缓存"

    df2 = mod._load_history()
    assert len(calls) == 1, "成功后第二次调用走缓存，不重新下载"
    pd.testing.assert_frame_equal(df1, df2)
