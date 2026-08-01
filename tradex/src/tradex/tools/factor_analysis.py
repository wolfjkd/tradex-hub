"""
Category 13: Factor Analysis — 多因子分析 (V2.5.0).

为 AI Agent 提供多因子综合评分和因子库查询服务。

设计原则：
  1. 因子标准化：Z-Score 标准化处理，消除量纲影响
  2. 加权融合：支持等权、自定义权重、IC加权三种模式
  3. 因子分类：价值/成长/质量/动量/风险 五大类
  4. 可解释性：每个股票的因子得分明细可追溯

Tools (共 2 个):
  73. calculate_factor_score  - 多因子综合评分
  74. get_factor_catalog      - 获取因子库清单
"""

from __future__ import annotations

import math
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..utils.formatter import dict_to_json, error_response


# ──────────────────────────────────────────────────────────────────
# 因子库定义
# ──────────────────────────────────────────────────────────────────

FACTOR_CATALOG = [
    # 价值类因子
    {"name": "pe", "category": "value", "desc": "市盈率PE(TTM)", "direction": "negative", "unit": "倍"},
    {"name": "pb", "category": "value", "desc": "市净率PB", "direction": "negative", "unit": "倍"},
    {"name": "ps", "category": "value", "desc": "市销率PS(TTM)", "direction": "negative", "unit": "倍"},
    {"name": "dividend_yield", "category": "value", "desc": "股息率", "direction": "positive", "unit": "%"},
    {"name": "ev_ebitda", "category": "value", "desc": "EV/EBITDA", "direction": "negative", "unit": "倍"},

    # 成长类因子
    {"name": "revenue_growth", "category": "growth", "desc": "营收同比增长率", "direction": "positive", "unit": "%"},
    {"name": "profit_growth", "category": "growth", "desc": "净利润同比增长率", "direction": "positive", "unit": "%"},
    {"name": "eps_growth", "category": "growth", "desc": "EPS同比增长率", "direction": "positive", "unit": "%"},
    {"name": "roe", "category": "growth", "desc": "净资产收益率ROE", "direction": "positive", "unit": "%"},

    # 质量类因子
    {"name": "gross_margin", "category": "quality", "desc": "毛利率", "direction": "positive", "unit": "%"},
    {"name": "net_margin", "category": "quality", "desc": "净利率", "direction": "positive", "unit": "%"},
    {"name": "debt_ratio", "category": "quality", "desc": "资产负债率", "direction": "negative", "unit": "%"},
    {"name": "current_ratio", "category": "quality", "desc": "流动比率", "direction": "positive", "unit": "倍"},
    {"name": "cash_flow_ratio", "category": "quality", "desc": "经营现金流/净利润", "direction": "positive", "unit": "倍"},

    # 动量类因子
    {"name": "momentum_5d", "category": "momentum", "desc": "5日动量", "direction": "positive", "unit": "%"},
    {"name": "momentum_20d", "category": "momentum", "desc": "20日动量", "direction": "positive", "unit": "%"},
    {"name": "momentum_60d", "category": "momentum", "desc": "60日动量", "direction": "positive", "unit": "%"},
    {"name": "rsi_14", "category": "momentum", "desc": "14日RSI", "direction": "neutral", "unit": ""},

    # 风险类因子
    {"name": "beta", "category": "risk", "desc": "Beta系数", "direction": "neutral", "unit": ""},
    {"name": "volatility_20d", "category": "risk", "desc": "20日波动率", "direction": "negative", "unit": "%"},
    {"name": "max_drawdown_60d", "category": "risk", "desc": "60日最大回撤", "direction": "negative", "unit": "%"},
    {"name": "sharpe_60d", "category": "risk", "desc": "60日夏普比率", "direction": "positive", "unit": ""},
]

FACTOR_CATEGORIES = {
    "value": "价值类因子",
    "growth": "成长类因子",
    "quality": "质量类因子",
    "momentum": "动量类因子",
    "risk": "风险类因子",
}


# ──────────────────────────────────────────────────────────────────
# 因子计算核心算法
# ──────────────────────────────────────────────────────────────────

def _zscore_normalize(values: list[float]) -> list[float]:
    """Z-Score 标准化。"""
    if len(values) == 0:
        return []
    mean = sum(values) / len(values)
    if len(values) > 1:
        variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
        std = math.sqrt(variance)
    else:
        std = 0.0
    if std == 0:
        return [0.0] * len(values)
    return [(v - mean) / std for v in values]


def _adjust_direction(scores: list[float], direction: str) -> list[float]:
    """根据因子方向调整（negative 反转，neutral 保持）。"""
    if direction == "negative":
        return [-s for s in scores]
    return scores


