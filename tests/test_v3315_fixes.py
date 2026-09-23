"""v3.3.15 修复回归测试。

覆盖 4 组修复（全部离线可跑，不真连网）：
  P1-1  _prev_quarter_end 季度末真实日期（Q2/Q3 不再产出 20260631 / 20260931）
  P1-2  8 个 fetcher 静默吞异常 → 上抛（交由 SmartRouter 降级并计健康度）
  P2-1/P2-2  7 个「单源无兜底」数据类型的备源注册与优先级
  P4    备源适配器基本契约（fetch_hot_rank_ths / fetch_industry_comparison_ths）
"""

from datetime import datetime

import pandas as pd
import pytest
from unittest.mock import MagicMock

from tradex.data_sources import akshare_fetchers as akf
from tradex.data_sources.akshare_fetchers import (
    _prev_quarter_end,
    fetch_baidu_economic_calendar,
    fetch_baidu_trade_notify,
    fetch_futures_news,
    fetch_hot_search_baidu,
    fetch_hot_rank_data,
    fetch_xueqiu_hot,
    fetch_fund_hold_data,
    fetch_fund_hold_direct,
    fetch_industry_comparison_ths,
    fetch_hot_rank_ths,
)
from tradex.data_sources import ths_fetchers as ths_mod
from tradex.data_sources.registry import register_all_sources, get_router


# ============================================================
# P1-1: _prev_quarter_end 季度末真实日期
# ============================================================

class TestPrevQuarterEnd:
    """上一季度末必须落在真实存在的日期（6→30, 9→30, 12→31）。"""

    def test_specific_dates(self):
        # (today, expected) — 全部显式传参，不依赖当前系统时间
        cases = [
            (datetime(2026, 9, 14), "20260630"),   # Q3 的上一季
            (datetime(2026, 9, 30), "20260630"),
            (datetime(2026, 10, 1), "20260930"),    # 跨入 Q4
            (datetime(2026, 6, 30), "20260331"),     # Q2 上一季是 Q1
            (datetime(2026, 3, 31), "20251231"),     # 跨年：Q1 上一季是去年 Q4
            (datetime(2026, 1, 1), "20251231"),
            (datetime(2024, 4, 1), "20240331"),      # 闰年 2024
        ]
        for today, expected in cases:
            assert _prev_quarter_end(today) == expected, f"{today} → 期望 {expected}"

    def test_invalid_dates_never_produced(self):
        """关键回归：2026 全年 12 个月每月 15 日调用，结果必须全部合法，
        且永远不等于 20260631 / 20260931 这类不存在的日期。"""
        bad = {"20260631", "20260931"}
        for month in range(1, 13):
            s = _prev_quarter_end(datetime(2026, month, 15))
            # 能解析且不抛异常即合法日期
            dt = datetime.strptime(s, "%Y%m%d")
            assert s not in bad, f"第 {month} 月产出非法日期 {s}"
            assert dt.year == 2026 or dt.year == 2025, f"第 {month} 月年份异常: {s}"

    @pytest.mark.parametrize("year", [2024, 2025, 2026])
    @pytest.mark.parametrize("input_month,expect_month,expect_last", [
        (4, 3, 31),    # 上一季度末 = Q1 末（3月，31天）
        (7, 6, 30),    # 上一季度末 = Q2 末（6月，30天）
        (10, 9, 30),   # 上一季度末 = Q3 末（9月，30天）
        (1, 12, 31),   # 上一季度末 = 去年 Q4 末（12月，31天）
    ])
    def test_quarter_end_month_last_day(self, year, input_month, expect_month, expect_last):
        s = _prev_quarter_end(datetime(year, input_month, 15))
        dt = datetime.strptime(s, "%Y%m%d")
        assert dt.month == expect_month
        assert dt.day == expect_last


