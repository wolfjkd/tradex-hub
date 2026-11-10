"""TwoLevelCache.get_or_set 深接口测试（2026-11-11 批次C4 Top）。

序列化边界收进缓存层：调用方一律传/收 Python 对象；
读时历史 JSON 字符串条目自动 loads 还原；写时对象直存；None 不缓存。
"""

import pytest

from tradex.utils.cache import TwoLevelCache


@pytest.fixture()
def c(tmp_path):
    return TwoLevelCache(cache_dir=str(tmp_path / "c"), file_enabled=True)


class TestGetOrSet:
    def test_miss_computes_and_caches(self, c):
        calls = []

        def factory():
            calls.append(1)
            return {"k": 1}

        assert c.get_or_set("a", factory, ttl=60) == {"k": 1}
        assert len(calls) == 1
        # 第二次命中缓存，factory 不再执行
        assert c.get_or_set("a", factory, ttl=60) == {"k": 1}
        assert len(calls) == 1

    def test_legacy_json_string_entry_loads(self, c):
        """历史 json.dumps 写入的 str 条目读出自动还原为对象。"""
        c.set("b", '{"x": 2}', ttl=60)
        assert c.get_or_set("b", lambda: {"x": 0}, ttl=60) == {"x": 2}

    def test_non_json_string_returned_as_is(self, c):
        """非 JSON 字符串条目（如纯文本）原样返回，不炸不吞。"""
        c.set("c", "普通文本", ttl=60)
        assert c.get_or_set("c", lambda: "x", ttl=60) == "普通文本"

    def test_none_result_not_cached(self, c):
        """factory 返回 None 不缓存（失败/空值不冻结语义）。"""
        calls = []

        def factory():
            calls.append(1)
            return None

        assert c.get_or_set("d", factory, ttl=60) is None
        assert c.get_or_set("d", factory, ttl=60) is None
        assert len(calls) == 2  # 每次都重算

    def test_factory_exception_propagates_and_not_cached(self, c):
        def factory():
            raise RuntimeError("source down")

        with pytest.raises(RuntimeError, match="source down"):
            c.get_or_set("e", factory, ttl=60)
        assert c.get("e") is None

    def test_object_write_survives_file_roundtrip(self, c, tmp_path):
        """对象直存 → 文件层 JSON 落盘 → 新实例读回同对象（持久化等价）。"""
        payload = {"list": [1, 2, 3], "s": "值"}
        c.set("f", payload, ttl=7200)  # >=1h 走文件层
        c2 = TwoLevelCache(cache_dir=str(tmp_path / "c"), file_enabled=True)
        c2._memory.clear()
        assert c2.get_or_set("f", lambda: None, ttl=7200) == payload
