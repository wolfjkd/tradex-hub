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

import gzip
import json
import logging
import os
import re
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
# 源 3：MSCI — index_review（L2 直连静态文件 + PDF 抽取）（OFFSRC-00 P03）
# ============================================================
# P00 结论（2026-11-27）：Akamai Challenge 不复现，数据在 app2 静态域——
#   ① 名单：index_review.html 逐期目录 → MSCI_<Mon><YY>_ChinaAPublicList_EN.pdf
#     （第 1 页即完整名单纯文本，第 2 页起免责声明）
#   ② 期次日历：ir_dates.csv（gzip，未来 8 期公布日+生效日）→ P07 倒计时数据源
#   ③ 摘要哨兵：Announcement 枚举端点 → DocGet/pub_key 直链（pub_key 已是
#     URL-encoded Base64，拼接时禁止二次编码）
# ⚠️ ST（Global Standard）PDF 的 China（H股/中概）子集暂不解析：明细按 Region
#   分节且无 CHINA 行锚点，pypdf 文本流切分脆弱——留 TODO 待结构再评估（R6 范围纪律）。

_MSCI_INDEX_REVIEW_URL = "https://app2.msci.com/eqb/gimi/stdindex/index_review.html"
_MSCI_IR_DATES_URL = "https://app2.msci.com/eqb/pressreleases/archive/ir_dates.csv"
_MSCI_ANNOUNCE_ENUM_URL = (
    "https://app2.msci.com/webapp/index_ann/Announcement"
    "?doc_type=ANNOUNCEMENT&lang=en&prod_type=STANDARD&visibility=public&format=html"
)
_MSCI_DOCGET_URL = "https://app2.msci.com/webapp/index_ann/DocGet?pub_key={pub_key}&lang=en&format=html"
_MSCI_BASE = "https://app2.msci.com"

_MSCI_MONTH_CODE = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}
_MSCI_MONTH_NAME = {v: k for k, v in _MSCI_MONTH_CODE.items()}
_MSCI_EN_MONTH_NUM = {
    m.lower(): i
    for i, m in enumerate(
        ("January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December"), start=1,
    )
}


def _msci_review_code(review_period: str) -> str:
    """期次标识归一：'2026-11' → 'Nov26'；'Nov26' 原样。"""
    code = review_period.strip()
    m = re.fullmatch(r"(\d{4})-(\d{2})", code)
    if m:
        year2 = m.group(1)[2:]
        month = int(m.group(2))
        month_abbr = _MSCI_MONTH_NAME.get(month)
        if month_abbr is None:
            raise ValueError(f"非法期次月份: {review_period!r}")
        return f"{month_abbr}{year2}"
    if re.fullmatch(r"[A-Z][a-z]{2}\d{2}", code) and code[:3] in _MSCI_MONTH_CODE:
        return code
    raise ValueError(
        f"期次格式应为 'YYYY-MM' 或 '<Mon><YY>'（如 2026-11 / Nov26）: {review_period!r}"
    )


def _msci_period_from_code(code: str) -> str:
    """'Nov26' → '2026-11'（文件名期次 → 规范期次）。"""
    mm = re.fullmatch(r"([A-Z][a-z]{2})(\d{2})", code)
    if not mm or mm.group(1) not in _MSCI_MONTH_CODE:
        raise OfficialDisclosureSourceError(f"MSCI 期次标识无法解析: {code!r}")
    return f"20{mm.group(2)}-{_MSCI_MONTH_CODE[mm.group(1)]:02d}"


def _date_en_to_iso(text: str) -> str:
    """英文日期 'November 11, 2026' → '2026-11-11'。"""
    m = re.fullmatch(r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})", text.strip())
    if not m or m.group(1).lower() not in _MSCI_EN_MONTH_NUM:
        raise OfficialDisclosureSourceError(f"MSCI 英文日期无法解析: {text!r}")
    return f"{m.group(3)}-{_MSCI_EN_MONTH_NUM[m.group(1).lower()]:02d}-{int(m.group(2)):02d}"


