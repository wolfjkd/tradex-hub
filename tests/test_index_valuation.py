"""
中证指数官方估值（index_valuation）测试（2026-11-08 复活批次）。

背景：v3.6.0 曾以 zealink 实现本类型，后域名 DNS 死亡被剥离；
现换中证官网 OSS 自动估值文件（oss-ch.csindex.com.cn，一手 xls）。

fetcher：mock _csi_session.get 隔离网络（真机冒烟标 network 单独跑）；
service/REST：mock 路由层；MCP：FastMCP 注册断言。
"""

import io
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


def _fake_valuation_bytes() -> bytes:
    """造双语表头的假估值文件（read_excel 按内容自动识别格式）。"""
    buf = io.BytesIO()
    pd.DataFrame(
        {
            "日期Date": [20261105, 20261106],
            "指数代码Index Code": ["300", "300"],
            "指数中文全称Chinese Name(Full)": ["沪深300指数", "沪深300指数"],
            "指数中文简称Index Chinese Name": ["沪深300", "沪深300"],
            "指数英文全称English Name(Full)": ["CSI 300 Index", "CSI 300 Index"],
            "指数英文简称Index English Name": ["CSI 300", "CSI 300"],
            "市盈率1（总股本）P/E1": [14.2, 14.16],
            "市盈率2（计算用股本）P/E2": [15.9, 15.24],
            "股息率1（总股本）D/P1": [2.76, 2.78],
            "股息率2（计算用股本）D/P2": [2.54, 2.57],
        }
    ).to_excel(buf, index=False, engine="openpyxl")
    return buf.getvalue()


def _mock_resp(content: bytes = b"", status_ok: bool = True):
    resp = MagicMock()
    resp.content = content
    if status_ok:
        resp.raise_for_status = lambda: None
    else:
        resp.raise_for_status = lambda: (_ for _ in ()).throw(
            __import__("requests").HTTPError("404")
        )
    return resp


class TestFetchIndexValuation:
    def test_parse_columns_and_order(self):
        """双语表头定位 → 中文列裁剪 + 日期降序（最新在前）。"""
        from tradex.data_sources.macro_official_fetchers import fetch_index_valuation

        with patch(
            "tradex.data_sources.macro_official_fetchers._csi_session.get",
            return_value=_mock_resp(_fake_valuation_bytes()),
        ):
            df = fetch_index_valuation()
        assert list(df.columns) == [
            "日期",
            "市盈率1(总股本)",
            "市盈率2(计算用股本)",
            "股息率1(总股本)",
            "股息率2(计算用股本)",
        ]
        assert df.iloc[0]["日期"] == "20261106"  # 降序：最新在前
        assert df.iloc[0]["市盈率2(计算用股本)"] == 15.24
        assert df.iloc[0]["股息率2(计算用股本)"] == 2.57

    def test_custom_index_code_in_url(self):
        from tradex.data_sources.macro_official_fetchers import (
            _CSI_INDICATOR_URL,
            fetch_index_valuation,
        )

        with patch(
            "tradex.data_sources.macro_official_fetchers._csi_session.get",
            return_value=_mock_resp(_fake_valuation_bytes()),
        ) as mocked:
            fetch_index_valuation(index_code="980017")
        url = mocked.call_args[0][0] if mocked.call_args[0] else mocked.call_args.kwargs.get("url")
        assert url == _CSI_INDICATOR_URL.format(index_code="980017")
        assert "indicator/" in url  # 目录段防回退（2026-11-08 实测漏段 404）

    def test_empty_file_raises(self):
        """空表必须抛出，不吞（SmartRouter 降级纪律）。"""
        from tradex.data_sources.macro_official_fetchers import fetch_index_valuation

        with patch(
            "tradex.data_sources.macro_official_fetchers._csi_session.get",
            return_value=_mock_resp(b""),
        ):
            with pytest.raises(Exception):
                fetch_index_valuation()

    def test_http_error_raises(self):
        from tradex.data_sources.macro_official_fetchers import fetch_index_valuation

        with patch(
            "tradex.data_sources.macro_official_fetchers._csi_session.get",
            return_value=_mock_resp(status_ok=False),
        ):
            with pytest.raises(Exception):
                fetch_index_valuation()

    def test_direct_connection_no_proxy(self):
        """国内源铁律：trust_env 必须为 False（不读系统代理）。"""
        from tradex.data_sources.macro_official_fetchers import _csi_session

        assert _csi_session.trust_env is False

    @pytest.mark.network
    def test_real_000300(self):
        """真机冒烟：沪深300 官方估值文件可取（不挂代理直连）。"""
        import os

        for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            os.environ.pop(k, None)
        from tradex.data_sources.macro_official_fetchers import fetch_index_valuation

        df = fetch_index_valuation("000300")
        assert len(df) > 0
        assert "市盈率2(计算用股本)" in df.columns


class TestIndexValuationService:
    def test_service_shape_and_cache(self):
        from tradex.service import macro_service

        fake_df = pd.DataFrame(
            {
                "日期": ["20261106"],
                "市盈率1(总股本)": [14.16],
                "市盈率2(计算用股本)": [15.24],
                "股息率1(总股本)": [2.78],
                "股息率2(计算用股本)": [2.57],
            }
        )
        macro_service.cache.invalidate("index_valuation:000300")
        with patch.object(
            macro_service._router,
            "route",
            return_value=(fake_df, "csindex_official"),
        ) as mocked:
            out = macro_service.get_index_valuation()
            assert out["source"] == "csindex_official"
            assert out["count"] == 1
            assert out["data"][0]["市盈率2(计算用股本)"] == 15.24
            out2 = macro_service.get_index_valuation()  # 命中缓存
            mocked.assert_called_once()
            assert out2 == out
        macro_service.cache.invalidate("index_valuation:000300")


class TestIndexValuationRest:
    def test_envelope_ok(self):
        from fastapi.testclient import TestClient

        from tradex.api.routes import router as routes_router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(routes_router, prefix="/api/v1")
        client = TestClient(app)
        with patch(
            "tradex.service.macro_service.get_index_valuation",
            return_value={"index_code": "000300", "data": [{"日期": "20261106"}], "source": "csindex_official", "count": 1},
        ):
            r = client.get("/api/v1/macro/index-valuation")
        assert r.status_code == 200
        body = r.json()
        assert body.get("code") == 0
        assert body["data"]["index_code"] == "000300"

    def test_source_failure_returns_502(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from tradex.api.routes import router as routes_router

        app = FastAPI()
        app.include_router(routes_router, prefix="/api/v1")
        client = TestClient(app)
        with patch(
            "tradex.service.macro_service.get_index_valuation",
            side_effect=RuntimeError("中证 OSS 不可达"),
        ):
            r = client.get("/api/v1/macro/index-valuation")
        assert r.status_code == 502


class TestIndexValuationMcp:
    def test_registered_in_fastmcp(self):
        import asyncio

        from mcp.server.fastmcp import FastMCP

        from tradex.tools import macro_official

        mcp = FastMCP("idx-val-test")
        macro_official.register(mcp)
        tools = asyncio.new_event_loop().run_until_complete(mcp.list_tools())
        names = {t.name for t in tools}
        assert "get_index_valuation" in names
