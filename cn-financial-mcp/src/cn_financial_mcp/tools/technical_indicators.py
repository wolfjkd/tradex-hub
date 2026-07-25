"""
Category 10: Technical Indicators Calculation — 纯函数技术指标计算 (V2.5.0).

为 AI Agent 提供标准化的技术指标计算服务，输入价格数组，输出指标数组。
与 signal_data.get_technical_indicator 的区别：
  - get_technical_indicator: 输入股票代码 → 查询行情 → 计算（依赖 stockstats）
  - calculate_*: 输入价格数组 → 纯计算（无外部依赖，无网络请求）

设计原则：
  1. 纯函数：输入价格数组，输出指标数组，无副作用
  2. 标准算法：与 Excel、通达信、同花顺计算结果一致
  3. 边界处理：正确处理 null 值、除零、数据不足等边界情况
  4. 统一精度：保留4位小数
  5. 无外部依赖：纯 Python 实现，不依赖 TA-Lib / stockstats / pandas

Tools (共 6 个):
  62. calculate_ma_ema   - MA/EMA 均线计算
  63. calculate_macd      - MACD 指标计算
  64. calculate_kdj       - KDJ 随机指标
  65. calculate_rsi       - RSI 相对强弱指数
  66. calculate_boll      - BOLL 布林带
  67. calculate_atr       - ATR 平均真实波幅
"""

from __future__ import annotations

import math
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..utils.formatter import dict_to_json, error_response


# ──────────────────────────────────────────────────────────────────
# 纯函数算法实现（与 quantcore/indicators.py 保持一致）
# ──────────────────────────────────────────────────────────────────

def _sma(closes: list[float], period: int) -> list[float | None]:
    """简单移动平均，前 period-1 个为 None。"""
    n = len(closes)
    if n < period or period <= 0:
        return [None] * n
    result: list[float | None] = [None] * (period - 1)
    window_sum = sum(closes[:period])
    result.append(round(window_sum / period, 4))
    for i in range(period, n):
        window_sum += closes[i] - closes[i - period]
        result.append(round(window_sum / period, 4))
    return result


def _ema(closes: list[float], period: int) -> list[float | None]:
    """指数移动平均，首值用 SMA 初始化。"""
    n = len(closes)
    if n < period or period <= 0:
        return [None] * n
    result: list[float | None] = [None] * (period - 1)
    multiplier = 2.0 / (period + 1)
    prev_ema = sum(closes[:period]) / period
    result.append(round(prev_ema, 4))
    for i in range(period, n):
        prev_ema = closes[i] * multiplier + prev_ema * (1 - multiplier)
        result.append(round(prev_ema, 4))
    return result


def _stddev(values: list[float], mean: float) -> float:
    """总体标准差。"""
    if len(values) == 0:
        return 0.0
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(variance)


# ──────────────────────────────────────────────────────────────────
# MCP 工具注册
# ──────────────────────────────────────────────────────────────────

