"""QI-ARCH-10 缓存出口收拢行为锁定（2026-11-22，工单 09/10）。

get_or_set 迁移后调用方层语义锁定（接口层四语义点见 tests/test_cache_get_or_set.py）：
- 空态不入缓存（factory 返回 None，调用方重建空态 dict，每次重算）
- cache_hit 标注（out 回调）与条件缓存（store 闸门：decision.enabled）
- limit 截断不污染缓存全量（浅拷贝防御语义保真）
- 降级原因串不入缓存（store 闸门拒存 str，每次重算）

路由与缓存实例全部 monkeypatch 隔离，不触网。
"""

from types import SimpleNamespace

from tradex.utils.cache import TwoLevelCache


def _fresh_cache(monkeypatch, module, tmp_path) -> TwoLevelCache:
    """给目标模块换上独立缓存实例（隔离全局单例，无文件层）。"""
    c = TwoLevelCache(cache_dir=str(tmp_path / "c"), file_enabled=False)
    monkeypatch.setattr(module, "cache", c)
    return c


class TestMarketServiceEmptyState:
    """get_money_flow：空态早退改 factory None 后语义保真。"""

    def test_empty_recomputes_each_call(self, monkeypatch, tmp_path):
        from tradex.service import market_service

        c = _fresh_cache(monkeypatch, market_service, tmp_path)
        calls = []

        def fake_route(*args, **kwargs):
            calls.append(1)
            return {"realtime": [], "history": []}, "fake_src"

        monkeypatch.setattr(
            market_service, "_router", SimpleNamespace(route=fake_route)
        )

        expected = {
            "symbol": "600519",
            "rows": [],
            "message": "该股票暂无资金流向数据",
        }
        for _ in range(2):
            assert market_service.get_money_flow("600519") == expected
        assert len(calls) == 2  # 空态未冻结，两次都重算
        assert c.get("money_flow:600519") is None

    def test_non_empty_hit_caches(self, monkeypatch, tmp_path):
        from tradex.service import market_service

        _fresh_cache(monkeypatch, market_service, tmp_path)
        calls = []

        def fake_route(*args, **kwargs):
            calls.append(1)
            return {
                "realtime": [
                    {
                        "time": "09:30",
                        "main_net": 1.0,
                        "small": 0,
                        "mid": 0,
                        "large": 0,
                        "super_large": 0,
                    }
                ],
                "history": [],
            }, "fake_src"

        monkeypatch.setattr(
            market_service, "_router", SimpleNamespace(route=fake_route)
        )

        first = market_service.get_money_flow("600519")
        second = market_service.get_money_flow("600519")
        assert len(calls) == 1  # 第二次命中缓存
        assert second == first
        assert second["rows"][0]["主力净流入"] == 1.0


class TestBigcapsConditionalCache:
    """get_bigcaps：out 回调 cache_hit 标注 + store 闸门条件缓存 + 副本防御。"""

    def _fake_route(self, calls):
        def fake_route(*args, **kwargs):
            calls.append(1)
            return {
                "stocks": [{"code": "600519", "name": "贵州茅台"}],
                "as_of": "2026-11-21",
                "source": "fake_src",
                "source_note": "",
                "threshold_yi": 500,
                "unpriced": [],
            }, "fake_src"

        return fake_route

    def test_cache_hit_flag_and_no_pollution(self, monkeypatch, tmp_path):
        from tradex.service import bigcaps_service

        _fresh_cache(monkeypatch, bigcaps_service, tmp_path)
        calls = []
        monkeypatch.setattr(
            bigcaps_service, "_router", SimpleNamespace(route=self._fake_route(calls))
        )
        monkeypatch.setattr(
            bigcaps_service,
            "resolve_cache",
            lambda *a, **k: SimpleNamespace(enabled=True, ttl_seconds=60),
        )

        first = bigcaps_service.get_bigcaps(limit=0)
        assert first["cache_hit"] is False
        assert first["returned"] == 1
        second = bigcaps_service.get_bigcaps(limit=0)
        assert second["cache_hit"] is True  # out 回调标注
        assert len(calls) == 1  # 命中缓存
        assert second["count"] == 1  # 缓存全量未被 limit 截断污染

    def test_decision_disabled_never_caches(self, monkeypatch, tmp_path):
        from tradex.service import bigcaps_service

        c = _fresh_cache(monkeypatch, bigcaps_service, tmp_path)
        calls = []
        monkeypatch.setattr(
            bigcaps_service, "_router", SimpleNamespace(route=self._fake_route(calls))
        )
        monkeypatch.setattr(
            bigcaps_service,
            "resolve_cache",
            lambda *a, **k: SimpleNamespace(enabled=False, ttl_seconds=60),
        )

        bigcaps_service.get_bigcaps()
        bigcaps_service.get_bigcaps()
        assert len(calls) == 2  # store 闸门：enabled=False 不落缓存，每次重算
        assert c.stats["size"] == 0


class TestTurnoverHistoryStoreGate:
    """_try_history：降级原因串 store 闸门拒存（原样不入缓存）+ 结果 dict 正常缓存。"""

    def _patch(self, monkeypatch, tmp_path, route_impl):
        from tradex.service import turnover_service

        _fresh_cache(monkeypatch, turnover_service, tmp_path)
        monkeypatch.setattr(
            turnover_service, "_router", SimpleNamespace(route=route_impl)
        )
        monkeypatch.setattr(
            turnover_service,
            "resolve_cache",
            lambda *a, **k: SimpleNamespace(enabled=True, ttl_seconds=60),
        )

    def test_degradation_reason_not_cached(self, monkeypatch, tmp_path):
        from tradex.service import turnover_service

        calls = []

        def fake_route(*args, **kwargs):
            calls.append(1)
            raise RuntimeError("包未发布")

        self._patch(monkeypatch, tmp_path, fake_route)
        meta = SimpleNamespace(cache_policy="daily")

        reason1 = turnover_service._try_history("20261121", meta)
        reason2 = turnover_service._try_history("20261121", meta)
        assert isinstance(reason1, str) and "包未发布" in reason1
        assert reason2 == reason1
        assert len(calls) == 2  # 原因串不入缓存，每次重算

    def test_success_result_cached_with_cache_hit(self, monkeypatch, tmp_path):
        from tradex.service import turnover_service

        calls = []

        def fake_route(*args, **kwargs):
            calls.append(1)
            return {
                "rows": [
                    {
                        "market": "sh",
                        "code": "600519",
                        "name": "贵州茅台",
                        "amount": 1e9,
                        "prev_close": 100.0,
                        "close": 101.0,
                        "volume": 1000,
                    }
                ],
                "date": "20261121",
                "as_of": "x",
                "source": "fake_src",
                "source_url": "",
            }, "fake_src"

        self._patch(monkeypatch, tmp_path, fake_route)
        meta = SimpleNamespace(cache_policy="daily")

        first = turnover_service._try_history("20261121", meta)
        second = turnover_service._try_history("20261121", meta)
        assert isinstance(first, dict) and first["cache_hit"] is False
        assert second["cache_hit"] is True
        assert len(calls) == 1  # 结果 dict 入缓存，第二次命中
        assert second["stocks"][0]["code"] == "600519"