def _parse_msci_review_links(html: str) -> list[tuple[str, str]]:
    """index_review.html → [(期次码 Nov26, ChinaA PDF 相对链接)]，最新在前。"""
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for rel in re.findall(r'href="(/eqb/gimi/stdindex/MSCI_([A-Za-z]{3}\d{2})_ChinaAPublicList(?:_EN)?\.pdf)"', html, re.I):
        link, code = rel[0], rel[1].capitalize()
        if code[:3].capitalize() not in _MSCI_MONTH_CODE or code in seen:
            continue
        seen.add(code)
        pairs.append((code, link))
    if not pairs:
        raise OfficialDisclosureSourceError(
            "MSCI 期次目录页未解析到任何 ChinaAPublicList 链接（断源或结构变化）"
        )
    return pairs


def _parse_msci_chinaa_text(text: str, review_period: str, file_url: str, limit: int) -> pd.DataFrame:
    """China A 名单 PDF 第 1 页抽取文本 → 统一模型行（每条 add/delete 一行）。

    校验线：明细计数必须与首页 SUMMARY 表一致，不符 = 结构变化抛异常（假数据防线）。
    securities 恒为 []：PDF 只有英文公司名与 (HK-C) 港股通标记，无 A 股代码——
    不臆译不伪造代码（诚实空态原则）。
    """
    if "MSCI CHINA A INDEX" not in text:
        raise OfficialDisclosureSourceError(
            f"MSCI 名单 PDF 不含 'MSCI CHINA A INDEX' 标题（结构变化?）: {file_url}"
        )
    m_ann = re.search(r"^[A-Za-z]+,\s+([A-Za-z]+\s+\d{1,2},\s*\d{4})\s*$", text, re.M)
    if not m_ann:
        raise OfficialDisclosureSourceError("MSCI 名单 PDF 首行无公布日期（结构变化?）")
    announce_iso = _date_en_to_iso(m_ann.group(1))
    m_eff = re.search(
        r"effective as of the close of business on\s+([A-Za-z]+\s+\d{1,2},\s*\d{4})", text
    )
    if not m_eff:
        raise OfficialDisclosureSourceError("MSCI 名单 PDF 无生效日声明（结构变化?）")
    effective_iso = _date_en_to_iso(m_eff.group(1))

    # 摘要表计数（MSCI CHINA A INDEX <added> <deleted>）
    m_sum = re.search(
        r"MSCI\s+CHINA\s+A\s+INDEX\s+(\d+)\s+(\d+)", text
    )
    if not m_sum:
        raise OfficialDisclosureSourceError("MSCI 名单 PDF 无 China A 摘要计数行（结构变化?）")
    want_add, want_del = int(m_sum.group(1)), int(m_sum.group(2))

    # 明细区：最后一次出现指数标题之后（首页底部双栏）
    body_start = text.rfind("MSCI CHINA A INDEX")
    body = text[body_start:]
    additions_i = body.find("Additions")
    if additions_i < 0:
        raise OfficialDisclosureSourceError("MSCI 名单 PDF 无 Additions 明细区（结构变化?）")
    lines = body[additions_i + len("Additions"):].splitlines()

    adds: list[str] = []
    dels: list[str] = []
    for ln in lines:
        if len(adds) >= want_add and len(dels) >= want_del:
            break  # 计数达标即停（后续为说明文字）——比模式匹配终止更稳
        cells = [c.strip() for c in re.split(r"\s{2,}", ln.strip()) if c.strip()]
        cells = [c for c in cells if c not in ("Additions", "Deletions")]  # 标题词过滤
        if not cells:
            continue
        if len(cells) == 1 and len(cells[0]) > 60 and not re.search(r"\([A-Z0-9-]+\)\s*$", cells[0]):
            continue  # 免责声明/说明长句跳过（计数校验兜底）
        left_set = bool(ln) and not ln[0].isspace()  # 行首空格 = 左栏空缺（仅右栏行）
        if len(cells) == 2:
            adds.append(cells[0])
            dels.append(cells[1])
        elif len(cells) == 1:
            (adds if left_set else dels).append(cells[0])
        else:
            adds.append(cells[0])
            dels.append(cells[-1])
    # 计数校验：与首页 SUMMARY 不一致 = 解析失败（假数据比 5xx 更糟）
    if len(adds) != want_add or len(dels) != want_del:
        raise OfficialDisclosureSourceError(
            f"MSCI China A 名单明细计数不符（结构变化?）：解析 add={len(adds)}/del={len(dels)}"
            f" vs 摘要 {want_add}/{want_del} — {file_url}"
        )

    period = _msci_period_from_code(review_period)
    rows: list[dict] = []
    for action, names in (("add", adds), ("delete", dels)):
        for name in names:
            market_tag = ""
            m_tag = re.search(r"\(([A-Z0-9-]+)\)\s*$", name)
            if m_tag:
                market_tag = m_tag.group(1)
            rows.append({
                "source_name": "msci",
                "doc_type": "index_review",
                "publish_time": f"{announce_iso}T00:00:00Z",
                "effective_time": f"{effective_iso}T00:00:00Z",
                "title": f"MSCI China A Index Review {period}: "
                         f"{'纳入' if action == 'add' else '剔除'} {name}",
                "summary": f"{action.upper()} {name} — MSCI China A Index {period} 季度评审"
                           + (f"（{market_tag}）" if market_tag else ""),
                "url": file_url,
                "securities": "[]",
                "source_grade": "official",
                "raw_json": json.dumps({
                    "review_period": period, "action": action,
                    "security_name_en": name, "market_tag": market_tag,
                    "file_url": file_url,
                    "note": "MSCI 官方 PDF 第 1 页原文（英文原名，A 股代码映射未臆译）",
                }, ensure_ascii=False),
            })
    return _rows_to_df(rows).head(limit)


