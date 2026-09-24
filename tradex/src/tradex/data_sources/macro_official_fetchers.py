"""
官方宏观数据源 fetch_fn 包装器（人行/统计局/中债/中国货币网）。

提供以下 fetcher：
  - fetch_pboc_social_financing:     人民银行社融数据
  - fetch_nbs_pmi:                   国家统计局 PMI
  - fetch_chinabond_yield_curve:     中债国债/信用债收益率曲线
  - fetch_repo_fixing_rates:         中国货币网回购定盘利率
  - fetch_lpr_history:               LPR 历史

设计原则：
  - 全部官方一手数据（人行/统计局/中债/中国货币网），与 akshare(抓东财聚合) 上游独立
  - 失败时返回空 DataFrame，不抛异常

借鉴：simonlin1212/a-stock-data 的 §11 宏观与利率层实现思路。
"""

from __future__ import annotations

import io
import logging
import re
from datetime import datetime
from typing import Any

import pandas as pd
from curl_cffi import requests as curl_requests

logger = logging.getLogger("tradex.macro_official")

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
_TIMEOUT = 20


# ============================================================
# 人行社融 — pboc_social_financing
# ============================================================

def fetch_pboc_social_financing(
    year: int = 0,
    **kwargs,
) -> pd.DataFrame:
    """人民银行社融数据（月度 12 列）。

    Args:
        year: 年份，默认当前年

    Returns:
        DataFrame with columns: 月份, 社融规模增量(万亿), 人民币贷款(万亿), ...
    """
    if not year:
        year = datetime.now().year

    try:
        url = f"http://www.pbc.gov.cn/diaochatongjisi/116219/116319/{year}/{year}.html"
        headers = {
            "User-Agent": _UA,
            "Referer": "http://www.pbc.gov.cn/",
            "Accept": "*/*",
        }
        resp = curl_requests.get(
            url, headers=headers, timeout=_TIMEOUT, impersonate="chrome120"
        )
        resp.raise_for_status()
        # 人行页面是 HTML，需要解析表格
        try:
            tables = pd.read_html(io.StringIO(resp.text))
        except ValueError:
            return pd.DataFrame()
        if not tables:
            return pd.DataFrame()

        # 通常第一个表是月度增量表
        df = tables[0]
        return df.head(15)  # 取前 15 行

    except Exception as e:
        logger.warning("fetch_pboc_social_financing(%d) failed: %s", year, e)
        return pd.DataFrame()


# ============================================================
# 国家统计局 PMI — nbs_pmi
# ============================================================

def fetch_nbs_pmi(**kwargs) -> pd.DataFrame:
    """国家统计局 PMI（制造业 + 非制造业）。

    注意：统计局页面有全角括号 + 内带空格，需要清理。

    Returns:
        DataFrame with columns: 月份, 制造业PMI, 非制造业PMI
    """
    try:
        url = "http://www.stats.gov.cn/sj/zxfb/202402/t20240229_1947915.html"
        headers = {
            "User-Agent": _UA,
            "Referer": "http://www.stats.gov.cn/",
            "Accept": "*/*",
        }
        resp = curl_requests.get(
            url, headers=headers, timeout=_TIMEOUT, impersonate="chrome120"
        )
        resp.raise_for_status()
        text = resp.text
        # 清理全角括号 + 内部空格
        text = text.replace("（", "(").replace("）", ")")
        text = re.sub(r"\(\s+([^)]+?)\s+\)", r"(\1)", text)

        try:
            tables = pd.read_html(io.StringIO(text))
        except ValueError:
            return pd.DataFrame()
        if not tables:
            return pd.DataFrame()
        return tables[0].head(20)

    except Exception as e:
        logger.warning("fetch_nbs_pmi failed: %s", e)
        return pd.DataFrame()


# ============================================================
# 中债收益率曲线 — chinabond_yield_curve
# ============================================================

