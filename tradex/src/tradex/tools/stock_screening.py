"""
Category 14: Stock Screening — 条件选股 (V2.5.0).

为 AI Agent 提供条件选股扫描服务，支持多维度条件组合筛选。

设计原则：
  1. 多维筛选：基本面/技术面/资金面/风险面 四大类条件
  2. 条件组合：支持 AND 逻辑组合多条件
  3. 排序输出：支持按指定字段升序/降序排序
  4. 上限控制：支持 limit 限制返回数量

Tools (共 2 个):
  75. screen_stocks              - 条件选股扫描
  76. get_screening_conditions   - 获取支持的选股条件清单
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..utils.formatter import dict_to_json, error_response


# ──────────────────────────────────────────────────────────────────
# 选股条件库定义
# ──────────────────────────────────────────────────────────────────

SCREENING_CONDITIONS = [
    # 基本面条件
    {"name": "pe", "category": "fundamental", "desc": "市盈率PE(TTM)", "type": "range", "unit": "倍",
     "operators": ["<", "<=", ">", ">=", "between"]},
    {"name": "pb", "category": "fundamental", "desc": "市净率PB", "type": "range", "unit": "倍",
     "operators": ["<", "<=", ">", ">=", "between"]},
    {"name": "ps", "category": "fundamental", "desc": "市销率PS", "type": "range", "unit": "倍",
     "operators": ["<", "<=", ">", ">=", "between"]},
    {"name": "market_cap", "category": "fundamental", "desc": "总市值", "type": "range", "unit": "亿元",
     "operators": ["<", "<=", ">", ">=", "between"]},
    {"name": "roe", "category": "fundamental", "desc": "ROE净资产收益率", "type": "range", "unit": "%",
     "operators": ["<", "<=", ">", ">=", "between"]},
    {"name": "revenue_growth", "category": "fundamental", "desc": "营收同比增长率", "type": "range", "unit": "%",
     "operators": ["<", "<=", ">", ">=", "between"]},
    {"name": "profit_growth", "category": "fundamental", "desc": "净利润同比增长率", "type": "range", "unit": "%",
     "operators": ["<", "<=", ">", ">=", "between"]},
    {"name": "dividend_yield", "category": "fundamental", "desc": "股息率", "type": "range", "unit": "%",
     "operators": ["<", "<=", ">", ">=", "between"]},
    {"name": "gross_margin", "category": "fundamental", "desc": "毛利率", "type": "range", "unit": "%",
     "operators": ["<", "<=", ">", ">=", "between"]},

    # 技术面条件
    {"name": "price", "category": "technical", "desc": "最新价", "type": "range", "unit": "元",
     "operators": ["<", "<=", ">", ">=", "between"]},
    {"name": "ma5", "category": "technical", "desc": "5日均线", "type": "range", "unit": "元",
     "operators": ["<", "<=", ">", ">=", "between"]},
    {"name": "ma20", "category": "technical", "desc": "20日均线", "type": "range", "unit": "元",
     "operators": ["<", "<=", ">", ">=", "between"]},
    {"name": "ma60", "category": "technical", "desc": "60日均线", "type": "range", "unit": "元",
     "operators": ["<", "<=", ">", ">=", "between"]},
    {"name": "rsi_14", "category": "technical", "desc": "14日RSI", "type": "range", "unit": "",
     "operators": ["<", "<=", ">", ">=", "between"]},
    {"name": "macd_dif", "category": "technical", "desc": "MACD DIF值", "type": "range", "unit": "",
     "operators": ["<", "<=", ">", ">=", "between"]},
    {"name": "boll_percent_b", "category": "technical", "desc": "布林带%B", "type": "range", "unit": "",
     "operators": ["<", "<=", ">", ">=", "between"]},
    {"name": "volume_ratio", "category": "technical", "desc": "量比", "type": "range", "unit": "倍",
     "operators": ["<", "<=", ">", ">=", "between"]},
    {"name": "turnover_rate", "category": "technical", "desc": "换手率", "type": "range", "unit": "%",
     "operators": ["<", "<=", ">", ">=", "between"]},
    {"name": "momentum_5d", "category": "technical", "desc": "5日涨幅", "type": "range", "unit": "%",
     "operators": ["<", "<=", ">", ">=", "between"]},
    {"name": "momentum_20d", "category": "technical", "desc": "20日涨幅", "type": "range", "unit": "%",
     "operators": ["<", "<=", ">", ">=", "between"]},

    # 资金面条件
    {"name": "net_inflow", "category": "capital", "desc": "主力净流入", "type": "range", "unit": "万元",
     "operators": ["<", "<=", ">", ">=", "between"]},
    {"name": "north_inflow", "category": "capital", "desc": "北向资金持股变动", "type": "range", "unit": "万股",
     "operators": ["<", "<=", ">", ">=", "between"]},

    # 风险面条件
    {"name": "beta", "category": "risk", "desc": "Beta系数", "type": "range", "unit": "",
     "operators": ["<", "<=", ">", ">=", "between"]},
    {"name": "volatility_20d", "category": "risk", "desc": "20日年化波动率", "type": "range", "unit": "%",
     "operators": ["<", "<=", ">", ">=", "between"]},
    {"name": "max_drawdown_60d", "category": "risk", "desc": "60日最大回撤", "type": "range", "unit": "%",
     "operators": ["<", "<=", ">", ">=", "between"]},

    # 布尔型条件
    {"name": "is_st", "category": "flag", "desc": "是否ST股", "type": "bool", "unit": "",
     "operators": ["=="]},
    {"name": "is_limit_up", "category": "flag", "desc": "今日是否涨停", "type": "bool", "unit": "",
     "operators": ["=="]},
    {"name": "is_limit_down", "category": "flag", "desc": "今日是否跌停", "type": "bool", "unit": "",
     "operators": ["=="]},
    {"name": "board", "category": "flag", "desc": "上市板块", "type": "enum",
     "enum_values": ["main_sh", "main_sz", "gem", "star", "bse"], "unit": "",
     "operators": ["in", "not_in"]},
    {"name": "industry", "category": "flag", "desc": "所属行业", "type": "enum",
     "enum_values": [], "unit": "", "operators": ["in", "not_in"]},
]

CONDITION_CATEGORIES = {
    "fundamental": "基本面条件",
    "technical": "技术面条件",
    "capital": "资金面条件",
    "risk": "风险面条件",
    "flag": "标记条件",
}


# ──────────────────────────────────────────────────────────────────
# 选股核心算法
# ──────────────────────────────────────────────────────────────────

def _match_condition(value: Any, operator: str, target: Any) -> bool:
    """检查单个值是否满足条件。"""
    if value is None:
        return False
    try:
        if operator == "<":
            return value < target
        elif operator == "<=":
            return value <= target
        elif operator == ">":
            return value > target
        elif operator == ">=":
            return value >= target
        elif operator == "==":
            return value == target
        elif operator == "between":
            # target 应为 [low, high]
            if isinstance(target, (list, tuple)) and len(target) == 2:
                return target[0] <= value <= target[1]
            return False
        elif operator == "in":
            return value in target
        elif operator == "not_in":
            return value not in target
        else:
            return False
    except (TypeError, ValueError):
        return False


def _parse_condition(cond: dict) -> tuple[str, str, Any]:
    """解析条件字典为 (field, operator, target)。"""
    field = cond.get("field", "")
    operator = cond.get("operator", ">=")
    target = cond.get("value")
    return field, operator, target


# ──────────────────────────────────────────────────────────────────
# MCP 工具注册
# ──────────────────────────────────────────────────────────────────

def register(mcp: FastMCP):
    """Register stock screening tools with the MCP server."""

    @mcp.tool()
    async def screen_stocks(
        stocks_data: list[dict[str, Any]],
        conditions: list[dict[str, Any]],
        sort_by: str = "",
        sort_order: str = "desc",
        limit: int = 50,
    ) -> str:
        """
        条件选股扫描。

        输入股票数据和多维度条件，输出符合条件的股票列表。
        支持基本面/技术面/资金面/风险面/标记 五大类条件组合筛选。

        Args:
            stocks_data: 股票数据数组，每个元素是一个股票的字典
                [{"code": "000001", "name": "平安银行", "pe": 8.5, "pb": 0.6, "price": 12.3, ...}, ...]
            conditions: 筛选条件数组（AND 逻辑）
                [
                    {"field": "pe", "operator": "<", "value": 20},
                    {"field": "pb", "operator": "<", "value": 2},
                    {"field": "roe", "operator": ">", "value": 15},
                    {"field": "is_st", "operator": "==", "value": false},
                    {"field": "board", "operator": "in", "value": ["main_sh", "main_sz"]}
                ]
            sort_by: 排序字段（可选），如 "pe" 或 "total_score"
            sort_order: 排序方向 "asc" 或 "desc"，默认 desc
            limit: 返回数量上限，默认50

        Returns:
            选股结果 (JSON):
            - results: 符合条件的股票列表
            - summary: 统计摘要
            - conditions_applied: 实际应用的条件
        """
        try:
            if not stocks_data:
                return error_response("参数错误: stocks_data 不能为空", "screen_stocks")
            if not conditions:
                return dict_to_json({
                    "success": True,
                    "results": stocks_data[:limit],
                    "summary": {
                        "total_input": len(stocks_data),
                        "total_matched": len(stocks_data),
                        "returned": min(len(stocks_data), limit),
                    },
                    "conditions_applied": [],
                })

            # 解析条件
            parsed_conditions = [_parse_condition(c) for c in conditions]

            # 筛选
            matched: list[dict] = []
            for stock in stocks_data:
                all_match = True
                for field, operator, target in parsed_conditions:
                    value = stock.get(field)
                    if not _match_condition(value, operator, target):
                        all_match = False
                        break
                if all_match:
                    matched.append(stock)

            # 排序
            if sort_by:
                reverse = (sort_order.lower() == "desc")
                try:
                    matched.sort(
                        key=lambda x: x.get(sort_by) if x.get(sort_by) is not None else float('-inf'),
                        reverse=reverse,
                    )
                except (TypeError, ValueError):
                    pass  # 排序失败时保持原序

            # 限制数量
            limited = matched[:limit]

            return dict_to_json({
                "success": True,
                "results": limited,
                "summary": {
                    "total_input": len(stocks_data),
                    "total_matched": len(matched),
                    "returned": len(limited),
                    "match_rate": round(len(matched) / len(stocks_data), 4) if stocks_data else 0,
                },
                "conditions_applied": conditions,
                "sort_by": sort_by,
                "sort_order": sort_order,
            })
        except Exception as e:
            return error_response(f"条件选股失败: {e}", "screen_stocks")

    @mcp.tool()
    async def get_screening_conditions() -> str:
        """
        获取支持的选股条件清单。

        返回所有可选的筛选字段，包含字段名、所属类别、类型、单位和支持的运算符。
        可用于让 AI Agent 了解 screen_stocks 工具支持的筛选条件。

        Returns:
            选股条件清单 (JSON):
            - categories: 条件类别
            - conditions: 条件详情列表
            - total_count: 条件总数
            - examples: 使用示例
        """
        try:
            return dict_to_json({
                "success": True,
                "categories": CONDITION_CATEGORIES,
                "conditions": SCREENING_CONDITIONS,
                "total_count": len(SCREENING_CONDITIONS),
                "operator_explanation": {
                    "<": "小于",
                    "<=": "小于等于",
                    ">": "大于",
                    ">=": "大于等于",
                    "==": "等于（用于布尔/枚举）",
                    "between": "区间（value 传 [low, high]）",
                    "in": "在集合中（value 传数组）",
                    "not_in": "不在集合中（value 传数组）",
                },
                "examples": [
                    {
                        "desc": "低估值蓝筹",
                        "conditions": [
                            {"field": "pe", "operator": "<", "value": 15},
                            {"field": "pb", "operator": "<", "value": 1.5},
                            {"field": "market_cap", "operator": ">", "value": 500},
                            {"field": "is_st", "operator": "==", "value": False}
                        ]
                    },
                    {
                        "desc": "高成长小盘",
                        "conditions": [
                            {"field": "revenue_growth", "operator": ">", "value": 30},
                            {"field": "profit_growth", "operator": ">", "value": 50},
                            {"field": "market_cap", "operator": "between", "value": [50, 300]},
                            {"field": "board", "operator": "in", "value": ["main_sh", "main_sz"]}
                        ]
                    },
                    {
                        "desc": "超跌反弹",
                        "conditions": [
                            {"field": "rsi_14", "operator": "<", "value": 30},
                            {"field": "boll_percent_b", "operator": "<", "value": 0.2},
                            {"field": "momentum_20d", "operator": "<", "value": -10}
                        ]
                    }
                ],
                "usage": (
                    "调用 screen_stocks 工具，传入 stocks_data 和 conditions 即可筛选。"
                    "stocks_data 的每个元素必须包含 conditions 中用到的字段名。"
                ),
            })
        except Exception as e:
            return error_response(f"获取选股条件清单失败: {e}", "get_screening_conditions")