def _parse_msci_ir_dates(csv_text: str, limit: int) -> pd.DataFrame:
    """ir_dates.csv（已解压）→ 未来期次日历（#BOD..#EOD 之间表格）。"""
    m = re.search(r"#BOD(.*?)#EOD", csv_text, re.S)
    if not m:
        raise OfficialDisclosureSourceError("MSCI ir_dates.csv 无 #BOD/#EOD 数据块（结构变化?）")
    rows: list[dict] = []
    for line in m.group(1).splitlines():
        line = line.strip().rstrip(",")
        if not line or "|" not in line:
            continue
        parts = [p.strip().strip('"') for p in line.split("|")]
        if len(parts) < 4 or parts[0].lower() in ("quarter", ""):
            continue
        quarter, event, ann, eff = parts[0], parts[1], parts[2], parts[3]
        m1 = re.fullmatch(r"(\d{2})-(\d{2})-(\d{4})", ann)
        m2 = re.fullmatch(r"(\d{2})-(\d{2})-(\d{4})", eff)
        if not (m1 and m2):
            continue  # 非日期行跳过
        ann_iso = f"{m1.group(3)}-{m1.group(1)}-{m1.group(2)}"
        eff_iso = f"{m2.group(3)}-{m2.group(1)}-{m2.group(2)}"
        rows.append({
            "source_name": "msci",
            "doc_type": "index_review",
            "publish_time": f"{ann_iso}T00:00:00Z",
            "effective_time": f"{eff_iso}T00:00:00Z",
            "title": f"MSCI Index Review {quarter}（{event}）日程",
            "summary": f"公布 {ann_iso}（北京时间次日凌晨）· 生效 {eff_iso} 收盘后",
            "url": _MSCI_IR_DATES_URL,
            "securities": "[]",
            "source_grade": "official",
            "raw_json": json.dumps(
                {"quarter": quarter, "event": event,
                 "announcement_date": ann_iso, "effective_date": eff_iso},
                ensure_ascii=False,
            ),
        })
    if not rows:
        raise OfficialDisclosureSourceError("MSCI ir_dates.csv 解析后零期次（结构变化?）")
    return _rows_to_df(rows).head(limit)


