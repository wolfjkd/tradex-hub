"""
Category 11: Performance Metrics Calculation — 绩效指标计算 (V2.5.0).

为 AI Agent 提供专业的回测绩效分析服务。
输入权益曲线和交易记录，输出完整的绩效报告。

设计原则：
  1. 专业性：覆盖学术界和工业界常用的所有绩效指标
  2. 完整性：收益、风险、风险调整收益、交易质量、费用统计全覆盖
  3. 可解释性：每个指标都有明确的定义和计算公式
  4. 鲁棒性：正确处理空数据、零交易、全亏损等边界情况

Tools (共 2 个):
  68. calculate_performance      - 计算完整绩效指标
  69. list_performance_metrics   - 列出支持的绩效指标清单
"""

from __future__ import annotations

import math
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..utils.formatter import dict_to_json, error_response


# ──────────────────────────────────────────────────────────────────
# 绩效指标算法实现（与 quantcore/metrics.py 保持一致并扩展）
# ──────────────────────────────────────────────────────────────────

def _total_return(equity_curve: list[float]) -> float:
    if len(equity_curve) < 2 or equity_curve[0] == 0:
        return 0.0
    return (equity_curve[-1] - equity_curve[0]) / equity_curve[0]


def _annualized_return(equity_curve: list[float], trading_days: int = 252) -> float:
    if len(equity_curve) < 2:
        return 0.0
    total_ret = _total_return(equity_curve)
    days = len(equity_curve)
    if days <= 0 or (1 + total_ret) <= 0:
        return 0.0
    return (1 + total_ret) ** (trading_days / days) - 1


def _volatility(equity_curve: list[float], trading_days: int = 252) -> float:
    if len(equity_curve) < 2:
        return 0.0
    returns = [
        equity_curve[i] / equity_curve[i - 1] - 1
        for i in range(1, len(equity_curve))
        if equity_curve[i - 1] != 0
    ]
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return math.sqrt(variance) * math.sqrt(trading_days)


def _downside_volatility(equity_curve: list[float], trading_days: int = 252) -> float:
    if len(equity_curve) < 2:
        return 0.0
    returns = [
        equity_curve[i] / equity_curve[i - 1] - 1
        for i in range(1, len(equity_curve))
        if equity_curve[i - 1] != 0
    ]
    downside = [r for r in returns if r < 0]
    if len(downside) < 2:
        return 0.0
    mean = sum(downside) / len(downside)
    variance = sum((r - mean) ** 2 for r in downside) / (len(downside) - 1)
    return math.sqrt(variance) * math.sqrt(trading_days)


def _max_drawdown(equity_curve: list[float]) -> tuple[float, int, int]:
    """返回 (最大回撤率, 起点索引, 终点索引)。"""
    if len(equity_curve) < 2:
        return 0.0, 0, 0
    max_equity = equity_curve[0]
    max_dd = 0.0
    peak_idx = 0
    trough_idx = 0
    temp_peak = 0
    for i, eq in enumerate(equity_curve):
        if eq > max_equity:
            max_equity = eq
            temp_peak = i
        if max_equity > 0:
            dd = (max_equity - eq) / max_equity
            if dd > max_dd:
                max_dd = dd
                peak_idx = temp_peak
                trough_idx = i
    return max_dd, peak_idx, trough_idx


def _sharpe_ratio(equity_curve: list[float], risk_free_rate: float = 0.03) -> float:
    ann_return = _annualized_return(equity_curve)
    vol = _volatility(equity_curve)
    if vol == 0:
        return 0.0
    return (ann_return - risk_free_rate) / vol


def _sortino_ratio(equity_curve: list[float], risk_free_rate: float = 0.03) -> float:
    ann_return = _annualized_return(equity_curve)
    downside_vol = _downside_volatility(equity_curve)
    if downside_vol == 0:
        return 0.0
    return (ann_return - risk_free_rate) / downside_vol