class TestFundHoldDefaultDate:
    """机构持仓未传 date 时默认走 _prev_quarter_end，日期必须合法。

    注：hold 分支已改由 fetch_fund_hold_direct 承担（akshare 列错位停用），
    故这里断言直取版传给东财的 date 参数。
    """

    def test_default_date_is_prev_quarter_end_and_parsable(self, monkeypatch):
        from tradex.data_sources import em_client

        captured = {}

        class _Resp:
            def json(self):
                return {"pages": 1, "data": [{
                    "SECURITY_CODE": "000680", "SECURITY_NAME_ABBR": "山推股份",
                    "HOULD_NUM": "4", "TOTAL_SHARES": "1", "HOLD_VALUE": "1",
                    "FREESHARES_RATIO": "1", "HOLDCHA": "减仓",
                    "HOLDCHA_NUM": "1", "HOLDCHA_RATIO": "1",
                }]}

        def fake_em_get(url, params=None, **kw):
            captured["params"] = params or {}
            return _Resp()

        monkeypatch.setattr(em_client, "em_get", fake_em_get)

        fetch_fund_hold_direct(endpoint="hold", symbol="社保持仓")  # 不传 date

        expected = _prev_quarter_end()
        # 直取版把 YYYYMMDD 转成东财要的 YYYY-MM-DD
        assert captured["params"]["date"] == (
            f"{expected[:4]}-{expected[4:6]}-{expected[6:]}"
        )
        # 必须能被 strptime 解析（即真实存在的日期），且不得是旧的非法形态
        datetime.strptime(expected, "%Y%m%d")
        assert not expected.endswith("0631"), f"{expected} 是非法日期（6月无31日）"
        assert not expected.endswith("0931"), f"{expected} 是非法日期（9月无31日）"


# ============================================================
# P1-2: 静默吞异常 → 上抛
# ============================================================

def _patch_ak_raising(monkeypatch, *attrs):
    """monkeypatch akshare_fetchers._ak 返回一个 stub，其 *attrs 各方法抛 RuntimeError。"""
    fake = MagicMock()
    for attr in attrs:
        setattr(fake, attr, MagicMock(side_effect=RuntimeError("upstream down")))
    monkeypatch.setattr(akf, "_ak", lambda: fake)
    return fake


class TestExceptionPropagation:
    """8 个 fetcher 原吞异常（return pd.DataFrame()），现必须向上抛出。"""

    def test_baidu_economic_calendar_raises(self, monkeypatch):
        _patch_ak_raising(monkeypatch, "news_economic_baidu")
        with pytest.raises(RuntimeError):
            fetch_baidu_economic_calendar()

    def test_baidu_trade_notify_raises(self, monkeypatch):
        # 默认 endpoint=suspend → ak.news_trade_notify_suspend_baidu（会走网络的分支）
        _patch_ak_raising(monkeypatch, "news_trade_notify_suspend_baidu")
        with pytest.raises(RuntimeError):
            fetch_baidu_trade_notify(endpoint="suspend")

    def test_index_news_sentiment_source_retired(self):
        """旧主源已退役：函数与配套 SSL hack 都必须真删干净，不能只是不注册。

        上游 chinascope 永久失效（301 跳官网首页返 HTML），留着这个源只会有害：
        每次白失败一次、污染健康度、且必须保留「篡改进程级 requests.Session.request
        的全局副作用」hack。所以断言的是「彻底移除」，不是「不注册」。
        """
        assert not hasattr(akf, "fetch_index_news_sentiment"), (
            "fetch_index_news_sentiment 应已删除（上游永久失效）"
        )
        assert not hasattr(akf, "_ssl_patch_lock"), (
            "_ssl_patch_lock 应随退役源一并删除（其唯一服务对象已不存在）"
        )
        # threading 若已无其他用途，模块属性也不该再被 import 进来
        assert not hasattr(akf, "threading"), (
            "akshare_fetchers 不应再 import threading（原先只服务于 _ssl_patch_lock）"
        )

    def test_futures_news_raises(self, monkeypatch):
        _patch_ak_raising(monkeypatch, "futures_news_shmet")
        with pytest.raises(RuntimeError):
            fetch_futures_news(symbol="全部")

    def test_hot_search_baidu_raises(self, monkeypatch):
        _patch_ak_raising(monkeypatch, "stock_hot_search_baidu")
        with pytest.raises(RuntimeError):
            fetch_hot_search_baidu()

    def test_hot_rank_data_raises(self, monkeypatch):
        # 默认 endpoint=rank → ak.stock_hot_rank_em（会走网络的分支）
        _patch_ak_raising(monkeypatch, "stock_hot_rank_em")
        with pytest.raises(RuntimeError):
            fetch_hot_rank_data(endpoint="rank")

    def test_xueqiu_hot_raises(self, monkeypatch):
        # 默认 endpoint=follow → ak.stock_hot_follow_xq（会走网络的分支）
        _patch_ak_raising(monkeypatch, "stock_hot_follow_xq")
        with pytest.raises(RuntimeError):
            fetch_xueqiu_hot(endpoint="follow")

    def test_fund_hold_data_detail_raises(self, monkeypatch):
        # hold 分支已改为直接 raise（akshare 列错位停用），故这里测 detail 分支：
        # detail → ak.stock_report_fund_hold_detail（会走网络的分支）
        _patch_ak_raising(monkeypatch, "stock_report_fund_hold_detail")
        with pytest.raises(RuntimeError):
            fetch_fund_hold_data(endpoint="detail", symbol="000001")

    def test_fund_hold_hold_branch_disabled(self):
        """akshare 的 hold 分支必须直接 raise，不能再作为兜底（否则会返回错标数据）。"""
        with pytest.raises(RuntimeError, match="列已错位"):
            fetch_fund_hold_data(endpoint="hold")