def _parse_msci_announcements(enum_html: str, limit: int) -> pd.DataFrame:
    """Announcement 枚举 → DocGet 摘要哨兵（每条公告一行：标题+时间+链接）。"""
    entries = list(dict.fromkeys(
        re.findall(r'pub_key=([^&"\'\s]+)', enum_html)
    ))
    if not entries:
        raise OfficialDisclosureSourceError(
            "MSCI Announcement 枚举无 pub_key 直链（断源或结构变化）"
        )
    rows: list[dict] = []
    for pub_key in entries[:limit]:
        url = _MSCI_DOCGET_URL.format(pub_key=pub_key)
        doc = _http_get(url).decode("utf-8", errors="replace")
        m_title = re.search(r"<title>(.*?)</title>", doc, re.S)
        m_time = re.search(
            r"Announcement for ([A-Za-z]+ \d{1,2}, \d{4}) at (\d{2}:\d{2}) (?:PM|AM) GMT", doc
        )
        title = (m_title.group(1).strip() if m_title else "")[:120]
        if not title:
            raise OfficialDisclosureSourceError(f"MSCI DocGet 无标题（结构变化?）: {url}")
        if m_time:
            iso_date = _date_en_to_iso(m_time.group(1))
            publish = f"{iso_date}T{m_time.group(2)}:00Z"
        else:
            publish = ""
        rows.append({
            "source_name": "msci",
            "doc_type": "index_review",
            "publish_time": publish,
            "effective_time": "",
            "title": title,
            "summary": f"MSCI 官方公告（pub_key={pub_key}）",
            "url": url,
            "securities": "[]",
            "source_grade": "official",
            "raw_json": json.dumps({"pub_key": pub_key}, ensure_ascii=False),
        })
    return _rows_to_df(rows)


def _fetch_msci(limit: int, data: str = "list", review_period: str = "", **kwargs) -> pd.DataFrame:
    """MSCI 分发入口。

    data="list"（默认）：最新（或指定期次）China A 名单明细，每条 add/delete 一行；
    data="dates"：未来期次日历（ir_dates.csv，P07 倒计时数据源）；
    data="summary"：公告摘要哨兵（Announcement 枚举 + DocGet）。
    """
    kind = (data or "list").strip().lower()
    if kind == "list":
        links = _parse_msci_review_links(
            _http_get(_MSCI_INDEX_REVIEW_URL).decode("utf-8", errors="replace")
        )
        if review_period and str(review_period).strip():
            code = _msci_review_code(review_period)
            match = next((p for p in links if p[0] == code), None)
            if match is None:
                raise ValueError(f"期次 {code} 无 China A 名单文件; 可用: {[p[0] for p in links]}")
        else:
            match = links[0]
        file_url = _MSCI_BASE + match[1]
        pdf_bytes = _http_get(file_url)
        from pypdf import PdfReader
        import io as _io

        try:
            reader = PdfReader(_io.BytesIO(pdf_bytes))
            text = reader.pages[0].extract_text() or ""
        except Exception as exc:
            raise OfficialDisclosureSourceError(
                f"MSCI 名单 PDF 抽取失败（结构变化?）: {file_url} ({exc})"
            ) from exc
        if not text.strip():
            raise OfficialDisclosureSourceError(
                f"MSCI 名单 PDF 第 1 页零文本（扫描件或结构变化?）: {file_url}"
            )
        return _parse_msci_chinaa_text(text, match[0], file_url, limit)
    if kind == "dates":
        raw = _http_get(_MSCI_IR_DATES_URL)
        try:
            csv_text = gzip.decompress(raw).decode("utf-8", errors="replace")
        except Exception:
            csv_text = raw.decode("utf-8", errors="replace")
        return _parse_msci_ir_dates(csv_text, limit)
    if kind == "summary":
        return _parse_msci_announcements(
            _http_get(_MSCI_ANNOUNCE_ENUM_URL).decode("utf-8", errors="replace"), limit
        )
    raise ValueError(
        f"未知 msci data 类型: {data!r}; 可用: list | dates | summary"
    )


# ============================================================
# 源 4：FTSE Russell — index_review（L2 公告 PDF，按 id 直取）（OFFSRC-00 P04）
# ============================================================
# P00 结论（2026-11-27）+ 2026-11-28 复测：域名迁 LSEG；公告 getnotice/?id=NNN
# 直出 PDF 200（含公布日/生效日/期次名，名单在附件 xlsx 需门户登录）。
# 列表枚举不可达：notices 列表页 JS 渲染 + GetNotices AJAX 端点对脚本请求回
# SPA 壳（无会话）——故本源按 notice id 直取（id 由人工从 lseg notices 页查询，
# 如 GEIS Dec2026 = 2622506），不伪造列表（诚实空态原则）。

