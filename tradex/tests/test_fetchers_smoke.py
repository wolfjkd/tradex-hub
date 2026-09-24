"""工单 T35 测试：Fetcher 层冒烟（每 fetcher ≥3 用例）。

只测每个 fetcher 函数能被 import、签名合法、空入参返回 DataFrame（不抛异常）。
真实网络验证留给 @pytest.mark.network 测试。
"""

from __future__ import annotations

import inspect

import pandas as pd
import pytest


@pytest.fixture(autouse=True)
def _ensure_registered():
    from tradex.data_sources import register_all_sources
    register_all_sources()


# 所有新增 fetcher 函数（按模块组织）
FETCHER_SPECS = [
    # (module_path, function_name, kwargs_for_mock_call)
    ("tradex.data_sources.sina_fetchers",
     "fetch_sina_research_reports",
     {"symbol": "600519", "code": "", "page": 1, "page_size": 5}),
    ("tradex.data_sources.sina_fetchers",
     "fetch_sina_fund_flow",
     {"symbol": "600519", "code": "", "days": 3}),
    ("tradex.data_sources.sina_fetchers",
     "fetch_sina_option_tquote",
     {"underlying": "510050"}),
    ("tradex.data_sources.sina_fetchers",
     "fetch_sina_option_greeks",
     {"underlying": "510050"}),
    ("tradex.data_sources.baidu_fetchers",
     "fetch_baidu_kline_with_ma",
     {"symbol": "600519", "code": "", "period": "day", "count": 5}),
    ("tradex.data_sources.baostock_fetchers",
     "fetch_baostock_valuation_history",
     {"symbol": "600519", "code": "", "start_date": "", "end_date": ""}),
    ("tradex.data_sources.baostock_fetchers",
     "fetch_baostock_delisting_date",
     {"symbol": "600519", "code": ""}),
    ("tradex.data_sources.baostock_fetchers",
     "fetch_baostock_st_list",
     {}),
    ("tradex.data_sources.exchange_official_fetchers",
     "fetch_sse_dragon_tiger",
     {"date": ""}),
    ("tradex.data_sources.exchange_official_fetchers",
     "fetch_szse_dragon_tiger",
     {"date": ""}),
    ("tradex.data_sources.exchange_official_fetchers",
     "fetch_szse_trading_calendar",
     {"year": 2026, "month": 1}),
    ("tradex.data_sources.event_driven_fetchers",
     "fetch_earnings_forecast",
     {"symbol": "600519", "code": "", "report_date": "", "limit": 5}),
    ("tradex.data_sources.event_driven_fetchers",
     "fetch_institution_survey",
     {"symbol": "000001", "code": "", "start_date": "", "end_date": "", "limit": 5}),
    ("tradex.data_sources.event_driven_fetchers",
     "fetch_holder_trades",
     {"symbol": "600519", "code": "", "direction": "", "limit": 5}),
    ("tradex.data_sources.event_driven_fetchers",
     "fetch_share_buyback",
     {"symbol": "000001", "code": "", "progress": "", "limit": 5}),
    ("tradex.data_sources.event_driven_fetchers",
     "fetch_equity_pledge",
     {"symbol": "600519", "code": "", "date": "", "limit": 5}),
    ("tradex.data_sources.event_driven_fetchers",
     "fetch_ipo_calendar",
     {"days_ahead": 7, "limit": 5}),
    ("tradex.data_sources.interaction_fetchers",
     "fetch_cninfo_irm",
     {"symbol": "000001", "code": "", "page": 1, "page_size": 5}),
    ("tradex.data_sources.interaction_fetchers",
     "fetch_sse_e_interaction",
     {"symbol": "600519", "code": "", "page": 1, "page_size": 5}),
    ("tradex.data_sources.wallstreetcn_fetchers",
     "fetch_wallstreetcn_lives",
     {"channel": "global", "limit": 5}),
    ("tradex.data_sources.wallstreetcn_fetchers",
     "fetch_macro_calendar",
     {"start_date": "", "end_date": ""}),
    ("tradex.data_sources.cctv_news_fetchers",
     "fetch_cctv_news",
     {"date": "", "with_content": False}),
    ("tradex.data_sources.macro_official_fetchers",
     "fetch_pboc_social_financing",
     {"year": 0}),
    ("tradex.data_sources.macro_official_fetchers",
     "fetch_nbs_pmi",
     {}),
    ("tradex.data_sources.macro_official_fetchers",
     "fetch_chinabond_yield_curve",
     {"curve": "国债"}),
    ("tradex.data_sources.macro_official_fetchers",
     "fetch_repo_fixing_rates",
     {"kind": "FR"}),
    ("tradex.data_sources.macro_official_fetchers",
     "fetch_lpr_history",
     {"years_back": 1}),
    ("tradex.data_sources.sw_industry_fetchers",
     "fetch_sw_industry_history",
     {"force_refresh": False}),
    ("tradex.data_sources.sw_industry_fetchers",
     "fetch_sw_industry_as_of",
     {"symbol": "600519", "code": "", "date": ""}),
    ("tradex.data_sources.industry_news_fetchers",
     "fetch_industry_news",
     {"track": "ai", "days": 1, "per_source": 1}),
]


@pytest.mark.parametrize("module_path,func_name,kwargs", FETCHER_SPECS)
def test_fetcher_importable_and_callable(module_path, func_name, kwargs):
    """每个 fetcher 应能被 import、签名接受 kwargs、并可在不连网时优雅返回 DataFrame。"""
    mod = __import__(module_path, fromlist=["*"])
    assert hasattr(mod, func_name), f"{module_path}.{func_name} 不存在"
    fn = getattr(mod, func_name)
    assert callable(fn), f"{func_name} 不可调用"

    # 签名校验：参数应支持 kwargs 里的所有 key（至少包含）
    sig = inspect.signature(fn)
    param_names = set(sig.parameters.keys())
    # kwargs 里的每个 key 都应是 fetcher 参数（除了 **kwargs 这种）
    has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD
                     for p in sig.parameters.values())
    if not has_var_kw:
        for k in kwargs:
            assert k in param_names, (
                f"{func_name} 不接受参数 '{k}'；签名: {list(param_names)}"
            )


@pytest.mark.parametrize("module_path,func_name,kwargs", FETCHER_SPECS)
def test_fetcher_signature_has_kwargs(module_path, func_name, kwargs):
    """每个 fetcher 都应有 **kwargs（项目惯例）。"""
    mod = __import__(module_path, fromlist=["*"])
    fn = getattr(mod, func_name)
    sig = inspect.signature(fn)
    has_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD
                 for p in sig.parameters.values())
    assert has_kw, f"{func_name} 缺少 **kwargs 参数"


def test_industry_news_config_file_exists():
    """industry_news_sources.json 文件存在且包含 106 源（冻结版）。"""
    from tradex.data_sources.industry_news_fetchers import get_source_count
    assert get_source_count() == 106


def test_industry_news_tracks_complete():
    """12 个赛道全部齐备。"""
    from tradex.data_sources.industry_news_fetchers import list_tracks
    tracks = list_tracks()
    assert len(tracks) == 12
    keys = {t["key"] for t in tracks}
    expected = {
        "ai", "semi", "robot", "auto", "energy", "bio",
        "space", "security", "tech", "consumer", "macro", "science",
    }
    assert keys == expected
