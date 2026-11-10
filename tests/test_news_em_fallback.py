"""news_data/stock_news_em ArrowInvalid 转调防御测试（2026-11-11 批次B①）。

背景：akshare 库内 bug × pyarrow 环境——stock_news_em 内部
`.str.replace(r"\\u3000",…, regex=True)` 的 RE2/pyarrow 正则内核不支持
`\\u` 转义 → ArrowInvalid("invalid escape sequence")。hub venv 无 pyarrow
不触发；装了 pyarrow 的下游环境（如 TradeX）必炸。

防御：捕获该特征异常转调 news_fetchers.fetch_em_news_direct（同 schema
兜底，registry 里本就是 news_data 的 P999 备源）。红回路：monkeypatch
主源抛 ArrowInvalid 断言降级成功。
"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


class _FakeArrowInvalid(Exception):
    """模拟 pyarrow ArrowInvalid（hub venv 无 pyarrow，按类型名+消息判定）。"""


def _boom_arrow_invalid(*args, **kwargs):
    raise _FakeArrowInvalid(
        "Invalid index: (invalid escape sequence: '\\u3000')..."
    )


def _boom_other(symbol: str, **kwargs):
    raise ConnectionError("em api 502")  # 非本 bug 特征，必须照常上抛


def _sentinel_df() -> pd.DataFrame:
    return pd.DataFrame(
        [{"新闻标题": "直连标题", "发布时间": "2026-11-11 09:30:00"}]
    )


@pytest.fixture()
def sentinel():
    return _sentinel_df()


class TestStockNewsEmArrowInvalidFallback:
    def test_arrow_invalid_falls_back_to_em_direct(self, sentinel):
        """主源抛 ArrowInvalid 特征异常 → 转调 em_news_direct 返回其结果。"""
        from tradex.data_sources import akshare_fetchers as akf
        from tradex.data_sources import news_fetchers as nf

        fake_ak = MagicMock()
        fake_ak.stock_news_em = _boom_arrow_invalid
        with patch.object(akf, "_ak", return_value=fake_ak), patch.object(
            nf, "fetch_em_news_direct", return_value=sentinel
        ) as mock_direct:
            df = akf.fetch_news_data(endpoint="stock_news_em", symbol="600519")
        assert df is sentinel or df.equals(sentinel)
        mock_direct.assert_called_once()
        assert mock_direct.call_args.kwargs.get("symbol") == "600519"

    def test_other_errors_propagate(self):
        """非该 bug 特征的异常照常上抛（SmartRouter 记账降级纪律）。"""
        from tradex.data_sources import akshare_fetchers as akf

        fake_ak = MagicMock()
        fake_ak.stock_news_em = _boom_other
        with patch.object(akf, "_ak", return_value=fake_ak), patch(
            "tradex.data_sources.news_fetchers.fetch_em_news_direct"
        ) as mock_direct:
            with pytest.raises(ConnectionError):
                akf.fetch_news_data(endpoint="stock_news_em", symbol="600519")
        mock_direct.assert_not_called()

    def test_other_endpoints_unaffected(self, sentinel):
        """防御只挂 stock_news_em，其余 endpoint 行为不变。"""
        from tradex.data_sources import akshare_fetchers as akf

        fake_ak = MagicMock()
        fake_ak.news_cctv = _boom_arrow_invalid
        with patch.object(akf, "_ak", return_value=fake_ak):
            with pytest.raises(_FakeArrowInvalid):
                akf.fetch_news_data(endpoint="news_cctv", date="2026-11-10")

    def test_fallback_failure_propagates(self):
        """兜底也失败 → 兜底异常上抛（不做二次吞并）。"""
        from tradex.data_sources import akshare_fetchers as akf
        from tradex.data_sources import news_fetchers as nf

        fake_ak = MagicMock()
        fake_ak.stock_news_em = _boom_arrow_invalid
        with patch.object(akf, "_ak", return_value=fake_ak), patch.object(
            nf, "fetch_em_news_direct", side_effect=ConnectionError("em down")
        ):
            with pytest.raises(ConnectionError, match="em down"):
                akf.fetch_news_data(endpoint="stock_news_em", symbol="600519")
