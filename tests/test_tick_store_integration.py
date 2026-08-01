"""
TickStore 集成测试 — 验证 SQLite 持久化 + eltdx_get_ticks 工具的缓存逻辑。

测试范围:
  1. TickStore 初始化（SQLite 创建 _tick_meta 表）
  2. save_tick 写入数据
  3. load_tick 读取数据
  4. 元数据查询（list_dates / list_codes / get_stats）
  5. eltdx_get_ticks 工具缓存逻辑（第一次网络，第二次从缓存）

与 tests/test_tick_store.py（纯函数单测）的区别：
  - 本测试通过 FakeMCP 捕获 eltdx_data.register() 注册的 eltdx_get_ticks 工具
  - monkeypatch eltdx provider（_get_client / _get_tick_store）
  - 验证 eltdx_get_ticks 与 TickStore 的端到端缓存交互
  - 所有 SQLite 操作使用 tmp_path 临时目录，不污染项目 data/ 目录
"""

import os
import sys
import json
import sqlite3
import asyncio
from unittest.mock import MagicMock

import pytest

from astock_signals.tick_store import TickStore


# ---------------------------------------------------------------------------
# 路径设置：确保 cn_financial_mcp.tools.eltdx_data 可被 import
# ---------------------------------------------------------------------------
_CN_MCP_SRC = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "cn-financial-mcp", "src")
)
if _CN_MCP_SRC not in sys.path:
    sys.path.insert(0, _CN_MCP_SRC)

_HUB_SRC = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "src"))
if _HUB_SRC not in sys.path:
    sys.path.insert(0, _HUB_SRC)


# ---------------------------------------------------------------------------
# FakeMCP：捕获 register(mcp) 注册的工具函数
# ---------------------------------------------------------------------------
class FakeMCP:
    """模拟 FastMCP，捕获 @mcp.tool() 装饰的函数。"""

    def __init__(self):
        self.tools = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


# ---------------------------------------------------------------------------
# 测试用样例数据
# ---------------------------------------------------------------------------
_SAMPLE_TICKS = [
    {"time": "09:30:01", "price": 1800.0, "volume": 100, "amount": 180000.0,
     "direction": "buy", "bid1": 1799.90, "ask1": 1800.00},
    {"time": "09:30:02", "price": 1800.10, "volume": 200, "amount": 360020.0,
     "direction": "sell", "bid1": 1799.80, "ask1": 1800.10},
    {"time": "09:30:03", "price": 1799.90, "volume": 150, "amount": 269985.0,
     "direction": "buy", "bid1": 1799.90, "ask1": 1800.00},
]


class TestTickStoreInit:
    """TickStore 初始化。"""

    def test_init_creates_sqlite_db(self, tmp_path):
        """初始化后在指定路径创建 SQLite 数据库文件。"""
        db_path = str(tmp_path / "test_tick.db")
        store = TickStore(db_path=db_path)
        assert os.path.exists(db_path)

    def test_init_creates_meta_table(self, tmp_path):
        """初始化后 _tick_meta 表存在。"""
        db_path = str(tmp_path / "test_tick.db")
        store = TickStore(db_path=db_path)
        conn = sqlite3.connect(db_path)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='_tick_meta'"
        ).fetchall()
        conn.close()
        assert len(tables) == 1
        assert tables[0][0] == "_tick_meta"


class TestTickStoreSaveAndLoad:
    """save_tick / load_tick 写入读取。"""

    def test_save_tick_writes_data(self, tmp_path):
        """save_tick 写入数据并返回插入行数。"""
        store = TickStore(db_path=str(tmp_path / "test_tick.db"))
        inserted = store.save_tick("600519", "20260801", _SAMPLE_TICKS)
        assert inserted == 3

    def test_save_tick_creates_data_table(self, tmp_path):
        """save_tick 后对应的数据表存在。"""
        db_path = str(tmp_path / "test_tick.db")
        store = TickStore(db_path=db_path)
        store.save_tick("600519", "20260801", _SAMPLE_TICKS)
        conn = sqlite3.connect(db_path)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='tick_600519_20260801'"
        ).fetchall()
        conn.close()
        assert len(tables) == 1

    def test_load_tick_reads_data(self, tmp_path):
        """load_tick 返回写入的数据。"""
        store = TickStore(db_path=str(tmp_path / "test_tick.db"))
        store.save_tick("600519", "20260801", _SAMPLE_TICKS)
        df = store.load_tick("600519", "20260801")
        assert not df.empty
        assert len(df) == 3
        assert "time" in df.columns
        assert "price" in df.columns

    def test_load_tick_nonexistent_returns_empty(self, tmp_path):
        """读取不存在的数据返回空 DataFrame。"""
        store = TickStore(db_path=str(tmp_path / "test_tick.db"))
        df = store.load_tick("999999", "20260101")
        assert df.empty


