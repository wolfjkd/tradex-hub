"""工单 H5 测试：全市场成交额榜（通达信盘后包）。

覆盖：
- 盘后包二进制解析（.cod 150 字节 / .md1 512 字节）
- A 股过滤（剔除指数 / 债券 / 回购）
- 成交额排序、涨跌幅换算
- 包缺失/下载失败 → 实时榜降级并标注
- 幂等缓存 / MCP + REST 双通道
"""

from __future__ import annotations

import asyncio
import io
import json
import struct
import zipfile

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tradex.api import routes as rest_routes
from tradex.data_sources import tdx_package_fetchers as tdxpkg
from tradex.service import turnover_service
from tradex.shortline.meta import SHORTLINE_ENDPOINTS

_YMD = "20261105"


# ---------------------------------------------------------------- 样本包


def _cod_record(code: str, seq: int, name: str) -> bytes:
    rec = bytearray(150)
    rec[0:6] = code.encode("ascii")
    struct.pack_into("<H", rec, 32, seq)
    raw = name.encode("gbk")
    rec[40:40 + len(raw)] = raw
    return bytes(rec)


def _md1_block(prev: float, o: float, h: float, l: float, c: float, vol: int, amount: float) -> bytes:
    blk = bytearray(512)
    struct.pack_into("<d", blk, 4, prev)
    struct.pack_into("<4d", blk, 12, o, h, l, c)
    struct.pack_into("<Q", blk, 56, vol)
    struct.pack_into("<d", blk, 72, amount)
    return bytes(blk)


