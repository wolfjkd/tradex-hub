"""
HTTP 直连数据源 fetch_fn 包装器。

纯 HTTP 抓取的数据源（不依赖 akshare），主要是腾讯行情接口。
仅本文件允许直接发起 HTTP 请求获取行情数据。

全局行情（global_market_quote）通过腾讯 qt.gtimg.cn 批量获取，
支持美股/大宗/亚太指数/外汇等外围行情。
"""

from __future__ import annotations

import logging
import urllib.request

import pandas as pd

logger = logging.getLogger("tradex.http")

# 全局直连 opener（绕过系统代理，避免代理失败）
_NO_PROXY_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
    urllib.request.HTTPSHandler(),
)


def _urlopen_no_proxy(url: str, timeout: int = 10) -> object:
    """使用直连 opener 发起请求，绕过系统代理配置。"""
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "Mozilla/5.0")
    return _NO_PROXY_OPENER.open(req, timeout=timeout)


def _tencent_quote_vals(code: str) -> list:
    """从腾讯 qt.gtimg.cn 获取个股行情，返回 ~ 分隔的值列表。"""
    prefix = "sh" if code.startswith("6") else "sz"
    url = f"https://qt.gtimg.cn/q={prefix}{code}"
    resp = _urlopen_no_proxy(url, timeout=5)
    raw = resp.read().decode("gbk")
    if '"' not in raw:
        raise RuntimeError("tencent quote: no data")
    return raw.split('"')[1].split("~")


def fetch_realtime_quote_tencent(symbol: str = "", code: str = "", **kwargs):
    """实时行情（腾讯 qt.gtimg.cn）。返回单行 DataFrame，含'代码'列。

    作为 realtime_quote 的 priority=200 兜底源。
    兼容 symbol/code 两种参数名（SmartRouter 路由归一化）。
    """
    import pandas as pd
    sym = symbol or code
    if not sym:
        raise RuntimeError("stock code is required (symbol or code)")
    vals = _tencent_quote_vals(sym)
    if len(vals) < 50:
        raise RuntimeError("tencent returned insufficient data")
    return pd.DataFrame([{
        "代码": sym,
        "名称": vals[1] if len(vals) > 1 else "",
        "最新价": float(vals[3]) if vals[3] else 0,
        "涨跌幅": float(vals[32]) if len(vals) > 32 and vals[32] else 0,
        "成交量": float(vals[36]) if len(vals) > 36 and vals[36] else 0,
        "成交额": float(vals[37]) if len(vals) > 37 and vals[37] else 0,
        "最高": float(vals[33]) if len(vals) > 33 and vals[33] else 0,
        "最低": float(vals[34]) if len(vals) > 34 and vals[34] else 0,
        "今开": float(vals[5]) if len(vals) > 5 and vals[5] else 0,
        "昨收": float(vals[4]) if len(vals) > 4 and vals[4] else 0,
        "总市值": float(vals[45]) if len(vals) > 45 and vals[45] else 0,
        "流通市值": float(vals[44]) if len(vals) > 44 and vals[44] else 0,
        "市盈率": float(vals[39]) if len(vals) > 39 and vals[39] else 0,
    }])


def fetch_profit_forecast_tencent(symbol: str = "", code: str = "", **kwargs) -> dict:
    """一致预期（腾讯行情兜底）。仅返回价格/PE，无 EPS 预测数据。

    作为 profit_forecast 的 priority=100 备源（当同花顺抓取失败时）。
    兼容 symbol/code 两种参数名（SmartRouter 路由归一化）。
    """
    sym = symbol or code
    if not sym:
        raise RuntimeError("stock code is required (symbol or code)")
    vals = _tencent_quote_vals(sym)
    if len(vals) < 50:
        raise RuntimeError("tencent returned insufficient data for profit_forecast")
    price = float(vals[3]) if vals[3] else 0
    pe_ttm = float(vals[39]) if len(vals) > 39 and vals[39] else 0
    return {
        "symbol": sym,
        "source": "tencent qt.gtimg.cn (price only)",
        "price": price,
        "pe_ttm": pe_ttm,
        "forecasts": [],
        "summary": "同花顺 EPS 抓取失败，仅返回腾讯实时价格/PE",
    }


# ============================================================
# 全局行情批量获取 — global_market_quote
# ============================================================

# 腾讯接口支持的全局行情代码表
# 格式: (code, 类别, 中文名称)
# 注意：腾讯接口不支持大宗商品(hf_*)、A50期货(int_fta50)、日经(int_nikkei)、KOSPI、外汇汇率(usUSDCNH)
GLOBAL_QUOTE_CODES = [
    # 美股指数
    ("usDJI", "美股指数", "道琼斯"),
    ("usIXIC", "美股指数", "纳斯达克"),
    ("usINX", "美股指数", "标普500"),
    # 热门美股
    ("usNVDA", "热门美股", "英伟达"),
    ("usTSLA", "热门美股", "特斯拉"),
    ("usAAPL", "热门美股", "苹果"),
    ("usMSFT", "热门美股", "微软"),
    ("usAMZN", "热门美股", "亚马逊"),
    ("usGOOGL", "热门美股", "谷歌"),
    ("usMETA", "热门美股", "Meta"),
    ("usMU", "热门美股", "美光科技"),
    ("usAMAT", "热门美股", "应用材料"),
    # 亚太指数
    ("hkHSI", "亚太指数", "恒生指数"),
    ("hkHSTECH", "亚太指数", "恒生科技"),
    # 韩股龙头
    ("kr005930", "韩股", "三星电子"),
    ("kr000660", "韩股", "SK海力士"),
    # 外汇
    ("whDINIW", "外汇", "美元指数"),
]


