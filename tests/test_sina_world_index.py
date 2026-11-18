"""新浪 znb 全球指数 fetcher 载荷形状校验回归（QI-STD-92，2026-11-18 质检整改）。

根因：fetch_sina_world_index 只查 `'"' in text` + fields[1] 可 float——
风控 HTML / 错误页含引号极常见，可解析出伪造行情值（伪 point 交 TradeX
展示）。修复：载荷形状校验（`var hq_str_znb_` 前缀 + ≥12 字段），不过即
诚实空态 {}（与既有空代码族口径一致——QI-STD-93 归一前先堵伪造路径）。
"""
from unittest.mock import MagicMock, patch

# 正常 znb 载荷（12 字段，位次 0=名称 1=最新 2=涨跌额 3=涨跌幅 8=开盘 9=昨收
# 10=最高 11=最低；KOSPI 数值取 2026-11-14 实测样本形态）
_NORMAL_PAYLOAD = (
    'var hq_str_znb_KOSPI="首尔综合指数,5290.53,-52.38,-0.98,5349.07,5342.91,'
    '5350.00,5288.00,5342.91,5302.00,5295.50,5291.20";'
)


def _resp(text: str) -> MagicMock:
    resp = MagicMock()
    resp.content = text.encode("gbk", errors="ignore")
    return resp


class TestZnbPayloadShape:
    def test_risk_control_html_yields_empty_dict(self):
        """非规范响应（含引号的风控/错误页）不得解析出伪 point。

        样本构造：split('"')[1]='访问受限,5290.53'——split(',') 后 fields[0]
        非空、fields[1] 恰可 float，修复前产出伪行情值
        {'name': '访问受限', 'point': 5290.53, ...} 交 TradeX 展示。
        """
        from tradex.data_sources import sina_fetchers

        html = '<script>var msg="访问受限,5290.53";</script>'
        with patch.object(sina_fetchers, "curl_requests") as mock_req:
            mock_req.get.return_value = _resp(html)
            assert sina_fetchers.fetch_sina_world_index("KOSPI") == {}

    def test_normal_payload_parses(self):
        """规范 12 字段载荷正常解析（防校验误伤）。"""
        from tradex.data_sources import sina_fetchers

        with patch.object(sina_fetchers, "curl_requests") as mock_req:
            mock_req.get.return_value = _resp(_NORMAL_PAYLOAD)
            result = sina_fetchers.fetch_sina_world_index("KOSPI")
        assert result["name"] == "首尔综合指数"
        assert result["point"] == 5290.53
        assert result["pct"] == -0.98
        assert result["open"] == 5342.91
        assert result["lastclose"] == 5302.00
        assert result["amount"] == 0.0

    def test_empty_quote_family_yields_empty_dict(self):
        """空代码族 var hq_str_znb_XXX=""; 保持既有诚实空态 {}。"""
        from tradex.data_sources import sina_fetchers

        with patch.object(sina_fetchers, "curl_requests") as mock_req:
            mock_req.get.return_value = _resp('var hq_str_znb_KOSPI="";')
            assert sina_fetchers.fetch_sina_world_index("KOSPI") == {}

    def test_truncated_payload_yields_empty_dict(self):
        """前缀对但字段数不足（截断/改版载荷）→ 空态，不出半伪值。"""
        from tradex.data_sources import sina_fetchers

        truncated = 'var hq_str_znb_KOSPI="首尔综合指数,5290.53,-52.38";'
        with patch.object(sina_fetchers, "curl_requests") as mock_req:
            mock_req.get.return_value = _resp(truncated)
            assert sina_fetchers.fetch_sina_world_index("KOSPI") == {}

    def test_code_case_normalized(self):
        """大小写归一（QI-STD-93 本批部分）：kospi/KOSPI/kospi带空格 路由行为
        一致——URL 统一 upper 形态，不再依赖调用侧自觉传大写。"""
        from tradex.data_sources import sina_fetchers

        captured = {}

        def _fake_get(url, **kwargs):
            captured["url"] = url
            return _resp(_NORMAL_PAYLOAD)

        with patch.object(sina_fetchers, "curl_requests") as mock_req:
            mock_req.get.side_effect = _fake_get
            r_lower = sina_fetchers.fetch_sina_world_index("kospi")
        with patch.object(sina_fetchers, "curl_requests") as mock_req2:
            mock_req2.get.side_effect = _fake_get
            r_upper = sina_fetchers.fetch_sina_world_index(" KOSPI ")
        assert captured["url"] == "https://hq.sinajs.cn/list=znb_KOSPI"
        assert r_lower == r_upper
