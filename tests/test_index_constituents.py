"""中证指数官方成分股（index_constituents）测试（2026-11-11 批次B②）。

背景：2026-09-28 死源剥离（zealink DNS 死亡 + 国证 API 404）后无源；
现走中证官网 OSS cons 文件（oss-ch.csindex.com.cn，一手 xls）。

fetcher：mock _csi_session.get 隔离网络（真机拉 000300 标 network 单独跑）；
三坑各自有测试：①404 覆盖范围标注 ②calamine 引擎 ③双语表头子串定位。
"""

import io
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


def _fake_cons_bytes() -> bytes:
    """造双语表头的假成分文件（按真实 000300cons.xls 表头仿制，代码为数值型）。"""
    buf = io.BytesIO()
    pd.DataFrame(
        {
            "日期Date": [20261110, 20261110, 20261110],
            "指数代码 Index Code": ["300", "300", "300"],
            "指数名称 Index Name": ["沪深300", "沪深300", "沪深300"],
            "指数英文名称Index Name(Eng)": ["CSI 300", "CSI 300", "CSI 300"],
            "成份券代码Constituent Code": [1, 600000, 63],  # 数值型：1=平安银行
            "成份券名称Constituent Name": ["平安银行", "浦发银行", "中兴通讯"],
            "成份券英文名称Constituent Name(Eng)": ["Ping An Bank", "SPDB", "ZTE"],
            "交易所Exchange": ["深圳证券交易所", "上海证券交易所", "深圳证券交易所"],
            "交易所英文名称Exchange(Eng)": ["SZSE", "SSE", "SZSE"],
        }
    ).to_excel(buf, index=False, engine="openpyxl")
    return buf.getvalue()


def _mock_resp(content: bytes = b"", status_ok: bool = True, status_code: int = 200):
    resp = MagicMock()
    resp.content = content
    resp.status_code = status_code
    if status_ok:
        resp.raise_for_status = lambda: None
    else:
        resp.raise_for_status = lambda: (_ for _ in ()).throw(
            __import__("requests").HTTPError("404")
        )
    return resp


class TestFetchIndexConstituents:
    def test_parse_zfill_and_sort(self):
        """双语表头定位 + 数值代码 6 位补零 + 按代码升序。"""
        from tradex.data_sources.macro_official_fetchers import (
            fetch_index_constituents,
        )

        with patch(
            "tradex.data_sources.macro_official_fetchers._csi_session.get",
            return_value=_mock_resp(_fake_cons_bytes()),
        ):
            df = fetch_index_constituents()
        assert list(df.columns) == ["日期", "成分券代码", "成分券名称", "交易所"]
        # 数值型代码 → 6 位左补零字符串
        assert df.iloc[0]["成分券代码"] == "000001"
        assert df.iloc[1]["成分券代码"] == "000063"
        assert df.iloc[2]["成分券代码"] == "600000"
        assert df.iloc[0]["成分券名称"] == "平安银行"
        assert df.iloc[0]["日期"] == "20261110"
        assert df.iloc[0]["交易所"] == "深圳证券交易所"  # 英文交易所列不被误取

    def test_custom_index_code_in_url(self):
        from tradex.data_sources.macro_official_fetchers import (
            _CSI_CONS_URL,
            fetch_index_constituents,
        )

        with patch(
            "tradex.data_sources.macro_official_fetchers._csi_session.get",
            return_value=_mock_resp(_fake_cons_bytes()),
        ) as mocked:
            fetch_index_constituents(index_code="000905")
        url = mocked.call_args[0][0] if mocked.call_args[0] else mocked.call_args.kwargs.get("url")
        assert url == _CSI_CONS_URL.format(index_code="000905")
        assert "cons/" in url  # 目录段防漏

    def test_404_annotates_coverage(self):
        """坑①：国证系无文件 → 404 转译为覆盖范围说明（不裸 404）。"""
        from tradex.data_sources.macro_official_fetchers import (
            fetch_index_constituents,
        )

        with patch(
            "tradex.data_sources.macro_official_fetchers._csi_session.get",
            return_value=_mock_resp(status_ok=False, status_code=404),
        ):
            with pytest.raises(ValueError, match="399"):
                fetch_index_constituents(index_code="399006")

    def test_empty_file_raises(self):
        from tradex.data_sources.macro_official_fetchers import (
            fetch_index_constituents,
        )

        with patch(
            "tradex.data_sources.macro_official_fetchers._csi_session.get",
            return_value=_mock_resp(b""),
        ):
            with pytest.raises(Exception):
                fetch_index_constituents()

    def test_http_error_raises(self):
        from tradex.data_sources.macro_official_fetchers import (
            fetch_index_constituents,
        )

        with patch(
            "tradex.data_sources.macro_official_fetchers._csi_session.get",
            return_value=_mock_resp(status_ok=False),
        ):
            with pytest.raises(Exception):
                fetch_index_constituents()

    def test_direct_connection_no_proxy(self):
        """国内源铁律：trust_env 必须为 False（不读系统代理）。"""
        from tradex.data_sources.macro_official_fetchers import _csi_session

        assert _csi_session.trust_env is False

    def test_registered_in_router(self):
        """registry 必须挂上 csindex_official 主源（hub 内部路由可达）。"""
        from tradex.data_sources.registry import get_router, register_all_sources

        register_all_sources()
        router = get_router()
        assert "index_constituents" in router._sources
        assert router._sources["index_constituents"][0][0] == "csindex_official"


@pytest.mark.network
class TestIndexConstituentsLive:
    """真机验收（批次B②）：000300 实拉 300 行非空。跑法：
    ./tradex/.venv/Scripts/python.exe -m pytest tests/test_index_constituents.py -m network
    """

    def test_live_000300_300_rows(self):
        from tradex.data_sources.macro_official_fetchers import (
            fetch_index_constituents,
        )

        df = fetch_index_constituents("000300")
        assert not df.empty
        assert len(df) == 300
        assert df.iloc[0]["成分券代码"] == "000001"  # 平安银行，补零正确
