"""通达信官网盘后包解析（工单 H5）。

数据源事实（2026-11-06 实测）：
  - URL: ``https://www.tdx.com.cn/products/data/data/g4day/{YYYYMMDD}.zip``
  - 每日 17:00 后发布，约 2.7MB；每个市场一对文件：
      ``{market}{YYMMDD}.cod``  代码表，150 字节/条
      ``{market}{YYMMDD}.md1``  行情块，512 字节/块
  - 代码表：code[0:6] ASCII；行情块序号 seq=uint16@[32:34]；名称 GBK@[40:72]
  - 行情块：昨收 double@[4:12]；开高低收 4×double@[12:44]；
           成交量 uint64@[56:64]；成交额 double@[72:80]
  - close<=0 的块（880/881 自编指数等）不是证券，跳过

二进制布局参考 jing2uo/tdx2db（MIT）与 a-stock-data §1.3，本机已用 2026-11-05
真实包对拍（600519 成交额 67.5 亿 / 000001 14.3 亿 / 920000 北交所可用）。
"""

from __future__ import annotations

import io
import logging
import math
import re
import struct
import zipfile
from datetime import datetime

import requests as _requests

logger = logging.getLogger("tradex.tdx_package")

# 国内接口直连：requests 默认 trust_env=True 会读 HTTP(S)_PROXY
_session = _requests.Session()
_session.trust_env = False

TDX_PACKAGE_URL = "https://www.tdx.com.cn/products/data/data/g4day/{ymd}.zip"
# 盘后包从这一天起带北交所文件（a-stock-data 2026-09-20 二分实测）
TDX_BJ_FIRST_DAY = "20220506"
# 每个市场有收盘价的最少行数（实测下限，低于即判定文件残缺/格式漂移）
TDX_MIN_PRICED = {"sh": 10000, "sz": 3000, "bj": 50}

_COD_RECORD = 150
_MD1_BLOCK = 512


def _parse_package(content: bytes, ymd: str, *, enforce_minimums: bool = True) -> list[dict]:
    """解析盘后包，返回全部「有价」证券的日线行。

    Raises:
        RuntimeError: 文件缺块、条数对不上、代码非法/重复、数值非有限、市场行数低于下限。
    """
    archive = zipfile.ZipFile(io.BytesIO(content))
    names = set(archive.namelist())
    rows: list[dict] = []
    for market in ("sh", "sz", "bj"):
        cod_name = f"{market}{ymd[2:]}.cod"
        md1_name = f"{market}{ymd[2:]}.md1"
        if market == "bj" and ymd < TDX_BJ_FIRST_DAY and cod_name not in names and md1_name not in names:
            continue  # 该日之前的包还没有北交所文件
        if cod_name not in names or md1_name not in names:
            raise RuntimeError(f"通达信盘后包缺少 {cod_name}/{md1_name}，格式可能已变")
        cod = archive.read(cod_name)
        md1 = archive.read(md1_name)
        if len(cod) % _COD_RECORD or len(md1) % _MD1_BLOCK:
            raise RuntimeError(f"{market} 代码表或行情块长度不是整块，文件可能被截断")
        if len(cod) // _COD_RECORD != len(md1) // _MD1_BLOCK:
            raise RuntimeError(
                f"{market} 代码表 {len(cod) // _COD_RECORD} 条、"
                f"行情块 {len(md1) // _MD1_BLOCK} 块，对不上"
            )
        before = len(rows)
        codes: set[str] = set()
        seqs: set[int] = set()
        for offset in range(0, len(cod), _COD_RECORD):
            record = cod[offset:offset + _COD_RECORD]
            code = record[0:6].rstrip(b"\x00 ").decode("ascii", "replace")
            seq = struct.unpack("<H", record[32:34])[0]
            if not re.fullmatch("[0-9]{6}", code):
                raise RuntimeError(f"{market} 代码表出现非 6 位数字代码 {code!r}，格式可能已变")
            if code in codes or seq in seqs:
                raise RuntimeError(f"{market} 代码表有重复代码/行情块序号（{code!r}, seq={seq}）")
            codes.add(code)
            seqs.add(seq)
            block = md1[seq * _MD1_BLOCK:(seq + 1) * _MD1_BLOCK]
            if len(block) != _MD1_BLOCK:
                raise RuntimeError(f"{market}{code} 行情块越界（seq={seq}）")
            prev_close = struct.unpack("<d", block[4:12])[0]
            open_, high, low, close = struct.unpack("<4d", block[12:44])
            amount = struct.unpack("<d", block[72:80])[0]
            if not all(math.isfinite(v) for v in (prev_close, open_, high, low, close, amount)):
                raise RuntimeError(f"{market}{code} 行情块出现非有限数值，文件可能已损坏")
            if close <= 0:
                continue  # 880/881 自编板块指数当日无价，整块为 0，不是证券
            volume = struct.unpack("<Q", block[56:64])[0]
            raw_name = record[40:72].split(b"\x00")[0]
            try:
                name = raw_name.decode("gbk").strip()
            except UnicodeDecodeError as exc:
                raise RuntimeError(f"{market}{code} 名称不是 GBK，文件可能已损坏") from exc
            if not name:
                raise RuntimeError(f"{market}{code} 有价格却没有名称，文件可能已损坏")
            rows.append({
                "date": f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}",
                "market": market,
                "code": code,
                "name": name,
                "prev_close": round(prev_close, 4),
                "open": round(open_, 4),
                "high": round(high, 4),
                "low": round(low, 4),
                "close": round(close, 4),
                "volume": volume,
                "amount": round(amount, 2),
            })
        if enforce_minimums and len(rows) - before < TDX_MIN_PRICED[market]:
            raise RuntimeError(
                f"{market} 市场只有 {len(rows) - before} 条有价记录"
                f"（实测下限 {TDX_MIN_PRICED[market]}），文件可能残缺或格式已变"
            )
    return rows