class TestTickStoreMetadata:
    """元数据查询。"""

    def test_list_dates(self, tmp_path):
        """list_dates 返回已存储的日期列表。"""
        store = TickStore(db_path=str(tmp_path / "test_tick.db"))
        store.save_tick("600519", "20260801", _SAMPLE_TICKS)
        store.save_tick("600519", "20260802", _SAMPLE_TICKS)
        dates = store.list_dates("600519")
        assert len(dates) == 2
        assert "20260801" in dates
        assert "20260802" in dates

    def test_list_codes(self, tmp_path):
        """list_codes 返回已存储的代码列表。"""
        store = TickStore(db_path=str(tmp_path / "test_tick.db"))
        store.save_tick("600519", "20260801", _SAMPLE_TICKS)
        store.save_tick("000001", "20260801", _SAMPLE_TICKS)
        codes = store.list_codes()
        assert "600519" in codes
        assert "000001" in codes

    def test_get_stats(self, tmp_path):
        """get_stats 返回存储统计信息。"""
        store = TickStore(db_path=str(tmp_path / "test_tick.db"))
        store.save_tick("600519", "20260801", _SAMPLE_TICKS)
        stats = store.get_stats()
        assert len(stats) == 1
        assert stats[0]["code"] == "600519"
        assert stats[0]["trade_date"] == "20260801"
        assert stats[0]["row_count"] == 3


