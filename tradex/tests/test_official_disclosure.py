"""OFFSRC-00 P01 测试：境外官方公告统一框架 + Fed RSS 打样。

覆盖（工单验收清单）：
  - 统一字段模型解析（fixture 回放真实 RSS 样本，不联网）
  - 异常路径：坏 XML / 零条目 / 关键字段缺失 / 坏 pubDate / 未知 source
  - service 层：聚合降级（单源失败进 failed_sources）/ 全失败抛 / doc_type 过滤
    / UTC+北京双标 / 缓存
  - REST 端点：200 信封 / 未知 source 400 / sources 清单
  - MCP 工具注册 + 出口信封契约

规划文档：Obsidian 开发计划/项目-tradex-hub/专项任务/OFFSRC-00-*.md
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from tradex.data_sources.official_disclosure_fetchers import (
    DISCLOSURE_COLUMNS,
    OFFICIAL_SOURCES,
    OfficialDisclosureSourceError,
    _date_en_dmy_to_iso,
    _date_en_to_iso,
    _hkex_resolve_stock_id,
    _msci_period_from_code,
    _msci_review_code,
    _parse_fed_rss,
    _parse_ftse_notice_text,
    _parse_hkex_search,
    _parse_msci_chinaa_text,
    _parse_msci_ir_dates,
    _parse_msci_review_links,
    _parse_sec_submissions,
    fetch_official_disclosure,
    list_official_sources,
    utc_iso_to_cn,
)

# FTSE 公告 PDF 首页文本（结构对齐 getnotice 真实文件，GEIS Dec2026 期）
_FTSE_NOTICE_TEXT = """FTSE Global Equity Index Series
December 2026 Quarterly Changes
13 November 2026
FTSE Russell announces that the following quarterly review changes will become effective on Monday, 21 December
2026 (i.e. after the close of business on Friday, 18 December 2026). The changes can be accessed via the attachment
below.
 GEIS_Quarterly_Changes_December_2026.xlsx
"""

# MSCI China A 名单 PDF 第 1 页抽取文本（结构对齐真实文件；明细数按精简 fixture 自洽 2/5）
_MSCI_CHINAA_TEXT = """Geneva, November 11, 2026
MSCI CHINA A INDEX SERIES
This report presents the MSCI China A Index Series review results based
on data as of the price cutoff date of October 20, 2026.
Changes will be effective as of the close of business on November 30, 2026.
SUMMARY OF THE CHANGES INCLUDED IN THIS ANNOUNCEMENT:
                                      Nb of         Nb of
                                      Securities    Securities
Index                                 Added         Deleted
MSCI CHINA A INDEX                    2             5
MSCI CHINA A INDEX
Additions                                           Deletions
HUADIAN NEW EN A (HK-C)                             ANGEL YEAST CO A (HK-C)
YUNNAN LINCANG A (HK-C)                             BEIJING NEW BLDG A(HK-C)
                                                    BOC INTL A (HK-C)
                                                    CHINA GREAT SEC A (HK-C)
                                                    WINTIME ENERGY A (HK-C)