_FTSE_NOTICE_URL = (
    "https://research.ftserussell.com/products/index-notices/home/getnotice/?id={notice_id}"
)
_FTSE_EN_MONTH_NUM = dict(_MSCI_EN_MONTH_NUM)  # 复用英文月份表


def _date_en_dmy_to_iso(text: str) -> str:
    """英式日期 '21 December 2026' → '2026-12-21'。"""
    m = re.fullmatch(
        r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", text.strip()
    )
    if not m or m.group(2).lower() not in _FTSE_EN_MONTH_NUM:
        raise OfficialDisclosureSourceError(f"FTSE 英式日期无法解析: {text!r}")
    return f"{m.group(3)}-{_FTSE_EN_MONTH_NUM[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"


def _parse_ftse_notice_text(text: str, notice_id: str, url: str) -> pd.DataFrame:
    """FTSE 公告 PDF 首页文本 → 一行公告（期次/公布日/生效日；名单附件需登录不抓）。"""
    if "ftse russell" not in text.lower() and "ftse" not in text.lower():
        raise OfficialDisclosureSourceError(
            f"FTSE 公告 PDF 无 FTSE 标识（结构变化?）: {url}"
        )
    m_series = re.search(r"^(FTSE [^\n]+)", text)
    m_period = re.search(
        r"([A-Z][a-z]+\s+\d{4}\s+(?:Quarterly|Semi-Annual|Annual)[^\n]*)", text
    )
    if not m_period:
        raise OfficialDisclosureSourceError(f"FTSE 公告无期次标题（结构变化?）: {url}")
    m_eff = re.search(
        r"effective on\s+(?:[A-Za-z]+,\s*)?(\d{1,2}\s+[A-Za-z]+\s+\d{4})", text
    )
    if not m_eff:
        raise OfficialDisclosureSourceError(f"FTSE 公告无生效日（结构变化?）: {url}")
    effective_iso = _date_en_dmy_to_iso(m_eff.group(1))
    # 公布日 = 标题后第一个独立日期（如 '13 November 2026'）
    m_ann = re.search(r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})", text)
    if not m_ann:
        raise OfficialDisclosureSourceError(f"FTSE 公告无公布日期（结构变化?）: {url}")
    announce_iso = _date_en_dmy_to_iso(m_ann.group(1))
    period_title = re.sub(r"\s+", " ", m_period.group(1)).strip()
    series = re.sub(r"\s+", " ", m_series.group(1)).strip() if m_series else "FTSE Russell"

    return _rows_to_df([{
        "source_name": "ftse",
        "doc_type": "index_review",
        "publish_time": f"{announce_iso}T00:00:00Z",
        "effective_time": f"{effective_iso}T00:00:00Z",
        "title": f"FTSE {period_title}（{series}）",
        "summary": (
            f"公布 {announce_iso} · 生效 {effective_iso} 收盘后；"
            "逐只名单为登录门户附件（GetAttachment 需注册），本源不含名单"
        ),
        "url": url,
        "securities": "[]",
        "source_grade": "official",
        "raw_json": json.dumps({
            "notice_id": notice_id, "period_title": period_title,
            "series": series, "announcement_date": announce_iso,
            "effective_date": effective_iso,
            "note": "名单 xlsx 需 FTSE 门户登录（P00 结论），诚实不抓",
        }, ensure_ascii=False),
    }])


