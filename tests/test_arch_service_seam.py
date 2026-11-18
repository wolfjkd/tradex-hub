"""A③ 验收（QI-ARCH-05，2026-11-18 质检整改）：kpl/industry_news 补 service
接缝 + 错误信封语义与 serve_envelope 唯一口径一致。

原形态：路由越层直伸手 SmartRouter（违硬约定#9）+ kpl 400 配 ERR_INTERNAL
头（与 serve_envelope ValueError→400 的 ERR_BAD_REQUEST 语义漂移）。
"""

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tradex.api.schemas import ERR_BAD_REQUEST, ERR_DATA_SOURCE_UNREACHABLE, ERR_OK
from tradex.service import industry_news_service, kpl_service


def _client() -> TestClient:
    from tradex.api.routes import industry_news as in_routes
    from tradex.api.routes import kpl as kpl_routes

    app = FastAPI()
    app.include_router(kpl_routes.router, prefix="/api/v1")
    app.include_router(in_routes.routes_router if hasattr(in_routes, "routes_router") else in_routes.router, prefix="/api/v1")
    return TestClient(app)


class TestKplServiceSeam:
    def test_limit_up_via_service(self):
        """路由走 service 层（mock service 即生效 = 不再直伸手 router）。"""
        client = _client()
        with patch.object(kpl_service, "limit_up", return_value=[{"code": "301999"}]):
            r = client.get("/api/v1/kpl/limit-up", params={"date": "20261118"})
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == ERR_OK
        assert body["data"] == [{"code": "301999"}]

    def test_value_error_matches_serve_envelope(self):
        """ValueError → 400 + X-ErrCode=ERR_BAD_REQUEST（原 ERR_INTERNAL 漂移归一）。"""
        client = _client()

        def boom(**kw):
            raise ValueError("交易日无数据")

        with patch.object(kpl_service, "limit_up", side_effect=boom):
            r = client.get("/api/v1/kpl/limit-up", params={"date": "20261118"})
        assert r.status_code == 400
        assert r.headers["x-errcode"] == str(ERR_BAD_REQUEST)

    def test_other_error_matches_serve_envelope(self):
        """非 ValueError → 502 + X-ErrCode=ERR_DATA_SOURCE_UNREACHABLE。"""
        client = _client()

        def boom(**kw):
            raise RuntimeError("conn reset")

        with patch.object(kpl_service, "limit_up", side_effect=boom):
            r = client.get("/api/v1/kpl/limit-up", params={"date": "20261118"})
        assert r.status_code == 502
        assert r.headers["x-errcode"] == str(ERR_DATA_SOURCE_UNREACHABLE)

    def test_invalid_date_400_bad_request_code(self):
        """非法日期 400 头归一 ERR_BAD_REQUEST（原 ERR_INTERNAL）。"""
        client = _client()
        r = client.get("/api/v1/kpl/limit-up", params={"date": "abc"})
        assert r.status_code == 400
        assert r.headers["x-errcode"] == str(ERR_BAD_REQUEST)


class TestIndustryNewsServiceSeam:
    def test_unknown_track_400(self):
        """「未知赛道」ValueError → 400（serve_envelope 唯一语义）。"""
        client = _client()
        r = client.get("/api/v1/industry-news/get", params={"track": "bogus"})
        assert r.status_code == 400
        assert "未知赛道" in r.json()["detail"]

    def test_tracks_via_service(self):
        client = _client()
        with patch.object(
            industry_news_service, "tracks", return_value={"tracks": [], "source_count": 0}
        ):
            r = client.get("/api/v1/industry-news/tracks")
        assert r.status_code == 200
        assert r.json()["data"] == {"tracks": [], "source_count": 0}
