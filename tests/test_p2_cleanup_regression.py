"""
P2 技术债清理回归单测（v3.3.11，B4/B5/B16/B17/B20/B22/B24）。

覆盖：
  - B4  : 腾讯行情前缀防重（_tencent_quote_vals 不拼接 szsh600000）
  - B5  : eltdx_stream 代理环境变量临时移除/恢复（不永久污染进程）
  - B16 : eltdx period 归一化（daily→day，非法值抛错）
  - B17 : EMA 通达信口径首值=X[0]（MACD/ATR 无前导 None）
  - B20 : signal_generation 收敛复用 technical_indicators 单一实现
  - B22 : 版本号语义化比较（1.10 > 1.9）
  - B24 : _market_cn/_pure_code 市场识别鲁棒（不静默 NaN）

全部离线，无网络依赖。
"""

from __future__ import annotations

import os
import sys

import pytest

# ── 路径设置 ──────────────────────────────────────────────────
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_PROJECT_ROOT, "tradex", "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from tradex.utils.data_source_monitor import _has_update  # noqa: E402
from tradex.data_sources import eltdx_fetchers as ef  # noqa: E402
from tradex.data_sources import http_fetchers as hf  # noqa: E402
from tradex.data_sources import eltdx_stream as es  # noqa: E402
from tradex.tools import signal_generation as sg  # noqa: E402


# ════════════════════════════════════════════════════════════════
# B22: 版本号语义化比较
# ════════════════════════════════════════════════════════════════

class TestVersionCompare:
    def test_one_ten_greater_than_one_nine(self):
        """1.10 > 1.9（字符串比较会误判，tuple 比较正确）。"""
        assert _has_update("1.9", "1.10") is True

    def test_equal_versions_no_update(self):
        assert _has_update("3.3.10", "3.3.10") is False

    def test_newer_major(self):
        assert _has_update("3.9.9", "4.0.0") is True

    def test_downgrade_is_not_update(self):
        """latest 更旧不算 has_update。"""
        assert _has_update("3.3.10", "3.3.9") is False

    def test_unknown_ignored(self):
        assert _has_update("unknown", "3.3.10") is False
        assert _has_update("3.3.10", "unknown") is False
        assert _has_update("", "3.3.10") is False

    def test_v_prefix_and_suffix_handled(self):
        """v1.2.3 / 1.2.3rc1 之类仍能数值比较主体。"""
        assert _has_update("v1.2.3", "1.2.4") is True


# ════════════════════════════════════════════════════════════════
# B16: eltdx period 归一化
# ════════════════════════════════════════════════════════════════

class TestNormalizePeriod:
    def test_daily_aliases_to_day(self):
        for p in ("day", "daily", "d", "1d", "DAY", " Daily "):
            assert ef._normalize_period(p) == "day", p

    def test_weekly_monthly_aliases(self):
        assert ef._normalize_period("weekly") == "week"
        assert ef._normalize_period("w") == "week"
        assert ef._normalize_period("monthly") == "month"
        assert ef._normalize_period("1m") == "month"

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            ef._normalize_period("hourly")
        with pytest.raises(ValueError):
            ef._normalize_period("")


# ════════════════════════════════════════════════════════════════
# B24: 市场代码识别鲁棒
# ════════════════════════════════════════════════════════════════

class TestMarketCn:
    @pytest.mark.parametrize("code,expected", [
        ("sh600000", "沪"),
        ("sz000001", "深"),
        ("bj430001", "京"),
        ("600519", "沪"),
        ("688981", "沪"),
        ("000001", "深"),
        ("300750", "深"),
        ("920001", "京"),
        ("430001", "京"),
        ("", ""),
        (None, ""),
        ("garbage", ""),
    ])
    def test_market_mapping(self, code, expected):
        assert ef._market_cn(code) == expected

    def test_no_silent_nan(self):
        """无法识别返回空串而非 NaN（不污染后续 map 结果）。"""
        assert ef._market_cn("zz1234") == ""

    @pytest.mark.parametrize("code,expected", [
        ("sh600000", "600000"),
        ("600000", "600000"),
        ("bj430001", "430001"),
    ])
    def test_pure_code(self, code, expected):
        assert ef._pure_code(code) == expected


# ════════════════════════════════════════════════════════════════
# B4: 腾讯行情前缀防重
# ════════════════════════════════════════════════════════════════

