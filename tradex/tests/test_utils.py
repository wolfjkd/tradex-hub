"""
Tests for utility modules (cache, formatter, symbol).
"""

import json
import time

import pandas as pd
import pytest

from tradex.utils.cache import TTLCache
from tradex.utils.formatter import df_to_json, dict_to_json, error_response
from tradex.utils.symbol import (
    format_with_exchange,
    get_exchange,
    get_market_name,
    is_valid_a_share_code,
    normalize_symbol,
)


# === cache.py tests ===

class TestTTLCache:
    def test_set_and_get(self):
        c = TTLCache()
        c.set("key1", "value1", ttl=60)
        assert c.get("key1") == "value1"

    def test_expired_entry(self):
        c = TTLCache()
        c.set("key1", "value1", ttl=0)
        time.sleep(0.01)
        assert c.get("key1") is None

    def test_missing_key(self):
        c = TTLCache()
        assert c.get("nonexistent") is None

    def test_invalidate(self):
        c = TTLCache()
        c.set("key1", "value1", ttl=60)
        c.invalidate("key1")
        assert c.get("key1") is None

    def test_clear(self):
        c = TTLCache()
        c.set("k1", "v1", ttl=60)
        c.set("k2", "v2", ttl=60)
        c.clear()
        assert c.size == 0

    def test_cleanup(self):
        c = TTLCache()
        c.set("expired", "val", ttl=0)
        c.set("valid", "val", ttl=60)
        time.sleep(0.01)
        removed = c.cleanup()
        assert removed == 1
        assert c.get("valid") == "val"


# === formatter.py tests ===

class TestFormatter:
    def test_df_to_json_basic(self):
        df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
        result = json.loads(df_to_json(df))
        assert len(result) == 2
        assert result[0]["a"] == 1

    def test_df_to_json_empty(self):
        df = pd.DataFrame()
        result = json.loads(df_to_json(df))
        assert result == []

    def test_df_to_json_max_rows(self):
        df = pd.DataFrame({"a": range(100)})
        result = json.loads(df_to_json(df, max_rows=5))
        assert len(result) == 5

    def test_dict_to_json(self):
        data = {"name": "贵州茅台", "code": "600519"}
        result = json.loads(dict_to_json(data))
        assert result["name"] == "贵州茅台"

    def test_error_response(self):
        result = json.loads(error_response("test error", "test_tool"))
        assert result["error"] is True
        assert "test error" in result["message"]
        assert result["tool"] == "test_tool"


# === symbol.py tests ===

class TestSymbol:
    def test_normalize_basic(self):
        assert normalize_symbol("600519") == "600519"
        assert normalize_symbol("000001") == "000001"

    def test_normalize_with_prefix(self):
        assert normalize_symbol("sh600519") == "600519"
        assert normalize_symbol("SZ000001") == "000001"
        assert normalize_symbol("SH.600519") == "600519"

    def test_normalize_short_code(self):
        assert normalize_symbol("1") == "000001"

    def test_get_exchange(self):
        assert get_exchange("600519") == "sh"
        assert get_exchange("000001") == "sz"
        assert get_exchange("300750") == "sz"
        assert get_exchange("688981") == "sh"

    def test_get_market_name(self):
        assert "上交所" in get_market_name("600519")
        assert "深交所" in get_market_name("000001")
        assert "创业板" in get_market_name("300750")
        assert "科创板" in get_market_name("688981")

    def test_format_with_exchange(self):
        assert format_with_exchange("600519") == "sh600519"
        assert format_with_exchange("000001") == "sz000001"

    def test_is_valid(self):
        assert is_valid_a_share_code("600519") is True
        assert is_valid_a_share_code("000001") is True
        assert is_valid_a_share_code("300750") is True
        assert is_valid_a_share_code("688981") is True
        assert is_valid_a_share_code("999999") is False
        assert is_valid_a_share_code("abcdef") is False