def _calmar_ratio(equity_curve: list[float]) -> float:
    ann_return = _annualized_return(equity_curve)
    max_dd, _, _ = _max_drawdown(equity_curve)
    if max_dd == 0:
        return float('inf') if ann_return > 0 else 0.0
    return ann_return / max_dd


def _win_rate(trades: list[dict]) -> float:
    if len(trades) == 0:
        return 0.0
    win_count = sum(1 for t in trades if t.get('profit', 0) > 0)
    return win_count / len(trades)


def _profit_factor(trades: list[dict]) -> float:
    gross_profit = sum(t.get('profit', 0) for t in trades if t.get('profit', 0) > 0)
    gross_loss = abs(sum(t.get('profit', 0) for t in trades if t.get('profit', 0) < 0))
    if gross_loss == 0:
        return float('inf') if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def _expected_return(trades: list[dict]) -> float:
    if len(trades) == 0:
        return 0.0
    return sum(t.get('profit', 0) for t in trades) / len(trades)


def _var_95(equity_curve: list[float]) -> float:
    """95% 置信度下的 VaR（历史模拟法）。"""
    if len(equity_curve) < 2:
        return 0.0
    returns = [
        equity_curve[i] / equity_curve[i - 1] - 1
        for i in range(1, len(equity_curve))
        if equity_curve[i - 1] != 0
    ]
    if len(returns) < 5:
        return 0.0
    returns_sorted = sorted(returns)
    idx = int(len(returns_sorted) * 0.05)
    return abs(returns_sorted[idx])


def _cvar_95(equity_curve: list[float]) -> float:
    """95% 置信度下的 CVaR（条件 VaR）。"""
    if len(equity_curve) < 2:
        return 0.0
    returns = [
        equity_curve[i] / equity_curve[i - 1] - 1
        for i in range(1, len(equity_curve))
        if equity_curve[i - 1] != 0
    ]
    if len(returns) < 5:
        return 0.0
    returns_sorted = sorted(returns)
    idx = max(1, int(len(returns_sorted) * 0.05))
    tail = returns_sorted[:idx]
    return abs(sum(tail) / len(tail))


# ──────────────────────────────────────────────────────────────────
# 支持的绩效指标清单
# ──────────────────────────────────────────────────────────────────

PERFORMANCE_METRICS_CATALOG = [
    # 收益类
    {"name": "total_return", "category": "return", "desc": "总收益率", "formula": "(末值-初值)/初值"},
    {"name": "annualized_return", "category": "return", "desc": "年化收益率", "formula": "(1+总收益)^(252/天数)-1"},
    {"name": "benchmark_return", "category": "return", "desc": "基准收益率", "formula": "需传入基准权益曲线"},
    {"name": "excess_return", "category": "return", "desc": "超额收益率", "formula": "策略年化-基准年化"},

    # 风险类
    {"name": "volatility", "category": "risk", "desc": "年化波动率", "formula": "std(日收益)*sqrt(252)"},
    {"name": "downside_volatility", "category": "risk", "desc": "下行波动率", "formula": "std(负收益)*sqrt(252)"},
    {"name": "max_drawdown", "category": "risk", "desc": "最大回撤率", "formula": "max((峰值-谷值)/峰值)"},
    {"name": "var_95", "category": "risk", "desc": "VaR(95%)", "formula": "历史模拟法95%分位数"},
    {"name": "cvar_95", "category": "risk", "desc": "CVaR(95%)", "formula": "尾部5%收益均值"},

    # 风险调整收益
    {"name": "sharpe_ratio", "category": "risk_adjusted", "desc": "夏普比率", "formula": "(年化收益-无风险利率)/波动率"},
    {"name": "sortino_ratio", "category": "risk_adjusted", "desc": "索提诺比率", "formula": "(年化收益-无风险利率)/下行波动率"},
    {"name": "calmar_ratio", "category": "risk_adjusted", "desc": "卡尔玛比率", "formula": "年化收益/最大回撤"},

    # 交易质量
    {"name": "win_rate", "category": "trade_quality", "desc": "胜率", "formula": "盈利交易数/总交易数"},
    {"name": "profit_factor", "category": "trade_quality", "desc": "盈亏比", "formula": "总盈利/总亏损"},
    {"name": "expected_return", "category": "trade_quality", "desc": "期望收益", "formula": "总盈亏/交易数"},
    {"name": "total_trades", "category": "trade_quality", "desc": "总交易数", "formula": "len(trades)"},
    {"name": "avg_profit_per_trade", "category": "trade_quality", "desc": "单笔平均盈亏", "formula": "总盈亏/交易数"},

    # 费用统计
    {"name": "total_commission", "category": "cost", "desc": "总佣金", "formula": "sum(commission)"},
    {"name": "total_tax", "category": "cost", "desc": "总印花税", "formula": "sum(stamp_tax)"},
    {"name": "total_slippage", "category": "cost", "desc": "总滑点成本", "formula": "sum(slippage)"},
    {"name": "total_cost", "category": "cost", "desc": "总交易成本", "formula": "佣金+印花税+滑点"},
]