def _tencent_global_batch() -> pd.DataFrame:
    """批量获取腾讯全局行情（单次请求拉取所有预设代码）。

    Returns:
        DataFrame with columns: 代码, 名称, 类别, 最新价, 涨跌额, 涨跌幅, 昨收, 今开, 最高, 最低, 更新时间
    """
    codes = [c[0] for c in GLOBAL_QUOTE_CODES]
    url = "https://qt.gtimg.cn/q=" + ",".join(codes)
    resp = _urlopen_no_proxy(url, timeout=10)
    raw = resp.read().decode("gbk")

    rows = []
    for line in raw.strip().split(";"):
        line = line.strip()
        if not line or "=" not in line:
            continue
        parts = line.split("=", 1)
        key = parts[0].strip().replace("v_", "")
        raw_val = parts[1].strip().strip('"')
        fields = raw_val.split("~")

        # 查找代码对应的类别
        category = ""
        for c, cat, _ in GLOBAL_QUOTE_CODES:
            if c == key:
                category = cat
                break

        name = fields[1] if len(fields) > 1 else key
        price = float(fields[3]) if len(fields) > 3 and fields[3] else 0.0
        last_close = float(fields[4]) if len(fields) > 4 and fields[4] else 0.0
        open_px = float(fields[5]) if len(fields) > 5 and fields[5] else 0.0
        high = float(fields[33]) if len(fields) > 33 and fields[33] else 0.0
        low = float(fields[34]) if len(fields) > 34 and fields[34] else 0.0
        change = float(fields[31]) if len(fields) > 31 and fields[31] else 0.0
        change_pct = float(fields[32]) if len(fields) > 32 and fields[32] else 0.0
        ts = fields[30] if len(fields) > 30 else ""

        rows.append({
            "代码": key,
            "名称": name,
            "类别": category,
            "最新价": price,
            "涨跌额": change,
            "涨跌幅": change_pct,
            "昨收": last_close,
            "今开": open_px,
            "最高": high,
            "最低": low,
            "更新时间": ts,
        })

    return pd.DataFrame(rows)


def fetch_global_quote_tencent(**kwargs) -> pd.DataFrame:
    """全局行情批量获取（腾讯 qt.gtimg.cn）。

    一次性获取美股/大宗/亚太指数/热门股/外汇共 30+ 个品种的实时行情。
    作为 global_market_quote 数据类型的唯一源。

    Returns:
        DataFrame with columns: 代码, 名称, 类别, 最新价, 涨跌额, 涨跌幅, 昨收, 今开, 最高, 最低, 更新时间
    """
    try:
        df = _tencent_global_batch()
        if df is None or df.empty:
            raise RuntimeError("tencent global batch returned empty")
        return df
    except Exception as e:
        logger.warning("fetch_global_quote_tencent failed: %s", e)
        raise


def fetch_market_overview_tencent(**kwargs) -> pd.DataFrame:
    """A股主要指数行情（腾讯 qt.gtimg.cn 兜底）。

    作为 market_overview 的备用源，解决 akshare 代理失败问题。
    获取上证指数、深证成指、创业板指等主要指数行情。

    Returns:
        DataFrame with columns: 代码, 名称, 最新价, 涨跌幅, 涨跌额, 成交额, 成交量
    """
    # 腾讯A股指数代码：sh000001(上证), sz399001(深证), sz399006(创业板), sz399852(中证1000), sh000688(科创50), sh000300(沪深300), sh000905(中证500)
    index_codes = ["sh000001", "sz399001", "sz399006", "sh000688", "sh000300", "sh000905", "sz399852"]
    url = "https://qt.gtimg.cn/q=" + ",".join(index_codes)
    try:
        resp = _urlopen_no_proxy(url, timeout=10)
        raw = resp.read().decode("gbk")
        rows = []
        for line in raw.strip().split(";"):
            line = line.strip()
            if not line or "=" not in line:
                continue
            parts = line.split("=", 1)
            raw_val = parts[1].strip().strip('"')
            fields = raw_val.split("~")
            name = fields[1] if len(fields) > 1 else ""
            price = float(fields[3]) if len(fields) > 3 and fields[3] else 0.0
            change = float(fields[31]) if len(fields) > 31 and fields[31] else 0.0
            change_pct = float(fields[32]) if len(fields) > 32 and fields[32] else 0.0
            volume = float(fields[36]) if len(fields) > 36 and fields[36] else 0.0
            amount = float(fields[37]) if len(fields) > 37 and fields[37] else 0.0
            rows.append({
                "指数名称": name,
                "最新点位": price,
                "涨跌额": change,
                "涨跌幅": change_pct,
                "成交量(手)": volume,
                "成交额(元)": amount,
            })
        if not rows:
            raise RuntimeError("tencent index batch returned empty")
        return pd.DataFrame(rows)
    except Exception as e:
        logger.warning("fetch_market_overview_tencent failed: %s", e)
        raise
