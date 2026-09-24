"""
新浪财经直连数据源 fetch_fn 包装器。

提供以下 fetcher（均使用 curl_cffi 直连新浪财经 HTTP 接口）：
  - fetch_sina_research_reports:    新浪研报列表（个股或全市场翻页）
  - fetch_sina_fund_flow:           新浪日度资金流（东财资金流被封时降级）
  - fetch_sina_option_tquote:       新浪 ETF 期权 T 型报价
  - fetch_sina_option_greeks:       新浪 ETF 期权希腊字母 + IV

设计原则：
  - 每个 fetch_fn 接受 **kwargs，返回 DataFrame（统一格式）
  - 失败时返回空 DataFrame，不抛异常（容错设计）
  - 仅使用 curl_cffi（requests 兼容层），不引入其他第三方依赖
  - 与东财系完全独立上游，作为 priority=100/200 备源使用

借鉴：simonlin1212/a-stock-data 的 §2.4 / §4.5 / §9.1 端点实现思路。
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

import pandas as pd
from curl_cffi import requests as curl_requests

logger = logging.getLogger("tradex.sina")

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
_TIMEOUT = 15


def _normalize_code(symbol: str = "", code: str = "") -> str:
    """归一化股票代码为 6 位纯数字。兼容 symbol/code 两种参数名。"""
    sym = (symbol or code or "").strip()
    if not sym:
        raise ValueError("stock code is required (symbol or code)")
    return sym.strip().lower()


# ============================================================
# 新浪研报列表 — sina_research_reports
# ============================================================

def fetch_sina_research_reports(
    symbol: str = "",
    code: str = "",
    page: int = 1,
    page_size: int = 20,
    **kwargs,
) -> pd.DataFrame:
    """新浪财经研报列表直连。

    作为 research_report 的独立备源（新浪与东财完全不同上游）。
    返回标题、类型、机构、研究员、日期；不含评级和目标价
    （评级/目标价仍由主源 tdx_mcp 或东财提供）。

    Args:
        symbol: 6 位股票代码，如 "600519"
        code: 6 位股票代码（别名）
        page: 页码，从 1 开始
        page_size: 每页条数，默认 20

    Returns:
        DataFrame with columns: 标题, 类型, 机构, 研究员, 日期, 股票代码
    """
    sym = _normalize_code(symbol, code)
    try:
        # 新浪研报接口（参照 sinarf 端点）
        url = "https://stock.finance.sina.com.cn/relate/api/jsonp.php/IO.XSRV2.CallbackList['netNetServicessss']"
        params = {
            "symbol": sym,
            "page": str(page),
            "num": str(page_size),
        }
        headers = {
            "User-Agent": _UA,
            "Referer": "https://stock.finance.sina.com.cn/",
            "Accept": "*/*",
        }
        resp = curl_requests.get(
            url, params=params, headers=headers, timeout=_TIMEOUT, impersonate="chrome120"
        )
        resp.raise_for_status()
        text = resp.text.strip()

        # 解析 JSONP 包裹：IO.XSRV2.CallbackList['...']({...})
        m = re.search(r"\(({.+})\)", text)
        if not m:
            return pd.DataFrame()
        data = json.loads(m.group(1))
        items = data.get("result", {}).get("data", [])
        if not items:
            return pd.DataFrame()

        rows = []
        for it in items:
            rows.append({
                "标题": (it.get("title") or "").strip(),
                "类型": (it.get("type") or "").strip(),
                "机构": (it.get("org") or "").strip(),
                "研究员": (it.get("author") or "").strip(),
                "日期": (it.get("pub_date") or "").strip(),
                "股票代码": sym,
            })
        df = pd.DataFrame(rows)
        df = df[df["标题"] != ""]
        return df.reset_index(drop=True)

    except Exception as e:
        logger.warning("fetch_sina_research_reports(%s) failed: %s", sym, e)
        return pd.DataFrame()


# ============================================================
# 新浪日度资金流 — sina_fund_flow
# ============================================================

def fetch_sina_fund_flow(
    symbol: str = "",
    code: str = "",
    days: int = 10,
    **kwargs,
) -> pd.DataFrame:
    """新浪财经个股资金流向（日度），作为 fund_flow 的独立备源。

    东财 push2his 被风控时降级到此源。新浪接口返回最近 N 天日度资金流。

    Args:
        symbol: 6 位股票代码
        code: 6 位股票代码（别名）
        days: 返回最近天数，默认 10

    Returns:
        DataFrame with columns: 日期, 收盘价, 涨跌幅, 主力净流入, 游资净流入, 散户净流入
    """
    sym = _normalize_code(symbol, code)
    try:
        # 新浪资金流接口（参照 sinarf /FinanceService 页面接口）
        url = f"https://stock.finance.sina.com.cn/relate/api/openapi.php/FinanceService.getFundFlow"
        params = {
            "symbol": sym,
            "num": str(min(max(days, 1), 60)),
        }
        headers = {
            "User-Agent": _UA,
            "Referer": "https://stock.finance.sina.com.cn/",
            "Accept": "*/*",
        }
        resp = curl_requests.get(
            url, params=params, headers=headers, timeout=_TIMEOUT, impersonate="chrome120"
        )
        resp.raise_for_status()
        data = resp.json()
        items = (data.get("result") or {}).get("data", {}).get("fund_flow", [])
        if not items:
            return pd.DataFrame()

        rows = []
        for it in items:
            rows.append({
                "日期": (it.get("trade_date") or "").strip(),
                "收盘价": float(it.get("close") or 0),
                "涨跌幅": float(it.get("change_pct") or 0),
                "主力净流入": float(it.get("main_net") or 0),
                "游资净流入": float(it.get("super_net") or 0),
                "散户净流入": float(it.get("retail_net") or 0),
            })
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df = df.sort_values("日期", ascending=False).reset_index(drop=True)
        return df

    except Exception as e:
        logger.warning("fetch_sina_fund_flow(%s) failed: %s", sym, e)
        return pd.DataFrame()


# ============================================================
# 新浪 ETF 期权 T 型报价 — sina_option_tquote
# ============================================================

def fetch_sina_option_tquote(
    underlying: str = "510050",
    **kwargs,
) -> pd.DataFrame:
    """新浪财经 ETF 期权 T 型报价直连。

    返回指定标的的所有合约的实时报价（买卖五档 / 持仓量 / 行权价 / 最新价）。
    作为 etf_option_tquote 的主源（新浪期权接口稳定且零鉴权）。

    Args:
        underlying: 标的代码，默认 "510050"（50ETF），可选 "510300"（300ETF）/"159919"（嘉实 300）

    Returns:
        DataFrame with columns: 合约代码, 合约名称, 最新价, 行权价, 持仓量,
                                买一价, 卖一价, 买一量, 卖一量, 类型(认沽/认购), 到期月份
    """
    try:
        # 新浪期权 T 型报价接口
        url = "https://stock.finance.sina.com.cn/futures/api/openapi.php/OptionService.getOptionT"
        params = {
            "underlying": underlying,
        }
        headers = {
            "User-Agent": _UA,
            "Referer": "https://stock.finance.sina.com.cn/",
            "Accept": "*/*",
        }
        resp = curl_requests.get(
            url, params=params, headers=headers, timeout=_TIMEOUT, impersonate="chrome120"
        )
        resp.raise_for_status()
        data = resp.json()
        opt_data = data.get("result", {}).get("data", {}).get("option", [])
        if not opt_data:
            return pd.DataFrame()

        rows = []
        for it in opt_data:
            rows.append({
                "合约代码": (it.get("symbol") or "").strip(),
                "合约名称": (it.get("name") or "").strip(),
                "最新价": float(it.get("price") or 0),
                "行权价": float(it.get("strike") or 0),
                "持仓量": float(it.get("open_interest") or 0),
                "买一价": float(it.get("bid") or 0),
                "卖一价": float(it.get("ask") or 0),
                "买一量": float(it.get("bid_vol") or 0),
                "卖一量": float(it.get("ask_vol") or 0),
                "类型": "认购" if (it.get("call_put") == "C" or it.get("type") == "call") else "认沽",
                "到期月份": (it.get("expire_month") or "").strip(),
            })
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df = df[df["合约代码"] != ""].reset_index(drop=True)
        return df

    except Exception as e:
        logger.warning("fetch_sina_option_tquote(%s) failed: %s", underlying, e)
        return pd.DataFrame()


# ============================================================
# 新浪 ETF 期权希腊字母 + IV — sina_option_greeks
# ============================================================

def fetch_sina_option_greeks(
    underlying: str = "510050",
    **kwargs,
) -> pd.DataFrame:
    """新浪财经 ETF 期权希腊字母 + 隐含波动率直连。

    返回 Delta / Gamma / Theta / Vega / Rho / IV 等希腊字母。
    作为 etf_option_greeks 的主源。

    Args:
        underlying: 标的代码，默认 "510050"

    Returns:
        DataFrame with columns: 合约代码, 合约名称, Delta, Gamma, Theta, Vega, Rho, IV(隐含波动率)
    """
    try:
        url = "https://stock.finance.sina.com.cn/futures/api/openapi.php/OptionService.getGreeks"
        params = {
            "underlying": underlying,
        }
        headers = {
            "User-Agent": _UA,
            "Referer": "https://stock.finance.sina.com.cn/",
            "Accept": "*/*",
        }
        resp = curl_requests.get(
            url, params=params, headers=headers, timeout=_TIMEOUT, impersonate="chrome120"
        )
        resp.raise_for_status()
        data = resp.json()
        greeks_data = data.get("result", {}).get("data", {}).get("greeks", [])
        if not greeks_data:
            return pd.DataFrame()

        rows = []
        for it in greeks_data:
            rows.append({
                "合约代码": (it.get("symbol") or "").strip(),
                "合约名称": (it.get("name") or "").strip(),
                "Delta": float(it.get("delta") or 0),
                "Gamma": float(it.get("gamma") or 0),
                "Theta": float(it.get("theta") or 0),
                "Vega": float(it.get("vega") or 0),
                "Rho": float(it.get("rho") or 0),
                "IV": float(it.get("iv") or 0),
            })
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df = df[df["合约代码"] != ""].reset_index(drop=True)
        return df

    except Exception as e:
        logger.warning("fetch_sina_option_greeks(%s) failed: %s", underlying, e)
        return pd.DataFrame()
