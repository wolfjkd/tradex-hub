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
# 个股资金流向 — sina_fund_flow（函数名沿用，实现已切到东财 F10 fflow）
# ============================================================
#
# ⚠️ 2026-09-25 切源说明：
#   原「新浪 FinanceService.getFundFlow」openapi 接口被新浪下线（HTTP 404），
#   akshare 同期所有 fund_flow 系函数被东财服务端断连（RemoteDisconnected），
#   雪球 capitalflow 返回 403，腾讯 FundflowController 已废弃。
#   实测唯一稳定可用的个股日度资金流接口是东财 F10 fflow：
#     https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get
#   该接口绕过 akshare 层（用 curl_cffi + chrome120 指纹直连），稳定返回
#   个股日度资金流明细（主力/小单/中单/大单/超大单净额与占比、收盘价、涨跌幅）。
#   函数名保持 fetch_sina_fund_flow 不变以兼容既有调用点（registry.py、
#   backup_source_tools.py、sources_health.py），但实际数据来自东财 F10。

def _em_secid(sym: str) -> str:
    """把 6 位股票代码转成东财 secid（沪市 1. / 深市 0. / 北交所 0.）。

    规则：
      - 6 开头（600/601/603/605/688）→ 1.<code>（含科创板 688）
      - 9 / 7 开头（B 股）→ 1.<code>
      - 0/3/2 开头（含创业板 300、深主板 000/001、中小 002）→ 0.<code>
      - 8 / 4 开头（北交所 8xx / 三板 4xx）→ 0.<code>
    """
    sym = sym.strip().lower()
    if not sym or len(sym) != 6 or not sym.isdigit():
        raise ValueError(f"非法股票代码: {sym}")
    first = sym[0]
    if first in ("6", "9", "7"):
        return f"1.{sym}"
    return f"0.{sym}"


def fetch_sina_fund_flow(
    symbol: str = "",
    code: str = "",
    days: int = 10,
    **kwargs,
) -> pd.DataFrame:
    """个股资金流向（日度）。函数名沿用 sina_fund_flow 以兼容既有调用点，
    实际数据来自东财 F10 fflow 接口（新浪 FinanceService 接口已被下线）。

    作为 fund_flow 的有效备源（绕过 akshare 风控层，直连稳定）。

    Args:
        symbol: 6 位股票代码
        code: 6 位股票代码（别名）
        days: 返回最近天数，默认 10（最大 60）

    Returns:
        DataFrame with columns:
            日期, 收盘价, 涨跌幅,
            主力净流入, 小单净流入, 中单净流入, 大单净流入, 超大单净流入,
            主力净占比, 小单净占比, 中单净占比, 大单净占比, 超大单净占比
    """
    sym = _normalize_code(symbol, code)
    try:
        secid = _em_secid(sym)
        url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
        params = {
            "secid": secid,
            "lmt": str(min(max(days, 1), 60)),
            "klt": "101",  # 101=日线
            "fields1": "f1,f2,f3,f7",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63",
            "ut": "b2884a393a59ad64002292a3e90d46a5",
        }
        headers = {
            "User-Agent": _UA,
            "Referer": "https://quote.eastmoney.com/",
            "Accept": "*/*",
        }
        resp = curl_requests.get(
            url, params=params, headers=headers, timeout=_TIMEOUT, impersonate="chrome120"
        )
        resp.raise_for_status()
        data = resp.json()
        klines = (data.get("data") or {}).get("klines", [])
        if not klines:
            return pd.DataFrame()

        rows = []
        for line in klines:
            p = line.split(",")
            if len(p) < 13:
                continue
            # 东财字段顺序：
            # f51=日期, f52=主力净额, f53=小单净额, f54=中单净额, f55=大单净额,
            # f56=超大单净额, f57=主力净占比, f58=小单净占比, f59=中单净占比,
            # f60=大单净占比, f61=超大单净占比, f62=收盘价, f63=涨跌幅
            try:
                rows.append({
                    "日期": p[0].strip(),
                    "收盘价": float(p[11] or 0),
                    "涨跌幅": float(p[12] or 0),
                    "主力净流入": float(p[1] or 0),
                    "小单净流入": float(p[2] or 0),
                    "中单净流入": float(p[3] or 0),
                    "大单净流入": float(p[4] or 0),
                    "超大单净流入": float(p[5] or 0),
                    "主力净占比": float(p[6] or 0),
                    "小单净占比": float(p[7] or 0),
                    "中单净占比": float(p[8] or 0),
                    "大单净占比": float(p[9] or 0),
                    "超大单净占比": float(p[10] or 0),
                })
            except (ValueError, IndexError):
                continue
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