def _normalize_date(date: str) -> str:
    """归一交易日为 YYYYMMDD（允许 YYYY-MM-DD / 空=今天）。"""
    s = str(date or "").strip().replace("-", "")
    if not s:
        return datetime.now().strftime("%Y%m%d")
    if len(s) != 8 or not s.isdigit():
        raise ValueError(f"date 参数格式错误：{date!r}（应为 YYYYMMDD）")
    return s


def fetch_tdx_daily_package(date: str = "", **kwargs) -> dict:
    """下载并解析某交易日的通达信盘后包（全市场日线含成交额）。

    Raises:
        ValueError: 404（非交易日 / 当日包尚未发布 / 超出官网保留范围）。
        RuntimeError: 下载失败、不是 zip、zip 损坏、格式漂移。
    """
    ymd = _normalize_date(date)
    url = TDX_PACKAGE_URL.format(ymd=ymd)
    try:
        resp = _session.get(url, timeout=(10, 90))
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"通达信盘后包下载失败 {url}: {exc}") from exc
    if resp.status_code == 404:
        raise ValueError(
            f"{date or ymd} 没有通达信盘后包：非交易日、当日包尚未发布（通常 17:00 后），"
            "或早于官网保留范围"
        )
    if resp.status_code != 200:
        raise RuntimeError(f"通达信盘后包 HTTP {resp.status_code}: {url}")
    content = resp.content
    if not content.startswith(b"PK"):
        raise RuntimeError("通达信盘后包不是 zip 文件，可能是错误页")
    try:
        rows = _parse_package(content, ymd)
    except (zipfile.BadZipFile, struct.error, EOFError) as exc:
        raise RuntimeError(f"通达信盘后包 {url} 无法解压: {type(exc).__name__}: {exc}") from exc
    return {
        "date": f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}",
        "ymd": ymd,
        "as_of": f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]} 17:00 后发布",
        "kind": "history",
        "source": "tdx_official",
        "source_url": url,
        "rows": rows,
        "count": len(rows),
    }