def _build_package(rows_by_market: dict[str, list[dict]]) -> bytes:
    """按市场构造样本 zip；rows 里每项含 code/name/prev/o/h/l/c/vol/amount。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for market, rows in rows_by_market.items():
            cod = b"".join(
                _cod_record(row["code"], seq, row["name"]) for seq, row in enumerate(rows)
            )
            md1 = b"".join(
                _md1_block(row["prev"], row["o"], row["h"], row["l"], row["c"],
                           row["vol"], row["amount"])
                for row in rows
            )
            zf.writestr(f"{market}{_YMD[2:]}.cod", cod)
            zf.writestr(f"{market}{_YMD[2:]}.md1", md1)
    return buf.getvalue()


def _sample_rows():
    return {
        "sh": [
            {"code": "600519", "name": "贵州茅台", "prev": 1400.0, "o": 1401.0,
             "h": 1460.0, "l": 1398.0, "c": 1452.0, "vol": 4_670_000,
             "amount": 6_752_970_915.0},
            {"code": "880099", "name": "自编指数", "prev": 100.0, "o": 100.0,
             "h": 100.0, "l": 100.0, "c": 0.0, "vol": 0, "amount": 0.0},
            {"code": "204001", "name": "GC001", "prev": 1.3, "o": 1.3,
             "h": 1.4, "l": 1.3, "c": 1.39, "vol": 22_000_000,
             "amount": 2_210_000_000_000.0},
        ],
        "sz": [
            {"code": "000001", "name": "平安银行", "prev": 11.52, "o": 11.60,
             "h": 11.70, "l": 11.50, "c": 11.64, "vol": 122_000_000,
             "amount": 1_429_433_016.32},
        ],
        "bj": [
            {"code": "920000", "name": "安徽凤凰", "prev": 11.20, "o": 11.30,
             "h": 11.60, "l": 11.20, "c": 11.48, "vol": 1_226_896,
             "amount": 14_083_357.8},
        ],
    }


@pytest.fixture(autouse=True)
def _low_minimums(monkeypatch):
    """样本包行数远小于真实下限，测试时把下限压到 1（生产逻辑不变）。"""
    monkeypatch.setattr(tdxpkg, "TDX_MIN_PRICED", {"sh": 1, "sz": 1, "bj": 1})


class TestParsePackage:
    def test_parse_fields_and_skip_zero_close(self):
        rows = tdxpkg._parse_package(_build_package(_sample_rows()), _YMD)
        assert len(rows) == 4  # 880099 收盘 0 被跳过
        moutai = next(r for r in rows if r["code"] == "600519")
        assert moutai["name"] == "贵州茅台"
        assert moutai["close"] == 1452.0
        assert moutai["amount"] == 6_752_970_915.0
        assert moutai["volume"] == 4_670_000
        assert moutai["date"] == "2026-11-05"
        assert moutai["market"] == "sh"

    def test_count_mismatch_raises(self):
        content = _build_package({"sh": _sample_rows()["sh"]})
        # 删掉一个块制造条数对不上：重建 zip
        buf = io.BytesIO()
        src = zipfile.ZipFile(io.BytesIO(content))
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("sh261105.cod", src.read("sh261105.cod"))
            zf.writestr("sh261105.md1", src.read("sh261105.md1")[:-512])
        with pytest.raises(RuntimeError, match="对不上"):
            tdxpkg._parse_package(buf.getvalue(), _YMD)

    def test_non_digit_code_raises(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("sh261105.cod", _cod_record("ABCDEF", 0, "怪代码"))
            zf.writestr("sh261105.md1", _md1_block(10, 10, 10, 10, 10, 100, 1000))
        with pytest.raises(RuntimeError, match="非 6 位"):
            tdxpkg._parse_package(buf.getvalue(), _YMD)

    def test_missing_market_file_raises(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("sh261105.cod", _cod_record("600519", 0, "贵州茅台"))
        with pytest.raises(RuntimeError, match="缺少"):
            tdxpkg._parse_package(buf.getvalue(), _YMD)


# ---------------------------------------------------------------- 排名


class TestRanking:
    def test_is_a_share(self):
        assert turnover_service.is_a_share("sh", "600519")
        assert turnover_service.is_a_share("sh", "688981")
        assert turnover_service.is_a_share("sz", "300750")
        assert turnover_service.is_a_share("bj", "920000")
        assert not turnover_service.is_a_share("sh", "880099")
        assert not turnover_service.is_a_share("sh", "204001")
        assert not turnover_service.is_a_share("sh", "510300")
        assert not turnover_service.is_a_share("sz", "159915")

    def test_rank_rows_sorted_and_converted(self):
        rows = tdxpkg._parse_package(_build_package(_sample_rows()), _YMD)
        top = turnover_service.rank_rows(rows, 10)
        codes = [item["code"] for item in top]
        assert codes[0] == "600519"
        assert "204001" not in codes
        moutai = top[0]
        assert moutai["amount_yi"] == 67.5297
        assert moutai["change_pct"] == 3.71  # 1452/1400 - 1

    def test_rank_limit(self):
        rows = tdxpkg._parse_package(_build_package(_sample_rows()), _YMD)
        assert len(turnover_service.rank_rows(rows, 1)) == 1


# ---------------------------------------------------------------- service


class _FakeRouter:
    def __init__(self, *, package_payload=None, package_error=None, df=None, df_source="eltdx"):
        self.package_payload = package_payload
        self.package_error = package_error
        self.df = df
        self.df_source = df_source
        self.calls: list[tuple[str, dict]] = []

    def route(self, data_type, **kwargs):
        self.calls.append((data_type, kwargs))
        if data_type == "tdx_daily_package":
            if self.package_error:
                raise self.package_error
            return self.package_payload, "tdx_official"
        if data_type == "category_quotes":
            return self.df, self.df_source
        raise AssertionError(f"unexpected data_type {data_type}")


def _package_payload():
    rows = tdxpkg._parse_package(_build_package(_sample_rows()), _YMD)
    return {
        "date": "2026-11-05",
        "ymd": _YMD,
        "as_of": "2026-11-05 17:00 后发布",
        "kind": "history",
        "source": "tdx_official",
        "source_url": "https://example/20261105.zip",
        "rows": rows,
        "count": len(rows),
    }


def _realtime_df():
    return pd.DataFrame([
        {"代码": "sh600519", "现价": 1452.0, "涨跌幅": 3.71, "成交额": 6.75e9},
        {"代码": "sz000001", "现价": 11.64, "涨跌幅": 1.04, "成交额": 1.43e9},
        {"代码": "sh204001", "现价": 1.39, "涨跌幅": 0.7, "成交额": 2.2e12},
    ])


@pytest.fixture(autouse=True)
def _clean_cache():
    from tradex.shortline.meta import cache_key
    from tradex.utils.cache import cache as _c

    for date_key in ("latest", _YMD, "20261106"):
        _c.invalidate(cache_key("shortline.turnover_top", date=date_key))
    _c.invalidate(cache_key("shortline.turnover_top", kind="realtime"))
    yield


class TestTurnoverService:
    def test_history_path_and_cache(self, monkeypatch):
        fake = _FakeRouter(package_payload=_package_payload())
        monkeypatch.setattr(turnover_service, "_router", fake)

        first = turnover_service.get_turnover_top(date=_YMD, limit=10)
        second = turnover_service.get_turnover_top(date=_YMD, limit=3)

        assert first["kind"] == "history"
        assert first["source"] == "tdx_official"
        assert first["as_of"] == "2026-11-05 17:00 后发布"
        assert second["cache_hit"] is True
        assert second["returned"] == 3
        assert len(fake.calls) == 1

    def test_package_missing_degrades_to_realtime(self, monkeypatch):
        fake = _FakeRouter(
            package_error=ValueError("2026-11-06 没有通达信盘后包"),
            df=_realtime_df(),
        )
        monkeypatch.setattr(turnover_service, "_router", fake)

        result = turnover_service.get_turnover_top(date="20261106", limit=5)
        assert result["kind"] == "realtime"
        assert result["degradation"]["from"] == "history"
        assert "没有通达信盘后包" in result["degradation"]["reason"]
        assert result["stocks"][0]["code"] == "600519"
        assert "此刻榜" in result["source"]
        assert "204001" not in [s["code"] for s in result["stocks"]]

    def test_realtime_kind_skips_package(self, monkeypatch):
        fake = _FakeRouter(df=_realtime_df())
        monkeypatch.setattr(turnover_service, "_router", fake)
        result = turnover_service.get_turnover_top(kind="realtime", limit=2)
        assert result["kind"] == "realtime"
        assert [c[0] for c in fake.calls] == ["category_quotes"]

    def test_invalid_kind_raises(self):
        with pytest.raises(ValueError):
            turnover_service.get_turnover_top(kind="bogus")

    def test_bad_package_payload_degrades(self, monkeypatch):
        fake = _FakeRouter(package_payload={"rows": "not-a-list"}, df=_realtime_df())
        monkeypatch.setattr(turnover_service, "_router", fake)
        result = turnover_service.get_turnover_top(date=_YMD, limit=5)
        assert result["kind"] == "realtime"


# ---------------------------------------------------------------- 双通道


class TestTurnoverChannels:
    def test_mcp_tool_returns_json(self, monkeypatch):
        from mcp.server.fastmcp import FastMCP
        from tradex.tools.shortline import register

        fake = _FakeRouter(package_payload=_package_payload())
        monkeypatch.setattr(turnover_service, "_router", fake)

        mcp = FastMCP("test_turnover")
        register(mcp)
        fn = mcp._tool_manager._tools["get_shortline_turnover_top"].fn
        data = json.loads(asyncio.run(fn(date=_YMD, limit=5, kind="auto")))
        assert data["kind"] == "history"
        assert data["returned"] == 3

    def test_rest_route_returns_envelope(self, monkeypatch):
        fake = _FakeRouter(package_payload=_package_payload())
        monkeypatch.setattr(turnover_service, "_router", fake)

        app = FastAPI()
        app.include_router(rest_routes.router, prefix="/api/v1")
        client = TestClient(app)
        resp = client.get(f"/api/v1/shortline/turnover-top?date={_YMD}&limit=5")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["kind"] == "history"

    def test_rest_route_invalid_kind_400(self, monkeypatch):
        fake = _FakeRouter(df=_realtime_df())
        monkeypatch.setattr(turnover_service, "_router", fake)
        app = FastAPI()
        app.include_router(rest_routes.router, prefix="/api/v1")
        client = TestClient(app)
        resp = client.get("/api/v1/shortline/turnover-top?kind=bogus")
        assert resp.status_code == 400
        assert "非法 kind" in resp.text

    def test_metadata(self):
        endpoint = SHORTLINE_ENDPOINTS["shortline.turnover_top"]
        assert endpoint.status == "implemented"
        assert endpoint.cache_policy == "package_long"