def fetch_chinabond_yield_curve(
    curve: str = "国债",  # 国债 / 商业银行AAA / 中短票AAA
    **kwargs,
) -> pd.DataFrame:
    """中债国债/信用债收益率曲线（3月~30年）。

    Args:
        curve: 曲线类型，默认"国债"

    Returns:
        DataFrame with columns: 期限, 收益率(%)
    """
    try:
        curve_map = {
            "国债": "CBM_YIELD_GOV",
            "商业银行AAA": "CBM_YIELD_BANK_AAA",
            "中短票AAA": "CBM_YIELD_CP_AAA",
        }
        curve_id = curve_map.get(curve, "CBM_YIELD_GOV")
        url = f"https://yield.chinabond.com.cn/cbweb-mn/yield_main"
        params = {
            "curveId": curve_id,
            "locale": "zh_CN",
        }
        headers = {
            "User-Agent": _UA,
            "Referer": "https://yield.chinabond.com.cn/",
            "Accept": "*/*",
        }
        resp = curl_requests.get(
            url, params=params, headers=headers, timeout=_TIMEOUT, impersonate="chrome120"
        )
        resp.raise_for_status()
        try:
            data = resp.json()
        except Exception:
            # 可能返回 HTML，尝试解析表格
            try:
                tables = pd.read_html(io.StringIO(resp.text))
                if tables:
                    return tables[0].head(15)
            except ValueError:
                pass
            return pd.DataFrame()

        items = data.get("data") or []
        if not items:
            return pd.DataFrame()

        rows = []
        for it in items:
            rows.append({
                "期限": (it.get("term") or "").strip(),
                "收益率(%)": float(it.get("yield") or 0),
            })
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)

    except Exception as e:
        logger.warning("fetch_chinabond_yield_curve(%s) failed: %s", curve, e)
        return pd.DataFrame()


# ============================================================
# 回购定盘利率 — repo_fixing_rates
# ============================================================

def fetch_repo_fixing_rates(
    kind: str = "FR",  # FR / FDR
    **kwargs,
) -> pd.DataFrame:
    """中国货币网回购定盘利率（FR001/FR007/FR014 或 FDR001/FDR007/FDR014）。

    Returns:
        DataFrame with columns: 日期, FR001, FR007, FR014
    """
    try:
        indicator = "FDR" if kind.upper() == "FDR" else "FR"
        url = "https://www.chinamoney.com.cn/r/cms/www/chinamoney/data/fd/fixed-reference-rate.json"
        params = {
            "lang": "CN",
            "indicator": indicator,
        }
        headers = {
            "User-Agent": _UA,
            "Referer": "https://www.chinamoney.com.cn/",
            "Accept": "application/json",
        }
        resp = curl_requests.get(
            url, params=params, headers=headers, timeout=_TIMEOUT, impersonate="chrome120"
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("records") or data.get("data") or []
        if not items:
            return pd.DataFrame()

        rows = []
        for it in items:
            rows.append({
                "日期": (it.get("date") or "").strip(),
                "FR001": float(it.get("rate1") or it.get("FR001") or 0),
                "FR007": float(it.get("rate2") or it.get("FR007") or 0),
                "FR014": float(it.get("rate3") or it.get("FR014") or 0),
            })
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)

    except Exception as e:
        logger.warning("fetch_repo_fixing_rates(%s) failed: %s", kind, e)
        return pd.DataFrame()


# ============================================================
# LPR 历史 — lpr_history
# ============================================================

def fetch_lpr_history(
    years_back: int = 5,
    **kwargs,
) -> pd.DataFrame:
    """LPR（贷款市场报价利率）历史（1 年 + 5 年），来自中国货币网。

    Returns:
        DataFrame with columns: 日期, 1年期LPR(%), 5年期LPR(%)
    """
    try:
        url = "https://www.chinamoney.com.cn/r/cms/www/chinamoney/data/fd/lpr-historical.json"
        headers = {
            "User-Agent": _UA,
            "Referer": "https://www.chinamoney.com.cn/chinese/bk-lpr/",
            "Accept": "application/json",
        }
        resp = curl_requests.get(
            url, headers=headers, timeout=_TIMEOUT, impersonate="chrome120"
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("records") or data.get("data") or []
        if not items:
            return pd.DataFrame()

        cutoff_year = datetime.now().year - years_back
        rows = []
        for it in items:
            date_str = (it.get("date") or "").strip()
            try:
                year = int(date_str.split("-")[0])
            except (ValueError, IndexError):
                continue
            if year < cutoff_year:
                continue
            rows.append({
                "日期": date_str,
                "1年期LPR(%)": float(it.get("rate1") or it.get("lpr1") or 0),
                "5年期LPR(%)": float(it.get("rate2") or it.get("lpr5") or 0),
            })
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows).sort_values("日期", ascending=False).reset_index(drop=True)
        return df

    except Exception as e:
        logger.warning("fetch_lpr_history failed: %s", e)
        return pd.DataFrame()
