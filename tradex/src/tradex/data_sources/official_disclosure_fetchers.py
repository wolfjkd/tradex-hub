"""境外官方公告统一数据源 fetch_fn 包装器（OFFSRC-00 P01，2026-11-27）。

提供统一类型 ``official_disclosure``：一套字段模型 + 按源分发的适配器入口，
境外官方机构公告（Fed 首发打样；SEC EDGAR / FTSE Russell / MSCI / HKEX /
恒生 按 OFFSRC-00 工单序 P02–P05 逐个接入）。

统一字段模型（规划文档 §5.2，DataFrame 列，全部字符串，缺省空串）：
  source_name    来源机构        fed | msci | ftse | sec_edgar | hkex | hsi
  doc_type       文档类型        index_review | filing | press_release | macro_release
  publish_time   发布时刻        ISO8601 UTC（存储口径；北京时间展示由 service 双标）
  effective_time 生效时刻        ISO8601 UTC，无则空串
  title          标题
  summary        摘要
  url            官方原文链接
  securities     涉及标的        JSON 数组字符串（如 "[]"，可含代码列表）
  source_grade   来源等级        official | secondary
  raw_json       原始载荷        单条原始数据 JSON（防解析丢字段）

设计原则：
  - 聚合分发模式：与 industry_news「1 类型 12 赛道」同构——一个 data_type
    + 一个 source_name（official_direct），fetcher 内部按 ``source`` 参数
    分发到各源的解析函数；加新源 = 在 OFFICIAL_SOURCES 登记，不动 _SOURCE_TABLE。
  - 纯 Python 标准库抓取（urllib + xml.etree），零第三方依赖（照 industry_news 先例）。
  - 失败必须抛出（v3.3.15 起约定）：断源/结构变化/零条目一律抛
    OfficialDisclosureSourceError，由 SmartRouter 记账降级；吞成空表会让
    降级链与健康分全部失效。
  - 网络铁律（AGENTS.md §1.3）：默认直连（显式空 ProxyHandler，不读
    HTTP(S)_PROXY）；如个别境外源确需代理，用专用变量 OFFSRC_PROXY 显式
    指定，不污染其他数据源。

规划文档：Obsidian 开发计划/项目-tradex-hub/专项任务/OFFSRC-00-*.md
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Callable
from xml.etree import ElementTree as ET

import pandas as pd

logger = logging.getLogger("tradex.official_disclosure")

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_TIMEOUT = 30  # 境外站直连实测 2-6s（2026-11-26/27），放宽到 30s 留 HKEX 慢响余量

# 统一列序（fetcher 输出契约，service/下游全按此对齐）
DISCLOSURE_COLUMNS = (
    "source_name", "doc_type", "publish_time", "effective_time",
    "title", "summary", "url", "securities", "source_grade", "raw_json",
)


class OfficialDisclosureSourceError(RuntimeError):
    """境外官方源断源/结构变化/零条目。

    假数据比 5xx 更糟（健康分正常但读数无效），必须抛出走 SmartRouter 降级；
    自定义异常类型替代消息字符串匹配哨兵（QI-STD 纪律，异常链 raise from）。
    """


def _build_opener() -> urllib.request.OpenerDirector:
    """构建 opener：默认显式直连；OFFSRC_PROXY 专用变量可覆盖（不读 HTTP_PROXY 系）。"""
    proxy = os.environ.get("OFFSRC_PROXY", "").strip()
    if proxy:
        logger.info("official_disclosure using OFFSRC_PROXY: %s", proxy)
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy}),
            urllib.request.HTTPSHandler(),
        )
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),  # 显式空字典 = 直连（铁律：不读环境代理变量）
        urllib.request.HTTPSHandler(),
    )


def _http_get(url: str) -> bytes:
    """直连 GET，非 200 抛 OfficialDisclosureSourceError（断源语义，SmartRouter 记账）。"""
    req = urllib.request.Request(
        url, headers={"User-Agent": _UA, "Accept": "*/*"},
    )
    try:
        resp = _build_opener().open(req, timeout=_TIMEOUT)
        body = resp.read()
        status = getattr(resp, "status", resp.getcode())
    except OfficialDisclosureSourceError:
        raise
    except Exception as exc:
        raise OfficialDisclosureSourceError(f"境外官方源请求失败: {url} ({exc})") from exc
    if status != 200:
        raise OfficialDisclosureSourceError(
            f"境外官方源 HTTP {status}: {url}（bytes={len(body)}）"
        )
    return body


def _rfc822_to_utc_iso(text: str) -> str:
    """RFC822 时间（RSS pubDate）→ ISO8601 UTC（统一存储口径）。"""
    dt = parsedate_to_datetime(text.strip())
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_iso_to_cn(utc_iso: str) -> str:
    """ISO8601 UTC → 北京时间展示口径（YYYY-MM-DD HH:MM）。空串原样返回。"""
    if not utc_iso:
        return ""
    dt = datetime.strptime(utc_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")


def _empty_disclosure_df() -> pd.DataFrame:
    """带统一列序的空表（仅限「合法零条目」场景；断源禁止走此路径）。"""
    return pd.DataFrame(columns=list(DISCLOSURE_COLUMNS))


def _rows_to_df(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        raise OfficialDisclosureSourceError("境外官方源解析后零条目（断源或结构变化）")
    df = pd.DataFrame(rows, columns=list(DISCLOSURE_COLUMNS))
    return df


# ============================================================
# 源 1：Fed 美联储 — press_release（RSS 2.0，L1）
# ============================================================

_FED_RSS_URL = "https://www.federalreserve.gov/feeds/press_all.xml"


def _parse_fed_rss(xml_bytes: bytes, limit: int) -> pd.DataFrame:
    """解析 Fed press_all RSS（标准 RSS 2.0：title/link/guid/description/category/pubDate）。"""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise OfficialDisclosureSourceError(f"Fed RSS XML 解析失败（结构变化?）: {exc}") from exc
    items = root.findall("./channel/item")
    if not items:
        raise OfficialDisclosureSourceError("Fed RSS 零条目（断源或结构变化）")

    rows: list[dict] = []
    for item in items:
        def _text(tag: str) -> str:
            node = item.find(tag)
            return (node.text or "").strip() if node is not None and node.text else ""

        title = _text("title")
        link = _text("link")
        pub = _text("pubDate")
        if not title or not link or not pub:
            # 关键字段缺失 = 结构变化，逐条校验比事后静默丢字段诚实
            raise OfficialDisclosureSourceError(
                f"Fed RSS 条目关键字段缺失（title/link/pubDate）: {title[:40]!r}"
            )
        try:
            publish_utc = _rfc822_to_utc_iso(pub)
        except Exception as exc:
            raise OfficialDisclosureSourceError(
                f"Fed RSS pubDate 无法解析: {pub!r}"
            ) from exc
        category = _text("category")
        raw_item = {
            "title": title, "link": link, "guid": _text("guid"),
            "description": _text("description"), "category": category,
            "pubDate": pub,
        }
        rows.append({
            "source_name": "fed",
            "doc_type": "press_release",
            "publish_time": publish_utc,
            "effective_time": "",
            "title": title,
            "summary": _text("description"),
            "url": link,
            "securities": "[]",
            "source_grade": "official",
            "raw_json": json.dumps(raw_item, ensure_ascii=False),
        })
    return _rows_to_df(rows).head(limit)


def _fetch_fed(limit: int, **kwargs) -> pd.DataFrame:
    """Fed 全部新闻稿 RSS（议息决议/监管声明/贴现窗会议纪要等，官方一手）。"""
    return _parse_fed_rss(_http_get(_FED_RSS_URL), limit)


# ============================================================
# 源 2：SEC EDGAR — filing（官方 JSON API，L0）（OFFSRC-00 P02，2026-11-28）
# ============================================================

# SEC 公平访问政策要求声明请求方身份（UA = 软件名 + 联系方式），并限 10 req/s；
# 本仓单次调用天然低于限流，聚合默认清单时每只间隔 _SEC_RATE_GAP 秒。
_SEC_UA = "tradex-hub data fetcher wolfjkd/tradex-hub"
_SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:0>10}.json"
_SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SEC_ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{doc}"
_SEC_RATE_GAP = 0.12  # 聚合多 CIK 时请求间隔（≈8 req/s < 10 req/s 上限）
# 中概默认观察清单（ADR/二次上市代表；identifier 留空时的聚合口径）
_SEC_DEFAULT_ADRS = (
    "BABA", "PDD", "JD", "LI", "NIO", "BIDU", "NTES", "TCOM", "BEKE", "ZTO",
)

# ticker→CIK 映射进程内缓存（官方文件 ~1MB，进程生命周期一次）
_ticker_map_cache: dict[str, tuple[int, str]] | None = None


def _sec_opener() -> urllib.request.OpenerDirector:
    """SEC 专用 opener：显式直连 + 声明 UA（公平访问政策）。"""
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler()
    )


def _sec_get_json(url: str) -> dict:
    req = urllib.request.Request(
        url, headers={"User-Agent": _SEC_UA, "Accept": "application/json"}
    )
    try:
        with _sec_opener().open(req, timeout=_TIMEOUT) as resp:
            status = getattr(resp, "status", resp.getcode())
            body = resp.read()
    except Exception as exc:
        raise OfficialDisclosureSourceError(f"SEC EDGAR 请求失败: {url} ({exc})") from exc
    if status != 200:
        raise OfficialDisclosureSourceError(
            f"SEC EDGAR HTTP {status}: {url}（bytes={len(body)}）"
        )
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise OfficialDisclosureSourceError(
            f"SEC EDGAR 响应非 JSON（结构变化?）: {url}"
        ) from exc


def _sec_ticker_map() -> dict[str, tuple[int, str]]:
    """ticker → (CIK, 公司名称)，官方映射文件进程内缓存。"""
    global _ticker_map_cache
    if _ticker_map_cache is None:
        data = _sec_get_json(_SEC_TICKERS_URL)
        mapping: dict[str, tuple[int, str]] = {}
        for entry in data.values():
            ticker = str(entry.get("ticker") or "").upper()
            if ticker:
                mapping[ticker] = (int(entry["cik_str"]), str(entry.get("title") or ""))
        if not mapping:
            raise OfficialDisclosureSourceError("SEC ticker 映射解析后为空（结构变化?）")
        _ticker_map_cache = mapping
    return _ticker_map_cache


def _sec_resolve_cik(identifier: str) -> tuple[int, str]:
    """identifier → (CIK, 名称)。纯数字按 CIK 直用；否则按 ticker 查官方映射。"""
    ident = identifier.strip()
    if ident.isdigit():
        return int(ident), ""
    cik, name = _sec_ticker_map().get(ident.upper(), (0, ""))
    if not cik:
        raise ValueError(
            f"ticker {ident!r} 未在 SEC 官方映射中找到（检查代码或直接给 CIK）"
        )
    return cik, name


def _parse_sec_submissions(payload: dict, limit: int, form_type: str = "") -> pd.DataFrame:
    """解析 submissions JSON 的 filings.recent → 统一模型（doc_type=filing）。"""
    recent = (payload.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    if not forms:
        raise OfficialDisclosureSourceError(
            "SEC submissions filings.recent 为空（断源或结构变化）"
        )
    cik = int(payload.get("cik") or 0)
    entity = str(payload.get("name") or "")
    ticker = str((payload.get("tickers") or [""])[0] or "").upper()
    want = (form_type or "").strip().upper() or None

    rows: list[dict] = []
    for i, form in enumerate(forms):
        if want is not None and str(form).upper() != want:
            continue
        filing_date = str(recent.get("filingDate", [""] * len(forms))[i] or "")
        if not filing_date:
            continue  # 无 filingDate 的残缺条目跳过（不伪造时间）
        accession = str(recent.get("accessionNumber", [""] * len(forms))[i] or "")
        primary_doc = str(recent.get("primaryDocument", [""] * len(forms))[i] or "")
        report_date = str(recent.get("reportDate", [""] * len(forms))[i] or "")
        desc = str(recent.get("primaryDocDescription", [""] * len(forms))[i] or "").strip()
        url = (
            _SEC_ARCHIVE_URL.format(cik=cik, acc_nodash=accession.replace("-", ""), doc=primary_doc)
            if accession and primary_doc
            else ""
        )
        raw_item = {
            "form": str(form), "filingDate": filing_date, "reportDate": report_date,
            "accessionNumber": accession, "primaryDocument": primary_doc,
            "primaryDocDescription": desc, "entity": entity,
        }
        rows.append({
            "source_name": "sec_edgar",
            "doc_type": "filing",
            "publish_time": f"{filing_date}T00:00:00Z",
            "effective_time": f"{report_date}T00:00:00Z" if report_date else "",
            "title": f"{entity}: {form} {desc or primary_doc}".strip(),
            "summary": desc or primary_doc,
            "url": url,
            "securities": json.dumps([ticker] if ticker else [], ensure_ascii=False),
            "source_grade": "official",
            "raw_json": json.dumps(raw_item, ensure_ascii=False),
        })
        if len(rows) >= limit:
            break
    return _rows_to_df(rows)


def _fetch_sec_edgar(limit: int, identifier: str = "", form_type: str = "", **kwargs) -> pd.DataFrame:
    """SEC EDGAR 最近披露（identifier=ticker/CIK；留空聚合默认中概 10 只）。"""
    import time as _time

    if identifier and str(identifier).strip():
        cik, _name = _sec_resolve_cik(identifier)
        payload = _sec_get_json(_SEC_SUBMISSIONS_URL.format(cik=cik))
        return _parse_sec_submissions(payload, limit, form_type=form_type)
    # 聚合默认清单：每只取 min(limit, 5) 条，间隔 _SEC_RATE_GAP 防超 10 req/s
    per = max(1, min(limit, 5))
    frames: list[pd.DataFrame] = []
    for i, ticker in enumerate(_SEC_DEFAULT_ADRS):
        if i:
            _time.sleep(_SEC_RATE_GAP)
        cik, _name = _sec_resolve_cik(ticker)
        payload = _sec_get_json(_SEC_SUBMISSIONS_URL.format(cik=cik))
        frames.append(_parse_sec_submissions(payload, per, form_type=form_type))
    return _rows_to_df(
        pd.concat(frames, ignore_index=True)
        .sort_values("publish_time", ascending=False)
        .to_dict(orient="records")
    )


# ============================================================
# 源登记表 — P02–P05 接新源在此加行（不动 _SOURCE_TABLE / 计数断言）
# ============================================================

# value = (分发函数, 一句话说明)。函数签名统一 (limit, **kwargs) -> DataFrame。
OFFICIAL_SOURCES: dict[str, tuple[Callable[..., pd.DataFrame], str]] = {
    "fed": (_fetch_fed, "美联储新闻稿 RSS（议息/监管声明，官方一手）"),
    "sec_edgar": (_fetch_sec_edgar, "SEC EDGAR 最近披露（中概股 10-K/10-Q/8-K/6-K，官方 JSON API）"),
}


def list_official_sources() -> list[dict]:
    """已接入境外官方源清单（供 REST /sources 与 MCP 说明用）。"""
    return [
        {"source": name, "description": desc, "status": "active"}
        for name, (_fn, desc) in sorted(OFFICIAL_SOURCES.items())
    ]


def fetch_official_disclosure(source: str = "fed", limit: int = 30, **kwargs) -> pd.DataFrame:
    """统一分发入口（注册为 official_disclosure 类型唯一 fetcher）。

    Args:
        source: 境外官方源 key（见 OFFICIAL_SOURCES），未知 key 抛 ValueError
        limit: 最多返回条数

    Returns:
        统一字段模型 DataFrame（列序见 DISCLOSURE_COLUMNS）

    Raises:
        ValueError: 未知 source（参数错误，非断源）
        OfficialDisclosureSourceError: 断源/结构变化/零条目（SmartRouter 记账降级）
    """
    key = (source or "").strip().lower()
    entry = OFFICIAL_SOURCES.get(key)
    if entry is None:
        raise ValueError(f"未知境外官方源: {source!r}; 可用: {sorted(OFFICIAL_SOURCES)}")
    fn, _desc = entry
    try:
        return fn(limit=limit, **kwargs)
    except OfficialDisclosureSourceError:
        raise  # 断源语义原样上抛，SmartRouter 记账
    except ValueError:
        raise
    except Exception as exc:
        # 其余异常统一包成断源语义（保留真因链），避免裸异常穿透路由层
        logger.warning("fetch_official_disclosure(%s) failed: %s", key, exc)
        raise OfficialDisclosureSourceError(
            f"境外官方源抓取失败 ({key}): {exc}"
        ) from exc