def _fetch_ftse(limit: int, identifier: str = "", **kwargs) -> pd.DataFrame:
    """FTSE 公告直取（identifier=notice id，支持逗号/分号分隔多个）。"""
    raw_ids = (identifier or "").strip()
    if not raw_ids:
        raise ValueError(
            "FTSE 源需 notice id（如 identifier='2622506'，多个用逗号分隔）；"
            "id 请从 lseg.com/en/ftse-russell/index-resources/notices 人工查询"
            "（列表接口对脚本请求不可达，本源不伪造列表）"
        )
    ids = [s for s in re.split(r"[,;\s]+", raw_ids) if s]
    frames: list[pd.DataFrame] = []
    for notice_id in ids:
        if not notice_id.isdigit():
            raise ValueError(f"FTSE notice id 应为纯数字: {notice_id!r}")
        url = _FTSE_NOTICE_URL.format(notice_id=notice_id)
        pdf_bytes = _http_get(url)
        from pypdf import PdfReader
        import io as _io

        try:
            reader = PdfReader(_io.BytesIO(pdf_bytes))
            text = "\n".join((p.extract_text() or "") for p in reader.pages[:2])
        except Exception as exc:
            raise OfficialDisclosureSourceError(
                f"FTSE 公告 PDF 抽取失败（结构变化?）: {url} ({exc})"
            ) from exc
        if not text.strip():
            raise OfficialDisclosureSourceError(
                f"FTSE 公告 PDF 零文本（扫描件或结构变化?）: {url}"
            )
        frames.append(_parse_ftse_notice_text(text, notice_id, url))
    df = pd.concat(frames, ignore_index=True)
    return df.head(limit) if limit and len(df) > limit else df


# ============================================================
# 源 5：HKEXnews 披露易 — filing（两步查询：prefix.do → titleSearchServlet）
# ============================================================
# P00 结论（2026-11-27）契约：symbol → prefix.do 映射内部 stockId（≠代码！
# 直接传 00700 → recordCnt=0）→ titleSearchServlet（GET）JSON 出参（result
# 为转义 JSON 字符串，DATE_TIME=DD/MM/YYYY 香港时区，FILE_LINK 相对路径）。
# 响应 2-4.5s（_TIMEOUT=30 覆盖）；searchType=1 按代码 / 0 按标题关键词。

_HKEX_PREFIX_URL = (
    "https://www1.hkexnews.hk/search/prefix.do"
    "?callback=callback&lang=ZH&type=A&name={name}&market=SEHK"
)
_HKEX_SEARCH_URL = "https://www1.hkexnews.hk/search/titleSearchServlet.do"
_HKEX_BASE = "https://www1.hkexnews.hk"
_HKEX_MARKET = "SEHK"  # SEHK 主板 | GEM 创业板（走 /gem/ 路径）


def _hkex_resolve_stock_id(symbol: str) -> tuple[int, str]:
    """港股代码 → (内部 stockId, 公司名)。prefix.do JSONP 解析。"""
    name = symbol.strip().lstrip("0") or "0"
    url = _HKEX_PREFIX_URL.format(name=name)
    text = _http_get(url).decode("utf-8", errors="replace")
    m = re.search(
        r'"stockInfo"\s*:\s*\[\s*\{\s*"stockId"\s*:\s*(\d+)\s*,\s*"code"\s*:\s*"(\d+)"',
        text,
    )
    if not m:
        raise OfficialDisclosureSourceError(
            f"HKEX prefix.do 未解析到 stockId（代码不存在或结构变化）: {symbol!r}"
        )
    return int(m.group(1)), m.group(2)


def _hkex_strip_noise(value: str) -> str:
    """LONG_TEXT/SHORT_TEXT/STOCK_CODE 内 <br/> 等噪音清洗。"""
    return re.sub(r"\s*<br\s*/?\s*>", " ", value or "").strip()