def register(mcp: FastMCP):
    """Register technical indicator calculation tools with the MCP server."""

    @mcp.tool()
    async def calculate_ma_ema(
        closes: list[float],
        period: int = 20,
        type: str = "both",
    ) -> str:
        """
        计算 MA(简单移动平均) / EMA(指数移动平均) 均线。

        与 Excel/通达信计算结果一致。前 period-1 个数据点返回 null。

        Args:
            closes: 收盘价数组，如 [10.5, 10.8, 11.2, ...]
            period: 计算周期，默认20
            type: 计算类型 - "sma" | "ema" | "both"(默认，同时返回SMA和EMA)

        Returns:
            均线计算结果 (JSON):
            - ma: SMA 数组（type 为 sma 或 both 时返回）
            - ema: EMA 数组（type 为 ema 或 both 时返回）
            - period: 周期
            - data_points: 输入数据点数
            - valid_points: 有效计算点数（非 null）
        """
        try:
            if not closes or period <= 0:
                return error_response(
                    "参数错误: closes 不能为空，period 必须为正整数",
                    "calculate_ma_ema",
                )
            if type not in ("sma", "ema", "both"):
                return error_response(
                    f"参数错误: type 必须为 sma/ema/both，当前为 {type}",
                    "calculate_ma_ema",
                )

            result: dict[str, Any] = {
                "success": True,
                "period": period,
                "data_points": len(closes),
                "type": type,
            }
            if type in ("sma", "both"):
                ma_arr = _sma(closes, period)
                result["ma"] = ma_arr
                result["ma_valid_points"] = sum(1 for x in ma_arr if x is not None)
            if type in ("ema", "both"):
                ema_arr = _ema(closes, period)
                result["ema"] = ema_arr
                result["ema_valid_points"] = sum(1 for x in ema_arr if x is not None)

            return dict_to_json(result)
        except Exception as e:
            return error_response(f"MA/EMA 计算失败: {e}", "calculate_ma_ema")

    @mcp.tool()
    async def calculate_macd(
        closes: list[float],
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
    ) -> str:
        """
        计算 MACD 指标（DIF、DEA、MACD柱）。

        算法：
        - DIF = EMA(close, fast) - EMA(close, slow)
        - DEA = EMA(DIF, signal)
        - MACD柱 = 2 * (DIF - DEA)

        与通达信 MACD 计算结果一致。前 slow_period-1 个 DIF 为 null。

        Args:
            closes: 收盘价数组
            fast_period: 快线周期，默认12
            slow_period: 慢线周期，默认26
            signal_period: 信号线周期，默认9

        Returns:
            MACD 计算结果 (JSON):
            - dif: DIF 线数组
            - dea: DEA 信号线数组
            - macd: MACD 柱状图数组
            - fast_period / slow_period / signal_period: 周期参数
        """
        try:
            if not closes or len(closes) < slow_period:
                return error_response(
                    f"数据不足: 需要至少 {slow_period} 个数据点，当前 {len(closes)}",
                    "calculate_macd",
                )

            fast_ema = _ema(closes, fast_period)
            slow_ema = _ema(closes, slow_period)

            # 对齐两个 EMA 数组（slow_ema 比 fast_ema 多 slow_period-fast_period 个前导 null）
            offset = slow_period - fast_period
            dif: list[float | None] = [None] * (slow_period - 1)
            for i in range(slow_period - 1, len(closes)):
                f = fast_ema[i]
                s = slow_ema[i]
                if f is None or s is None:
                    dif.append(None)
                else:
                    dif.append(round(f - s, 4))

            # DEA = EMA(DIF, signal_period)，跳过前导 None
            dif_valid_start = slow_period - 1
            dif_valid = [v for v in dif[dif_valid_start:] if v is not None]
            dea_valid = _ema(dif_valid, signal_period)

            dea: list[float | None] = [None] * (dif_valid_start + signal_period - 1)
            dea.extend(dea_valid[signal_period - 1:] if len(dea_valid) >= signal_period else [])

            # MACD 柱 = 2 * (DIF - DEA)
            macd_bar: list[float | None] = []
            for i in range(len(dif)):
                d = dif[i]
                e = dea[i] if i < len(dea) else None
                if d is None or e is None:
                    macd_bar.append(None)
                else:
                    macd_bar.append(round(2 * (d - e), 4))

            return dict_to_json({
                "success": True,
                "dif": dif,
                "dea": dea,
                "macd": macd_bar,
                "fast_period": fast_period,
                "slow_period": slow_period,
                "signal_period": signal_period,
                "data_points": len(closes),
            })
        except Exception as e:
            return error_response(f"MACD 计算失败: {e}", "calculate_macd")

    @mcp.tool()
    async def calculate_kdj(
        highs: list[float],
        lows: list[float],
        closes: list[float],
        period: int = 9,
        k_period: int = 3,
        d_period: int = 3,
    ) -> str:
        """
        计算 KDJ 随机指标（K、D、J 值）。

        算法：
        - RSV = (close - lowest_low) / (highest_high - lowest_low) * 100
        - 初始 K = 50, 初始 D = 50
        - K = (2/3) * 前K + (1/3) * RSV
        - D = (2/3) * 前D + (1/3) * K
        - J = 3 * K - 2 * D

        与通达信 KDJ 计算结果一致。

        Args:
            highs: 最高价数组
            lows: 最低价数组
            closes: 收盘价数组
            period: RSV 周期，默认9
            k_period: K 平滑周期，默认3
            d_period: D 平滑周期，默认3

        Returns:
            KDJ 计算结果 (JSON):
            - k: K 值数组
            - d: D 值数组
            - j: J 值数组
            - period / k_period / d_period: 周期参数
        """
        try:
            if not (len(highs) == len(lows) == len(closes)):
                return error_response(
                    "参数错误: highs / lows / closes 长度必须相同",
                    "calculate_kdj",
                )
            if len(closes) < period:
                return error_response(
                    f"数据不足: 需要至少 {period} 个数据点，当前 {len(closes)}",
                    "calculate_kdj",
                )

            k_arr: list[float] = []
            d_arr: list[float] = []
            j_arr: list[float] = []
            prev_k = 50.0
            prev_d = 50.0

            for i in range(len(closes)):
                start = max(0, i - period + 1)
                ll = min(lows[start:i + 1])
                hh = max(highs[start:i + 1])
                den = hh - ll
                rsv = 50.0 if den == 0.0 else ((closes[i] - ll) / den * 100.0)

                prev_k = (2.0 / k_period) * prev_k + (1.0 / k_period) * rsv
                prev_d = (2.0 / d_period) * prev_d + (1.0 / d_period) * prev_k
                j_val = 3 * prev_k - 2 * prev_d

                k_arr.append(round(prev_k, 4))
                d_arr.append(round(prev_d, 4))
                j_arr.append(round(j_val, 4))

            return dict_to_json({
                "success": True,
                "k": k_arr,
                "d": d_arr,
                "j": j_arr,
                "period": period,
                "k_period": k_period,
                "d_period": d_period,
                "data_points": len(closes),
            })
        except Exception as e:
            return error_response(f"KDJ 计算失败: {e}", "calculate_kdj")

    @mcp.tool()
    async def calculate_rsi(
        closes: list[float],
        period: int = 14,
    ) -> str:
        """
        计算 RSI 相对强弱指数（Wilder 平滑法）。

        算法：
        - 计算每日涨跌幅
        - 分离上涨幅度和下跌幅度
        - Wilder 平滑平均：avg = (prev_avg * (period-1) + current) / period
        - RSI = 100 - 100 / (1 + avg_gain / avg_loss)

        与通达信 RSI 计算结果一致。前 period 个为 null。

        Args:
            closes: 收盘价数组
            period: 计算周期，默认14

        Returns:
            RSI 计算结果 (JSON):
            - rsi: RSI 值数组（前 period 个为 null）
            - period: 周期
            - data_points: 数据点数
        """
        try:
            if len(closes) < period + 1:
                return error_response(
                    f"数据不足: 需要至少 {period + 1} 个数据点，当前 {len(closes)}",
                    "calculate_rsi",
                )

            deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
            gains = [max(d, 0) for d in deltas]
            losses = [abs(min(d, 0)) for d in deltas]

            # 初始平均（简单平均）
            avg_gain = sum(gains[:period]) / period
            avg_loss = sum(losses[:period]) / period

            rsi_arr: list[float | None] = [None] * period
            # 第一个 RSI 值
            if avg_loss == 0:
                rsi_arr[period - 1] = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi_arr[period - 1] = round(100 - 100 / (1 + rs), 4)

            # Wilder 平滑
            for i in range(period, len(deltas)):
                avg_gain = (avg_gain * (period - 1) + gains[i]) / period
                avg_loss = (avg_loss * (period - 1) + losses[i]) / period
                if avg_loss == 0:
                    rsi_arr.append(100.0)
                else:
                    rs = avg_gain / avg_loss
                    rsi_arr.append(round(100 - 100 / (1 + rs), 4))

            return dict_to_json({
                "success": True,
                "rsi": rsi_arr,
                "period": period,
                "data_points": len(closes),
                "valid_points": sum(1 for x in rsi_arr if x is not None),
            })
        except Exception as e:
            return error_response(f"RSI 计算失败: {e}", "calculate_rsi")

    @mcp.tool()
    async def calculate_boll(
        closes: list[float],
        period: int = 20,
        k: float = 2.0,
    ) -> str:
        """
        计算布林带（BOLL）上轨、中轨、下轨。

        算法：
        - 中轨 = SMA(close, period)
        - 上轨 = 中轨 + k * 标准差
        - 下轨 = 中轨 - k * 标准差
        - 带宽 = (上轨 - 下轨) / 中轨
        - %B = (收盘价 - 下轨) / (上轨 - 下轨)

        与通达信 BOLL 计算结果一致。前 period-1 个为 null。

        Args:
            closes: 收盘价数组
            period: 计算周期，默认20
            k: 标准差倍数，默认2.0

        Returns:
            BOLL 计算结果 (JSON):
            - upper: 上轨数组
            - middle: 中轨数组
            - lower: 下轨数组
            - bandwidth: 带宽数组
            - percent_b: %B 数组
            - period / k: 参数
        """
        try:
            if len(closes) < period:
                return error_response(
                    f"数据不足: 需要至少 {period} 个数据点，当前 {len(closes)}",
                    "calculate_boll",
                )

            n = len(closes)
            upper: list[float | None] = [None] * (period - 1)
            middle: list[float | None] = [None] * (period - 1)
            lower: list[float | None] = [None] * (period - 1)
            bandwidth: list[float | None] = [None] * (period - 1)
            percent_b: list[float | None] = [None] * (period - 1)

            for i in range(period - 1, n):
                window = closes[i - period + 1:i + 1]
                mean = sum(window) / period
                std = _stddev(window, mean)
                mid = round(mean, 4)
                up = round(mean + k * std, 4)
                lo = round(mean - k * std, 4)
                upper.append(up)
                middle.append(mid)
                lower.append(lo)
                bandwidth.append(round((up - lo) / mid, 4) if mid != 0 else None)
                percent_b.append(
                    round((closes[i] - lo) / (up - lo), 4) if (up - lo) != 0 else None
                )

            return dict_to_json({
                "success": True,
                "upper": upper,
                "middle": middle,
                "lower": lower,
                "bandwidth": bandwidth,
                "percent_b": percent_b,
                "period": period,
                "k": k,
                "data_points": n,
            })
        except Exception as e:
            return error_response(f"BOLL 计算失败: {e}", "calculate_boll")

    @mcp.tool()
    async def calculate_atr(
        highs: list[float],
        lows: list[float],
        closes: list[float],
        period: int = 14,
    ) -> str:
        """
        计算 ATR 平均真实波幅。

        算法：
        - TR = max(high-low, |high-pre_close|, |low-pre_close|)
        - ATR = EMA(TR, period)

        与通达信 ATR 计算结果一致。前 period 个为 null。

        Args:
            highs: 最高价数组
            lows: 最低价数组
            closes: 收盘价数组
            period: 计算周期，默认14

        Returns:
            ATR 计算结果 (JSON):
            - atr: ATR 值数组
            - tr: TR 真实波幅数组（首个为 null）
            - period: 周期
            - data_points: 数据点数
        """
        try:
            if not (len(highs) == len(lows) == len(closes)):
                return error_response(
                    "参数错误: highs / lows / closes 长度必须相同",
                    "calculate_atr",
                )
            if len(closes) < period + 1:
                return error_response(
                    f"数据不足: 需要至少 {period + 1} 个数据点，当前 {len(closes)}",
                    "calculate_atr",
                )

            n = len(closes)
            # 第一个 TR 为 None（无前收盘）
            tr_arr: list[float | None] = [None]
            for i in range(1, n):
                tr1 = highs[i] - lows[i]
                tr2 = abs(highs[i] - closes[i - 1])
                tr3 = abs(lows[i] - closes[i - 1])
                tr_arr.append(round(max(tr1, tr2, tr3), 4))

            # ATR = EMA(TR, period)，从第1个TR开始计算（跳过None）
            tr_valid = [tr_arr[i] for i in range(1, n)]
            atr_valid = _ema(tr_valid, period)

            # ATR 前 period 个为 None（加上首个TR的None）
            atr_arr: list[float | None] = [None] * (period)  # 1 (TR None) + (period-1) (EMA warmup)
            atr_arr.extend(atr_valid[period - 1:] if len(atr_valid) >= period else [])

            return dict_to_json({
                "success": True,
                "atr": atr_arr,
                "tr": tr_arr,
                "period": period,
                "data_points": n,
                "valid_points": sum(1 for x in atr_arr if x is not None),
            })
        except Exception as e:
            return error_response(f"ATR 计算失败: {e}", "calculate_atr")
