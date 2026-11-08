"""
国债收益率降级链测试（2026-11-08 中债改版修复批次）。

背景：中债 yield_main 接口改版（JSON → JS 填充页面），chinabond_official
主源解析出全 NaN 空壳。修复两处：
  1. 主源纪律——空壳必须抛出走降级（假数据比 5xx 更糟）；
  2. 备源兜底——em_bond_backup（akshare bond_zh_us_rate，东财 datacenter）。
"""

from unittest.mock import patch

import pandas as pd
import pytest


class TestChinabondGuard:
    def test_html_shell_raises(self):
        """read_html 拿到全 NaN 空壳必须抛出，不返回假数据。"""
        import io

        from tradex.data_sources.macro_official_fetchers import (
            fetch_chinabond_yield_curve,
        )

        # 模拟改版后的 JS 填充页面：表格骨架在、数值全空
        shell_html = "<table><tr><th>颜色</th><th>收益率(%)</th></tr><tr><td></td><td></td></tr></table>"
        fake_resp = pd.read_html(io.StringIO(shell_html))[0]

        class FakeResp:
            text = shell_html
            content = shell_html.encode()

            def json(self):
                raise ValueError("not json")

            def raise_for_status(self):
                return None

        with patch(
            "tradex.data_sources.macro_official_fetchers.curl_requests.get",
            return_value=FakeResp(),
        ):
            with pytest.raises(Exception, match="空壳"):
                fetch_chinabond_yield_curve()

    def test_valid_html_table_still_works(self):
        """非空壳的合法 HTML 表格仍正常返回（不误伤）。"""
        import io

        from tradex.data_sources.macro_official_fetchers import (
            fetch_chinabond_yield_curve,
        )

        good_html = (
            "<table><tr><th>期限</th><th>收益率(%)</th></tr>"
            "<tr><td>10年</td><td>1.58</td></tr></table>"
        )

        class FakeResp:
            text = good_html
            content = good_html.encode()

            def json(self):
                raise ValueError("not json")

            def raise_for_status(self):
                return None

        with patch(
            "tradex.data_sources.macro_official_fetchers.curl_requests.get",
            return_value=FakeResp(),
        ):
            df = fetch_chinabond_yield_curve()
        assert not df.empty
        assert df.notna().to_numpy().any()


class TestEmBondBackup:
    def test_curve_guard(self):
        """备源仅支持国债曲线，其余抛出走记账。"""
        from tradex.data_sources.akshare_fetchers import fetch_bond_yield_cn_backup

        with pytest.raises(ValueError, match="仅支持国债"):
            fetch_bond_yield_cn_backup(curve="商业银行AAA")

    def test_all_nan_raises(self):
        from tradex.data_sources.akshare_fetchers import fetch_bond_yield_cn_backup

        fake = pd.DataFrame({"日期": ["2026-11-06"], "中国国债收益率10年": [None]})
        with patch("akshare.bond_zh_us_rate", return_value=fake):
            with pytest.raises(ValueError, match="NaN|无有效"):
                fetch_bond_yield_cn_backup()

    def test_rows_shape(self):
        from tradex.data_sources.akshare_fetchers import fetch_bond_yield_cn_backup

        fake = pd.DataFrame(
            {
                "日期": ["2026-11-05", "2026-11-06"],
                "中国国债收益率2年": [1.20, None],
                "中国国债收益率5年": [1.30, 1.3115],
                "中国国债收益率10年": [1.60, 1.5868],
                "中国国债收益率30年": [None, 2.0275],
            }
        )
        with patch("akshare.bond_zh_us_rate", return_value=fake):
            df = fetch_bond_yield_cn_backup()
        assert list(df.columns) == ["期限", "收益率(%)"]
        # 取最新有值行（11-06），行内 NaN 期限（2年）不进结果
        assert "10年" in set(df["期限"]) and "30年" in set(df["期限"])
        assert "2年" not in set(df["期限"])
        assert df[df["期限"] == "10年"]["收益率(%)"].iloc[0] == pytest.approx(1.5868)

    @pytest.mark.network
    def test_real_backup(self):
        """真机冒烟：备源直连取最新国债曲线。"""
        import os

        for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            os.environ.pop(k, None)
        from tradex.data_sources.akshare_fetchers import fetch_bond_yield_cn_backup

        df = fetch_bond_yield_cn_backup()
        assert "10年" in set(df["期限"])
        assert df[df["期限"] == "10年"]["收益率(%)"].iloc[0] > 0
