# -*- coding: utf-8 -*-
"""大智慧365 本地 WS fetcher 测试（协议来源：dzh-queue 破译 + 2026-11-14 IX*.index 新破译）"""

import json
import time
from unittest.mock import patch

import pytest

from tradex.data_sources import dzh_fetchers
from tradex.data_sources.dzh_fetchers import _parse_dyna, fetch_dzh_index_quote

# IXKS11 真实捕获帧（2026-11-14 WS 实测）
_HEAD = ["obj", "time", "avgvolume", "lastclose", "open", "high", "low", "new", "volume", "amount"]
_ROW = ["IXKS11.index", "1794580340", "0.000000", "5342.729980", "5452.410156",
        "5504.439941", "5259.089844", "5290.529785", "237339.000000", "0.000000"]


class TestParseDyna:
    def test_point_and_lastclose(self):
        q = _parse_dyna(_HEAD, _ROW)
        assert q["point"] == pytest.approx(5290.529785)
        assert q["lastclose"] == pytest.approx(5342.729980)

    def test_pct_cross_checked_with_em(self):
        # pct 与东财全球指数表交叉验证一致（-0.98%）
        q = _parse_dyna(_HEAD, _ROW)
        assert q["pct"] == pytest.approx(-0.98)

    def test_global_index_amount_zero(self):
        # 全球指数无成交额 → amount=0（前端隐藏成交额行，不编造）
        q = _parse_dyna(_HEAD, _ROW)
        assert q["amount"] == 0.0

    def test_missing_fields_tolerated(self):
        q = _parse_dyna(["obj", "new"], ["IXKS11.index", "5100.0"])
        assert q["point"] == 5100.0
        assert q["pct"] is None  # 无 lastclose 不算 pct（不编造）


class _FakeWS:
    """WS 桩：recv 按 seq 依次返回字符串帧 / 抛异常。"""

    def __init__(self, seq):
        self._seq = iter(seq)
        self.closed = False

    def send(self, q):
        pass

    def settimeout(self, t):
        pass

    def recv(self):
        step = next(self._seq)
        if isinstance(step, Exception):
            raise step
        return step

    def close(self):
        self.closed = True


_FRAME = json.dumps({"head": _HEAD, "datas": [[_ROW]]})


class TestSendRecvBehaviorLock:
    """D①/QI-STD-94 行为锁定闭合（2026-11-18 施工）。

    dzh dyna 协议响应帧 {head, datas} **无请求-响应关联字段**（req 镜像/id 类）
    可回显比对——按施工单 D① 预置分支二：「超时 + 断连重建」现行为以回归测试
    锁定并文档化闭合（台账条目改记 closed，复查条件不变：handler 改保持连接、
    响应帧出现关联字段时再升级为比对校验）。
    """

    @staticmethod
    def _fake_get_ws(ws_queue):
        """模拟真实 _get_ws 语义：按队列依次取新连接，存全局 _ws 再返回
        （except 分支的断连重建检查的是全局 _ws，测试桩必须还原这个副作用）。"""
        it = iter(ws_queue)

        def _get():
            ws = next(it)
            dzh_fetchers._ws = ws
            return ws

        return _get

    def test_timeout_then_rebuild_second_attempt_succeeds(self, monkeypatch):
        """首次超时 → 断连重建（close + _ws=None）→ 重试命中。"""
        monkeypatch.setattr(dzh_fetchers, "_fail_until", 0.0)
        monkeypatch.setattr(dzh_fetchers, "_ws", None)
        ws1 = _FakeWS([TimeoutError("stale conn")])
        ws2 = _FakeWS([_FRAME])
        with patch.object(
            dzh_fetchers, "_get_ws", side_effect=self._fake_get_ws([ws1, ws2])
        ):
            q = fetch_dzh_index_quote("IXKS11.index")
        assert q["point"] == pytest.approx(5290.529785)
        assert ws1.closed, "半开连接必须被显式断连重建"
        assert dzh_fetchers._ws is ws2, "重建成功后保持新连接供下次复用"

    def test_double_failure_enters_cooldown(self, monkeypatch):
        """连续两帧超时 → 冷却期进入（不打本地 WS）→ {} 诚实空态。"""
        monkeypatch.setattr(dzh_fetchers, "_fail_until", 0.0)
        monkeypatch.setattr(dzh_fetchers, "_ws", None)
        ws1 = _FakeWS([TimeoutError("t1")])
        ws2 = _FakeWS([TimeoutError("t2")])
        with patch.object(
            dzh_fetchers, "_get_ws", side_effect=self._fake_get_ws([ws1, ws2])
        ):
            q = fetch_dzh_index_quote("IXKS11.index")
        assert q == {}
        assert dzh_fetchers._fail_until > time.time()
        assert ws1.closed and ws2.closed

    def test_cooldown_short_circuits_no_ws_call(self, monkeypatch):
        """冷却期内直接 {}，不打本地 WS（DZH365 未运行场景不空耗）。"""
        monkeypatch.setattr(dzh_fetchers, "_fail_until", time.time() + 100.0)
        with patch.object(dzh_fetchers, "_get_ws", side_effect=AssertionError("cooldown 内不得建连")):
            q = fetch_dzh_index_quote("IXKS11.index")
        assert q == {}

    def test_empty_frame_yields_empty_dict(self, monkeypatch):
        """head/datas 空响应帧 → {}（诚实空态，不编造）。"""
        monkeypatch.setattr(dzh_fetchers, "_fail_until", 0.0)
        monkeypatch.setattr(dzh_fetchers, "_ws", None)
        ws = _FakeWS([json.dumps({"head": [], "datas": []})])
        with patch.object(dzh_fetchers, "_get_ws", return_value=ws):
            q = fetch_dzh_index_quote("IXKS11.index")
        assert q == {}