# ============================================================
# P2-1/P2-2: 备源注册与优先级
# ============================================================

# (data_type, source_name, expected_priority)
NEW_SOURCES = [
    ("industry_comparison", "ths_flow", 200),
    ("baidu_economic_calendar", "akshare_report_time", 100),
    ("baidu_trade_notify", "akshare_tfp", 100),
    ("hot_rank", "ths_hot", 100),
    ("hot_search", "ths_hot", 100),
    ("xueqiu_hot", "ths_hot", 100),
    ("index_news_sentiment", "legu_activity", 1),       # 旧主源退役后提为主源
    ("index_news_sentiment", "ths_distribution", 100),  # 跨上游备源（同花顺）
]
# 刻意保持单源的类型（未过度改动护栏）
#   - futures_news：上游上海有色网，akshare 无等价第二源
#   （fund_hold 原为单源，因 akshare 列错位已改为 em_zlsj_direct 主 + akshare 备，故移出）
SINGLE_SOURCE_TYPES = ["futures_news"]


def _source_priority(router, data_type, name):
    for (n, _fn, p, _e) in router._sources.get(data_type, []):
        if n == name:
            return p
    raise AssertionError(f"{data_type}:{name} 未在注册表中找到")


@pytest.fixture(scope="class")
def router():
    register_all_sources()  # 幂等，可安全多次调用
    return get_router()


class TestBackupSourceRegistration:
    """备源注册必须就位，且总注册数 94 → 101。

    NEW_SOURCES 的语义已从「v3.3.15 补的 7 个备源」演进为「v3.3.15 补的备源 +
    指数情绪源重装」：index_news_sentiment 因旧主源（chinascope）永久失效而
    整体重装 —— legu_activity 由备源(100)提为主源(1)，另补 ths_distribution(100)。
    该重装为「删一源 + 加一源」，故总数仍为 101。
    """

    def test_total_data_types(self, router):
        # 数据类型数：78（基线）→ 80（v0.1.0-DEV tdx_mcp 新增 screener / research_report 两类型；
        #   macro_data 为既有类型加源，不计入）
        # 2026-09-23 东财 push2 族退役：5 个类型因此变裸类型（无源）被 SmartRouter
        # 自动从 _sources 移除 → 80 - 5 = 75：
        #   industry_quotes / concept_attribution / market_breadth /
        #   limit_up_board / stock_boards
        assert len(router._sources) == 75

    def test_total_registrations(self, router):
        # 总注册数演进：90 → 94（v3.3.14）→ 101（v3.3.15）
        #   → 102（fund_hold 由单源升为 em_zlsj_direct + akshare 双源）
        #   → 107（v0.1.0-DEV tdx_mcp 新增 5 源：realtime/kline/screener/research/macro）
        #   → 100（2026-09-23 东财 push2 族退役：删 7 个注册点；
        #          news_data:em_news_direct 由 P1 改 P999 保留，算 1 个）
        assert sum(len(v) for v in router._sources.values()) == 100

    def test_new_sources_registered_with_priority(self, router):
        for data_type, name, prio in NEW_SOURCES:
            names = {n for (n, _fn, _p, _e) in router._sources.get(data_type, [])}
            assert name in names, f"{data_type} 缺少备源 {name}"
            assert _source_priority(router, data_type, name) == prio

    def test_backup_has_at_least_two_sources(self, router):
        for data_type, _name, _prio in NEW_SOURCES:
            sources = router._sources.get(data_type, [])
            assert len(sources) >= 2, f"{data_type} 源数量应 >= 2，实际 {len(sources)}"

    def test_fund_hold_and_futures_news_remain_single(self, router):
        for dt in SINGLE_SOURCE_TYPES:
            assert len(router._sources.get(dt, [])) == 1, f"{dt} 应仍为单源"


