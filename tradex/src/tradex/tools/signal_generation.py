"""
Category 12: Signal Generation — 交易信号生成 (V2.5.0).

基于技术指标组合判断，为 AI Agent 提供买卖信号生成与验证服务。

设计原则：
  1. 多指标组合：单一指标信号噪音大，组合判断更可靠
  2. 信号分级：强烈买入/买入/中性/卖出/强烈卖出 五级
  3. 评分量化：每个信号附 0-100 分值，便于排序
  4. 前瞻验证：信号生成后可验证未来N日收益，评估信号质量

Tools (共 3 个):
  70. generate_trading_signal   - 单票交易信号生成
  71. scan_stocks_for_signals   - 批量扫描股票信号
  72. validate_signal_quality   - 信号质量验证（前瞻收益）
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..utils.formatter import dict_to_json, error_response
from .technical_indicators import _sma, _ema, _stddev


# ──────────────────────────────────────────────────────────────────
# 信号生成核心算法
# ──────────────────────────────────────────────────────────────────

def _macd_calc(closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    """计算 MACD（内部使用，返回对齐后的数组）。"""
    fast_ema = _ema(closes, fast)
    slow_ema = _ema(closes, slow)
    n = len(closes)
    dif: list[float | None] = [None] * (slow - 1)
    for i in range(slow - 1, n):
        f = fast_ema[i]
        s = slow_ema[i]
        dif.append(round(f - s, 4) if (f is not None and s is not None) else None)

    dif_valid = [v for v in dif[slow - 1:] if v is not None]
    dea_valid = _ema(dif_valid, signal)
    dea: list[float | None] = [None] * (slow - 1 + signal - 1)
    dea.extend(dea_valid[signal - 1:] if len(dea_valid) >= signal else [])
    return {"dif": dif, "dea": dea}


def _kdj_calc(highs, lows, closes, n=9, m1=3, m2=3) -> dict:
    """计算 KDJ。"""
    k_arr, d_arr, j_arr = [], [], []
    prev_k, prev_d = 50.0, 50.0
    for i in range(len(closes)):
        start = max(0, i - n + 1)
        ll = min(lows[start:i + 1])
        hh = max(highs[start:i + 1])
        den = hh - ll
        rsv = 50.0 if den == 0.0 else ((closes[i] - ll) / den * 100.0)
        prev_k = (2.0 / m1) * prev_k + (1.0 / m1) * rsv
        prev_d = (2.0 / m2) * prev_d + (1.0 / m2) * prev_k
        j_val = 3 * prev_k - 2 * prev_d
        k_arr.append(prev_k)
        d_arr.append(prev_d)
        j_arr.append(j_val)
    return {"k": k_arr, "d": d_arr, "j": j_arr}


def _rsi_calc(closes: list[float], period: int = 14) -> list[float | None]:
    """计算 RSI（Wilder）。"""
    if len(closes) < period + 1:
        return [None] * len(closes)
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(d, 0) for d in deltas]
    losses = [abs(min(d, 0)) for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    rsi_arr: list[float | None] = [None] * period
    if avg_loss == 0:
        rsi_arr[period - 1] = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi_arr[period - 1] = round(100 - 100 / (1 + rs), 4)
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi_arr.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi_arr.append(round(100 - 100 / (1 + rs), 4))
    return rsi_arr


def _boll_calc(closes: list[float], period: int = 20, k: float = 2.0) -> dict:
    """计算布林带。"""
    n = len(closes)
    upper: list[float | None] = [None] * (period - 1)
    middle: list[float | None] = [None] * (period - 1)
    lower: list[float | None] = [None] * (period - 1)
    for i in range(period - 1, n):
        window = closes[i - period + 1:i + 1]
        mean = sum(window) / period
        std = _stddev(window, mean)
        upper.append(mean + k * std)
        middle.append(mean)
        lower.append(mean - k * std)
    return {"upper": upper, "middle": middle, "lower": lower}


def _generate_signal_for_stock(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float] | None = None,
) -> dict:
    """
    基于多指标组合生成单票交易信号。

    评分维度：
      - 趋势(30%): MA金叉死叉、价格与MA位置关系
      - 动量(25%): MACD金叉死叉、柱状图变化
      - 超买超卖(20%): KDJ/RSI 位置
      - 量能(15%): 量比、成交量变化
      - 风险(10%): 布林带位置、ATR波动
    """
    n = len(closes)
    if n < 30:
        return {
            "signal": "insufficient_data",
            "score": 0,
            "reason": f"数据不足: 需要至少30根K线，当前{n}根",
        }

    score = 50.0  # 中性起步
    reasons: list[str] = []

    # === 1. 趋势维度（MA5/MA20 金叉死叉）===
    ma5 = _sma(closes, 5)
    ma20 = _sma(closes, 20)
    last_ma5 = ma5[-1]
    last_ma20 = ma20[-1]
    prev_ma5 = ma5[-2]
    prev_ma20 = ma20[-2]

    if last_ma5 is not None and last_ma20 is not None:
        if prev_ma5 is not None and prev_ma20 is not None:
            if prev_ma5 <= prev_ma20 and last_ma5 > last_ma20:
                score += 15
                reasons.append("MA5上穿MA20(金叉)")
            elif prev_ma5 >= prev_ma20 and last_ma5 < last_ma20:
                score -= 15
                reasons.append("MA5下穿MA20(死叉)")
        if last_ma5 > last_ma20:
            score += 5
            reasons.append("价格在MA20上方(多头排列)")
        else:
            score -= 5
            reasons.append("价格在MA20下方(空头排列)")

    # === 2. 动量维度（MACD）===
    macd_data = _macd_calc(closes)
    dif = macd_data["dif"]
    dea = macd_data["dea"]
    if len(dif) >= 2 and len(dea) >= 2:
        last_dif = dif[-1]
        last_dea = dea[-1]
        prev_dif = dif[-2]
        prev_dea = dea[-2]
        if None not in (last_dif, last_dea, prev_dif, prev_dea):
            if prev_dif <= prev_dea and last_dif > last_dea:
                score += 12
                reasons.append("MACD金叉")
            elif prev_dif >= prev_dea and last_dif < last_dea:
                score -= 12
                reasons.append("MACD死叉")
            if last_dif > 0:
                score += 3
                reasons.append("DIF在零轴上方")
            else:
                score -= 3
                reasons.append("DIF在零轴下方")

    # === 3. 超买超卖（KDJ + RSI）===
    kdj_data = _kdj_calc(highs, lows, closes)
    last_k = kdj_data["k"][-1]
    last_d = kdj_data["d"][-1]
    last_j = kdj_data["j"][-1]
    if last_j < 0:
        score += 8
        reasons.append(f"KDJ超卖(J={last_j:.1f})")
    elif last_j > 100:
        score -= 8
        reasons.append(f"KDJ超买(J={last_j:.1f})")

    rsi_arr = _rsi_calc(closes)
    last_rsi = rsi_arr[-1] if rsi_arr else None
    if last_rsi is not None:
        if last_rsi < 30:
            score += 8
            reasons.append(f"RSI超卖({last_rsi:.1f})")
        elif last_rsi > 70:
            score -= 8
            reasons.append(f"RSI超买({last_rsi:.1f})")

    # === 4. 量能维度 ===
    if volumes and len(volumes) >= 6:
        vol_ma5 = sum(volumes[-6:-1]) / 5 if len(volumes) >= 6 else 0
        last_vol = volumes[-1]
        if vol_ma5 > 0:
            vol_ratio = last_vol / vol_ma5
            if vol_ratio > 1.5:
                score += 7
                reasons.append(f"放量(量比{vol_ratio:.2f})")
            elif vol_ratio < 0.5:
                score -= 3
                reasons.append(f"缩量(量比{vol_ratio:.2f})")

    # === 5. 风险维度（布林带位置）===
    boll = _boll_calc(closes)
    last_upper = boll["upper"][-1]
    last_lower = boll["lower"][-1]
    last_mid = boll["middle"][-1]
    last_close = closes[-1]
    if None not in (last_upper, last_lower, last_mid):
        if last_close >= last_upper:
            score -= 5
            reasons.append("触及布林上轨")
        elif last_close <= last_lower:
            score += 5
            reasons.append("触及布林下轨")

    # 分数边界
    score = max(0, min(100, score))

    # 信号分级
    if score >= 75:
        signal = "strong_buy"
    elif score >= 60:
        signal = "buy"
    elif score >= 40:
        signal = "neutral"
    elif score >= 25:
        signal = "sell"
    else:
        signal = "strong_sell"

    return {
        "signal": signal,
        "score": round(score, 2),
        "reasons": reasons,
        "indicators": {
            "ma5": last_ma5,
            "ma20": last_ma20,
            "macd_dif": dif[-1] if dif and dif[-1] is not None else None,
            "macd_dea": dea[-1] if dea and dea[-1] is not None else None,
            "kdj_k": round(last_k, 4),
            "kdj_d": round(last_d, 4),
            "kdj_j": round(last_j, 4),
            "rsi": last_rsi,
            "boll_upper": last_upper,
            "boll_middle": last_mid,
            "boll_lower": last_lower,
        },
    }


# ──────────────────────────────────────────────────────────────────
# MCP 工具注册
# ──────────────────────────────────────────────────────────────────

def register(mcp: FastMCP):
    """Register signal generation tools with the MCP server."""

    @mcp.tool()
    async def generate_trading_signal(
        highs: list[float],
        lows: list[float],
        closes: list[float],
        volumes: list[float] | None = None,
    ) -> str:
        """
        基于多指标组合生成单票交易信号。

        综合 MA/MACD/KDJ/RSI/BOLL/量比 等多维度评分，
        生成 strongly_buy/buy/neutral/sell/strong_sell 五级信号。

        评分维度：
        - 趋势(30%): MA5/MA20 金叉死叉
        - 动量(25%): MACD 金叉死叉、零轴位置
        - 超买超卖(20%): KDJ J值、RSI
        - 量能(15%): 量比变化
        - 风险(10%): 布林带位置

        Args:
            highs: 最高价数组（至少30根K线）
            lows: 最低价数组
            closes: 收盘价数组
            volumes: 成交量数组（可选）

        Returns:
            交易信号 (JSON):
            - signal: 信号级别 strong_buy/buy/neutral/sell/strong_sell
            - score: 综合评分 0-100
            - reasons: 触发原因列表
            - indicators: 最新技术指标值
        """
        try:
            if not (len(highs) == len(lows) == len(closes)):
                return error_response(
                    "参数错误: highs/lows/closes 长度必须相同",
                    "generate_trading_signal",
                )
            if volumes is not None and len(volumes) != len(closes):
                return error_response(
                    "参数错误: volumes 长度必须与 closes 相同",
                    "generate_trading_signal",
                )

            result = _generate_signal_for_stock(highs, lows, closes, volumes)
            result["data_points"] = len(closes)
            result["success"] = True
            return dict_to_json(result)
        except Exception as e:
            return error_response(f"信号生成失败: {e}", "generate_trading_signal")

    @mcp.tool()
    async def scan_stocks_for_signals(
        stocks_data: dict[str, dict[str, list[float]]],
        min_score: float = 0,
        signal_filter: str = "",
    ) -> str:
        """
        批量扫描多只股票的交易信号。

        输入多只股票的OHLCV数据，批量生成信号并按评分排序。
        适用于全市场选股、自选股扫描等场景。

        Args:
            stocks_data: 股票数据字典
            {
                "000001": {
                    "highs": [...], "lows": [...], "closes": [...], "volumes": [...]
                },
                "600519": {...}
            }
            min_score: 最低评分阈值，默认0（不筛选）
            signal_filter: 信号过滤，逗号分隔，如 "strong_buy,buy"

        Returns:
            扫描结果 (JSON):
            - results: 股票信号列表（按评分降序）
            - summary: 统计摘要（各信号级别数量）
            - total_scanned: 扫描总数
            - total_returned: 返回数量
        """
        try:
            if not stocks_data:
                return error_response("参数错误: stocks_data 不能为空", "scan_stocks_for_signals")

            allowed_signals = (
                set(signal_filter.split(",")) if signal_filter.strip() else None
            )

            results: list[dict] = []
            signal_counts: dict[str, int] = {}
            errors: list[dict] = []

            for code, data in stocks_data.items():
                try:
                    highs = data.get("highs", [])
                    lows = data.get("lows", [])
                    closes = data.get("closes", [])
                    volumes = data.get("volumes")

                    if not (len(highs) == len(lows) == len(closes)):
                        errors.append({"code": code, "error": "数据长度不一致"})
                        continue

                    sig = _generate_signal_for_stock(highs, lows, closes, volumes)
                    sig["code"] = code
                    sig["data_points"] = len(closes)

                    signal_counts[sig["signal"]] = signal_counts.get(sig["signal"], 0) + 1

                    if sig["score"] >= min_score:
                        if allowed_signals is None or sig["signal"] in allowed_signals:
                            results.append(sig)
                except Exception as e:
                    errors.append({"code": code, "error": str(e)})

            # 按评分降序
            results.sort(key=lambda x: x.get("score", 0), reverse=True)

            return dict_to_json({
                "success": True,
                "results": results,
                "summary": {
                    "total_scanned": len(stocks_data),
                    "total_returned": len(results),
                    "signal_counts": signal_counts,
                    "errors_count": len(errors),
                },
                "errors": errors[:10] if errors else [],
            })
        except Exception as e:
            return error_response(f"批量扫描失败: {e}", "scan_stocks_for_signals")

    @mcp.tool()
    async def validate_signal_quality(
        closes: list[float],
        signal_idx: int,
        forward_days: int = 5,
    ) -> str:
        """
        验证信号质量（前瞻收益分析）。

        在指定位置的信号生成后，统计未来N日的实际收益，
        用于评估信号的有效性。

        Args:
            closes: 收盘价数组
            signal_idx: 信号产生的索引位置（0-based）
            forward_days: 前瞻天数，默认5

        Returns:
            信号质量验证 (JSON):
            - forward_returns: 未来1/3/5/10/20日收益
            - max_gain: 期间最大涨幅
            - max_loss: 期间最大跌幅
            - win_rate: 上涨概率（基于日收益）
            - signal_price: 信号位置价格
            - end_price: 前瞻期末价格
        """
        try:
            if signal_idx < 0 or signal_idx >= len(closes):
                return error_response(
                    f"参数错误: signal_idx 必须在 [0, {len(closes) - 1}] 范围内",
                    "validate_signal_quality",
                )
            if forward_days <= 0:
                return error_response(
                    "参数错误: forward_days 必须为正整数",
                    "validate_signal_quality",
                )

            end_idx = min(signal_idx + forward_days, len(closes) - 1)
            signal_price = closes[signal_idx]
            end_price = closes[end_idx]

            # 未来各时点收益
            check_points = [1, 3, 5, 10, 20]
            forward_returns: dict[str, float] = {}
            for d in check_points:
                idx = min(signal_idx + d, len(closes) - 1)
                if idx > signal_idx and signal_price > 0:
                    forward_returns[f"d{d}"] = round(
                        (closes[idx] - signal_price) / signal_price * 100, 4
                    )

            # 期间最大涨跌幅
            future_prices = closes[signal_idx:end_idx + 1]
            max_gain = (max(future_prices) - signal_price) / signal_price * 100 if signal_price > 0 else 0
            max_loss = (min(future_prices) - signal_price) / signal_price * 100 if signal_price > 0 else 0

            # 日上涨概率
            daily_returns = [
                1 if future_prices[i] > future_prices[i - 1] else 0
                for i in range(1, len(future_prices))
            ]
            win_rate = sum(daily_returns) / len(daily_returns) if daily_returns else 0

            total_return = (end_price - signal_price) / signal_price * 100 if signal_price > 0 else 0

            return dict_to_json({
                "success": True,
                "signal_idx": signal_idx,
                "signal_price": signal_price,
                "end_idx": end_idx,
                "end_price": end_price,
                "forward_days": end_idx - signal_idx,
                "total_return_pct": round(total_return, 4),
                "forward_returns_pct": forward_returns,
                "max_gain_pct": round(max_gain, 4),
                "max_loss_pct": round(max_loss, 4),
                "win_rate": round(win_rate, 4),
                "up_days": sum(daily_returns),
                "down_days": len(daily_returns) - sum(daily_returns),
            })
        except Exception as e:
            return error_response(f"信号质量验证失败: {e}", "validate_signal_quality")
