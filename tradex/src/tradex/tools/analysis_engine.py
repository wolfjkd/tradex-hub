"""
Category 11: Technical Analysis Engine — 5 维度技术分析引擎。

为 AI Agent 提供标准化的技术分析服务，输入 OHLCV 数据，输出 5 维度分析结果。
五维度包括：均线系统、趋势分析、量价关系、筹码分布、形态识别。

设计原则：
  1. 维度解耦：5 个维度独立计算，单维度异常不影响其他维度
  2. 边界处理：数据不足时返回明确提示，不抛异常
  3. 统一精度：数值保留 4 位小数
  4. 无外部依赖：仅依赖 pandas，不依赖 TA-Lib / stockstats

Tools (共 1 个):
  analyze_technical - 5 维度技术分析（均线/趋势/量价/筹码/形态）
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pandas as pd
from mcp.server.fastmcp import FastMCP

from ..data_sources import get_router
from ..utils.cache import TTL_DAILY, cache
from ..utils.formatter import dict_to_json, error_response
from ..utils.symbol import normalize_symbol

_router = get_router()


# ──────────────────────────────────────────────────────────────────
# 5 维度技术分析引擎
# ──────────────────────────────────────────────────────────────────


class AnalysisEngine:
    """5 维度技术分析引擎。

    接收 OHLCV 数据 (pandas DataFrame)，提供均线系统、趋势分析、
    量价关系、筹码分布、形态识别 5 个维度的技术分析。

    Args:
        df: OHLCV DataFrame，需含 Date/Open/High/Low/Close/Volume 列。
        symbol: 股票代码（可选，用于结果标识）。
    """

    def __init__(self, df: pd.DataFrame, symbol: str = "") -> None:
        self.df = df.reset_index(drop=True)
        self.symbol = symbol

    def analyze_all(self) -> dict[str, Any]:
        """返回全部 5 维度分析结果。

        Returns:
            包含 symbol、数据概况、5 维度分析结果及汇总信号的字典。
        """
        n = len(self.df)
        last_date: str | None = None
        last_close: float | None = None
        if n > 0:
            if "Date" in self.df.columns:
                last_date = str(self.df["Date"].iloc[-1])[:10]
            if "Close" in self.df.columns:
                try:
                    last_close = round(float(self.df["Close"].iloc[-1]), 4)
                except (TypeError, ValueError):
                    last_close = None

        dimensions: dict[str, dict[str, Any]] = {
            "ma": self._analyze_ma(),
            "trend": self._analyze_trend(),
            "volume_price": self._analyze_volume_price(),
            "chip": self._analyze_chip(),
            "pattern": self._analyze_pattern(),
        }

        # 汇总关键信号，便于 AI Agent 快速决策
        signals: list[str] = []

        ma = dimensions["ma"]
        if ma.get("success"):
            alignment = ma.get("alignment", "")
            if alignment == "多头排列":
                signals.append("均线多头排列")
            elif alignment == "空头排列":
                signals.append("均线空头排列")
            for cs in ma.get("cross_signals", []):
                signals.append(f"{cs['short']}/{cs['long']}{cs['type']}")

        trend = dimensions["trend"]
        if trend.get("success"):
            signals.append(
                f"趋势{trend.get('trend', '')}({trend.get('strength_desc', '')})"
            )

        vp = dimensions["volume_price"]
        if vp.get("success"):
            if vp.get("is_abnormal"):
                signals.append("异常放量")
            # overall 已含"量价"前缀（量价同步/量价背离），直接使用
            overall = vp.get("overall", "")
            if overall:
                signals.append(overall)

        chip = dimensions["chip"]
        if chip.get("success"):
            pr = chip.get("profit_ratio")
            if pr is not None:
                if pr > 0.8:
                    signals.append("获利盘比例偏高")
                elif pr < 0.2:
                    signals.append("获利盘比例偏低(套牢盘多)")

        pattern = dimensions["pattern"]
        if pattern.get("success"):
            for p in pattern.get("patterns", []):
                signals.append(p["name"])

        return {
            "symbol": self.symbol,
            "data_points": n,
            "last_date": last_date,
            "last_close": last_close,
            "dimensions": dimensions,
            "summary": "；".join(signals) if signals else "无明显信号",
        }

    def _analyze_ma(self) -> dict[str, Any]:
        """均线系统分析：MA5/10/20/60 计算、多空排列判断、金叉/死叉检测。"""
        result: dict[str, Any] = {"dimension": "均线系统", "success": False}
        try:
            if "Close" not in self.df.columns:
                result["error"] = "缺少 Close 列"
                return result

            closes = self.df["Close"]
            n = len(closes)
            if n < 5:
                result["error"] = "数据不足，至少需要 5 个交易日"
                return result

            current_price = round(float(closes.iloc[-1]), 4)

            # 计算 MA5/10/20/60
            ma_periods = [5, 10, 20, 60]
            ma_values: dict[str, float | None] = {}
            ma_series: dict[int, pd.Series] = {}
            for p in ma_periods:
                if n >= p:
                    s = closes.rolling(p).mean()
                    ma_series[p] = s
                    tail = s.iloc[-1]
                    ma_values[f"ma{p}"] = (
                        round(float(tail), 4) if pd.notna(tail) else None
                    )
                else:
                    ma_values[f"ma{p}"] = None

            result["ma_values"] = ma_values
            result["current_price"] = current_price

            # 多空排列判断（需四条均线全部可用）
            alignment = "数据不足"
            if all(ma_values.get(f"ma{p}") is not None for p in ma_periods):
                ma_list = [ma_values[f"ma{p}"] for p in ma_periods]
                if ma_list[0] > ma_list[1] > ma_list[2] > ma_list[3]:
                    alignment = "多头排列"
                elif ma_list[0] < ma_list[1] < ma_list[2] < ma_list[3]:
                    alignment = "空头排列"
                else:
                    alignment = "交织排列"
            result["alignment"] = alignment

            # 金叉/死叉检测：扫描最近 5 个交易日
            cross_pairs = [(5, 10), (5, 20), (10, 20), (20, 60)]
            signals: list[dict[str, Any]] = []
            lookback = 5
            for short_p, long_p in cross_pairs:
                if short_p not in ma_series or long_p not in ma_series:
                    continue
                diff = (ma_series[short_p] - ma_series[long_p]).dropna()
                if len(diff) < 2:
                    continue
                check_n = min(lookback, len(diff) - 1)
                for j in range(check_n):
                    idx_curr = len(diff) - 1 - j
                    idx_prev = idx_curr - 1
                    if idx_prev < 0:
                        break
                    prev_d = float(diff.iloc[idx_prev])
                    curr_d = float(diff.iloc[idx_curr])
                    if prev_d <= 0 < curr_d:
                        signals.append({
                            "type": "金叉",
                            "short": f"MA{short_p}",
                            "long": f"MA{long_p}",
                            "days_ago": j,
                        })
                        break
                    elif prev_d >= 0 > curr_d:
                        signals.append({
                            "type": "死叉",
                            "short": f"MA{short_p}",
                            "long": f"MA{long_p}",
                            "days_ago": j,
                        })
                        break
            result["cross_signals"] = signals

            # 价格与 MA60 关系（牛熊分界参考）
            if ma_values.get("ma60") is not None:
                result["price_vs_ma60"] = (
                    "价格在 MA60 之上" if current_price > ma_values["ma60"]
                    else "价格在 MA60 之下"
                )

            result["success"] = True
        except Exception as e:
            result["error"] = f"均线分析失败: {e}"
        return result

    def _analyze_trend(self) -> dict[str, Any]:
        """趋势分析：上升/下降/震荡判断、趋势强度评分(0-100)。"""
        result: dict[str, Any] = {"dimension": "趋势分析", "success": False}
        try:
            if "Close" not in self.df.columns:
                result["error"] = "缺少 Close 列"
                return result

            closes = self.df["Close"]
            n = len(closes)
            if n < 10:
                result["error"] = "数据不足，至少需要 10 个交易日"
                return result

            # 使用最近 20 日（或全部数据）线性回归斜率判断趋势方向
            window = min(20, n)
            recent = closes.iloc[-window:].astype(float)

            x = list(range(window))
            x_mean = sum(x) / window
            y_mean = float(recent.mean())
            num = sum(
                (x[i] - x_mean) * (float(recent.iloc[i]) - y_mean)
                for i in range(window)
            )
            den = sum((x[i] - x_mean) ** 2 for i in range(window))
            slope = num / den if den != 0 else 0.0
            # 斜率标准化为日百分比（相对均价）
            slope_pct = slope / y_mean * 100 if y_mean != 0 else 0.0

            if slope_pct > 0.1:
                trend = "上升趋势"
            elif slope_pct < -0.1:
                trend = "下降趋势"
            else:
                trend = "震荡"
            result["trend"] = trend
            result["slope_pct"] = round(slope_pct, 4)

            # 趋势强度评分 (0-100)，基准 50
            score = 50.0

            # 1. 斜率贡献 (±25)
            score += max(-25.0, min(25.0, slope_pct * 50.0))

            # 2. 价格相对 MA20 偏离贡献 (±15)
            if n >= 20:
                ma20 = closes.rolling(20).mean().iloc[-1]
                if pd.notna(ma20) and float(ma20) != 0:
                    dev = (float(closes.iloc[-1]) - float(ma20)) / float(ma20) * 100
                    score += max(-15.0, min(15.0, dev * 3.0))

            # 3. 高低点结构贡献 (±10)
            if "High" in self.df.columns and "Low" in self.df.columns:
                highs = self.df["High"].iloc[-window:].astype(float)
                lows = self.df["Low"].iloc[-window:].astype(float)
                half = window // 2
                if half > 0:
                    first_high = float(highs.iloc[:half].max())
                    second_high = float(highs.iloc[half:].max())
                    first_low = float(lows.iloc[:half].min())
                    second_low = float(lows.iloc[half:].min())
                    if second_high > first_high and second_low > first_low:
                        score += 10.0  # 高低点同步抬高
                    elif second_high < first_high and second_low < first_low:
                        score -= 10.0  # 高低点同步降低

            score = max(0.0, min(100.0, score))
            result["strength_score"] = round(score, 2)

            if score >= 70:
                desc = "强势"
            elif score >= 55:
                desc = "偏强"
            elif score >= 45:
                desc = "中性"
            elif score >= 30:
                desc = "偏弱"
            else:
                desc = "弱势"
            result["strength_desc"] = desc

            result["success"] = True
        except Exception as e:
            result["error"] = f"趋势分析失败: {e}"
        return result

    def _analyze_volume_price(self) -> dict[str, Any]:
        """量价关系：量价同步/背离判断、异常放量检测。"""
        result: dict[str, Any] = {"dimension": "量价关系", "success": False}
        try:
            df = self.df
            if "Close" not in df.columns or "Volume" not in df.columns:
                result["error"] = "缺少 Close 或 Volume 列"
                return result

            n = len(df)
            if n < 6:
                result["error"] = "数据不足，至少需要 6 个交易日"
                return result

            closes = df["Close"].astype(float)
            volumes = df["Volume"].astype(float)

            # 最近 5 日逐日量价关系
            recent_n = min(5, n - 1)
            relations: list[dict[str, Any]] = []
            for i in range(n - recent_n, n):
                if i < 1:
                    continue
                price_chg = float(closes.iloc[i]) - float(closes.iloc[i - 1])
                vol_chg = float(volumes.iloc[i]) - float(volumes.iloc[i - 1])
                price_up = price_chg > 0
                vol_up = vol_chg > 0
                if price_up and vol_up:
                    rel = "量价齐升"
                elif not price_up and not vol_up:
                    rel = "量价齐跌"
                elif price_up and not vol_up:
                    rel = "价升量缩(背离)"
                else:
                    rel = "价跌量增(背离)"

                prev_close = float(closes.iloc[i - 1])
                prev_vol = float(volumes.iloc[i - 1])
                relations.append({
                    "date": str(df["Date"].iloc[i])[:10]
                    if "Date" in df.columns else str(i),
                    "relation": rel,
                    "price_change_pct": round(
                        price_chg / prev_close * 100, 4
                    ) if prev_close != 0 else None,
                    "volume_change_pct": round(
                        vol_chg / prev_vol * 100, 4
                    ) if prev_vol != 0 else None,
                })
            result["recent_relations"] = relations

            # 总体量价关系判断
            sync_count = sum(
                1 for r in relations if "齐升" in r["relation"] or "齐跌" in r["relation"]
            )
            divergence_count = len(relations) - sync_count
            result["overall"] = "量价同步" if sync_count >= divergence_count else "量价背离"
            result["sync_ratio"] = (
                round(sync_count / len(relations), 4) if relations else None
            )

            # 异常放量检测（对比 20 日均量）
            vol_window = min(20, n)
            avg_vol = float(volumes.iloc[-vol_window:].mean())
            latest_vol = float(volumes.iloc[-1])
            vol_ratio = latest_vol / avg_vol if avg_vol > 0 else 0.0
            result["avg_volume_20d"] = round(avg_vol, 2)
            result["latest_volume"] = round(latest_vol, 2)
            result["volume_ratio"] = round(vol_ratio, 4)
            result["is_abnormal"] = vol_ratio >= 2.0

            # 扫描最近 5 日异常放量记录
            abnormal: list[dict[str, Any]] = []
            for i in range(max(1, n - 5), n):
                v = float(volumes.iloc[i])
                ratio = v / avg_vol if avg_vol > 0 else 0.0
                if ratio >= 2.0:
                    abnormal.append({
                        "date": str(df["Date"].iloc[i])[:10]
                        if "Date" in df.columns else str(i),
                        "volume": round(v, 2),
                        "ratio": round(ratio, 4),
                        "level": "异常放量" if ratio >= 3.0 else "温和放量",
                    })
            result["abnormal_volume"] = abnormal

            result["success"] = True
        except Exception as e:
            result["error"] = f"量价分析失败: {e}"
        return result

    def _analyze_chip(self) -> dict[str, Any]:
        """筹码分布：筹码集中度、获利盘比例、支撑压力位（基于历史量价估算）。"""
        result: dict[str, Any] = {"dimension": "筹码分布", "success": False}
        try:
            df = self.df
            needed = {"High", "Low", "Close", "Volume"}
            if not needed.issubset(df.columns):
                result["error"] = "缺少 High/Low/Close/Volume 列"
                return result

            n = len(df)
            if n < 10:
                result["error"] = "数据不足，至少需要 10 个交易日"
                return result

            # 使用最近 60 日（或全部）数据估算筹码分布
            window = min(60, n)
            recent = df.iloc[-window:]
            typical_price = (
                recent["High"].astype(float)
                + recent["Low"].astype(float)
                + recent["Close"].astype(float)
            ) / 3.0
            volumes = recent["Volume"].astype(float)

            # 建立价格分箱（纯 Python，不依赖 numpy）
            price_min = float(recent["Low"].min())
            price_max = float(recent["High"].max())
            if price_max <= price_min:
                result["error"] = "价格区间过窄，无法分析筹码分布"
                return result

            n_bins = 30
            bin_width = (price_max - price_min) / n_bins
            bin_volumes = [0.0] * n_bins
            for tp, vol in zip(typical_price, volumes):
                idx = int((float(tp) - price_min) / bin_width)
                if idx >= n_bins:
                    idx = n_bins - 1
                elif idx < 0:
                    idx = 0
                bin_volumes[idx] += float(vol)

            total_vol = sum(bin_volumes)
            if total_vol <= 0:
                result["error"] = "成交量为零，无法分析筹码分布"
                return result

            current_price = float(df["Close"].iloc[-1])

            # 获利盘比例：当前价格以下的筹码占比
            profit_vol = 0.0
            for i in range(n_bins):
                bin_price = price_min + (i + 0.5) * bin_width
                if bin_price <= current_price:
                    profit_vol += bin_volumes[i]
            profit_ratio = profit_vol / total_vol
            result["profit_ratio"] = round(profit_ratio, 4)
            result["current_price"] = round(current_price, 4)

            # 筹码集中度：当前价格 ±10% 区间内的筹码占比
            lower_band = current_price * 0.9
            upper_band = current_price * 1.1
            concentrated_vol = 0.0
            for i in range(n_bins):
                bin_price = price_min + (i + 0.5) * bin_width
                if lower_band <= bin_price <= upper_band:
                    concentrated_vol += bin_volumes[i]
            concentration = concentrated_vol / total_vol
            result["concentration"] = round(concentration, 4)

            # 加权平均成本
            weighted_avg_cost = sum(
                (price_min + (i + 0.5) * bin_width) * bin_volumes[i]
                for i in range(n_bins)
            ) / total_vol
            result["avg_cost"] = round(weighted_avg_cost, 4)

            # 支撑位（当前价格下方筹码最密集处）/ 压力位（上方最密集处）
            support_vol = 0.0
            support_price = current_price
            resistance_vol = 0.0
            resistance_price = current_price
            for i in range(n_bins):
                bin_price = price_min + (i + 0.5) * bin_width
                if bin_price < current_price and bin_volumes[i] > support_vol:
                    support_vol = bin_volumes[i]
                    support_price = bin_price
                elif bin_price > current_price and bin_volumes[i] > resistance_vol:
                    resistance_vol = bin_volumes[i]
                    resistance_price = bin_price

            result["support_price"] = (
                round(support_price, 4) if support_vol > 0 else None
            )
            result["resistance_price"] = (
                round(resistance_price, 4) if resistance_vol > 0 else None
            )

            result["success"] = True
        except Exception as e:
            result["error"] = f"筹码分析失败: {e}"
        return result

    def _analyze_pattern(self) -> dict[str, Any]:
        """形态识别：双底/双顶、头肩顶/底等常见形态。"""
        result: dict[str, Any] = {"dimension": "形态识别", "success": False}
        try:
            df = self.df
            if "High" not in df.columns or "Low" not in df.columns:
                result["error"] = "缺少 High 或 Low 列"
                return result

            n = len(df)
            if n < 20:
                result["error"] = "数据不足，至少需要 20 个交易日"
                return result

            highs = df["High"].astype(float)
            lows = df["Low"].astype(float)
            current_price = float(df["Close"].iloc[-1]) if "Close" in df.columns else None

            # 寻找局部极值点（窗口=5）
            pw = 5
            raw_peaks: list[tuple[int, float]] = []
            raw_troughs: list[tuple[int, float]] = []
            for i in range(pw, n - pw):
                seg_high = highs.iloc[i - pw:i + pw + 1]
                seg_low = lows.iloc[i - pw:i + pw + 1]
                if float(highs.iloc[i]) >= float(seg_high.max()):
                    raw_peaks.append((i, float(highs.iloc[i])))
                if float(lows.iloc[i]) <= float(seg_low.min()):
                    raw_troughs.append((i, float(lows.iloc[i])))

            # 去重：相邻同向极值点间距需 >= pw，取最高/最低
            peaks = self._dedup_extrema(raw_peaks, pw, take_max=True)
            troughs = self._dedup_extrema(raw_troughs, pw, take_max=False)

            patterns: list[dict[str, Any]] = []
            tolerance = 0.03  # 价格相似度容差 3%

            # 双顶（M 顶）：最近 2 个峰值高度相近，中间有明显低谷
            if len(peaks) >= 2:
                p1_idx, p1_price = peaks[-2]
                p2_idx, p2_price = peaks[-1]
                ref = max(p1_price, p2_price)
                if ref > 0 and abs(p1_price - p2_price) / ref < tolerance:
                    mid_low = float(lows.iloc[p1_idx:p2_idx + 1].min())
                    neckline = min(p1_price, p2_price)
                    if neckline > 0 and (neckline - mid_low) / neckline > 0.03:
                        patterns.append({
                            "name": "双顶(M顶)",
                            "position": "顶部",
                            "peak1_price": round(p1_price, 4),
                            "peak2_price": round(p2_price, 4),
                            "neckline": round(mid_low, 4),
                            "signal": "看跌",
                        })

            # 头肩顶：最近 3 个峰值，中间最高，两肩相近
            if len(peaks) >= 3:
                s1_idx, s1_price = peaks[-3]
                h_idx, h_price = peaks[-2]
                s2_idx, s2_price = peaks[-1]
                shoulder_ref = max(s1_price, s2_price)
                if (
                    h_price > s1_price
                    and h_price > s2_price
                    and shoulder_ref > 0
                    and abs(s1_price - s2_price) / shoulder_ref < tolerance + 0.02
                    and (h_price - shoulder_ref) / shoulder_ref > 0.03
                ):
                    neckline = float(lows.iloc[s1_idx:s2_idx + 1].min())
                    patterns.append({
                        "name": "头肩顶",
                        "position": "顶部",
                        "left_shoulder": round(s1_price, 4),
                        "head": round(h_price, 4),
                        "right_shoulder": round(s2_price, 4),
                        "neckline": round(neckline, 4),
                        "signal": "看跌",
                    })

            # 双底（W 底）：最近 2 个谷值水平相近，中间有明显高峰
            if len(troughs) >= 2:
                t1_idx, t1_price = troughs[-2]
                t2_idx, t2_price = troughs[-1]
                ref = max(t1_price, t2_price)
                if ref > 0 and abs(t1_price - t2_price) / ref < tolerance:
                    mid_high = float(highs.iloc[t1_idx:t2_idx + 1].max())
                    neckline = max(t1_price, t2_price)
                    if neckline > 0 and (mid_high - neckline) / neckline > 0.03:
                        patterns.append({
                            "name": "双底(W底)",
                            "position": "底部",
                            "trough1_price": round(t1_price, 4),
                            "trough2_price": round(t2_price, 4),
                            "neckline": round(mid_high, 4),
                            "signal": "看涨",
                        })

            # 头肩底：最近 3 个谷值，中间最低，两肩相近
            if len(troughs) >= 3:
                s1_idx, s1_price = troughs[-3]
                h_idx, h_price = troughs[-2]
                s2_idx, s2_price = troughs[-1]
                shoulder_ref = min(s1_price, s2_price)
                if (
                    h_price < s1_price
                    and h_price < s2_price
                    and shoulder_ref > 0
                    and abs(s1_price - s2_price) / shoulder_ref < tolerance + 0.02
                    and (shoulder_ref - h_price) / shoulder_ref > 0.03
                ):
                    neckline = float(highs.iloc[s1_idx:s2_idx + 1].max())
                    patterns.append({
                        "name": "头肩底",
                        "position": "底部",
                        "left_shoulder": round(s1_price, 4),
                        "head": round(h_price, 4),
                        "right_shoulder": round(s2_price, 4),
                        "neckline": round(neckline, 4),
                        "signal": "看涨",
                    })

            result["patterns"] = patterns
            result["pattern_count"] = len(patterns)
            result["peaks_found"] = len(peaks)
            result["troughs_found"] = len(troughs)
            result["current_price"] = (
                round(current_price, 4) if current_price is not None else None
            )
            result["summary"] = (
                "、".join(p["name"] for p in patterns) if patterns
                else "未识别到明显形态"
            )
            result["success"] = True
        except Exception as e:
            result["error"] = f"形态识别失败: {e}"
        return result

    @staticmethod
    def _dedup_extrema(
        extrema: list[tuple[int, float]],
        min_gap: int,
        take_max: bool,
    ) -> list[tuple[int, float]]:
        """去重相邻极值点：间距不足 min_gap 时合并，保留更极端的值。

        Args:
            extrema: (index, price) 列表，按 index 升序。
            min_gap: 最小间距。
            take_max: True 时保留较高值（峰值），False 时保留较低值（谷值）。

        Returns:
            去重后的极值点列表。
        """
        filtered: list[tuple[int, float]] = []
        for idx, price in extrema:
            if not filtered or idx - filtered[-1][0] >= min_gap:
                filtered.append((idx, price))
            else:
                if take_max and price > filtered[-1][1]:
                    filtered[-1] = (idx, price)
                elif not take_max and price < filtered[-1][1]:
                    filtered[-1] = (idx, price)
        return filtered


# ──────────────────────────────────────────────────────────────────
# OHLCV 数据获取（via SmartRouter，不直接 import akshare/eltdx）
# ──────────────────────────────────────────────────────────────────


def _load_ohlcv(code: str, look_back_days: int) -> pd.DataFrame:
    """通过 SmartRouter 获取 OHLCV 数据（eltdx 主，akshare 备）。

    Args:
        code: 6 位股票代码。
        look_back_days: 回溯交易日数。

    Returns:
        含 Date/Open/High/Low/Close/Volume 列的 DataFrame（升序）。
    """
    end_date = datetime.now().strftime("%Y%m%d")
    # 额外缓冲 60 个交易日以保证 MA60 / 筹码分析等长周期指标可用
    fetch_trading_days = look_back_days + 60
    # 交易日转日历天（约 5/7 比例），额外 30 天节假日缓冲
    fetch_calendar_days = int(fetch_trading_days * 1.5) + 30
    start_date = (
        datetime.now() - timedelta(days=fetch_calendar_days)
    ).strftime("%Y%m%d")

    df, _src = _router.route(
        "historical_kline",
        symbol=code,
        period="daily",
        start_date=start_date,
        end_date=end_date,
        adjust="qfq",
    )

    if df is None or df.empty:
        raise ValueError(f"无法获取 {code} 的 OHLCV 数据")

    # 列名标准化（兼容东方财富中文列名与 eltdx/腾讯英文列名）
    col_map = {
        "日期": "Date", "开盘": "Open", "最高": "High",
        "最低": "Low", "收盘": "Close", "成交量": "Volume",
        "date": "Date", "open": "Open", "high": "High",
        "low": "Low", "close": "Close", "volume": "Volume",
    }
    df = df.rename(columns=col_map)
    needed = ["Date", "Open", "High", "Low", "Close", "Volume"]
    df = df[[c for c in needed if c in df.columns]]

    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"])

    # 确保数值列类型
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 按日期升序排列并重建索引
    if "Date" in df.columns:
        df = df.sort_values("Date").reset_index(drop=True)

    # 截取最近 look_back_days 个交易日（保留缓冲数据用于指标预热）
    if len(df) > look_back_days:
        df = df.iloc[-look_back_days:]

    return df


# ──────────────────────────────────────────────────────────────────
# MCP 工具注册
# ──────────────────────────────────────────────────────────────────


def register(mcp: FastMCP) -> None:
    """Register technical analysis engine tools with the MCP server."""

    @mcp.tool()
    async def analyze_technical(
        symbol: str,
        look_back_days: int = 30,
    ) -> str:
        """
        5 维度技术分析引擎（均线/趋势/量价/筹码/形态）。

        输入股票代码，自动获取 OHLCV 数据，输出 5 个维度的综合技术分析结果：
        1. 均线系统 — MA5/10/20/60、多空排列、金叉/死叉
        2. 趋势分析 — 上升/下降/震荡判断、趋势强度评分(0-100)
        3. 量价关系 — 量价同步/背离、异常放量检测
        4. 筹码分布 — 获利盘比例、筹码集中度、支撑压力位
        5. 形态识别 — 双底/双顶、头肩顶/底等常见形态

        Args:
            symbol: 6 位股票代码，如 "600519"。
            look_back_days: 回溯交易日数，默认 30。建议 >= 60 以支持 MA60 分析。

        Returns:
            5 维度技术分析结果 (JSON)，含数据概况、各维度详情及汇总信号。
        """
        symbol = normalize_symbol(symbol)

        if look_back_days <= 0:
            return error_response(
                "参数错误: look_back_days 必须为正整数",
                "analyze_technical",
            )

        cache_key = f"analyze_technical:{symbol}:{look_back_days}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            df = _load_ohlcv(symbol, look_back_days)
            if df is None or df.empty:
                return error_response(
                    f"无法获取 {symbol} 的 OHLCV 数据",
                    "analyze_technical",
                )

            engine = AnalysisEngine(df, symbol=symbol)
            result = engine.analyze_all()
            output = dict_to_json(result)
            cache.set(cache_key, output, TTL_DAILY)
            return output
        except Exception as e:
            return error_response(
                f"技术分析失败: {e}", "analyze_technical"
            )
