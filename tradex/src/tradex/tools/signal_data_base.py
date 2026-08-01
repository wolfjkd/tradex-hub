"""
Signal Data — 信号数据基础子模块 (signal_data_base)。

原 signal_data.py 拆分自 v3.0.0，本子模块承载信号数据基础工具：
涨停归因、解禁日历、概念归属、一致预期、技术指标。

TradingAgents-astock 移植层基础工具集。

Tools (共 6 个):
  get_hot_stocks                - 涨停股票+主题归因（同花顺 editorial）
  get_lockup_expiry             - 限售解禁日历（东财 datacenter）
  get_concept_attribution       - 个股概念板块归属（东财 push2delay）
  get_profit_forecast           - 一致预期EPS/Forward PE/PEG（同花顺）
  get_technical_indicator       - 技术指标计算 MACD/RSI/Boll（stockstats）
  list_technical_indicators     - 列出所有支持的技术指标及说明
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

from mcp.server.fastmcp import FastMCP

from ..utils.cache import TTL_DAILY, cache
from ..utils.formatter import error_response, dict_to_json
from ..utils.symbol import normalize_symbol

# Import astock_signals modules from Hub src/

from astock_signals import (  # noqa: E402
    get_hot_stocks_json,
    get_lockup_expiry_json,
    get_concept_blocks_json,
    get_supported_indicators,
    get_indicator_description,
)


def register(mcp: FastMCP):
    """Register signal data base tools with the MCP server."""

    @mcp.tool()
    async def get_hot_stocks(date: str = "") -> str:
        """
        获取涨停股票及主题归因（同花顺 editorial 人工标注）。

        返回当日涨停股票列表，含人工标注的上涨原因标签（如"算力租赁+AI政务"），
        以及主题频次统计。

        Args:
            date: 日期 YYYY-MM-DD，空字符串默认今天。

        Returns:
            涨停股票列表及主题归因 (JSON)，含股票代码/名称/涨幅/换手率/
            成交额/DDE净量/原因标签，以及主题频次 top20。
        """
        cache_key = f"hot_stocks:{date or 'today'}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            result = get_hot_stocks_json(date)
            output = dict_to_json(result)

            if len(result.get("stocks", [])) > 0:
                cache.set(cache_key, output, TTL_DAILY)

            return output
        except Exception as e:
            return error_response(
                f"获取涨停归因数据失败: {e}", "get_hot_stocks"
            )

    @mcp.tool()
    async def get_lockup_expiry(
        symbol: str,
        trade_date: str = "",
        forward_days: int = 90,
    ) -> str:
        """
        获取个股限售解禁日历。

        包含历史解禁记录和未来待解禁安排，自动计算累计解禁占比并提示风险。

        Args:
            symbol: 6位股票代码，如 "000858"。
            trade_date: 参考日期 YYYY-MM-DD，空字符串默认今天。
            forward_days: 向前查询天数，默认90天。

        Returns:
            解禁日历 (JSON)，含历史记录和待解禁列表，以及风险提示。
        """
        symbol = normalize_symbol(symbol)
        if not trade_date or trade_date.strip() == "":
            trade_date = datetime.now().strftime("%Y-%m-%d")

        cache_key = f"lockup:{symbol}:{trade_date}:{forward_days}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            data = get_lockup_expiry_json(symbol, trade_date, forward_days)
            output = dict_to_json(data)
            cache.set(cache_key, output, TTL_DAILY)
            return output
        except Exception as e:
            return error_response(
                f"获取解禁日历失败: {e}", "get_lockup_expiry"
            )

    @mcp.tool()
    async def get_concept_attribution(symbol: str) -> str:
        """
        获取个股所属概念/行业/地域板块。

        显示股票归属于哪些概念板块、行业分类和地域板块，
        每个板块含当日涨跌幅。主力源：东方财富，备用源：百度股市通。

        Args:
            symbol: 6位股票代码，如 "688017"。

        Returns:
            概念归属数据 (JSON)，含概念/行业/地域三个维度的板块列表。
        """
        symbol = normalize_symbol(symbol)
        cache_key = f"concept_attribution:{symbol}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            data = get_concept_blocks_json(symbol)
            output = dict_to_json(data)
            if data.get("source"):
                cache.set(cache_key, output, TTL_DAILY)
            return output
        except Exception as e:
            return error_response(
                f"获取概念归属失败: {e}", "get_concept_attribution"
            )

    @mcp.tool()
    async def get_profit_forecast(symbol: str) -> str:
        """
        获取分析师一致预期EPS及Forward PE/PEG估值。

        基于同花顺分析师一致预期数据，计算Forward PE、PEG、
        以及PE消化年限（PEG估值框架）。

        Args:
            symbol: 6位股票代码，如 "600519"。

        Returns:
            一致预期数据 (JSON)，含FY年份/EPS均值/预测机构数/
            Forward PE/PEG/PE消化年限。
        """
        import math
        import re

        symbol = normalize_symbol(symbol)
        cache_key = f"profit_forecast:{symbol}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            code = symbol
            url = f"https://basic.10jqka.com.cn/new/{code}/worth.html"
            import requests as _rq
            _headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36"
                ),
                "Referer": "https://basic.10jqka.com.cn/",
            }
            resp = _rq.get(url, headers=_headers, timeout=15)
            resp.encoding = "gbk"
            html = resp.text

            # --- Step 1: Find EPS forecast <thead> + <tbody> ---
            # The EPS table has <thead> with columns: 年度, 预测机构数, 最小值, 均值, 最大值, 行业平均数
            thead_pat = re.compile(
                r"<thead[^>]*>\s*<tr>\s*<th>\s*年度\s*</th>\s*"
                r"<th>\s*预测机构数\s*</th>.*?</thead>",
                re.DOTALL,
            )
            thead_m = thead_pat.search(html)
            if not thead_m:
                return error_response(
                    f"{symbol} 无分析师一致预期数据（找不到EPS预测表头）",
                    "get_profit_forecast",
                )

            # Find next <tbody> after the <thead>
            tbody_pat = re.compile(r"<tbody[^>]*>(.*?)</tbody>", re.DOTALL)
            tbody_m = tbody_pat.search(html, thead_m.end())
            if not tbody_m:
                return error_response(
                    f"{symbol} 无分析师一致预期数据（找不到EPS预测表体）",
                    "get_profit_forecast",
                )

            tbody_html = tbody_m.group(1)

            # Parse each row: <tr>...<th>YEAR</th><td...>N1</td><td>N2</td>...
            row_pat = re.compile(
                r"<tr[^>]*>\s*<th[^>]*>\s*(\d{4})\s*</th>\s*"
                r"<td[^>]*>\s*(\d+)\s*</td>\s*"        # 预测机构数
                r"<td[^>]*>\s*([\d.]+)\s*</td>\s*"      # 最小值
                r"<td[^>]*>\s*([\d.]+)\s*</td>\s*"      # 均值
                r"<td[^>]*>\s*([\d.]+)\s*</td>\s*"      # 最大值
                r"<td[^>]*>\s*([\d.]+)\s*</td>"         # 行业平均数
                r".*?</tr>",
                re.DOTALL,
            )

            eps_by_year: dict[str, float] = {}
            forecast_rows: list[dict] = []
            for rm in row_pat.finditer(tbody_html):
                fy = rm.group(1)
                analysts = int(rm.group(2))
                eps_min = rm.group(3)
                eps_mean = float(rm.group(4))
                eps_max = rm.group(5)
                industry_avg = rm.group(6)

                entry = {
                    "year": fy,
                    "analysts": analysts,
                    "eps_min": eps_min,
                    "eps_mean": eps_mean,
                    "eps_max": eps_max,
                    "industry_average": industry_avg,
                    "low_coverage_warning": analysts < 3,
                }
                forecast_rows.append(entry)
                if analysts > 0:
                    eps_by_year[fy] = eps_mean

            if not forecast_rows:
                return error_response(
                    f"{symbol} 无分析师一致预期数据", "get_profit_forecast"
                )

            # --- Step 2: Extract summary text from <p class="tip"> ---
            tip_pat = re.compile(
                r'<p[^>]*class="tip[^"]*"[^>]*>(.*?)</p>', re.DOTALL
            )
            tip_m = tip_pat.search(html, thead_m.start() - 2000, thead_m.start())
            summary_text = ""
            if tip_m:
                summary_text = re.sub(r"<[^>]+>", "", tip_m.group(1)).strip()

            # --- Step 3: Get current price for forward valuation ---
            result = {
                "symbol": symbol,
                "source": "同花顺 analyst consensus",
                "summary": summary_text,
                "forecasts": forecast_rows,
            }

            try:
                import urllib.request as _ur
                prefix = "sh" if code.startswith("6") else "sz"
                quote_url = f"https://qt.gtimg.cn/q={prefix}{code}"
                req = _ur.Request(quote_url)
                req.add_header("User-Agent", "Mozilla/5.0")
                quote_resp = _ur.urlopen(req, timeout=5)
                raw = quote_resp.read().decode("gbk")
                vals = raw.split('"')[1].split("~") if '"' in raw else []
                if len(vals) >= 53:
                    price = float(vals[3]) if vals[3] else 0
                    pe_ttm = float(vals[39]) if vals[39] else 0
                    result["price"] = price
                    result["pe_ttm"] = pe_ttm

                    years_sorted = sorted(eps_by_year.keys())
                    if years_sorted and eps_by_year.get(years_sorted[0], 0) > 0:
                        eps_cur = eps_by_year[years_sorted[0]]
                        fwd_pe = round(price / eps_cur, 1)
                        result["forward_pe"] = fwd_pe
                        result["forward_pe_year"] = years_sorted[0]

                        if (
                            len(years_sorted) >= 2
                            and eps_by_year.get(years_sorted[1], 0) > 0
                        ):
                            eps_next = eps_by_year[years_sorted[1]]
                            cagr = eps_next / eps_cur - 1
                            if cagr > 0:
                                peg = round(fwd_pe / (cagr * 100), 2)
                                result["peg"] = peg
                                result["eps_cagr"] = round(cagr * 100, 1)
                                if fwd_pe > 30:
                                    digest = round(
                                        math.log(fwd_pe / 30) / math.log(1 + cagr), 1
                                    )
                                    result["pe_digestion_years"] = digest
                            else:
                                result["peg"] = None
                                result["eps_cagr"] = round(cagr * 100, 1)
                                result["peg_note"] = (
                                    "EPS declining, PEG not applicable"
                                )
            except Exception as e:
                result["valuation_note"] = f"Forward valuation unavailable: {e}"

            output = dict_to_json(result)
            cache.set(cache_key, output, TTL_DAILY)
            return output

        except Exception as e:
            return error_response(
                f"获取一致预期失败: {e}", "get_profit_forecast"
            )

    @mcp.tool()
    async def get_technical_indicator(
        symbol: str,
        indicator: str,
        curr_date: str = "",
        look_back_days: int = 30,
    ) -> str:
        """
        计算个股技术指标。

        支持 MACD、RSI、布林带、ATR、SMA、EMA、VWMA、MFI 等 13 种常用指标。
        底层使用 stockstats 标准库计算，数据源为 AKShare（东方财富）OHLCV。

        Args:
            symbol: 6位股票代码，如 "600519"。
            indicator: 指标名称，可选: macd, macds, macdh, rsi,
                       boll, boll_ub, boll_lb, atr, vwma, mfi,
                       close_50_sma, close_200_sma, close_10_ema。
            curr_date: 参考日期 YYYY-MM-DD，空字符串默认今天。
            look_back_days: 回溯天数，默认30天。

        Returns:
            技术指标值 (JSON)，含日期和指标值列表。
        """
        import json as _json

        symbol = normalize_symbol(symbol)
        if not curr_date or curr_date.strip() == "":
            curr_date = datetime.now().strftime("%Y-%m-%d")

        if indicator not in get_supported_indicators():
            return error_response(
                f"不支持的指标 '{indicator}'。可选: {get_supported_indicators()}",
                "get_technical_indicator",
            )

        cache_key = f"indicator:{symbol}:{indicator}:{curr_date}:{look_back_days}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            from astock_signals.indicators import calculate_indicators, _load_ohlcv

            # Load OHLCV data
            df = _load_ohlcv(symbol, curr_date, source="akshare")
            result_df = calculate_indicators(df, indicator, look_back_days)

            if result_df.empty:
                return error_response(
                    f"无 {indicator} 数据 ({symbol})", "get_technical_indicator"
                )

            data = {
                "symbol": symbol,
                "indicator": indicator,
                "indicator_desc": get_indicator_description(indicator),
                "curr_date": curr_date,
                "look_back_days": look_back_days,
                "values": [],
            }
            for _, row in result_df.iterrows():
                data["values"].append({
                    "date": str(row["Date"])[:10],
                    "value": row[indicator],
                })

            output = _json.dumps(data, ensure_ascii=False)
            cache.set(cache_key, output, TTL_DAILY)
            return output

        except Exception as e:
            return error_response(
                f"计算技术指标失败: {e}", "get_technical_indicator"
            )

    @mcp.tool()
    async def list_technical_indicators() -> str:
        """
        列出所有支持的技术指标及其说明。

        Returns:
            指标列表 (JSON)，含指标名称和中文说明。
        """
        result = []
        for name in get_supported_indicators():
            result.append({
                "name": name,
                "description": get_indicator_description(name),
            })
        return dict_to_json(result)
