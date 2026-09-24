"""
产业链资讯 RSS 直连数据源 fetch_fn 包装器。

提供以下 fetcher：
  - fetch_industry_news(track, days):  按赛道抓取产业链资讯（多源合并 + 合规过滤）

设计原则：
  - 冻结版 sources.json（不再自动同步上游）
  - 纯 Python 标准库抓取（urllib + xml.etree），零第三方依赖
  - 与 tradex-hub 现有财经新闻源（财联社/东财/新浪）上游完全独立
  - 不做 AI 提炼（保留原始数据，AI 提炼由下游 TradeX 看板负责）

借鉴：simonlin1212/investment-news 的 sources.json 结构与 fetch.py 抓取思路。
本文件冻结上游，108 源清单不再自动更新。
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET
from typing import Any

import pandas as pd

logger = logging.getLogger("tradex.industry_news")

# sources.json 路径（与本文件同目录）
_SOURCES_PATH = os.path.join(os.path.dirname(__file__), "industry_news_sources.json")

# 模块级缓存
_sources_cache: dict | None = None
_sources_lock = threading.Lock()

# 全局 opener：按需走代理（默认尝试环境变量 HTTP_PROXY/HTTPS_PROXY；
# 若需要直连国内接口，把这两个环境变量留空即可）。
# 海外 RSS 源在国内环境必须通过代理（如 Clash 127.0.0.1:7897）才能访问。
def _resolve_proxy() -> dict:
    """解析代理配置，优先级：INDUSTRY_NEWS_PROXY > HTTP_PROXY/HTTPS_PROXY。

    专用变量 INDUSTRY_NEWS_PROXY 可避免污染 tradex-hub 其他数据源（A 股接口仍直连）。
    返回 {} 表示直连，{'http': url, 'https': url} 表示走代理。
    """
    # 1. 专用变量优先
    specific = os.environ.get("INDUSTRY_NEWS_PROXY", "").strip()
    if specific:
        return {"http": specific, "https": specific}
    # 2. 系统变量兜底
    proxies = {}
    for var in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        val = os.environ.get(var, "").strip()
        if val:
            # http 和 https 都映射（urllib 的 ProxyHandler 用 scheme 作 key）
            proxies["http"] = val
            proxies["https"] = val
            break
    return proxies


def _build_opener() -> urllib.request.OpenerDirector:
    """根据当前环境变量构建 opener —— 每次调用都实时读，避免进程启动时刻固化。"""
    proxies = _resolve_proxy()
    if proxies:
        logger.info("industry_news using proxy: %s", proxies.get("https") or proxies.get("http"))
        return urllib.request.build_opener(
            urllib.request.ProxyHandler(proxies),
            urllib.request.HTTPSHandler(),
        )
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),  # 显式空字典=直连
        urllib.request.HTTPSHandler(),
    )


# 兼容旧代码保留模块级 _OPENER（仍可被外部直接引用），但实际抓取改为每次动态构建
_OPENER = _build_opener()


def _load_sources() -> dict:
    """加载并缓存 sources.json。"""
    global _sources_cache
    with _sources_lock:
        if _sources_cache is None:
            try:
                with open(_SOURCES_PATH, "r", encoding="utf-8") as f:
                    _sources_cache = json.load(f)
            except Exception as e:
                logger.error("Failed to load sources.json: %s", e)
                _sources_cache = {"sources": [], "redline_keywords": []}
    return _sources_cache


def _is_redlined(text: str, keywords: list[str]) -> bool:
    """检查文本是否命中红线词（赌博/加密货币/色情等）。"""
    text_lower = text.lower()
    for kw in keywords:
        if kw.lower() in text_lower:
            return True
    return False


def _parse_rss_date(raw: str) -> datetime | None:
    """解析 RSS 日期字段（RFC822 多种变种）为 datetime。"""
    if not raw:
        return None
    raw = raw.strip()
    # 常见格式：Mon, 23 Sep 2026 10:30:00 +0000
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%d %H:%M:%S",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _fetch_rss(url: str, timeout: int = 15) -> list[dict]:
    """抓单个 RSS 源，返回原始条目列表。

    纯标准库 urllib + xml.etree，零第三方依赖。
    每次调用动态构建 opener，便于运行时切换代理。
    """
    try:
        opener = _build_opener()  # 动态构建，支持运行时代理切换
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "tradex-hub/3.6.0 (industry-news)")
        resp = opener.open(req, timeout=timeout)
        content = resp.read()
        # 尝试常见编码
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = content.decode("gbk")
            except UnicodeDecodeError:
                text = content.decode("utf-8", errors="ignore")

        root = ET.fromstring(text)
        items = []

        # RSS 2.0
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub = (item.findtext("pubDate") or "").strip()
            desc_raw = item.findtext("description") or ""
            desc = re.sub(r"<[^>]+>", "", desc_raw).strip()
            items.append({
                "title": title,
                "link": link,
                "pub_date_raw": pub,
                "description": desc[:500],
            })

        # Atom
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.findall(".//atom:entry", ns) or []:
            title = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip()
            link_elem = entry.find("atom:link", ns)
            link = link_elem.get("href", "") if link_elem is not None else ""
            pub = (entry.findtext("atom:updated", default="", namespaces=ns) or "").strip()
            summary = (entry.findtext("atom:summary", default="", namespaces=ns) or "")
            desc = re.sub(r"<[^>]+>", "", summary).strip()
            items.append({
                "title": title,
                "link": link,
                "pub_date_raw": pub,
                "description": desc[:500],
            })

        return items

    except Exception as e:
        logger.debug("RSS fetch failed for %s: %s", url, e)
        return []


def fetch_industry_news(
    track: str = "",
    days: int = 7,
    per_source: int = 6,
    **kwargs,
) -> pd.DataFrame:
    """按赛道抓取产业链资讯（多源合并 + 合规过滤）。

    Args:
        track: 赛道 key（ai/semi/robot/auto/energy/bio/space/security/tech/consumer/macro/science）
               留空表示抓全部赛道
        days: 最近 N 天，默认 7
        per_source: 每个源最多取 N 条，默认 6

    Returns:
        DataFrame with columns: 赛道, 来源, 标题, 链接, 发布时间, 摘要
    """
    sources_doc = _load_sources()
    all_sources = sources_doc.get("sources", [])
    redline = sources_doc.get("redline_keywords", [])
    fetch_cfg = sources_doc.get("fetch", {})
    timeout = int(fetch_cfg.get("timeout", 15))
    if days <= 0:
        days = int(fetch_cfg.get("recent_days", 7))
    if per_source <= 0:
        per_source = int(fetch_cfg.get("per_source", 6))

    # 按 track 过滤源
    if track:
        track = track.strip().lower()
        sources_to_fetch = [s for s in all_sources if s.get("hint", "").lower() == track]
        if not sources_to_fetch:
            raise ValueError(
                f"unknown track: {track}; valid tracks: ai/semi/robot/auto/energy/bio/space/security/tech/consumer/macro/science"
            )
    else:
        sources_to_fetch = all_sources

    # 计算截止时间（北京时间）
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # 抓取所有源（顺序抓，避免高频并发被一些源限流）
    rows: list[dict] = []
    for src in sources_to_fetch:
        url = src.get("url", "")
        src_name = src.get("name", "")
        src_track = src.get("hint", "")
        if not url:
            continue

        items = _fetch_rss(url, timeout=timeout)
        count = 0
        for it in items:
            if count >= per_source:
                break
            title = it.get("title", "")
            if not title:
                continue
            # 红线过滤
            if _is_redlined(title + " " + it.get("description", ""), redline):
                continue
            # 时间过滤
            dt = _parse_rss_date(it.get("pub_date_raw", ""))
            pub_time_str = ""
            if dt:
                # 转 UTC 比较
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt < cutoff:
                    continue
                pub_time_str = dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
            else:
                pub_time_str = it.get("pub_date_raw", "")

            rows.append({
                "赛道": src_track,
                "来源": src_name,
                "标题": title,
                "链接": it.get("link", ""),
                "发布时间": pub_time_str,
                "摘要": it.get("description", ""),
            })
            count += 1

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    # 按 发布时间 倒序
    df = df.sort_values("发布时间", ascending=False).reset_index(drop=True)
    return df


def list_tracks() -> list[dict]:
    """列出所有可用赛道（key + name + ashare 对应 A 股板块）。"""
    sources_doc = _load_sources()
    return sources_doc.get("industries", [])


def get_source_count() -> int:
    """获取冻结版源总数（信息查询用）。"""
    sources_doc = _load_sources()
    return len(sources_doc.get("sources", []))
