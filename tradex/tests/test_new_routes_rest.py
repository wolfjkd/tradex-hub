"""工单 T35 测试：6 个新 REST 端点（option / event / index / macro / interaction / industry-news）。

只验证：
- 端点可访问、返回 Envelope 结构
- 参数校验（symbol 6 位数字、track 在白名单）
- 错误码：400 / 422 / 502

不覆盖：网络层（数据源连通性）—— 留给后续 network 标记的测试。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from tradex.api.schemas import ERR_BAD_REQUEST, ERR_OK


def _build_min_app():
    """复用工单 06 的 app 构造逻辑。"""
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import JSONResponse
    from tradex.api import routes as rest_routes
    from tradex.api.schemas import (
        ERR_BAD_REQUEST, ERR_INTERNAL, ERR_NOT_FOUND, envelope_err,
    )
    app = FastAPI()
    app.include_router(rest_routes.router, prefix="/api/v1")

    @app.exception_handler(HTTPException)
    async def _h(request: Request, exc: HTTPException) -> JSONResponse:
        path = request.url.path
        if not path.startswith("/api/"):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        err_code = (
            int(exc.headers.get("X-ErrCode"))
            if exc.headers and exc.headers.get("X-ErrCode")
            else {400: ERR_BAD_REQUEST, 404: ERR_NOT_FOUND, 500: ERR_INTERNAL}.get(
                exc.status_code, ERR_INTERNAL
            )
        )
        return JSONResponse(
            envelope_err(err_code, str(exc.detail)).model_dump(),
            status_code=exc.status_code,
        )

    @app.middleware("http")
    async def _env(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/api/") and response.status_code != 200:
            try:
                body_bytes = b""
                async for chunk in response.body_iterator:
                    body_bytes += chunk
                try:
                    body = json.loads(body_bytes)
                except Exception:
                    body = {"raw": body_bytes.decode(errors="replace")}
                if isinstance(body, dict) and "code" in body:
                    return JSONResponse(body, status_code=response.status_code)
                code_map = {400: ERR_BAD_REQUEST, 404: ERR_NOT_FOUND,
                            422: ERR_BAD_REQUEST, 500: ERR_INTERNAL}
                code = code_map.get(response.status_code, ERR_INTERNAL)
                if response.status_code == 422 and isinstance(body, dict):
                    msg = json.dumps(body.get("detail", "validation error"),
                                     ensure_ascii=False)
                else:
                    msg = body.get("detail") if isinstance(body, dict) else str(body)
                return JSONResponse(
                    envelope_err(code, str(msg or "error")).model_dump(),
                    status_code=response.status_code,
                )
            except Exception:
                return response
        return response

    return app


@pytest.fixture(scope="module")
def client():
    return TestClient(_build_min_app())


def _clear_cache():
    try:
        from tradex.utils.cache import cache as _c
        _c.clear()
    except Exception:
        pass


# ---------- Option ----------

class TestOptionRest:
    """/api/v1/option/*"""

    def test_tquote_default_underlying(self, client):
        _clear_cache()
        r = client.get("/api/v1/option/tquote")
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == ERR_OK
        assert "data" in body and isinstance(body["data"], dict)
        assert "underlying" in body["data"]

    def test_greeks_returns_envelope(self, client):
        _clear_cache()
        r = client.get("/api/v1/option/greeks?underlying=510050")
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == ERR_OK
        assert "greeks" in body["data"]


# ---------- Event ----------

class TestEventRest:
    """/api/v1/event/*"""

    def test_earnings_forecast_valid(self, client):
        _clear_cache()
        r = client.get("/api/v1/event/earnings-forecast?symbol=600519")
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == ERR_OK
        assert "forecasts" in body["data"]

    def test_earnings_forecast_bad_symbol(self, client):
        r = client.get("/api/v1/event/earnings-forecast?symbol=abc123")
        assert r.status_code == 400
        body = r.json()
        assert body["code"] == ERR_BAD_REQUEST

    def test_institution_survey_returns_envelope(self, client):
        _clear_cache()
        r = client.get("/api/v1/event/institution-survey?symbol=000001")
        assert r.status_code == 200
        body = r.json()
        assert "surveys" in body["data"]

    def test_holder_trades_returns_envelope(self, client):
        _clear_cache()
        r = client.get("/api/v1/event/holder-trades?symbol=600519")
        assert r.status_code == 200

    def test_share_buyback_returns_envelope(self, client):
        _clear_cache()
        r = client.get("/api/v1/event/share-buyback?symbol=000001")
        assert r.status_code == 200

    def test_equity_pledge_returns_envelope(self, client):
        _clear_cache()
        r = client.get("/api/v1/event/equity-pledge?symbol=600519")
        assert r.status_code == 200

    def test_ipo_calendar_returns_envelope(self, client):
        _clear_cache()
        r = client.get("/api/v1/event/ipo-calendar")
        assert r.status_code == 200
        body = r.json()
        assert "ipos" in body["data"]


# ---------- Index ----------

class TestIndexRest:
    """/api/v1/index/*"""

    def test_constituents_default_300(self, client):
        _clear_cache()
        r = client.get("/api/v1/index/constituents")
        assert r.status_code == 200
        body = r.json()
        assert "constituents" in body["data"]

    def test_weights_returns_envelope(self, client):
        _clear_cache()
        r = client.get("/api/v1/index/weights?index_code=000300")
        assert r.status_code == 200

    def test_valuation_returns_envelope(self, client):
        _clear_cache()
        r = client.get("/api/v1/index/valuation?index_code=000905")
        assert r.status_code == 200


# ---------- Macro ----------

class TestMacroRest:
    """/api/v1/macro/*"""

    def test_pmi_returns_envelope(self, client):
        _clear_cache()
        r = client.get("/api/v1/macro/pmi")
        assert r.status_code == 200
        body = r.json()
        assert "data" in body["data"]

    def test_social_financing_returns_envelope(self, client):
        _clear_cache()
        r = client.get("/api/v1/macro/social-financing")
        assert r.status_code == 200

    def test_bond_yield_curve_returns_envelope(self, client):
        _clear_cache()
        r = client.get("/api/v1/macro/bond-yield-curve")
        assert r.status_code == 200

    def test_repo_fixing_rate_returns_envelope(self, client):
        _clear_cache()
        r = client.get("/api/v1/macro/repo-fixing-rate")
        assert r.status_code == 200

    def test_lpr_returns_envelope(self, client):
        _clear_cache()
        r = client.get("/api/v1/macro/lpr")
        assert r.status_code == 200

    def test_sw_industry_as_of_bad_symbol(self, client):
        # 长度 < 6 的 symbol 由 FastAPI 的 min_length 校验拦截 → 422
        r = client.get("/api/v1/macro/sw-industry-as-of?symbol=xxx")
        assert r.status_code in (400, 422)
        body = r.json()
        assert body["code"] == ERR_BAD_REQUEST


# ---------- Interaction ----------

class TestInteractionRest:
    """/api/v1/interaction/*"""

    def test_cninfo_irm_valid(self, client):
        _clear_cache()
        r = client.get("/api/v1/interaction/cninfo-irm?symbol=000001")
        assert r.status_code == 200
        body = r.json()
        assert "qa" in body["data"]

    def test_sse_e_interaction_valid(self, client):
        _clear_cache()
        r = client.get("/api/v1/interaction/sse-e-interaction?symbol=600519")
        assert r.status_code == 200

    def test_cninfo_irm_bad_symbol(self, client):
        # 长度 < 6 由 FastAPI min_length 校验拦截 → 422
        r = client.get("/api/v1/interaction/cninfo-irm?symbol=zzz")
        assert r.status_code in (400, 422)


# ---------- Industry News ----------

class TestIndustryNewsRest:
    """/api/v1/industry-news/*"""

    def test_tracks_endpoint(self, client):
        r = client.get("/api/v1/industry-news/tracks")
        assert r.status_code == 200
        body = r.json()
        assert "tracks" in body["data"]
        assert body["data"]["source_count"] >= 100  # 106 冻结版
        assert body["data"]["frozen_at"] == "2026-09-23"

    def test_get_news_valid_track(self, client):
        """track 合法时不应返回 400（不验证抓取成功，因 RSS 可能超时）。"""
        _clear_cache()
        r = client.get("/api/v1/industry-news/get?track=ai&days=3&per_source=1")
        # 合法 track 不应触发 400 参数错误；网络超时返回 502 也算通过本测试
        assert r.status_code != 400, \
            f"track=ai 是合法值，不应返回 400: {r.json()}"

    def test_get_news_unknown_track_400(self, client):
        r = client.get("/api/v1/industry-news/get?track=unknown_track")
        assert r.status_code == 400
        body = r.json()
        assert body["code"] == ERR_BAD_REQUEST

    def test_get_news_all_tracks(self, client):
        """空 track 不应触发 400（不验证抓取成功）。"""
        _clear_cache()
        r = client.get("/api/v1/industry-news/get?days=1&per_source=1")
        assert r.status_code != 400, \
            f"空 track 不应返回 400: {r.json()}"
