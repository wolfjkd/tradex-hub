"""official_disclosure_service：境外官方公告业务逻辑层（OFFSRC-00 P01，2026-11-27）。

数据层 data_sources/official_disclosure_fetchers.py（Fed RSS 打样，
SEC/FTSE/MSCI/HKEX/HSI 按工单序接入）。本层职责：
  - 单源查询（source 指定，断源异常透传 = 诚实失败）与全源聚合（单源失败
    显式降级进 failed_sources，全失败才抛——降级在 service 层显式处理，
    fetcher 侧仍然一律抛出，硬约定#5/#11 语义不变）
  - UTC 存储 + 北京时间展示双标（publish_time_utc / publish_time_cn）
  - 公告类 TTL_DAILY 对象缓存
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from ..data_sources import get_router
from ..data_sources.official_disclosure_fetchers import (
    OFFICIAL_SOURCES,
    list_official_sources,
    utc_iso_to_cn,
)
from ..utils.cache import TTL_DAILY, cache
from ..utils.formatter import df_to_records

logger = logging.getLogger(__name__)

_router = get_router()


def _df_to_disclosure_records(df: pd.DataFrame, max_rows: int) -> list[dict]:
    """统一模型 DataFrame → records，补北京时间展示列（UTC 存储口径不变）。"""
    if df is None or df.empty:
        return []
    out = df.head(max_rows).copy()
    out["publish_time_cn"] = out["publish_time"].map(utc_iso_to_cn)
    out["effective_time_cn"] = out["effective_time"].map(utc_iso_to_cn)
    return df_to_records(out, max_rows=max_rows)


def get_official_disclosures(
    source: str = "", doc_type: str = "", limit: int = 30,
    identifier: str = "", form_type: str = "",
    data: str = "", review_period: str = "",
) -> dict[str, Any]:
    """境外官方公告查询。

    Args:
        source: 源 key；空 = 聚合全部已接入源（单源失败显式降级）
        doc_type: 文档类型过滤（index_review/filing/press_release/macro_release），
            空返回全部
        limit: 每源最多返回条数
        identifier: 源特定实体标识（仅 sec_edgar 消费：ticker 或 CIK；其余源忽略）
        form_type: 源特定文书类型过滤（仅 sec_edgar 消费：如 10-K/6-K；其余源忽略）
        data: 源特定数据形态（仅 msci 消费：list=名单明细/dates=期次日历/
            summary=公告摘要；其余源忽略）
        review_period: 源特定期次（仅 msci 消费：'2026-11' 或 'Nov26'，默认最新期）

    Returns:
        dict(source / disclosures / failed_sources / count)
    """
    key = (source or "").strip().lower()
    if key and key not in OFFICIAL_SOURCES:
        raise ValueError(f"未知境外官方源: {source!r}; 可用: {sorted(OFFICIAL_SOURCES)}")

    def _factory() -> dict[str, Any]:
        wanted = [key] if key else sorted(OFFICIAL_SOURCES)
        disclosures: list[dict] = []
        failed_sources: list[dict] = []
        for src in wanted:
            try:
                df, route_src = _router.route(
                    "official_disclosure", source=src, limit=limit,
                    identifier=identifier, form_type=form_type,
                    data=data, review_period=review_period,
                )
                records = _df_to_disclosure_records(df, max_rows=limit)
                disclosures.extend(records)
            except Exception as exc:  # noqa: BLE001 - 聚合层显式降级（单源失败不拖垮其余源）
                logger.warning("official_disclosure 聚合降级 (%s): %s", src, exc)
                failed_sources.append({"source": src, "error": str(exc)})
        if not disclosures and failed_sources:
            # 全部源失败 = 断源，不是空态——诚实失败（硬约定#5）
            raise RuntimeError(
                f"境外官方公告全部源失败: {failed_sources}"
            )
        if doc_type:
            disclosures = [
                r for r in disclosures if r.get("doc_type") == doc_type
            ]
        disclosures.sort(key=lambda r: r.get("publish_time") or "", reverse=True)
        return {
            "source": key,
            "doc_type": doc_type,
            "disclosures": disclosures,
            "failed_sources": failed_sources,
            "count": len(disclosures),
        }

    return cache.get_or_set(
        f"official_disc:{key}:{doc_type}:{limit}:{identifier.strip().upper()}:"
        f"{form_type.strip().upper()}:{data.strip().lower()}:{review_period.strip()}",
        _factory, TTL_DAILY,
    )


def get_official_sources() -> dict[str, Any]:
    """列出已接入境外官方源（供 REST /sources 与 MCP 说明用）。"""
    return {"sources": list_official_sources(), "count": len(OFFICIAL_SOURCES)}
