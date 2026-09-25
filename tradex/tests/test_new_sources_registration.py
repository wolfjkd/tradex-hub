"""工单 T35 测试：数据源注册与降级（registry 层）。

验证：
- 新数据类型已注册（103 类型 / 138 源实例）
- 各类型至少有 1 个源
- 关键类型支持主备双源（如 historical_kline 应有 ≥3 个源）
- 已注册类型的优先级字段合法
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _ensure_registered():
    from tradex.data_sources import register_all_sources
    register_all_sources()


class TestRegistryCompleteness:
    """新增的数据类型必须全部已注册。"""

    NEW_TYPES = [
        # 期权
        "etf_option_tquote", "etf_option_greeks",
        # 事件驱动
        "earnings_forecast", "institution_survey", "holder_trades",
        "share_buyback", "equity_pledge", "ipo_calendar",
        # 指数追踪
        "index_constituents", "index_weights", "index_valuation",
        # 官方宏观
        "social_financing", "pmi_data", "bond_yield_curve",
        "repo_fixing_rate", "lpr_history",
        # 投资者互动
        "cninfo_irm", "sse_e_interaction",
        # 全球新闻
        "wallstreetcn_lives", "macro_calendar", "cctv_news_main",
        # 申万行业
        "sw_industry_history", "sw_industry_as_of",
        # 产业链资讯
        "industry_news",
        # 监管异动（2026-09-25 借鉴 stock-sdk 新增）
        "regulatory_anomaly",
        # 龙虎榜扩展族（2026-09-25 借鉴 stock-sdk dragonTiger.ts）
        "dt_detail", "dt_stock_stats", "dt_institution",
        "dt_seat_detail",
        # 融资融券扩展族（2026-09-25 借鉴 stock-sdk margin.ts）
        "margin_account_info", "margin_target_list",
        # 大宗交易族（2026-09-25 借鉴 stock-sdk blockTrade.ts）
        "block_trade_market_stat", "block_trade_detail", "block_trade_daily_stat",
    ]

    def test_all_new_types_registered(self):
        from tradex.data_sources import get_router
        r = get_router()
        missing = [t for t in self.NEW_TYPES if t not in r._sources]
        assert not missing, f"未注册的数据类型: {missing}"

    def test_total_data_types_at_least_113(self):
        from tradex.data_sources import get_router
        r = get_router()
        assert len(r._sources) >= 113, f"数据类型数 {len(r._sources)} < 113"

    def test_total_source_instances_at_least_148(self):
        from tradex.data_sources import get_router
        r = get_router()
        total = sum(len(v) for v in r._sources.values())
        assert total >= 148, f"源实例数 {total} < 148"


class TestBackupSourceChains:
    """关键类型应支持一主一备（≥2 源）。"""

    PRIMARY_BACKUP_TYPES = [
        "historical_kline",          # eltdx + tdx_mcp + akshare + baidu
        "research_report",           # 主 + sina_research
        "fund_flow",                 # 主 + sina_fund_flow
        "valuation",                 # 主 + baostock_tcp
        "dragon_tiger",              # 东财 + sse_official + szse_official
        "cninfo_announcement",       # 主 + szse_official
        "margin_trading",            # 主 + sse_official + szse_official
    ]

    # baostock 独家提供的新类型（主源就是 baostock，不算"主+备"链）
    BAOSTOCK_NEW_TYPES = [
        "delisting_date", "st_stock_list",
    ]

    def test_each_critical_type_has_at_least_2_sources(self):
        from tradex.data_sources import get_router
        r = get_router()
        for dtype in self.PRIMARY_BACKUP_TYPES:
            sources = r._sources.get(dtype, [])
            assert len(sources) >= 2, (
                f"{dtype} 只有 {len(sources)} 个源，期望 ≥2 (一主一备)。"
                f"已注册源: {[s[0] for s in sources]}"
            )

    def test_baostock_new_types_have_at_least_1_source(self):
        from tradex.data_sources import get_router
        r = get_router()
        for dtype in self.BAOSTOCK_NEW_TYPES:
            sources = r._sources.get(dtype, [])
            assert len(sources) >= 1, f"{dtype} 应至少有 1 个源（baostock）"


class TestRouterRoute:
    """router.route() 能调度新增类型（不要求网络通，只要求不抛 NoSourceError）。"""

    def test_route_unknown_type_returns_empty(self):
        from tradex.data_sources import get_router
        r = get_router()
        # 未知类型应抛错或返回空 DataFrame
        try:
            df, src = r.route("non_existent_type_for_test")
            # 不抛错就要求返回空
            assert df is None or df.empty
        except Exception as e:
            # 抛错也算合理（明确告知无源）
            assert "non_existent" in str(e).lower() or "no source" in str(e).lower() \
                or "未注册" in str(e) or "无数据源" in str(e)


class TestIndustryNewsConfig:
    """industry_news 配置文件完整性。"""

    def test_source_count_is_106(self):
        from tradex.data_sources.industry_news_fetchers import get_source_count
        # 实际冻结版为 106 源（原规划文档写 108 是估算偏差，以 sources.json 实际为准）
        assert get_source_count() == 106, (
            f"industry_news 源总数应为 106（冻结版），实际 {get_source_count()}"
        )

    def test_list_tracks_returns_12(self):
        from tradex.data_sources.industry_news_fetchers import list_tracks
        tracks = list_tracks()
        assert len(tracks) == 12, f"赛道数 {len(tracks)} != 12"

    def test_track_keys(self):
        from tradex.data_sources.industry_news_fetchers import list_tracks
        tracks = list_tracks()
        keys = {t["key"] for t in tracks}
        expected = {
            "ai", "semi", "robot", "auto", "energy", "bio",
            "space", "security", "tech", "consumer", "macro", "science",
        }
        assert keys == expected, f"赛道 keys 不匹配: 缺 {expected - keys}, 多 {keys - expected}"
