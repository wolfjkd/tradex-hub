"""
Concept block attribution (概念/板块归属) for A-stock individual stocks.

Determines which concept themes, industry sectors, and regional blocks
a given stock belongs to. Uses push2delay.eastmoney.com (mirror) as primary source.

Data sources:
  - push2delay.eastmoney.com: 东财延迟镜像（绕过 push2 CDN 封禁）
    - f100: industry (行业分类)
    - f102: region (地域板块)
    - f103: concept tags (概念标签, comma-separated)

Strategy: Query region board members (31 province boards) → find target stock →
extract industry/concept/region data. Each stock belongs to exactly one region board.

TradingAgents-astock 移植模块。V0.2 — push2delay 适配版。
"""

from __future__ import annotations

from datetime import datetime
import json
import logging
import os
import time
from typing import Any

import requests as _requests

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_PUSH2DELAY_URL = "https://push2delay.eastmoney.com/api/qt/clist/get"

# Stock-code prefix → likely region heuristic (not exact, just for first guess)
_CODE_REGION_GUESS: dict[str, str] = {
    "6": "上海板块",   # Shanghai exchange, mostly 长三角
    "0": "广东板块",   # Shenzhen exchange, mostly 珠三角
    "3": "广东板块",   # ChiNext, mostly 珠三角
    "8": "北京板块",   # STAR/Beijing exchange
}


def get_concept_blocks(ticker: str) -> str:
    """Get concept/sector/region blocks that a stock belongs to.

    Args:
        ticker: 6-digit A-stock code, e.g. '688017'.

    Returns:
        Formatted markdown with concept/industry/region classification.
    """
    code = ticker.strip()
    info = _get_stock_board_info(code)

    lines = [
        f"# Concept & Sector Blocks for {code} (A-stock)",
        f"# Source: 东方财富 (push2delay mirror)",
        f"# Retrieved: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]

    if info.get("error"):
        lines.append(f"Error: {info['error']}")
        return "\n".join(lines)

    name = info.get("name", code)
    lines.append(f"**{name}**")

    industry = info.get("industry", "")
    if industry:
        lines.append(f"\n## 行业\n  {industry}")

    region = info.get("region", "")
    if region:
        lines.append(f"\n## 地域\n  {region}")

    concepts = info.get("concepts", "")
    if concepts:
        lines.append(f"\n## 概念板块")
        for c in concepts.split(","):
            c = c.strip()
            if c:
                lines.append(f"  {c}")

    return "\n".join(lines)


def get_concept_blocks_json(ticker: str) -> dict[str, Any]:
    """Get concept blocks as structured JSON (for MCP tools).

    Returns:
        Dict with 'code', 'name', 'industry', 'region', 'concepts' keys.
    """
    code = ticker.strip()
    info = _get_stock_board_info(code)

    if info.get("error"):
        return {
            "code": code,
            "concepts": [],
            "industries": [],
            "regions": [],
            "error": info["error"],
        }

    concepts_list = (
        [c.strip() for c in info.get("concepts", "").split(",") if c.strip()]
        if info.get("concepts")
        else []
    )

    return {
        "code": code,
        "name": info.get("name", ""),
        "concepts": [{"name": c} for c in concepts_list],
        "industries": [{"name": info.get("industry", "")}] if info.get("industry") else [],
        "regions": [{"name": info.get("region", "")}] if info.get("region") else [],
        "source": "eastmoney_push2delay",
    }


# ---------------------------------------------------------------------------
# Private: stock board info via push2delay
# ---------------------------------------------------------------------------


def _get_stock_board_info(code: str) -> dict[str, str]:
    """Get industry/region/concept data for a single stock.

    Strategy:
      1. Get all region boards (~31 provinces)
      2. Try likely region first (based on stock code prefix)
      3. If not found, try other regions
      4. Extract f100 (industry), f102 (region), f103 (concepts)

    Returns dict with keys: name, industry, region, concepts, error.
    """
    # Step 1: Get region boards list
    try:
        region_boards = _get_region_boards()
        if not region_boards:
            return {"error": "无法获取地域板块列表"}
    except Exception as e:
        logger.warning("Failed to get region boards: %s", e)
        return {"error": f"获取地域板块列表失败: {e}"}

    # Step 2: Try likely region first
    prefix = code[0] if code else ""
    likely_region = _CODE_REGION_GUESS.get(prefix)

    search_order = list(region_boards.items())  # (name, bk_code)
    if likely_region:
        # Move likely region to front
        likely_items = [(k, v) for k, v in search_order if likely_region in k or k == likely_region]
        other_items = [(k, v) for k, v in search_order if likely_region not in k and k != likely_region]
        search_order = likely_items + other_items

    # Step 3: Search region boards
    for region_name, bk_code in search_order:
        try:
            result = _query_board_for_stock(bk_code, code)
            if result:
                result["region"] = region_name
                return result
        except Exception as e:
            logger.debug("Region board %s query failed: %s", region_name, e)
            continue

    return {"error": f"未找到 {code} 的概念归属数据"}


_region_boards_cache: dict[str, str] | None = None
_region_boards_ts: float = 0.0
_REGION_CACHE_TTL: float = 3600.0  # 1 小时过期


def _get_region_boards() -> dict[str, str]:
    """Get all region (地域) boards: {name: bk_code}.

    Uses push2delay mirror. Cached with 1-hour TTL.
    """
    global _region_boards_cache, _region_boards_ts
    if _region_boards_cache is not None and (time.time() - _region_boards_ts) < _REGION_CACHE_TTL:
        return _region_boards_cache
    boards: dict[str, str] = {}
    page = 1
    while True:
        r = _requests.get(
            _PUSH2DELAY_URL,
            params={
                "pn": str(page),
                "pz": "100",
                "po": "1",
                "np": "1",
                "fltt": "2",
                "invt": "2",
                "fs": "m:90+t:1",  # region boards
                "fields": "f12,f14",
            },
            headers={"User-Agent": _UA},
            timeout=10,
        )
        d = r.json()
        items = d.get("data", {}).get("diff", [])
        if not items:
            break
        for item in items:
            code = item.get("f12", "")
            name = item.get("f14", "")
            if code and name and not name.startswith(("沪", "深", "京")):
                boards[name] = code
        total = d.get("data", {}).get("total", 0)
        if len(boards) >= total or len(items) < 100:
            break
        page += 1

    logger.info("Loaded %d region boards via push2delay", len(boards))
    _region_boards_cache = boards
    _region_boards_ts = time.time()
    return boards


def _query_board_for_stock(bk_code: str, target_code: str) -> dict[str, str] | None:
    """Query a board's members and find the target stock.

    Returns dict with name, industry, concepts keys, or None if not found.
    """
    r = _requests.get(
        _PUSH2DELAY_URL,
        params={
            "pn": "1",
            "pz": "200",
            "po": "1",
            "np": "1",
            "fltt": "2",
            "invt": "2",
            "fs": f"b:{bk_code}",
            "fields": "f12,f14,f100,f102,f103",
        },
        headers={"User-Agent": _UA},
        timeout=10,
    )
    d = r.json()
    items = d.get("data", {}).get("diff", [])
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("f12") == target_code:
            return {
                "name": item.get("f14", ""),
                "industry": item.get("f100", ""),
                "concepts": item.get("f103", ""),
            }
    return None
