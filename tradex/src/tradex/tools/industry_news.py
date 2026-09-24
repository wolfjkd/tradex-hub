"""
产业链资讯工具模块（1 个 MCP 工具，聚合 12 赛道）。

Tool:
  - get_industry_news:     按赛道抓取产业链资讯（多源合并 + 合规过滤）
  - list_industry_tracks:  列出所有可用赛道

数据源：108 个海外英文 RSS 直连，对应 A 股 12 个板块。
不做 AI 提炼（保留原始数据，AI 提炼由下游 TradeX 看板负责）。
"""

from __future__ import annotations

import json
import logging

from mcp.server.fastmcp import FastMCP

import pandas as pd
from ..data_sources import get_router
from ..data_sources.industry_news_fetchers import list_tracks, get_source_count
from ..utils.cache import TTL_DAILY, cache
from ..utils.formatter import df_to_json, error_response

logger = logging.getLogger(__name__)

_router = get_router()

# 赛道 key 校验集合
_VALID_TRACKS = {
    "ai", "semi", "robot", "auto", "energy", "bio",
    "space", "security", "tech", "consumer", "macro", "science",
}


def register(mcp: FastMCP):
    """Register industry news tools."""

    @mcp.tool()
    async def get_industry_news(
        track: str = "",
        days: int = 7,
        per_source: int = 6,
    ) -> str:
        """
        获取产业链资讯（海外英文 RSS 直连，按赛道聚合，对应 A 股板块）。

        12 个赛道一一对应 A 股板块，真正驱动板块的领先信号往往先出现在全球英文源里：
          - ai      → AI 算力 / 大模型应用
          - semi    → 半导体设备 / 材料 / 芯片设计
          - robot   → 机器人 / 工业自动化
          - auto    → 新能源车 / 智驾
          - energy  → 光伏 / 储能 / 锂电 / 氢能
          - bio     → 创新药 / CXO / 医疗器械
          - space   → 商业航天
          - security→ 网安 / 信创
          - tech    → 互联网 / 软件服务
          - consumer→ 消费电子 / 数码
          - macro   → 全局宏观 / 大金融
          - science → 科研 / 前沿科技

        数据源：106 个海外英文 RSS（OpenAI/DeepMind/arXiv/SemiAnalysis/SpaceNews 等），
        纯 Python 标准库抓取，零第三方依赖，零鉴权。
        合规过滤自动剔除博彩/加密货币/色情类内容。
        **不做 AI 提炼**，保留原始标题/链接/发布时间/摘要，下游可自行消化。

        Args:
            track: 赛道 key（留空 = 全部 12 个赛道聚合）
            days: 最近 N 天，默认 7
            per_source: 每个源最多取 N 条，默认 6

        Returns:
            产业链资讯列表 (JSON)，含赛道、来源、标题、链接、发布时间、摘要。
        """
        try:
            if track:
                track = track.strip().lower()
                if track not in _VALID_TRACKS:
                    valid = "/".join(sorted(_VALID_TRACKS))
                    return error_response(
                        f"未知赛道: {track}; 可用赛道: {valid}",
                        "get_industry_news",
                    )
            df, src = _router.route(
                "industry_news",
                track=track, days=days, per_source=per_source,
            )
            return df_to_json(df)
        except Exception as e:
            return error_response(
                f"获取产业链资讯失败 (track={track}): {e}", "get_industry_news"
            )

    @mcp.tool()
    async def list_industry_tracks() -> str:
        """
        列出所有可用的产业链资讯赛道（12 个，对应 A 股板块）+ 当前冻结版源总数。

        Returns:
            赛道清单 + 源总数 (JSON)：[{key, name, ashare}, ...] + source_count
        """
        try:
            tracks = list_tracks()
            count = get_source_count()
            return json.dumps(
                {"tracks": tracks, "source_count": count, "frozen_at": "2026-09-23"},
                ensure_ascii=False,
            )
        except Exception as e:
            return error_response(
                f"列出赛道失败: {e}", "list_industry_tracks"
            )
