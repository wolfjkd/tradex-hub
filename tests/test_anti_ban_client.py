"""Tests for astock_signals.anti_ban_client — 限流与并发安全。

验证 em_get 在锁外 sleep、set_min_interval / em_reset_session 功能，
以及 10 线程并发调用时实际请求间隔 ≥ EM_MIN_INTERVAL * 0.9（允许 10% 抖动）。
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from astock_signals import anti_ban_client
from astock_signals.anti_ban_client import (
    _em_last_call,
    em_get,
    em_reset_session,
    set_min_interval,
)


@pytest.fixture(autouse=True)
def reset_state():
    """每个测试前后重置全局状态。"""
    _em_last_call[0] = 0.0
    original_interval = anti_ban_client._EM_MIN_INTERVAL
    # 测试用较小间隔，避免单测耗时过长
    set_min_interval(0.3)
    yield
    set_min_interval(original_interval)
    _em_last_call[0] = 0.0
    em_reset_session()


def test_em_get_single_call_returns_response():
    """单线程调用 em_get 应返回 session.get() 的结果。"""
    mock_response = MagicMock(status_code=200)
    mock_session = MagicMock()
    mock_session.get.return_value = mock_response

    with patch(
        "astock_signals.anti_ban_client._ensure_session",
        return_value=mock_session,
    ):
        result = em_get("https://example.com/test", params={"k": "v"})

    assert result is mock_response
    mock_session.get.assert_called_once()
    # 验证参数透传
    _, kwargs = mock_session.get.call_args
    assert kwargs["params"] == {"k": "v"}
    assert kwargs["timeout"] == 15


def test_em_get_concurrent_intervals_meet_min_interval():
    """10 线程并发调用，实际请求间隔应 ≥ EM_MIN_INTERVAL * 0.9。"""

    call_times: list[float] = []
    times_lock = threading.Lock()

    def fake_get(*args, **kwargs):
        t = time.time()
        with times_lock:
            call_times.append(t)
        return MagicMock(status_code=200)

    mock_session = MagicMock()
    mock_session.get.side_effect = fake_get

    with patch(
        "astock_signals.anti_ban_client._ensure_session",
        return_value=mock_session,
    ):
        threads = [
            threading.Thread(target=em_get, args=("https://example.com/test",))
            for _ in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert len(call_times) == 10
    call_times.sort()
    intervals = [b - a for a, b in zip(call_times, call_times[1:])]
    min_interval = min(intervals)
    threshold = anti_ban_client._EM_MIN_INTERVAL * 0.9

    assert min_interval >= threshold, (
        f"最小请求间隔 {min_interval:.4f}s 小于阈值 {threshold:.4f}s "
        f"(EM_MIN_INTERVAL={anti_ban_client._EM_MIN_INTERVAL})，"
        f"全部间隔: {[f'{x:.4f}' for x in intervals]}"
    )


def test_set_min_interval_updates_global():
    """set_min_interval 应即时更新 _EM_MIN_INTERVAL。"""
    set_min_interval(0.5)
    assert anti_ban_client._EM_MIN_INTERVAL == 0.5
    set_min_interval(1.2)
    assert anti_ban_client._EM_MIN_INTERVAL == 1.2


def test_em_reset_session_closes_and_clears():
    """em_reset_session 应关闭旧 session 并将 _EM_SESSION 置空。"""
    mock_session = MagicMock()
    anti_ban_client._EM_SESSION = mock_session

    em_reset_session()

    mock_session.close.assert_called_once()
    assert anti_ban_client._EM_SESSION is None


def test_em_reset_session_no_session_is_noop():
    """em_reset_session 在 _EM_SESSION 为 None 时不应报错。"""
    anti_ban_client._EM_SESSION = None
    # 不应抛异常
    em_reset_session()
    assert anti_ban_client._EM_SESSION is None


def test_em_get_first_call_after_reset_no_long_wait():
    """重置后第一次调用不应等待（_em_last_call[0]=0 时 wait<0 归零）。"""
    _em_last_call[0] = 0.0
    set_min_interval(1.0)

    mock_session = MagicMock()
    mock_session.get.return_value = MagicMock(status_code=200)

    start = time.time()
    with patch(
        "astock_signals.anti_ban_client._ensure_session",
        return_value=mock_session,
    ):
        em_get("https://example.com/test")
    elapsed = time.time() - start

    # 首次调用 wait=1.0-(now-0)=很负→归零，只剩 jitter(0.1~0.5)
    assert elapsed < 0.8, f"首次调用耗时 {elapsed:.3f}s 过长，可能仍持锁 sleep"