# ============================================================
# 机构持仓直取版（修复 akshare 列错位）
# ============================================================

class TestFundHoldDirect:
    """fetch_fund_hold_direct 按**字段名**映射列，且对列错位有守卫。"""

    def test_hold_maps_by_field_name_not_position(self, monkeypatch):
        """上游字段顺序被打乱，输出列语义仍必须正确 —— 这是本次修复的核心。"""
        from tradex.data_sources import em_client

        # 故意用**乱序**字段 + 夹带无关字段，模拟上游改版
        payload = {
            "pages": 1,
            "data": [{
                "HOLDCHA_RATIO": "-21.36",
                "SECURITY_NAME_ABBR": "山推股份",
                "UNRELATED_NOISE": "x",
                "SECURITY_CODE": "000680",
                "HOULD_NUM": "4",
                "TOTAL_SHARES": "87893360",
                "HOLD_VALUE": "883328268",
                "FREESHARES_RATIO": "6.68608925",
                "HOLDCHA": "减仓",
                "HOLDCHA_NUM": "-23868601",
            }],
        }

        class _Resp:
            def json(self):
                return payload

        monkeypatch.setattr(em_client, "em_get", lambda *a, **k: _Resp())
        df = akf.fetch_fund_hold_direct(endpoint="hold", symbol="社保持仓",
                                       date="20260630")
        row = df.iloc[0]
        assert row["股票代码"] == "000680"        # 不能是市值
        assert row["股票简称"] == "山推股份"       # 不能是代码
        assert row["持股变化"] == "减仓"           # 方向文本在方向列
        assert row["持股变动数值"] == -23868601    # 数值列是数值
        assert row["持股变动比例"] == -21.36
        assert row["持有基金家数"] == 4
        assert row["持股占流通股比"] == 6.68608925

    def test_misaligned_code_column_raises(self, monkeypatch):
        """守卫：股票代码列若拿到非 6 位数字（上游再改字段的典型征兆），
        必须抛错而不是把错标数据交给下游。"""
        from tradex.data_sources import em_client

        payload = {"pages": 1, "data": [{
            "SECURITY_CODE": "-415345718.82",   # 正是 akshare 错位时的表现
            "SECURITY_NAME_ABBR": "000680",
            "HOULD_NUM": "03", "TOTAL_SHARES": "4", "HOLD_VALUE": "87893360",
            "FREESHARES_RATIO": "6.68608925",
            "HOLDCHA": "减仓", "HOLDCHA_NUM": "-23868601", "HOLDCHA_RATIO": "-21.36",
        }]}

        class _Resp:
            def json(self):
                return payload

        monkeypatch.setattr(em_client, "em_get", lambda *a, **k: _Resp())
        with pytest.raises(RuntimeError, match="股票代码列异常"):
            akf.fetch_fund_hold_direct(endpoint="hold", symbol="社保持仓",
                                       date="20260630")

    def test_detail_endpoint_not_supported(self):
        """detail 不属于直取版职责，必须显式抛错让路由降级到 akshare。"""
        with pytest.raises(ValueError, match="仅支持 endpoint='hold'"):
            akf.fetch_fund_hold_direct(endpoint="detail", symbol="000001")

    def test_unknown_symbol_raises(self):
        with pytest.raises(ValueError, match="未知机构类型"):
            akf.fetch_fund_hold_direct(endpoint="hold", symbol="不存在的机构")


# ============================================================
# P4: 备源适配器基本契约
# ============================================================