# ──────────────────────────────────────────────────────────────────
# MCP 工具注册
# ──────────────────────────────────────────────────────────────────

def register(mcp: FastMCP):
    """Register performance metrics calculation tools with the MCP server."""

    @mcp.tool()
    async def calculate_performance(
        equity_curve: list[float],
        trades: list[dict] | None = None,
        benchmark_curve: list[float] | None = None,
        risk_free_rate: float = 0.03,
        trading_days: int = 252,
    ) -> str:
        """
        计算完整的策略绩效指标。

        输入权益曲线和交易记录，输出涵盖收益、风险、风险调整收益、
        交易质量、费用统计的完整绩效报告。

        Args:
            equity_curve: 权益曲线数组（日频），如 [1000000, 1005000, 1010000, ...]
            trades: 交易记录数组，每条记录可含 profit/commission/stamp_tax/slippage 字段
            benchmark_curve: 基准权益曲线（可选），用于计算超额收益
            risk_free_rate: 无风险利率，默认0.03（3%）
            trading_days: 年交易日数，默认252

        Returns:
            完整绩效报告 (JSON)，包含：
            - return_metrics: 收益类指标
            - risk_metrics: 风险类指标
            - risk_adjusted_metrics: 风险调整收益指标
            - trade_quality_metrics: 交易质量指标
            - cost_metrics: 费用统计指标
            - benchmark_metrics: 基准对比指标（如有基准）
        """
        try:
            if not equity_curve or len(equity_curve) < 2:
                return error_response(
                    "参数错误: equity_curve 至少需要 2 个数据点",
                    "calculate_performance",
                )

            trades = trades or []
            max_dd, peak_idx, trough_idx = _max_drawdown(equity_curve)

            # 收益类
            total_ret = _total_return(equity_curve)
            ann_ret = _annualized_return(equity_curve, trading_days)

            return_metrics = {
                "total_return": round(total_ret, 4),
                "annualized_return": round(ann_ret, 4),
                "days": len(equity_curve),
                "initial_equity": equity_curve[0],
                "final_equity": equity_curve[-1],
            }

            # 风险类
            risk_metrics = {
                "volatility": round(_volatility(equity_curve, trading_days), 4),
                "downside_volatility": round(_downside_volatility(equity_curve, trading_days), 4),
                "max_drawdown": round(max_dd, 4),
                "max_drawdown_peak_idx": peak_idx,
                "max_drawdown_trough_idx": trough_idx,
                "var_95": round(_var_95(equity_curve), 4),
                "cvar_95": round(_cvar_95(equity_curve), 4),
            }

            # 风险调整收益
            sharpe = _sharpe_ratio(equity_curve, risk_free_rate)
            sortino = _sortino_ratio(equity_curve, risk_free_rate)
            calmar = _calmar_ratio(equity_curve)
            risk_adjusted_metrics = {
                "sharpe_ratio": round(sharpe, 4) if sharpe != float('inf') else "inf",
                "sortino_ratio": round(sortino, 4) if sortino != float('inf') else "inf",
                "calmar_ratio": round(calmar, 4) if calmar != float('inf') else "inf",
                "risk_free_rate": risk_free_rate,
            }

            # 交易质量
            total_profit = sum(t.get('profit', 0) for t in trades)
            total_trades = len(trades)
            win_count = sum(1 for t in trades if t.get('profit', 0) > 0)
            loss_count = sum(1 for t in trades if t.get('profit', 0) < 0)
            pf = _profit_factor(trades)
            trade_quality_metrics = {
                "total_trades": total_trades,
                "win_count": win_count,
                "loss_count": loss_count,
                "win_rate": round(_win_rate(trades), 4),
                "profit_factor": round(pf, 4) if pf != float('inf') else "inf",
                "expected_return": round(_expected_return(trades), 4),
                "total_profit": round(total_profit, 4),
                "avg_profit_per_trade": round(total_profit / total_trades, 4) if total_trades > 0 else 0.0,
            }

            # 费用统计
            total_commission = sum(t.get('commission', 0) for t in trades)
            total_tax = sum(t.get('stamp_tax', 0) for t in trades)
            total_slippage = sum(t.get('slippage', 0) for t in trades)
            cost_metrics = {
                "total_commission": round(total_commission, 4),
                "total_tax": round(total_tax, 4),
                "total_slippage": round(total_slippage, 4),
                "total_cost": round(total_commission + total_tax + total_slippage, 4),
                "cost_per_trade": round(
                    (total_commission + total_tax + total_slippage) / total_trades, 4
                ) if total_trades > 0 else 0.0,
            }

            result: dict[str, Any] = {
                "success": True,
                "return_metrics": return_metrics,
                "risk_metrics": risk_metrics,
                "risk_adjusted_metrics": risk_adjusted_metrics,
                "trade_quality_metrics": trade_quality_metrics,
                "cost_metrics": cost_metrics,
            }

            # 基准对比
            if benchmark_curve and len(benchmark_curve) >= 2:
                bench_total_ret = _total_return(benchmark_curve)
                bench_ann_ret = _annualized_return(benchmark_curve, trading_days)
                benchmark_metrics = {
                    "benchmark_total_return": round(bench_total_ret, 4),
                    "benchmark_annualized_return": round(bench_ann_ret, 4),
                    "excess_return": round(ann_ret - bench_ann_ret, 4),
                    "excess_total_return": round(total_ret - bench_total_ret, 4),
                }
                result["benchmark_metrics"] = benchmark_metrics

            return dict_to_json(result)
        except Exception as e:
            return error_response(f"绩效指标计算失败: {e}", "calculate_performance")

    @mcp.tool()
    async def list_performance_metrics() -> str:
        """
        列出所有支持的绩效指标清单。

        返回按类别分组的绩效指标清单，每个指标包含名称、描述和计算公式。
        可用于让 AI Agent 了解 calculate_performance 工具的输出字段含义。

        Returns:
            绩效指标清单 (JSON):
            - categories: 指标类别列表
              - return: 收益类
              - risk: 风险类
              - risk_adjusted: 风险调整收益类
              - trade_quality: 交易质量类
              - cost: 费用统计类
            - metrics: 所有指标详情列表
            - total_count: 指标总数
        """
        try:
            categories = {
                "return": "收益类指标",
                "risk": "风险类指标",
                "risk_adjusted": "风险调整收益指标",
                "trade_quality": "交易质量指标",
                "cost": "费用统计指标",
            }
            return dict_to_json({
                "success": True,
                "categories": categories,
                "metrics": PERFORMANCE_METRICS_CATALOG,
                "total_count": len(PERFORMANCE_METRICS_CATALOG),
                "usage": "调用 calculate_performance 工具，传入 equity_curve 和 trades 即可获得以上所有指标的完整报告",
            })
        except Exception as e:
            return error_response(f"获取绩效指标清单失败: {e}", "list_performance_metrics")
