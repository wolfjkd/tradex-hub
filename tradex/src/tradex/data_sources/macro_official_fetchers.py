"""
官方宏观数据源 fetch_fn 包装器（人行/统计局/中债/中国货币网）。

提供以下 fetcher：
  - fetch_nbs_pmi:                   国家统计局 PMI（2026-09-28 动态化）
  - fetch_chinabond_yield_curve:     中债国债/信用债收益率曲线

2026-09-28 死源剥离（老板拍板）：pboc 社融（404）/ 货币网回购定盘 + LPR
（静态 json 404）上游已死且无备源，fetcher 与注册点一并移除，测试 skip 记录在案。

设计原则：
  - 全部官方一手数据（人行/统计局/中债/中国货币网），与 akshare(抓东财聚合) 上游独立
  - 失败必须抛出（v3.3.15 起约定，2026-09-28 审计统一）：由 SmartRouter 记账降级，
    吞成空表会让降级链与健康分全部失效

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


# ============================================================
# 国家统计局 PMI — nbs_pmi
# ============================================================

# 统计局「最新发布」列表页：每月 PMI 发布稿 URL 无固定地址，从这里动态定位
_NBS_LATEST_URL = "https://www.stats.gov.cn/sj/zxfb/"
_NBS_HEADERS = {
    "User-Agent": _UA,
    "Referer": "https://www.stats.gov.cn/",
    "Accept": "*/*",
}


def fetch_nbs_pmi(**kwargs) -> pd.DataFrame:
    """国家统计局 PMI（制造业 + 非制造业）。

    2026-09-28 审计修复：此前硬编码 2024-02-29 发布稿 URL，两年后仍把单期
    陈旧数据当实时结果返回。现改为两跳：先抓「最新发布」列表页定位最新一期
    《中国采购经理指数运行情况》，再进发布稿解析表格（2026-09-28 实测列表页
    可程序化解析，最新稿为 2026-08-31 发布）。

    注意：统计局页面有全角括号 + 内带空格，需要清理。

    Returns:
        DataFrame with columns: 月份, 制造业PMI, 非制造业PMI
    """
    try:
        list_resp = curl_requests.get(
            _NBS_LATEST_URL, headers=_NBS_HEADERS, timeout=_TIMEOUT,
            impersonate="chrome120",
        )
        list_resp.raise_for_status()
        hits = re.findall(
            r'href="([^"]+)"[^>]*>([^<]*采购经理指数运行情况[^<]*)<',
            list_resp.text,
        )
        if not hits:
            raise RuntimeError("stats.gov.cn 最新发布页未找到采购经理指数发布稿")
        href = hits[0][0]
        if href.startswith("./"):
            url = "https://www.stats.gov.cn/sj/zxfb/" + href[2:]
        elif href.startswith("http"):
            url = href
        elif href.startswith("/"):
            url = "https://www.stats.gov.cn" + href
        else:
            url = "https://www.stats.gov.cn/sj/zxfb/" + href

        resp = curl_requests.get(
            url, headers=_NBS_HEADERS, timeout=_TIMEOUT, impersonate="chrome120"
        )
        resp.raise_for_status()
        text = resp.text
        # 清理全角括号 + 内部空格
        text = text.replace("（", "(").replace("）", ")")
        text = re.sub(r"\(\s+([^)]+?)\s+\)", r"(\1)", text)

        try:
            tables = pd.read_html(io.StringIO(text))
        except ValueError:
            raise  # 解析失败属源故障，抛出由 SmartRouter 记账降级
        if not tables:
            return pd.DataFrame()
        return tables[0].head(20)

    except Exception as e:
        logger.warning("fetch_nbs_pmi failed: %s", e)
        raise  # 2026-09-28 审计修复：失败必须抛出，由 SmartRouter 记账降级（吞成空表会让降级链与健康分全部失效）


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
            raise  # 2026-09-28 审计修复：失败必须抛出，由 SmartRouter 记账降级（吞成空表会让降级链与健康分全部失效）

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
        raise  # 2026-09-28 审计修复：失败必须抛出，由 SmartRouter 记账降级（吞成空表会让降级链与健康分全部失效）


# ============================================================
# 回购定盘利率 — repo_fixing_rates
# ============================================================


# ============================================================
# LPR 历史 — lpr_history
# ============================================================

