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

import requests as _requests
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

class ChinabondEmptyShellError(RuntimeError):
    """中债接口返回空壳/空表（接口疑似改版）。

    假数据比 5xx 更糟（健康分正常但读数无效），必须抛出走 SmartRouter 降级。
    2026-11-10 引入：取代「空壳 in str(e)」消息字符串匹配哨兵——上游文案改了不再断语义。
    """


def _chinabond_html_to_curve_df(html_text: str) -> pd.DataFrame:
    """HTML 兜底解析：归一成与 JSON 分支同 schema（期限/收益率(%)），失败/空壳返回空表。

    2026-11-10 审计修复（双 schema）：read_html 分支此前原样返回 HTML 表，
    列名与 JSON 分支不一致，下游 macro_service 规整逻辑对其必错位——现统一在此归一。
    """
    try:
        tables = pd.read_html(io.StringIO(html_text))
    except Exception:
        return pd.DataFrame()
    if not tables:
        return pd.DataFrame()
    t = tables[0].head(15)
    if t.empty or not t.notna().to_numpy().any():
        return pd.DataFrame()
    col_term = next((c for c in t.columns if "期限" in str(c)), None)
    col_yield = next((c for c in t.columns if "收益率" in str(c) or "利率" in str(c)), None)
    if col_term is None or col_yield is None:
        return pd.DataFrame()
    out = pd.DataFrame(
        {
            "期限": t[col_term].astype(str).str.strip(),
            "收益率(%)": pd.to_numeric(t[col_yield], errors="coerce"),
        }
    ).dropna(subset=["收益率(%)"])
    if out.empty or (out["收益率(%)"] == 0).all():
        return pd.DataFrame()
    return out.reset_index(drop=True)


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
        except Exception as json_exc:
            # JSON 失败（接口半回归时可能返回 HTML 表）→ HTML 兜底归一解析；
            # 2026-11-10 重构：消除「空壳 in str(e)」哨兵与 except 块外裸 raise，
            # 失败显式抛 RuntimeError（带 json 真因链），由 SmartRouter 记账降级。
            df = _chinabond_html_to_curve_df(resp.text)
            if df.empty:
                raise RuntimeError(
                    f"中债收益率曲线空壳：json 解析失败({json_exc})且 HTML 表为空壳或无法归一"
                ) from json_exc
            return df

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
        out = pd.DataFrame(rows)
        # 2026-11-08 修复：yield_main 已改版为 JS 填充页面，read_html 会解析出
        # 全 NaN 空壳——假数据比 5xx 更糟（健康分正常但读数无效），必须抛出走降级。
        if out.empty or out["收益率(%)"].isna().all() or (out["收益率(%)"] == 0).all():
            raise ChinabondEmptyShellError(
                f"中债收益率曲线返回空壳（接口疑似改版），curve={curve}"
            )
        return out

    except Exception as e:
        logger.warning("fetch_chinabond_yield_curve(%s) failed: %s", curve, e)
        raise  # 2026-09-28 审计修复：失败必须抛出，由 SmartRouter 记账降级（吞成空表会让降级链与健康分全部失效）


# ============================================================
# 回购定盘利率 — repo_fixing_rates
# ============================================================


# ============================================================
# LPR 历史 — lpr_history
# ============================================================



# ============================================================
# 中证指数官方估值 — index_valuation（2026-11-08 复活）
# ============================================================

# v3.6.0 曾以 zealink（csi-web.cn.zealink.com，中证官网 CDN）实现本类型，
# 后该域名 DNS 失效被作为死源剥离（2026-11-08 实测 getaddrinfo 失败，确认真死）。
# 现换中证官网自动估值文件（oss-ch.csindex.com.cn OSS，官方一手，日度更新），
# 单文件同时给出 PE 与股息率，免去多源拼接。
_CSI_INDICATOR_URL = (
    "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/"
    "file/autofile/indicator/{index_code}indicator.xls"
)

# 该 OSS 对 curl_cffi 的 TLS 指纹返回 404（2026-11-08 实测），对原生 requests
# 放行 200——故本 fetcher 用 requests 直连（trust_env=False，国内源铁律）。
_csi_session = _requests.Session()
_csi_session.trust_env = False


def fetch_index_valuation(index_code: str = "000300", **kwargs) -> pd.DataFrame:
    """中证指数官方日度估值（PE + 股息率）。

    数据源为中证官网「指数估值」自动文件（xls，OLE2 格式，约近一月窗口，
    最新一行即最新交易日）。读 .xls 需要 xlrd>=2.0（仅支持 .xls，恰为本场景）。

    Args:
        index_code: 指数代码，默认 000300 沪深300

    Returns:
        DataFrame with columns: 日期, 市盈率1(总股本), 市盈率2(计算用股本),
        股息率1(总股本), 股息率2(计算用股本)，按日期降序（最新在前）
    """
    try:
        url = _CSI_INDICATOR_URL.format(index_code=index_code)
        headers = {
            "User-Agent": _UA,
            "Referer": "https://www.csindex.com.cn/",
            "Accept": "*/*",
        }
        resp = _csi_session.get(url, headers=headers, timeout=_TIMEOUT)
        resp.raise_for_status()
        df = pd.read_excel(io.BytesIO(resp.content))
        if df.empty:
            raise ValueError(f"中证估值文件为空：{url}")

        # 双语表头按关键子串定位，防中证改英文列名顺序
        col_date = next(c for c in df.columns if "日期" in str(c))
        col_pe1 = next(c for c in df.columns if "市盈率1" in str(c))
        col_pe2 = next(c for c in df.columns if "市盈率2" in str(c))
        col_dp1 = next(c for c in df.columns if "股息率1" in str(c))
        col_dp2 = next(c for c in df.columns if "股息率2" in str(c))

        out = df[[col_date, col_pe1, col_pe2, col_dp1, col_dp2]].copy()
        out.columns = [
            "日期", "市盈率1(总股本)", "市盈率2(计算用股本)",
            "股息率1(总股本)", "股息率2(计算用股本)",
        ]
        out["日期"] = out["日期"].astype(str).str.split(" ").str[0].str.replace("-", "", regex=False)
        for c in out.columns[1:]:
            out[c] = pd.to_numeric(out[c], errors="coerce")
        out = out.dropna(subset=["日期"]).sort_values("日期", ascending=False).reset_index(drop=True)
        if out.empty:
            raise ValueError(f"中证估值文件解析后无有效行：{url}")
        return out

    except Exception as e:
        logger.warning("fetch_index_valuation(%s) failed: %s", index_code, e)
        raise  # 失败必须抛出，由 SmartRouter 记账降级（v3.3.15 起约定）