class TestBackupAdapterContracts:
    """fetch_hot_rank_ths / fetch_industry_comparison_ths 的契约。"""

    def test_hot_rank_ths_unsupported_endpoint_raises(self):
        # 个股维度 endpoint 同花顺热榜无法替代 → 必须抛错（源码为 ValueError）
        for bad in ("detail", "realtime", "keyword", "latest", "relate"):
            with pytest.raises(ValueError):
                fetch_hot_rank_ths(endpoint=bad)

    def test_hot_rank_ths_supported_endpoint_returns_df(self, monkeypatch):
        # 支持的 endpoint 经 ths_fetchers.fetch_ths_hot_list 拿全市场榜
        df = pd.DataFrame({"排名": [1], "代码": ["600000"], "名称": ["浦发银行"]})
        monkeypatch.setattr(ths_mod, "fetch_ths_hot_list", lambda period: df)
        result = fetch_hot_rank_ths(endpoint="rank")
        assert isinstance(result, pd.DataFrame)
        assert not result.empty

    def test_industry_comparison_ths_structure(self, monkeypatch):
        df = pd.DataFrame({
            "行业": ["银行", "半导体"],
            "行业-涨跌幅": [1.5, -0.8],
            "领涨股": ["工商银行", "中芯国际"],
        })
        fake_ak = MagicMock()
        fake_ak.stock_fund_flow_industry.return_value = df
        monkeypatch.setattr(akf, "_ak", lambda: fake_ak)

        result = fetch_industry_comparison_ths()
        assert set(["source", "date", "code", "industries"]).issubset(result.keys())
        assert isinstance(result["industries"], list)
        assert len(result["industries"]) >= 1
        first = result["industries"][0]
        assert set(
            ["rank", "name", "change_pct", "up_count", "down_count", "leader"]
        ).issubset(first.keys())

    def test_industry_comparison_ths_empty_raises(self, monkeypatch):
        fake_ak = MagicMock()
        fake_ak.stock_fund_flow_industry.return_value = pd.DataFrame()
        monkeypatch.setattr(akf, "_ak", lambda: fake_ak)
        with pytest.raises(RuntimeError):
            fetch_industry_comparison_ths()


# ============================================================
# 机构持仓路由超时（基金持仓全量 11 页 > 路由默认 12s）
# ============================================================

class _MockMCP:
    """捕获 register() 中通过 @mcp.tool() 注册的 async 工具函数。"""

    def __init__(self) -> None:
        self.tools: dict = {}

    def tool(self):
        def decorator(func):
            self.tools[func.__name__] = func
            return func
        return decorator


def _capture_news_tools():
    from tradex.tools import news_events

    m = _MockMCP()
    news_events.register(m)
    return news_events, m.tools


class TestFundHoldRouteTimeout:
    """get_fund_hold 必须以**放宽后**的超时调用路由。

    背景：hold 分支走 em_zlsj_direct 的**全量翻页**，东财接口 pageSize 硬顶 500，
    「基金持仓」5311 行 / 11 页实测 ~17s，用路由默认 12s 会稳定超时；
    而「基金持仓」恰是 get_fund_hold 的**默认 symbol**，即无参调用必挂。
    """

    def test_route_called_with_relaxed_timeout(self, monkeypatch):
        import asyncio
        import json

        from tradex.utils.cache import cache

        cache.clear()  # 防止缓存命中导致 route 根本不被调用

        seen: dict = {}

        class _RecRouter:
            def route(self, data_type, timeout=None, **kw):
                seen["data_type"] = data_type
                seen["timeout"] = timeout
                seen["kwargs"] = kw
                return pd.DataFrame({
                    "序号": [1],
                    "股票代码": ["300308"],
                    "股票简称": ["中际旭创"],
                }), "em_zlsj_direct"

        news_events, tools = _capture_news_tools()
        monkeypatch.setattr(news_events, "_router", _RecRouter())

        raw = asyncio.run(tools["get_fund_hold"]())
        payload = json.loads(raw)

        assert seen["data_type"] == "fund_hold"
        assert seen["timeout"] == news_events._FUND_HOLD_ROUTE_TIMEOUT
        # 必须显著高于路由默认 12s，否则基金持仓仍会超时
        assert seen["timeout"] >= 30.0
        # 参数仍应原样透传
        assert seen["kwargs"] == {"endpoint": "hold", "symbol": "基金持仓"}
        assert payload[0]["股票代码"] == "300308"

    def test_default_symbol_is_the_slow_one(self):
        """无参调用的默认 symbol 就是「基金持仓」——正是最慢的那条，
        故超时放宽是必须项，而非可选优化。"""
        import inspect

        _news_events, tools = _capture_news_tools()
        sig = inspect.signature(tools["get_fund_hold"])
        assert sig.parameters["symbol"].default == "基金持仓"
        assert sig.parameters["endpoint"].default == "hold"