def _parse_hkex_search(payload_text: str, limit: int) -> pd.DataFrame:
    """titleSearchServlet 应答文本 → 统一模型行（doc_type=filing）。"""
    text = payload_text.strip()
    if not text:
        raise OfficialDisclosureSourceError("HKEX 查询应答为空（断源或结构变化）")
    # result 字段 = 转义的 JSON 数组字符串 → 两层 json.loads 解码
    # （unicode_escape 按 latin-1 语义拆多字节 UTF-8，中文必坏——禁用）
    try:
        outer = json.loads(text)
        result_str = outer.get("result")
    except json.JSONDecodeError as exc:
        raise OfficialDisclosureSourceError(
            f"HKEX 应答非 JSON（结构变化?）: {exc}"
        ) from exc
    if not isinstance(result_str, str):
        raise OfficialDisclosureSourceError("HKEX 应答无 result 字段（结构变化?）")
    try:
        items = json.loads(result_str)
    except json.JSONDecodeError as exc:
        raise OfficialDisclosureSourceError(
            f"HKEX result 二次解码失败（结构变化?）: {exc}"
        ) from exc
    if not items:
        raise OfficialDisclosureSourceError("HKEX 查询零记录（代码无公告或参数过窄）")

    rows: list[dict] = []
    for it in items:
        date_time = str(it.get("DATE_TIME") or "").strip()
        # DD/MM/YYYY HH:MM（香港时区 UTC+8）→ UTC ISO
        m_dt = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})\s+(\d{2}):(\d{2})", date_time)
        if not m_dt:
            continue  # 残缺时间戳跳过，不伪造
        hk = datetime(
            int(m_dt.group(3)), int(m_dt.group(2)), int(m_dt.group(1)),
            int(m_dt.group(4)), int(m_dt.group(5)),
            tzinfo=timezone(timedelta(hours=8)),
        )
        publish_utc = hk.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        file_link = str(it.get("FILE_LINK") or "").strip()
        title = _hkex_strip_noise(str(it.get("TITLE") or ""))
        stock_codes = [
            c for c in _hkex_strip_noise(str(it.get("STOCK_CODE") or "")).split()
            if c
        ]
        category = _hkex_strip_noise(
            str(it.get("SHORT_TEXT") or it.get("LONG_TEXT") or "")
        )
        rows.append({
            "source_name": "hkex",
            "doc_type": "filing",
            "publish_time": publish_utc,
            "effective_time": "",
            "title": title,
            "summary": category or "香港上市公司公告（披露易）",
            "url": (_HKEX_BASE + file_link) if file_link else "",
            "securities": json.dumps(stock_codes, ensure_ascii=False),
            "source_grade": "official",
            "raw_json": json.dumps(it, ensure_ascii=False),
        })
    return _rows_to_df(rows).head(limit)


def _fetch_hkex(limit: int, identifier: str = "", symbol: str = "", title: str = "", **kwargs) -> pd.DataFrame:
    """HKEX 披露易查询（identifier/symbol=港股代码；title=标题关键词走 extra_params，繁体命中率高）。"""
    sym = (symbol or identifier or "").strip()
    kw = (title or "").strip()
    if not sym and not kw:
        raise ValueError(
            "HKEX 源需 symbol（港股代码，如 700）或 title（标题关键词，繁体命中率高），"
            "两者至少其一；全市场流不支持（披露易为查询型接口）"
        )
    from_date = str(kwargs.get("from_date", "") or "").replace("-", "")
    to_date = str(kwargs.get("to_date", "") or "").replace("-", "")
    params: dict[str, str] = {
        "sortDir": "0", "optionsDateRange": "0", "category": "0",
        "market": _HKEX_MARKET, "documentType": "-1",
        "title": kw, "searchType": "1" if sym else "0",
        "t1code": "-2", "t2Gcode": "-2", "t2code": "-2",
        "rowRange": "100", "lang": "zh",
        "fromDate": from_date, "toDate": to_date,
    }
    if sym:
        stock_id, _code = _hkex_resolve_stock_id(sym)
        params["stockId"] = str(stock_id)
    else:
        params["stockId"] = "-1"
    from urllib.parse import urlencode

    url = f"{_HKEX_SEARCH_URL}?{urlencode(params)}"
    return _parse_hkex_search(_http_get(url).decode("utf-8", errors="replace"), limit)


# ============================================================
# 源登记表 — P02–P05 接新源在此加行（不动 _SOURCE_TABLE / 计数断言）
# ============================================================

# value = (分发函数, 一句话说明)。函数签名统一 (limit, **kwargs) -> DataFrame。
OFFICIAL_SOURCES: dict[str, tuple[Callable[..., pd.DataFrame], str]] = {
    "fed": (_fetch_fed, "美联储新闻稿 RSS（议息/监管声明，官方一手）"),
    "sec_edgar": (_fetch_sec_edgar, "SEC EDGAR 最近披露（中概股 10-K/10-Q/8-K/6-K，官方 JSON API）"),
    "msci": (_fetch_msci, "MSCI 季度指数评审（China A 名单 PDF/期次日历/公告摘要，官方一手）"),
    "ftse": (_fetch_ftse, "FTSE Russell 指数评审公告（按 notice id 直取，官方一手）"),
    "hkex": (_fetch_hkex, "HKEX 披露易港股公告（按代码/标题关键词查询，官方一手）"),
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
