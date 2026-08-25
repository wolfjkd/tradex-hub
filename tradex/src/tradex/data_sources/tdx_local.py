"""读通达信本地数据（离线，不封 IP）。

能力源自开源项目 **mootdx**（https://github.com/mootdx/mootdx，通达信数据读取封装），
借鉴其 reader 模块对 vipdoc 本地二进制文件的定位与解析思路，此处自行用 struct 实现
（不引入 mootdx 底层的 tdxpy 依赖，更轻量）。

通达信每天收盘后把行情写成本地二进制文件：
  - 日线：vipdoc/{market}/lday/{market}{code}.day（每条 32 字节）
  - 5分钟：vipdoc/{market}/fzline/{market}{code}.lc5
  - 1分钟：vipdoc/{market}/minline/{market}{code}.lc1

价值：本地数据零网络依赖，全市场 5900+ 只票离线可取，
是「东财被封、网络全断」时的兜底数据源。数据新鲜度取决于通达信最后更新的时间。
"""
from __future__ import annotations

import struct
from pathlib import Path

import pandas as pd

# 通达信安装目录候选（自动探测最新可用的）
_TDX_CANDIDATES = [
    "D:/通达信金融终端(开心果交易版)V2026.6",
    "D:/通达信金融终端(开心果交易版)V2026.3",
    "D:/通达信金融终端(开心果交易版)V2026",
    "D:/ciccwm_allinone",
    "C:/new_tdx",
]

_tdxdir_cache: Path | None = None


def detect_tdx_dir() -> Path | None:
    """自动探测通达信目录（找 vipdoc/sh/lday 存在的）。"""
    global _tdxdir_cache
    if _tdxdir_cache is not None:
        return _tdxdir_cache
    for cand in _TDX_CANDIDATES:
        p = Path(cand)
        if (p / "vipdoc" / "sh" / "lday").is_dir():
            _tdxdir_cache = p
            return p
    return None


def _market(code: str) -> str:
    """判断市场：sh 沪 / sz 深 / bj 北。"""
    c = str(code).zfill(6)
    if c.startswith(("6", "9", "5")):
        return "sh"
    if c.startswith(("8", "4")):
        return "bj"
    return "sz"


def _find_day_file(code: str, tdxdir: Path | None = None) -> Path | None:
    tdxdir = tdxdir or detect_tdx_dir()
    if tdxdir is None:
        return None
    code = str(code).split(".")[0].split("_")[0].zfill(6)
    market = _market(code)
    # 北交所日线也在 sh 目录下（通达信把北交所并入沪市 lday）
    sub_market = "sh" if market == "bj" else market
    path = tdxdir / "vipdoc" / sub_market / "lday" / f"{sub_market}{code}.day"
    return path if path.exists() else None


def fetch_local_kline(code: str, tdxdir: Path | None = None, **kwargs) -> pd.DataFrame:
    """读通达信本地日线（.day 二进制，离线）。

    Returns columns: date / open / high / low / close / volume / amount
    """
    path = _find_day_file(code, tdxdir)
    if path is None:
        return pd.DataFrame()
    data = path.read_bytes()
    rows = []
    for i in range(0, len(data), 32):
        rec = struct.unpack("<IIIIIfII", data[i:i + 32])
        rows.append({
            "date": str(rec[0]),
            "open": rec[1] / 100.0,
            "high": rec[2] / 100.0,
            "low": rec[3] / 100.0,
            "close": rec[4] / 100.0,
            "amount": rec[5],
            "volume": rec[6],
        })
    return pd.DataFrame(rows)


def get_last_trade_date(code: str, tdxdir: Path | None = None) -> str | None:
    """快速读取日线最后一条记录的日期（只读最后 32 字节，不读全量）。

    用于判断股票是否仍在正常交易：退市股/停牌股/已换代码股的最后交易日
    会明显早于市场最新交易日，据此可过滤掉本地残留的脏数据。
    """
    path = _find_day_file(code, tdxdir)
    if path is None:
        return None
    try:
        data = path.read_bytes()
        if len(data) < 32:
            return None
        rec = struct.unpack("<IIIIIfII", data[-32:])
        return str(rec[0])
    except Exception:  # noqa: BLE001
        return None


def _is_a_share(code: str) -> bool:
    """判断是否为正常 A 股（排除 B股/基金/债券/逆回购/可转债/通达信板块指数）。"""
    return (
        code.startswith(("600", "601", "603", "605", "688"))      # 沪主板 + 科创
        or code.startswith(("000", "001", "002", "003", "300", "301"))  # 深主板 + 创业
        or code.startswith(("43", "83", "87", "920"))  # 北交所（88 开头是通达信板块指数，排除）
    )


def list_local_codes(tdxdir: Path | None = None, markets: tuple = ("sh", "sz")) -> list[str]:
    """列出本地 vipdoc 日线目录下所有正常 A 股代码（纯 6 位）。"""
    tdxdir = tdxdir or detect_tdx_dir()
    if tdxdir is None:
        return []
    codes: list[str] = []
    for m in markets:
        lday = tdxdir / "vipdoc" / m / "lday"
        if not lday.is_dir():
            continue
        for f in lday.glob(f"{m}*.day"):
            code = f.stem[len(m):]  # 去掉 sh/sz 前缀
            if code.isdigit() and len(code) == 6 and _is_a_share(code):
                codes.append(code)
    return sorted(set(codes))


def fetch_local_minute(code: str, period: int = 5, tdxdir: Path | None = None, **kwargs) -> pd.DataFrame:
    """读通达信本地分钟线（.lc5=5分钟 / .lc1=1分钟，离线）。

    分钟线格式与日线不同（date 为 YYMMDD 压缩编码），此处解析 5 分钟线。
    """
    tdxdir = tdxdir or detect_tdx_dir()
    if tdxdir is None:
        return pd.DataFrame()
    code = str(code).split(".")[0].split("_")[0].zfill(6)
    market = _market(code)
    sub_market = "sh" if market == "bj" else market
    subdir = "fzline" if period == 5 else "minline"
    suffix = "lc5" if period == 5 else "lc1"
    path = tdxdir / "vipdoc" / sub_market / subdir / f"{sub_market}{code}.{suffix}"
    if not path.exists():
        return pd.DataFrame()
    data = path.read_bytes()
    rows = []
    for i in range(0, len(data), 32):
        rec = struct.unpack("<HHffffII", data[i:i + 32])
        dt = rec[0]  # YYMMDD 压缩：高16位是年份相关编码
        year = (dt // 2048) + 2004
        month = (dt % 2048) // 100
        day = (dt % 2048) % 100
        tm = rec[1]  # 分钟数
        hh, mm = tm // 60, tm % 60
        rows.append({
            "datetime": f"{year}-{month:02d}-{day:02d} {hh:02d}:{mm:02d}",
            "open": rec[2], "high": rec[3], "low": rec[4], "close": rec[5],
            "amount": rec[6], "volume": rec[7],
        })
    return pd.DataFrame(rows)