class TestEltdxGetTicksCacheLogic:
    """eltdx_get_ticks 工具的缓存逻辑集成测试。

    第一次调用：缓存为空 → 调用 eltdx provider → 异步写入 TickStore
    第二次调用：缓存命中 → 直接从 TickStore 返回，不调用 provider
    """

    def test_first_call_hits_network_second_call_from_cache(self, tmp_path, monkeypatch):
        """第一次调用走网络，第二次从缓存读取。"""
        from cn_financial_mcp.tools import eltdx_data

        # 准备临时 TickStore
        db_path = str(tmp_path / "cache_test.db")
        test_store = TickStore(db_path=db_path)

        # 准备 mock client（模拟 eltdx TdxClient）
        mock_tick_1 = MagicMock()
        mock_tick_1.time = "09:30:01"
        mock_tick_1.price = 1800.0
        mock_tick_1.volume = 100
        mock_tick_1.amount = 180000.0
        mock_tick_1.buy_or_sell = 0  # buy

        mock_tick_2 = MagicMock()
        mock_tick_2.time = "09:30:02"
        mock_tick_2.price = 1800.10
        mock_tick_2.volume = 200
        mock_tick_2.amount = 360020.0
        mock_tick_2.buy_or_sell = 1  # sell

        mock_result = MagicMock()
        mock_result.ticks = [mock_tick_1, mock_tick_2]

        mock_client = MagicMock()
        mock_client.trades.history.return_value = mock_result

        # monkeypatch eltdx_data 的 _get_client 和 _get_tick_store
        monkeypatch.setattr(eltdx_data, "_get_client", lambda: mock_client)
        monkeypatch.setattr(eltdx_data, "_get_tick_store", lambda: test_store)

        # 让 threading.Thread 同步执行（确保缓存写入完成）
        class _SyncThread:
            def __init__(self, target=None, args=(), kwargs=None, daemon=False):
                self._target = target
                self._args = args
                self._kwargs = kwargs or {}

            def start(self):
                if self._target:
                    self._target(*self._args, **self._kwargs)

            def join(self, timeout=None):
                pass

        monkeypatch.setattr(eltdx_data.threading, "Thread", _SyncThread)

        # 用 FakeMCP 捕获 eltdx_get_ticks 工具
        fake_mcp = FakeMCP()
        eltdx_data.register(fake_mcp)
        eltdx_get_ticks = fake_mcp.tools["eltdx_get_ticks"]

        # ── 第一次调用：缓存为空，走网络 ──
        result1 = asyncio.run(eltdx_get_ticks("600519", "20260801", count=100))
        data1 = json.loads(result1)
        assert data1["status"] == "success"
        assert data1["data"]["tick_count"] == 2
        assert mock_client.trades.history.call_count == 1

        # ── 第二次调用：缓存命中，不走网络 ──
        result2 = asyncio.run(eltdx_get_ticks("600519", "20260801", count=100))
        data2 = json.loads(result2)
        assert data2["status"] == "success"
        assert data2["data"]["tick_count"] == 2
        # 关键断言：网络调用次数仍为 1（第二次从缓存读取）
        assert mock_client.trades.history.call_count == 1

    def test_cache_returns_same_data_as_network(self, tmp_path, monkeypatch):
        """缓存返回的数据与网络返回的数据一致。"""
        from cn_financial_mcp.tools import eltdx_data

        db_path = str(tmp_path / "consistency_test.db")
        test_store = TickStore(db_path=db_path)

        mock_tick = MagicMock()
        mock_tick.time = "09:30:05"
        mock_tick.price = 1850.0
        mock_tick.volume = 300
        mock_tick.amount = 555000.0
        mock_tick.buy_or_sell = 0

        mock_result = MagicMock()
        mock_result.ticks = [mock_tick]

        mock_client = MagicMock()
        mock_client.trades.history.return_value = mock_result

        monkeypatch.setattr(eltdx_data, "_get_client", lambda: mock_client)
        monkeypatch.setattr(eltdx_data, "_get_tick_store", lambda: test_store)

        class _SyncThread:
            def __init__(self, target=None, args=(), kwargs=None, daemon=False):
                self._target = target
                self._args = args
                self._kwargs = kwargs or {}

            def start(self):
                if self._target:
                    self._target(*self._args, **self._kwargs)

            def join(self, timeout=None):
                pass

        monkeypatch.setattr(eltdx_data.threading, "Thread", _SyncThread)

        fake_mcp = FakeMCP()
        eltdx_data.register(fake_mcp)
        eltdx_get_ticks = fake_mcp.tools["eltdx_get_ticks"]

        # 第一次调用（网络）
        result1 = asyncio.run(eltdx_get_ticks("000001", "20260801", count=50))
        data1 = json.loads(result1)["data"]

        # 第二次调用（缓存）
        result2 = asyncio.run(eltdx_get_ticks("000001", "20260801", count=50))
        data2 = json.loads(result2)["data"]

        # 验证两次返回的 tick 数据一致
        assert data1["tick_count"] == data2["tick_count"]
        assert data1["ticks"][0]["price"] == data2["ticks"][0]["price"]
        assert data1["ticks"][0]["volume"] == data2["ticks"][0]["volume"]

    def test_no_cache_store_still_works(self, tmp_path, monkeypatch):
        """TickStore 不可用时（返回 None），eltdx_get_ticks 仍能正常工作。"""
        from cn_financial_mcp.tools import eltdx_data

        mock_tick = MagicMock()
        mock_tick.time = "09:30:01"
        mock_tick.price = 100.0
        mock_tick.volume = 10
        mock_tick.amount = 1000.0
        mock_tick.buy_or_sell = 0

        mock_result = MagicMock()
        mock_result.ticks = [mock_tick]

        mock_client = MagicMock()
        mock_client.trades.history.return_value = mock_result

        monkeypatch.setattr(eltdx_data, "_get_client", lambda: mock_client)
        monkeypatch.setattr(eltdx_data, "_get_tick_store", lambda: None)

        fake_mcp = FakeMCP()
        eltdx_data.register(fake_mcp)
        eltdx_get_ticks = fake_mcp.tools["eltdx_get_ticks"]

        result = asyncio.run(eltdx_get_ticks("600519", "20260801"))
        data = json.loads(result)
        assert data["status"] == "success"
        assert data["data"]["tick_count"] == 1
