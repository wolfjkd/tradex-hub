"""
fetch_profit_forecast 回归测试（QI-BUG-01，2026-11-22）。

背景：函数内引用未定义名 prefix → NameError 被函数尾部 except 吞成
valuation_note → 返回 dict 被 SmartRouter 记成功 → 备源永不接管，
前瞻估值六字段（price / pe_ttm / forward_pe / peg / eps_cagr /
pe_digestion_years）静默失效。本文件 mock 同花顺 HTML 与腾讯行情
响应做回归钉（rule 4：mock 隔离网络，不标 network）。
"""

from unittest.mock import MagicMock, patch

import pytest

# 同花顺 worth.html 结构样例：tip 段 + thead（年度/预测机构数/...）+ tbody 两年预测
THS_HTML = """<html><body>
<p class="tip">综合评估：目标价 66 元。</p>
<table>
<thead><tr><th>年度</th><th>预测机构数</th><th>每股收益低</th><th>每股收益均</th><th>每股收益高</th><th>行业平均</th></tr></thead>
<tbody>
<tr><th>2026</th><td>10</td><td>0.90</td><td>1.00</td><td>1.10</td><td>1.20</td></tr>
<tr><th>2027</th><td>8</td><td>1.20</td><td>1.30</td><td>1.40</td><td>1.25</td></tr>
</tbody>
</table>
</body></html>"""


def _tencent_raw() -> bytes:
    """腾讯 qt.gtimg.cn 响应体（~ 分隔；vals[3]=价格、vals[39]=PE，len>=53）。"""
    fields = [""] * 60
    fields[0] = "1"
    fields[1] = "上海建工"
    fields[2] = "600170"
    fields[3] = "60.00"
    fields[39] = "45.00"
    return ('v_sh600170="' + "~".join(fields) + '";').encode("gbk")


def _mock_html_resp(text: str):
    resp = MagicMock()
    resp.text = text
    return resp


class TestFetchProfitForecast:
    def test_six_valuation_fields_produced(self):
        """同花顺成功 → 六字段产出真实解析值（QI-BUG-01：修前 NameError 红、修后绿）。"""
        from tradex.data_sources.akshare_fetchers import fetch_profit_forecast

        mock_opener = MagicMock()
        mock_opener.open.return_value.read.return_value = _tencent_raw()
        with patch(
            "requests.Session.get", return_value=_mock_html_resp(THS_HTML)
        ), patch("urllib.request.build_opener", return_value=mock_opener):
            result = fetch_profit_forecast(symbol="600170")

        assert result["price"] == 60.0
        assert result["pe_ttm"] == 45.0
        assert result["forward_pe"] == 60.0  # 60.0 / eps_cur(1.0)
        assert result["peg"] == 2.0  # fwd_pe / (cagr*100) = 60/30
        assert result["eps_cagr"] == 30.0  # 1.3/1.0 - 1
        assert result["pe_digestion_years"] == pytest.approx(2.6, abs=0.05)
        assert "valuation_note" not in result
        # 腾讯行情 URL 的代码必须带交易所前缀（_prefixed_code）
        req = mock_opener.open.call_args[0][0]
        assert req.full_url == "https://qt.gtimg.cn/q=sh600170"

    def test_ths_failure_raises_for_router_degrade(self):
        """主源抓取失败必须抛出——SmartRouter 只有接到异常才记失败并降级备源。"""
        from tradex.data_sources.akshare_fetchers import fetch_profit_forecast

        with patch("requests.Session.get", side_effect=ConnectionError("ths down")):
            with pytest.raises(Exception):
                fetch_profit_forecast(symbol="600170")