def _calculate_single_factor(
    stock_codes: list[str],
    factor_values: list[float],
    direction: str,
) -> dict[str, float]:
    """计算单个因子的标准化得分。"""
    # 处理缺失值（None 用中位数填充）
    valid_values = [v for v in factor_values if v is not None]
    if not valid_values:
        return {code: 0.0 for code in stock_codes}
    median = sorted(valid_values)[len(valid_values) // 2]
    filled = [v if v is not None else median for v in factor_values]

    # Z-Score 标准化
    normalized = _zscore_normalize(filled)
    # 方向调整
    adjusted = _adjust_direction(normalized, direction)
    return {code: round(score, 4) for code, score in zip(stock_codes, adjusted)}


# ──────────────────────────────────────────────────────────────────
# MCP 工具注册
# ──────────────────────────────────────────────────────────────────

def register(mcp: FastMCP):
    """Register factor analysis tools with the MCP server."""

    @mcp.tool()
    async def calculate_factor_score(
        stock_codes: list[str],
        factor_data: dict[str, list[float]],
        weights: dict[str, float] | None = None,
    ) -> str:
        """
        多因子综合评分。

        输入多只股票的多个因子值，标准化处理后按权重加权得到综合评分。
        支持5类20+因子，可自定义权重。

        Args:
            stock_codes: 股票代码数组，如 ["000001", "600519", ...]
            factor_data: 因子数据字典
            {
                "pe": [10.5, 30.2, 15.8, ...],          # 与stock_codes一一对应
                "pb": [1.2, 8.5, 2.3, ...],
                "revenue_growth": [0.15, 0.20, 0.08, ...]
            }
            weights: 因子权重（可选），如 {"pe": 0.3, "pb": 0.2, "revenue_growth": 0.5}
                    未指定时所有因子等权

        Returns:
            多因子评分结果 (JSON):
            - scores: 综合评分列表（按分数降序）
              [{code, total_score, factor_scores: {...}}, ...]
            - summary: 统计摘要
            - weights_used: 实际使用的权重
        """
        try:
            if not stock_codes:
                return error_response("参数错误: stock_codes 不能为空", "calculate_factor_score")
            if not factor_data:
                return error_response("参数错误: factor_data 不能为空", "calculate_factor_score")

            n = len(stock_codes)
            for factor_name, values in factor_data.items():
                if len(values) != n:
                    return error_response(
                        f"参数错误: 因子 {factor_name} 的数据长度({len(values)})与股票数量({n})不一致",
                        "calculate_factor_score",
                    )

            # 验证因子是否在目录中
            catalog_names = {f["name"] for f in FACTOR_CATALOG}
            invalid_factors = set(factor_data.keys()) - catalog_names
            if invalid_factors:
                return error_response(
                    f"参数错误: 不支持的因子 {invalid_factors}，调用 get_factor_catalog 查看支持的因子",
                    "calculate_factor_score",
                )

            # 计算每个因子的得分
            factor_scores: dict[str, dict[str, float]] = {}
            for factor_name, values in factor_data.items():
                factor_meta = next(f for f in FACTOR_CATALOG if f["name"] == factor_name)
                factor_scores[factor_name] = _calculate_single_factor(
                    stock_codes, values, factor_meta["direction"]
                )

            # 权重处理
            if weights is None:
                weights = {name: 1.0 / len(factor_data) for name in factor_data.keys()}
            else:
                total_w = sum(weights.values())
                if total_w <= 0:
                    return error_response("参数错误: 权重总和必须大于0", "calculate_factor_score")
                weights = {k: v / total_w for k, v in weights.items()}
                # 未指定权重的因子用0
                for name in factor_data.keys():
                    if name not in weights:
                        weights[name] = 0.0

            # 综合评分
            results: list[dict] = []
            for i, code in enumerate(stock_codes):
                total_score = 0.0
                detail: dict[str, float] = {}
                for factor_name in factor_data.keys():
                    score = factor_scores[factor_name][code]
                    weighted = score * weights[factor_name]
                    total_score += weighted
                    detail[factor_name] = score
                results.append({
                    "code": code,
                    "total_score": round(total_score, 4),
                    "factor_scores": detail,
                })

            # 按综合得分降序
            results.sort(key=lambda x: x["total_score"], reverse=True)

            # 统计摘要
            all_scores = [r["total_score"] for r in results]
            summary = {
                "total_stocks": len(results),
                "mean_score": round(sum(all_scores) / len(all_scores), 4) if all_scores else 0,
                "max_score": round(max(all_scores), 4) if all_scores else 0,
                "min_score": round(min(all_scores), 4) if all_scores else 0,
                "top_10_pct_threshold": round(
                    sorted(all_scores, reverse=True)[max(1, len(all_scores) // 10) - 1], 4
                ) if len(all_scores) >= 10 else None,
            }

            return dict_to_json({
                "success": True,
                "scores": results,
                "summary": summary,
                "weights_used": weights,
            })
        except Exception as e:
            return error_response(f"因子评分计算失败: {e}", "calculate_factor_score")

    @mcp.tool()
    async def get_factor_catalog() -> str:
        """
        获取因子库清单。

        返回所有支持的因子列表，包含因子名称、所属类别、方向（正向/负向/中性）、单位。
        可用于让 AI Agent 了解 calculate_factor_score 工具支持的因子。

        Returns:
            因子库清单 (JSON):
            - categories: 因子类别
            - factors: 因子详情列表
            - total_count: 因子总数
        """
        try:
            return dict_to_json({
                "success": True,
                "categories": FACTOR_CATEGORIES,
                "factors": FACTOR_CATALOG,
                "total_count": len(FACTOR_CATALOG),
                "direction_explanation": {
                    "positive": "数值越大越好（如营收增长率）",
                    "negative": "数值越小越好（如PE）",
                    "neutral": "中性因子（如RSI、Beta）",
                },
                "usage": (
                    "调用 calculate_factor_score 工具，传入 stock_codes 和 factor_data 即可获得综合评分。"
                    "factor_data 的 key 必须是本清单中的因子 name，value 是与 stock_codes 一一对应的数值数组。"
                ),
            })
        except Exception as e:
            return error_response(f"获取因子清单失败: {e}", "get_factor_catalog")
