"""
同花顺问财数据源 fetch_fn 包装器。

通过 pywencai 库（可选依赖）或 iwencai OpenAPI 访问同花顺问财数据。
pywencai 支持自然语言查询选股、财务数据、新闻、公告、研报等。
iwencai OpenAPI 支持新闻、公告、研报的专业搜索。

设计原则：
  - pywencai 为可选依赖，未安装时返回空 DataFrame 并记录日志
  - iwencai OpenAPI 需要 IWENCAI_API_KEY 环境变量
  - 失败时返回空 DataFrame，不抛异常（容错设计）
"""

from __future__ import annotations

import logging
import os
from typing import Any

import pandas as pd

logger = logging.getLogger("tradex.wencai")

# iwencai OpenAPI 配置
IWENCAI_BASE_URL = os.environ.get(
    "IWENCAI_BASE_URL", "https://openapi.iwencai.com"
)
IWENCAI_API_KEY = os.environ.get("IWENCAI_API_KEY", "")


# ============================================================
# pywencai 查询 — wencai_query (pywencai 模式)
# ============================================================

def fetch_wencai_query(
    query: str = "",
    query_type: str = "stock",
    loop: bool = False,
    sort_key: str = "",
    sort_order: str = "desc",
    **kwargs,
) -> pd.DataFrame:
    """同花顺问财自然语言查询（pywencai 可选依赖）。

    通过 pywencai 库执行自然语言查询，获取选股/财务/行情等数据。
    pywencai 未安装时返回空 DataFrame。

    Args:
        query: 自然语言查询语句，如 "市值大于100亿 市盈率小于30"
        query_type: 查询类型，可选 {"stock", "fund", "index"}
        loop: 是否获取所有分页数据
        sort_key: 排序字段
        sort_order: 排序方向 {"asc", "desc"}

    Returns:
        DataFrame with query results
    """
    if not query:
        logger.debug("fetch_wencai_query: query is empty")
        return pd.DataFrame()

    try:
        import pywencai
    except ImportError:
        logger.warning(
            "pywencai 未安装，无法执行问财查询。"
            "请执行: pip install pywencai"
        )
        return pd.DataFrame()

    try:
        params: dict[str, Any] = {
            "query": query,
            "query_type": query_type,
            "loop": loop,
        }
        if sort_key:
            params["sort_key"] = sort_key
            params["sort_order"] = sort_order

        df = pywencai.get(**params)
        if df is None or df.empty:
            logger.debug("fetch_wencai_query(%s): empty", query[:50])
            return pd.DataFrame()
        return df
    except Exception as e:
        logger.warning("fetch_wencai_query(%s) failed: %s", query[:50], e)
        return pd.DataFrame()


# ============================================================
# iwencai OpenAPI 新闻搜索 — wencai_news (iwencai 模式)
# ============================================================

def fetch_wencai_news(
    keyword: str = "",
    channel: str = "news",
    limit: int = 20,
    **kwargs,
) -> pd.DataFrame:
    """同花顺问财 OpenAPI 新闻/公告/研报搜索。

    通过 iwencai OpenAPI 搜索财经新闻、公告、研报。
    需要设置环境变量 IWENCAI_API_KEY。

    Args:
        keyword: 搜索关键词
        channel: 搜索频道，可选 {"news": 新闻, "announcement": 公告, "report": 研报}
        limit: 返回条数，默认 20

    Returns:
        DataFrame with columns: 标题, 发布时间, 来源, 摘要, 链接
    """
    if not keyword:
        logger.debug("fetch_wencai_news: keyword is empty")
        return pd.DataFrame()

    if not IWENCAI_API_KEY:
        logger.warning(
            "IWENCAI_API_KEY 未设置，无法使用 iwencai OpenAPI。"
            "请设置环境变量 IWENCAI_API_KEY"
        )
        return pd.DataFrame()

    try:
        import json
        import urllib.request

        url = f"{IWENCAI_BASE_URL}/v1/comprehensive/search"
        payload = {
            "channels": [channel],
            "app_id": "tradex",
            "query": keyword,
        }
        headers = {
            "Authorization": f"Bearer {IWENCAI_API_KEY}",
            "Content-Type": "application/json",
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers=headers, method="POST"
        )

        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        # 解析响应
        items = result.get("data", {}).get("items", []) or []
        if not items:
            logger.debug("fetch_wencai_news(%s): empty result", keyword)
            return pd.DataFrame()

        articles = []
        for item in items[:limit]:
            articles.append({
                "标题": item.get("title", ""),
                "发布时间": item.get("publish_time", ""),
                "来源": item.get("source", ""),
                "摘要": item.get("summary", ""),
                "链接": item.get("url", ""),
            })

        if not articles:
            return pd.DataFrame()
        return pd.DataFrame(articles)

    except Exception as e:
        logger.warning("fetch_wencai_news(%s) failed: %s", keyword, e)
        return pd.DataFrame()