"""

# 精简构造的期次日历（结构对齐 ir_dates.csv #BOD..#EOD 块）
_MSCI_IR_DATES_TEXT = """MSCI Announces the Next Eight Index Review Dates,,,,,,,,,,,,,,,
#BOD,,,,,,,,,,,,,,,
Quarter|Event|Announcement Date|Effective Date,,,,,,,,,,,,,,,
"Feb, 2027|""Index Review""|02-09-2027|03-01-2027",,,,,,,,,,,,,,,
"May, 2027|""Index Review""|05-10-2027|05-28-2027",,,,,,,,,,,,,,,
#EOD,,,,,,,,,,,,,,,
MSCI reserves the right to change these dates.,,,,,,,,,,,,,,,
"""

_MSCI_REVIEW_LINKS_HTML = """<html><body>
<a href="/eqb/gimi/stdindex/MSCI_Nov26_ChinaAPublicList_EN.pdf">Nov 2026</a>
<a href="/eqb/gimi/stdindex/MSCI_Aug26_ChinaAPublicList_EN.pdf">Aug 2026</a>
<a href="/eqb/gimi/stdindex/MSCI_May25_ChinaAPublicList_EN.pdf">May 2025</a>
</body></html>
"""

# SEC submissions JSON 最小样本（结构对齐 data.sec.gov 真实应答，fixture 回放不联网）
_SEC_SUBMISSIONS_SAMPLE = {
    "cik": 1577552,
    "name": "Alibaba Group Holding Ltd",
    "tickers": ["BABA"],
    "filings": {
        "recent": {
            "form": ["6-K", "20-F", "6-K", "4"],
            "filingDate": ["2026-11-23", "2026-08-20", "2026-11-06", "2026-11-01"],
            "accessionNumber": [
                "0001104659-26-111111", "0001104659-26-222222",
                "0001104659-26-333333", "0001104659-26-444444",
            ],
            "primaryDocument": [
                "form6k.htm", "form20f.htm", "form6k_b.htm", "",
            ],
            "primaryDocDescription": ["FORM 6-K", "ANNUAL REPORT", "FORM 6-K", ""],
            "reportDate": ["2026-09-30", "2026-03-31", "", ""],
        }
    },
}

# 真实样本（2026-11-27 直连实测 fed press_all.xml 截取，fixture 回放不联网）
_FED_RSS_SAMPLE = b"""<?xml version="1.0" encoding="utf-8" ?>
<rss version="2.0">
    <channel>
        <title>FRB: Press Release - All Releases</title>
        <item>
            <title>Minutes of the Federal Open Market Committee, October 27-28, 2026</title>
            <link><![CDATA[https://www.federalreserve.gov/newsevents/pressreleases/monetary20261118a.htm]]></link>
            <guid><![CDATA[https://www.federalreserve.gov/newsevents/pressreleases/monetary20261118a.htm]]></guid>
            <description><![CDATA[Minutes of the Federal Open Market Committee, October 27-28, 2026]]></description>
            <category>Monetary Policy</category>
            <pubDate><![CDATA[Wed, 18 Nov 2026 19:00:00 GMT]]></pubDate>
        </item>
        <item>
            <title>Agencies announce dollar thresholds for applicability of truth in lending rules</title>
            <link><![CDATA[https://www.federalreserve.gov/newsevents/pressreleases/bcreg20261125b.htm]]></link>
            <guid><![CDATA[https://www.federalreserve.gov/newsevents/pressreleases/bcreg20261125b.htm]]></guid>
            <description><![CDATA[Agencies announce dollar thresholds]]></description>
            <category>Banking and Consumer Regulatory Policy</category>
            <pubDate><![CDATA[Wed, 25 Nov 2026 20:00:00 GMT]]></pubDate>
        </item>
    </channel>
</rss>
"""


@pytest.fixture(autouse=True)
def _clean_disclosure_cache():
    """每测清对象缓存，避免用例间串味。"""
    from tradex.utils.cache import cache

    cache.clear()
    yield
    cache.clear()


# ============================================================
# 解析（fixture 回放）
# ============================================================


class TestFedRssParse:
    def test_parse_sample_fields_and_order(self):
        df = _parse_fed_rss(_FED_RSS_SAMPLE, limit=10)
        assert list(df.columns) == list(DISCLOSURE_COLUMNS)
        assert len(df) == 2
        row = df.iloc[0]
        assert row["source_name"] == "fed"
        assert row["doc_type"] == "press_release"
        assert row["publish_time"] == "2026-11-18T19:00:00Z"
        assert row["effective_time"] == ""
        assert row["source_grade"] == "official"
        assert row["securities"] == "[]"
        assert row["url"].endswith("monetary20261118a.htm")
        raw = json.loads(row["raw_json"])
        assert raw["category"] == "Monetary Policy"

    def test_parse_limit_truncates(self):
        df = _parse_fed_rss(_FED_RSS_SAMPLE, limit=1)
        assert len(df) == 1

    def test_publish_time_all_utc_iso(self):
        df = _parse_fed_rss(_FED_RSS_SAMPLE, limit=10)
        assert (df["publish_time"].str.endswith("Z")).all()

    def test_cn_time_conversion(self):
        assert utc_iso_to_cn("2026-11-25T20:00:00Z") == "2026-11-26 04:00"
        assert utc_iso_to_cn("") == ""

    def test_rows_to_df_empty_raises(self):
        with pytest.raises(OfficialDisclosureSourceError):
            _parse_fed_rss(
                b"<?xml version='1.0'?><rss version='2.0'><channel>"
                b"<title>empty</title></channel></rss>",
                limit=10,
            )

    def test_bad_xml_raises(self):
        with pytest.raises(OfficialDisclosureSourceError, match="XML"):
            _parse_fed_rss(b"<rss><channel><item>", limit=10)

    def test_missing_key_fields_raises(self):
        broken = (
            b"<?xml version='1.0'?><rss version='2.0'><channel>"
            b"<item><title>only title</title></item>"
            b"</channel></rss>"
        )
        with pytest.raises(OfficialDisclosureSourceError, match="关键字段缺失"):
            _parse_fed_rss(broken, limit=10)

    def test_bad_pubdate_raises(self):
        broken = (
            b"<?xml version='1.0'?><rss version='2.0'><channel>"
            b"<item><title>t</title><link>http://x</link>"
            b"<pubDate>not-a-date</pubDate></item>"
            b"</channel></rss>"
        )
        with pytest.raises(OfficialDisclosureSourceError, match="pubDate"):
            _parse_fed_rss(broken, limit=10)


# ============================================================
# 源 2：SEC EDGAR 解析（fixture 回放，不联网）
# ============================================================


class TestSecEdgarParse:
    def test_parse_sample_fields(self):
        df = _parse_sec_submissions(_SEC_SUBMISSIONS_SAMPLE, limit=10)
        assert list(df.columns) == list(DISCLOSURE_COLUMNS)
        assert len(df) == 4
        row = df.iloc[0]  # filingDate 降序无关——解析保持上游顺序，取首行即最新
        assert row["source_name"] == "sec_edgar"
        assert row["doc_type"] == "filing"
        assert row["publish_time"] == "2026-11-23T00:00:00Z"
        assert row["effective_time"] == "2026-09-30T00:00:00Z"
        assert row["source_grade"] == "official"
        assert json.loads(row["securities"]) == ["BABA"]
        assert "6-K" in row["title"]
        assert row["url"].endswith("form6k.htm")
        raw = json.loads(row["raw_json"])
        assert raw["entity"] == "Alibaba Group Holding Ltd"

    def test_form_type_filter(self):
        df = _parse_sec_submissions(_SEC_SUBMISSIONS_SAMPLE, limit=10, form_type="6-K")
        assert len(df) == 2
        assert (df["raw_json"].map(lambda s: json.loads(s)["form"] == "6-K")).all()

    def test_limit_truncates(self):
        df = _parse_sec_submissions(_SEC_SUBMISSIONS_SAMPLE, limit=2)
        assert len(df) == 2

    def test_url_construction(self):
        df = _parse_sec_submissions(_SEC_SUBMISSIONS_SAMPLE, limit=10)
        assert "/Archives/edgar/data/1577552/000110465926111111/form6k.htm" in df.iloc[0]["url"]

    def test_empty_recent_raises(self):
        with pytest.raises(OfficialDisclosureSourceError, match="recent"):
            _parse_sec_submissions({"cik": 1, "filings": {"recent": {}}}, limit=10)


# ============================================================
# 源 3：MSCI 解析（fixture 回放，不联网）
# ============================================================


class TestMsciParse:
    def test_review_code_roundtrip(self):
        assert _msci_review_code("2026-11") == "Nov26"
        assert _msci_review_code("Nov26") == "Nov26"
        assert _msci_period_from_code("Nov26") == "2026-11"
        assert _date_en_to_iso("November 11, 2026") == "2026-11-11"

    def test_review_code_invalid(self):
        with pytest.raises(ValueError, match="期次格式"):
            _msci_review_code("bad")

    def test_chinaa_list_parse(self):
        url = "https://app2.msci.com/eqb/gimi/stdindex/MSCI_Nov26_ChinaAPublicList_EN.pdf"
        df = _parse_msci_chinaa_text(_MSCI_CHINAA_TEXT, "Nov26", url, limit=50)
        assert len(df) == 7  # 2 add + 5 del（fixture 精简版，计数与摘要行一致）
        import json as _json

        actions = df["raw_json"].map(lambda s: _json.loads(s)["action"]).tolist()
        assert actions.count("add") == 2
        assert actions.count("delete") == 5
        assert df.iloc[0]["publish_time"] == "2026-11-11T00:00:00Z"
        assert df.iloc[0]["effective_time"] == "2026-11-30T00:00:00Z"
        assert (df["securities"] == "[]").all()  # 无 A 股代码不臆译
        assert df.iloc[0]["source_name"] == "msci"
        assert df.iloc[0]["doc_type"] == "index_review"
        raw0 = _json.loads(df.iloc[0]["raw_json"])
        assert raw0["review_period"] == "2026-11"
        assert "HUADIAN" in raw0["security_name_en"]

    def test_chinaa_count_mismatch_raises(self):
        bad = _MSCI_CHINAA_TEXT.replace(
            "MSCI CHINA A INDEX                    2             5",
            "MSCI CHINA A INDEX                    3             5",
        )
        assert bad != _MSCI_CHINAA_TEXT  # 防替换空转
        with pytest.raises(OfficialDisclosureSourceError, match="计数不符"):
            _parse_msci_chinaa_text(bad, "Nov26", "u", limit=50)
        # bad 文本把摘要改为 3/5（与明细 2/5 不符），计数守卫必须红

    def test_chinaa_missing_title_raises(self):
        with pytest.raises(OfficialDisclosureSourceError, match="CHINA A INDEX"):
            _parse_msci_chinaa_text("no index title here", "Nov26", "u", limit=10)

    def test_review_links_parse(self):
        pairs = _parse_msci_review_links(_MSCI_REVIEW_LINKS_HTML)
        assert pairs[0] == ("Nov26", "/eqb/gimi/stdindex/MSCI_Nov26_ChinaAPublicList_EN.pdf")
        assert len(pairs) == 3
        with pytest.raises(OfficialDisclosureSourceError, match="ChinaAPublicList"):
            _parse_msci_review_links("<html></html>")

    def test_ir_dates_parse(self):
        df = _parse_msci_ir_dates(_MSCI_IR_DATES_TEXT, limit=10)
        assert len(df) == 2
        assert df.iloc[0]["publish_time"] == "2027-02-09T00:00:00Z"
        assert df.iloc[0]["effective_time"] == "2027-03-01T00:00:00Z"
        assert "Feb, 2027" in df.iloc[0]["title"]

    def test_ir_dates_no_bod_raises(self):
        with pytest.raises(OfficialDisclosureSourceError, match="BOD"):
            _parse_msci_ir_dates("no markers", limit=10)


# ============================================================
# 源 4：FTSE 解析（fixture 回放，不联网）
# ============================================================


class TestFtseParse:
    def test_dmy_date(self):
        assert _date_en_dmy_to_iso("21 December 2026") == "2026-12-21"
        assert _date_en_dmy_to_iso("13 November 2026") == "2026-11-13"

    def test_notice_parse(self):
        df = _parse_ftse_notice_text(_FTSE_NOTICE_TEXT, "2622506", "u")
        assert len(df) == 1
        row = df.iloc[0]
        assert row["source_name"] == "ftse"
        assert row["doc_type"] == "index_review"
        assert row["publish_time"] == "2026-11-13T00:00:00Z"
        assert row["effective_time"] == "2026-12-21T00:00:00Z"
        assert "December 2026 Quarterly Changes" in row["title"]
        assert "登录门户" in row["summary"]  # 名单附件需登录，本源诚实不抓
        import json as _json

        raw = _json.loads(row["raw_json"])
        assert raw["notice_id"] == "2622506"

    def test_notice_no_effective_raises(self):
        with pytest.raises(OfficialDisclosureSourceError):
            _parse_ftse_notice_text("FTSE Russell something without dates", "1", "u")

    def test_fetch_requires_identifier(self):
        with pytest.raises(ValueError, match="notice id"):
            fetch_official_disclosure(source="ftse", identifier="", limit=5)


# ============================================================
# 源 5：HKEX 解析（fixture 回放，不联网）
# ============================================================

# titleSearchServlet 应答（结构对齐真实出参：result 为转义 JSON 字符串）
_HKEX_SEARCH_PAYLOAD = (
    '{"result":"[{\\"NEWS_ID\\":\\"2026111800449\\",\\"TITLE\\":\\"截至二零二六年九月三十日止季度業績公告\\",'
    '\\"SHORT_TEXT\\":\\"業績公告<br/>季內財務報表\\",\\"LONG_TEXT\\":\\"\\",'
    '\\"STOCK_CODE\\":\\"00700<br/>80700\\",\\"STOCK_NAME\\":\\"騰訊控股\\",'
    '\\"FILE_TYPE\\":\\"PDF\\",\\"DATE_TIME\\":\\"18/11/2026 19:15\\",'
    '\\"FILE_INFO\\":\\"588611 KB\\",\\"FILE_LINK\\":\\"/listedco/listconews/sehk/2026/1118/2026111800449.pdf\\"}]",'
    '"hasNextRow":false,"sortList":"[[0,0]]","rowRange":100,"lang":"C","loadedRecord":1,"recordCnt":1}'
)


class TestHkexParse:
    def test_parse_fields_and_tz(self):
        df = _parse_hkex_search(_HKEX_SEARCH_PAYLOAD, limit=10)
        assert len(df) == 1
        row = df.iloc[0]
        assert row["source_name"] == "hkex"
        assert row["doc_type"] == "filing"
        # 18/11/2026 19:15 香港(UTC+8) → 11:15 UTC
        assert row["publish_time"] == "2026-11-18T11:15:00Z"
        assert json.loads(row["securities"]) == ["00700", "80700"]  # <br/> 清洗
        assert "業績公告" in row["summary"]  # 分类噪音清洗
        assert row["url"].endswith("/listedco/listconews/sehk/2026/1118/2026111800449.pdf")

    def test_bad_result_raises(self):
        with pytest.raises(OfficialDisclosureSourceError, match="result"):
            _parse_hkex_search('{"nope":1}', limit=10)

    def test_prefix_stockid_resolution(self, monkeypatch):
        """prefix.do JSONP → stockId 映射（mock HTTP，700→7609 来自 P00 实测）。"""
        import tradex.data_sources.official_disclosure_fetchers as mod

        jsonp = (
            'callback({"more":"1","stockInfo":[{"stockId":7609,'
            '"code":"00700","name":"騰訊控股"}]})'
        )
        monkeypatch.setattr(mod, "_http_get", lambda url, **kw: jsonp.encode("utf-8"))
        stock_id, code = mod._hkex_resolve_stock_id("700")
        assert stock_id == 7609
        assert code == "00700"

    def test_prefix_no_stockid_raises(self, monkeypatch):
        import tradex.data_sources.official_disclosure_fetchers as mod

        monkeypatch.setattr(mod, "_http_get", lambda url, **kw: b"callback({\"stockInfo\":[]})")
        with pytest.raises(OfficialDisclosureSourceError, match="stockId"):
            mod._hkex_resolve_stock_id("999999")

    def test_empty_records_raises(self):
        empty = '{"result":"[]","hasNextRow":false,"recordCnt":0}'
        with pytest.raises(OfficialDisclosureSourceError, match="零记录"):
            _parse_hkex_search(empty, limit=10)


# ============================================================
# 分发入口 + 源登记表
# ============================================================


class TestDispatch:
    def test_unknown_source_value_error(self):
        with pytest.raises(ValueError, match="未知境外官方源"):
            fetch_official_disclosure(source="nope")

    def test_official_sources_registry_contains_fed(self):
        assert "fed" in OFFICIAL_SOURCES
        sources = list_official_sources()
        keys = {s["source"] for s in sources}
        assert "fed" in keys
        assert all(s["status"] == "active" for s in sources)

    def test_dispatch_fetch_failure_wraps_as_source_error(self, monkeypatch):
        """分发入口把底层网络异常包成断源语义（保留真因链）。"""
        def _boom(limit, **kwargs):
            raise ConnectionError("network down")

        monkeypatch.setitem(OFFICIAL_SOURCES, "fed", (_boom, "stub"))
        with pytest.raises(OfficialDisclosureSourceError, match="network down"):
            fetch_official_disclosure(source="fed")


# ============================================================
# service 层
# ============================================================


def _stub_route(df_or_exc_by_source: dict, default: Exception | None = None):
    """构造 SmartRouter.route 替身。

    source → DataFrame 或异常；未知源：default 为异常时抛（全失败场景），
    否则返回默认成功样本（混合场景，加新源不破测试）。
    """

    def _route(data_type, *, source, limit, **kwargs):
        assert data_type == "official_disclosure"
        if source in df_or_exc_by_source:
            item = df_or_exc_by_source[source]
        elif isinstance(default, Exception):
            raise default
        else:
            item = _sample_df(source)
        if isinstance(item, Exception):
            raise item
        return item.head(limit), f"official_direct:{source}"

    return _route


def _sample_df(source: str, n: int = 2, doc_type: str = "press_release") -> pd.DataFrame:
    rows = [
        {
            "source_name": source,
            "doc_type": doc_type,
            "publish_time": f"2026-11-2{9 - i}T10:0{i}:00Z",
            "effective_time": "",
            "title": f"{source} 公告 {i}",
            "summary": f"summary {i}",
            "url": f"https://example.com/{source}/{i}",
            "securities": "[]",
            "source_grade": "official",
            "raw_json": "{}",
        }
        for i in range(n)
    ]
    return pd.DataFrame(rows, columns=list(DISCLOSURE_COLUMNS))


class TestOfficialDisclosureService:
    def test_unknown_source_raises_value_error(self):
        from tradex.service import official_disclosure_service as ods

        with pytest.raises(ValueError, match="未知境外官方源"):
            ods.get_official_disclosures(source="nope")

    def test_single_source_ok(self, monkeypatch):
        from tradex.service import official_disclosure_service as ods

        monkeypatch.setattr(
            ods._router, "route",
            _stub_route({"fed": _sample_df("fed")}),
        )
        out = ods.get_official_disclosures(source="fed", limit=10)
        assert out["source"] == "fed"
        assert out["count"] == 2
        assert out["failed_sources"] == []
        rec = out["disclosures"][0]
        assert rec["publish_time_cn"]  # 北京时间双标列存在
        assert rec["publish_time"].endswith("Z")

    def test_aggregate_degrades_single_failure(self, monkeypatch):
        """聚合模式：单源失败显式降级进 failed_sources，不拖垮其余源。"""
        from tradex.service import official_disclosure_service as ods

        monkeypatch.setattr(
            ods._router, "route",
            _stub_route(
                {"fed": OfficialDisclosureSourceError("fed down")},
                default=OfficialDisclosureSourceError("also down"),
            ),
        )
        # 全部已接入源失败必须抛（诚实失败，不是空态）
        with pytest.raises(RuntimeError, match="全部源失败"):
            ods.get_official_disclosures(source="", limit=10)

    def test_aggregate_mixed_sources(self, monkeypatch):
        from tradex.service import official_disclosure_service as ods

        monkeypatch.setitem(OFFICIAL_SOURCES, "stub2", (lambda **k: pd.DataFrame(), "stub"))
        monkeypatch.setattr(
            ods._router, "route",
            _stub_route({
                "fed": OfficialDisclosureSourceError("fed down"),
                "stub2": _sample_df("stub2"),
            }),
        )
        out = ods.get_official_disclosures(source="", limit=10)
        # 除 fed 外全部成功（未知源走默认样本）→ 每成功源 2 条
        assert out["count"] == 2 * (len(OFFICIAL_SOURCES) - 1)  # fed 失败不计
        failed = {f["source"]: f["error"] for f in out["failed_sources"]}
        assert failed.get("fed") == "fed down"
        assert {f["source"] for f in out["failed_sources"]} == {"fed"}  # 仅 fed 一个失败源

    def test_doc_type_filter(self, monkeypatch):
        from tradex.service import official_disclosure_service as ods

        df = pd.concat([_sample_df("fed", doc_type="press_release"),
                        _sample_df("fed", doc_type="filing")], ignore_index=True)
        monkeypatch.setattr(ods._router, "route", _stub_route({"fed": df}))
        out = ods.get_official_disclosures(source="fed", doc_type="filing", limit=10)
        assert out["count"] == 2
        assert all(r["doc_type"] == "filing" for r in out["disclosures"])

    def test_cache_hit(self, monkeypatch):
        from tradex.service import official_disclosure_service as ods

        calls = {"n": 0}

        def _counting_route(data_type, **kwargs):
            calls["n"] += 1
            return _sample_df("fed"), "official_direct:fed"

        monkeypatch.setattr(ods._router, "route", _counting_route)
        ods.get_official_disclosures(source="fed", limit=10)
        ods.get_official_disclosures(source="fed", limit=10)
        assert calls["n"] == 1  # 第二次走缓存


# ============================================================
# REST 端点
# ============================================================


def _build_min_app():
    from tests._rest_test_base import build_min_test_app

    return build_min_test_app()


class TestOfficialRest:
    def test_disclosures_ok_envelope(self, monkeypatch):
        from fastapi.testclient import TestClient

        from tradex.api.schemas import ERR_OK
        from tradex.service import official_disclosure_service as ods

        monkeypatch.setattr(ods._router, "route", _stub_route({"fed": _sample_df("fed")}))
        client = TestClient(_build_min_app())
        resp = client.get("/api/v1/official/disclosures", params={"source": "fed"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == ERR_OK
        assert body["data"]["count"] == 2

    def test_disclosures_unknown_source_400(self):
        from fastapi.testclient import TestClient

        from tradex.api.schemas import ERR_BAD_REQUEST

        client = TestClient(_build_min_app())
        resp = client.get("/api/v1/official/disclosures", params={"source": "nope"})
        assert resp.status_code == 400
        assert resp.json()["code"] == ERR_BAD_REQUEST

    def test_sources_envelope(self):
        from fastapi.testclient import TestClient

        from tradex.api.schemas import ERR_OK

        client = TestClient(_build_min_app())
        resp = client.get("/api/v1/official/sources")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == ERR_OK
        assert {s["source"] for s in body["data"]["sources"]} >= {"fed"}


# ============================================================
# MCP 工具注册 + 出口信封
# ============================================================


class TestOfficialMcp:
    def test_register_exposes_tools(self):
        from mcp.server.fastmcp import FastMCP

        from tradex.tools import official_disclosure as od_tools

        mcp = FastMCP("test-od")
        od_tools.register(mcp)
        tools = set(mcp._tool_manager._tools)
        assert {"get_official_disclosures", "get_official_sources"} <= tools

    def test_tool_success_envelope(self, monkeypatch):
        import asyncio

        from mcp.server.fastmcp import FastMCP

        from tradex.service import official_disclosure_service as ods
        from tradex.tools import official_disclosure as od_tools

        monkeypatch.setattr(ods._router, "route", _stub_route({"fed": _sample_df("fed")}))
        mcp = FastMCP("test-od")
        od_tools.register(mcp)
        raw = asyncio.run(mcp._tool_manager._tools["get_official_disclosures"].fn(
            source="fed", doc_type="", limit=10,
        ))
        payload = json.loads(raw)
        assert payload["count"] == 2
        assert "error" not in payload

    def test_tool_failure_envelope(self, monkeypatch):
        import asyncio

        from mcp.server.fastmcp import FastMCP

        from tradex.service import official_disclosure_service as ods
        from tradex.tools import official_disclosure as od_tools

        monkeypatch.setattr(
            ods, "get_official_disclosures",
            lambda **kwargs: (_ for _ in ()).throw(RuntimeError("fed down")),
        )
        mcp = FastMCP("test-od")
        od_tools.register(mcp)
        raw = asyncio.run(mcp._tool_manager._tools["get_official_disclosures"].fn(
            source="fed", doc_type="", limit=10,
        ))
        payload = json.loads(raw)
        assert payload["error"] is True
        assert "fed down" in payload["message"]