class TestTencentPrefixGuard:
    def test_url_no_double_prefix(self, monkeypatch):
        """已带前缀的代码不二次拼接（szsh600000 之类绝迹）。"""
        seen = {}

        class _FakeResp:
            def read(self):
                return 'v_sh600000="1~贵州茅台~600519~1500.0~1~2~3~4~5~6~7~8~9~10~11~12~13~14~15~16~17~18~19~20~21~22~23~24~25~26~27~28~29~30~31~32~33~34~35~36~37~38~39~40~41~42~43~44~45~46~47~48~49~50"'.encode("gbk")

        def fake_open(url, timeout=5):
            seen["url"] = url
            return _FakeResp()

        monkeypatch.setattr(hf, "_urlopen_no_proxy", fake_open)
        hf._tencent_quote_vals("sh600000")
        assert seen["url"] == "https://qt.gtimg.cn/q=sh600000"
        hf._tencent_quote_vals("600000")
        assert seen["url"] == "https://qt.gtimg.cn/q=sh600000"

    def test_sz_prefixed_kept(self, monkeypatch):
        seen = {}

        class _FakeResp:
            def read(self):
                return 'v_sz000001="1~平安银行~000001~10.0~1~2~3~4~5~6~7~8~9~10~11~12~13~14~15~16~17~18~19~20~21~22~23~24~25~26~27~28~29~30~31~32~33~34~35~36~37~38~39~40~41~42~43~44~45~46~47~48~49~50"'.encode("gbk")

        def fake_open(url, timeout=5):
            seen["url"] = url
            return _FakeResp()

        monkeypatch.setattr(hf, "_urlopen_no_proxy", fake_open)
        hf._tencent_quote_vals("sz000001")
        assert seen["url"] == "https://qt.gtimg.cn/q=sz000001"


# ════════════════════════════════════════════════════════════════
# B5: eltdx_stream 代理环境变量 临时移除/恢复
# ════════════════════════════════════════════════════════════════

class TestProxyEnvRestore:
    def test_remove_and_restore(self):
        os.environ["HTTP_PROXY"] = "http://127.0.0.1:7897"
        os.environ["HTTPS_PROXY"] = "http://127.0.0.1:7897"
        try:
            saved = es._without_proxy_env()
            assert "HTTP_PROXY" not in os.environ
            assert "HTTPS_PROXY" not in os.environ
            # 连接期间其他线程设置代理不应被清掉
            es._restore_env(saved)
            assert os.environ["HTTP_PROXY"] == "http://127.0.0.1:7897"
            assert os.environ["HTTPS_PROXY"] == "http://127.0.0.1:7897"
        finally:
            os.environ.pop("HTTP_PROXY", None)
            os.environ.pop("HTTPS_PROXY", None)

    def test_absent_keys_restored_as_absent(self):
        for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            os.environ.pop(k, None)
        saved = es._without_proxy_env()
        es._restore_env(saved)
        for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            assert k not in os.environ


# ════════════════════════════════════════════════════════════════
# B17+B20: EMA 通达信口径 + signal_generation 收敛到单一实现
# ════════════════════════════════════════════════════════════════

class TestEmaTdxAndConvergence:
    def test_signal_generation_no_duplicate_calcs(self):
        """B20: signal_generation 不再自带 MACD/KDJ/RSI/BOLL 重复实现。"""
        for name in ("_macd_calc", "_kdj_calc", "_rsi_calc", "_boll_calc"):
            assert not hasattr(sg, name), f"仍存在重复实现 {name}"

    def test_signal_generation_reuses_shared_values(self):
        """B20: 信号生成走 technical_indicators 同一实现且能正常产出。"""
        from tradex.tools import technical_indicators as ti
        assert sg._macd_values is ti._macd_values
        assert sg._kdj_values is ti._kdj_values
        assert sg._rsi_values is ti._rsi_values
        assert sg._boll_values is ti._boll_values

    def test_macd_arrays_fully_populated(self):
        """B17: MACD DIF/DEA/MACD 等长且全有效（无前导 None）。"""
        closes = [10.0 + i * 0.3 for i in range(40)]
        m = sg._macd_values(closes)
        assert len(m["dif"]) == len(m["dea"]) == len(m["macd"]) == 40
        assert all(v is not None for v in m["dif"])
        # MACD 柱 = 2*(DIF-DEA)
        for d, e, bar in zip(m["dif"], m["dea"], m["macd"]):
            assert bar == round(2 * (d - e), 4)

    def test_generate_signal_still_works(self):
        """收敛后 generate_trading_signal 主流程仍正常（回归护栏）。"""
        highs, lows, closes = [], [], []
        for i in range(60):
            c = round(10.0 + i * 0.2, 4)
            closes.append(c)
            highs.append(round(c + 0.2, 4))
            lows.append(round(c - 0.2, 4))
        result = sg._generate_signal_for_stock(highs, lows, closes)
        assert result["signal"] in {"strong_buy", "buy", "neutral", "sell", "strong_sell"}
        assert 0 <= result["score"] <= 100
