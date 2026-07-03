"""
Category 9: Signal Data — A-stock signal/event tools (V0.8).

TradingAgents-astock 移植层 + 品种扩展层。
补齐 Hub 在涨停归因、解禁日历、概念归属、一致预期、技术指标、
北向资金、个股资金流、龙虎榜、行业对比 9 个维度的数据短板。
V0.8 新增 ETF 和可转债 2 个品种的数据接口。

Tools (共 14 个，cn-financial-mcp 总计 61 个):
  48. get_hot_stocks                - 涨停股票+主题归因（同花顺 editorial）
  49. get_lockup_expiry             - 限售解禁日历（东财 datacenter）
  50. get_concept_attribution       - 个股概念板块归属（东财 push2delay）
  51. get_profit_forecast           - 一致预期EPS/Forward PE/PEG（同花顺）
  52. get_technical_indicator       - 技术指标计算 MACD/RSI/Boll（stockstats）
  53. list_technical_indicators     - 列出所有支持的技术指标及说明
  54. get_northbound_flow_signal    - 北向资金流向（同花顺 hsgtApi，astock_signals）
  55. get_fund_flow_signal          - 个股资金流向（东财 push2，astock_signals）
  56. get_dragon_tiger_signal       - 龙虎榜席位明细（东财 datacenter，astock_signals）
  57. get_industry_comparison_signal - 行业横向对比排名（东财 push2，astock_signals）
  58. get_etf_realtime_data         - ETF实时行情（AKShare fund_etf_spot_em）
  59. get_etf_kline_data            - ETF历史K线（AKShare fund_etf_hist_em）
  60. get_cb_realtime_data          - 可转债实时行情（AKShare bond_zh_cov）
  61. get_cb_value_analysis_data    - 可转债价值分析/转股溢价率（AKShare bond_zh_cov_value_analysis）
"""

from __future__ import annotations

import json
import sys
import os
from datetime import datetime

import akshare as ak
import pandas as pd
from mcp.server.fastmcp import FastMCP

from ..utils.cache import TTL_DAILY, TTL_REALTIME, cache
from ..utils.formatter import df_to_json, error_response, dict_to_json
from ..utils.symbol import normalize_symbol

# Import astock_signals modules from Hub src/
_HUB_SRC = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "src")
)
if _HUB_SRC not in sys.path:
    sys.path.insert(0, _HUB_SRC)

from astock_signals import (  # noqa: E402
    get_hot_stocks_json,
    get_lockup_expiry_json,
    get_concept_blocks_json,
    get_indicators_text,
    get_supported_indicators,
    get_indicator_description,
    get_northbound_flow_json,
    get_fund_flow_json,
    get_dragon_tiger_board_json,
    get_industry_comparison_json,
    get_etf_realtime_json,
    get_etf_kline_json,
    get_cb_realtime_json,
    get_cb_value_analysis_json,
    get_limit_up_board_json,
    get_board_sentiment_json,
    get_limit_up_insight,
)


def register(mcp: FastMCP):
    """Register signal data tools with the MCP server."""

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

    # ----------------------------------------------------------------
    # V0.7: 4 tools from astock_signals (northbound/fund_flow/
    #       dragon_tiger/industry) — TradingAgents-astock 移植
    # 函数名带 _signal 后缀以避免与 market/industry 模块同名冲突
    # ----------------------------------------------------------------

    @mcp.tool()
    async def get_northbound_flow_signal(
        curr_date: str = "",
        include_history: bool = False,
    ) -> str:
        """
        获取北向资金流向（沪深股通）。

        数据源：同花顺 hsgtApi，提供实时分钟级沪股通+深股通累计净买入。
        附带本地缓存的历史每日收盘数据（最多20个交易日）。

        Args:
            curr_date: 日期 YYYY-MM-DD，空字符串默认今天。
            include_history: 是否包含历史每日数据（最近20个交易日）。

        Returns:
            北向资金数据 (JSON)，含实时数据点、收盘净流入、多空信号、历史数据。
        """
        cache_key = f"northbound:{curr_date or 'today'}:{include_history}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            result = get_northbound_flow_json(curr_date, include_history)
            output = dict_to_json(result)
            if result.get("realtime"):
                cache.set(cache_key, output, TTL_REALTIME)
            return output
        except Exception as e:
            return error_response(
                f"获取北向资金数据失败: {e}", "get_northbound_flow_signal"
            )

    @mcp.tool()
    async def get_fund_flow_signal(
        symbol: str,
        curr_date: str = "",
        include_history: bool = True,
    ) -> str:
        """
        获取个股资金流向（主力/大单/中单/小单/超大单净流入）。

        数据源：东财 push2（实时分钟级）+ push2his（历史日线20天）。
        可作为 AKShare 版 get_money_flow 的备用数据源。

        Args:
            symbol: 6位股票代码，如 "600519"。
            curr_date: 日期 YYYY-MM-DD，空字符串默认今天。
            include_history: 是否包含历史每日资金流（最近20个交易日）。

        Returns:
            资金流向数据 (JSON)，含实时分钟级数据、历史日线、多空信号。
        """
        symbol = normalize_symbol(symbol)
        cache_key = f"fund_flow_signal:{symbol}:{curr_date or 'today'}:{include_history}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            result = get_fund_flow_json(symbol, curr_date, include_history)
            output = dict_to_json(result)
            if result.get("realtime"):
                cache.set(cache_key, output, TTL_REALTIME)
            return output
        except Exception as e:
            return error_response(
                f"获取个股资金流向失败: {e}", "get_fund_flow_signal"
            )

    @mcp.tool()
    async def get_dragon_tiger_signal(
        symbol: str,
        trade_date: str = "",
        look_back_days: int = 30,
    ) -> str:
        """
        获取个股龙虎榜数据（上榜记录 + 买卖席位 + 机构动向）。

        数据源：东财 datacenter-web（直连，不依赖 AKShare）。
        可作为 AKShare 版 get_dragon_tiger 的备用数据源。

        Args:
            symbol: 6位股票代码，如 "000858"。
            trade_date: 参考日期 YYYY-MM-DD，空字符串默认今天。
            look_back_days: 向前查询天数，默认30天。

        Returns:
            龙虎榜数据 (JSON)，含上榜记录、买卖席位TOP5、机构动向。
        """
        symbol = normalize_symbol(symbol)
        cache_key = f"dragon_tiger_signal:{symbol}:{trade_date or 'today'}:{look_back_days}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            result = get_dragon_tiger_board_json(symbol, trade_date, look_back_days)
            output = dict_to_json(result)
            cache.set(cache_key, output, TTL_DAILY)
            return output
        except Exception as e:
            return error_response(
                f"获取龙虎榜数据失败: {e}", "get_dragon_tiger_signal"
            )

    @mcp.tool()
    async def get_industry_comparison_signal(
        symbol: str = "",
        trade_date: str = "",
        top_n: int = 20,
    ) -> str:
        """
        获取行业横向对比排名（全行业涨跌幅/上涨下跌家数/领涨股）。

        数据源：东财 push2 行业板块排名（直连，不依赖 AKShare）。

        Args:
            symbol: 6位股票代码（可选，用于定位所属行业）。
            trade_date: 日期 YYYY-MM-DD，空字符串默认今天。
            top_n: 显示前/后N个行业，默认20。

        Returns:
            行业排名数据 (JSON)，含行业名称/涨跌幅/上涨下跌家数/领涨股。
        """
        if symbol:
            symbol = normalize_symbol(symbol)
        cache_key = f"industry_cmp:{symbol or 'all'}:{trade_date or 'today'}:{top_n}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            result = get_industry_comparison_json(symbol, trade_date, top_n)
            output = dict_to_json(result)
            if result.get("industries"):
                cache.set(cache_key, output, TTL_DAILY)
            return output
        except Exception as e:
            return error_response(
                f"获取行业对比数据失败: {e}", "get_industry_comparison_signal"
            )

    # ----------------------------------------------------------------
    # V0.8: 品种扩展 — ETF + 可转债
    # ----------------------------------------------------------------

    @mcp.tool()
    async def get_etf_realtime_data(
        top_n: int = 50,
        sort_by: str = "成交额",
    ) -> str:
        """
        获取ETF实时行情（全部ETF按成交额/涨跌幅排序）。

        数据源：AKShare fund_etf_spot_em（东方财富）。
        提供 IOPV估值、折价率、换手率等ETF特有字段。

        Args:
            top_n: 返回前N只ETF，默认50。
            sort_by: 排序字段，默认成交额，可选涨跌幅。

        Returns:
            ETF实时行情 (JSON)，含代码/名称/价格/涨跌幅/IOPV/成交额。
        """
        cache_key = f"etf_realtime:{top_n}:{sort_by}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            result = get_etf_realtime_json(top_n, sort_by)
            output = dict_to_json(result)
            if result.get("etfs"):
                cache.set(cache_key, output, TTL_REALTIME)
            return output
        except Exception as e:
            return error_response(
                f"获取ETF实时行情失败: {e}", "get_etf_realtime_data"
            )

    @mcp.tool()
    async def get_etf_kline_data(
        symbol: str,
        period: str = "daily",
        start_date: str = "",
        end_date: str = "",
        adjust: str = "",
    ) -> str:
        """
        获取ETF历史K线数据。

        数据源：AKShare fund_etf_hist_em（东方财富）。
        支持日/周/月线，可选前复权/后复权/不复权。

        Args:
            symbol: ETF代码，如 "513500"。
            period: K线周期 daily/weekly/monthly，默认daily。
            start_date: 开始日期 YYYYMMDD，默认近1年。
            end_date: 结束日期 YYYYMMDD，默认今天。
            adjust: 复权方式（''不复权/'qfq'前复权/'hfq'后复权）。

        Returns:
            ETF K线数据 (JSON)，含日期/开高低收/成交量/成交额/涨跌幅。
        """
        cache_key = f"etf_kline:{symbol}:{period}:{start_date}:{end_date}:{adjust}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            result = get_etf_kline_json(symbol, period, start_date, end_date, adjust)
            output = dict_to_json(result)
            if result.get("klines"):
                cache.set(cache_key, output, TTL_DAILY)
            return output
        except Exception as e:
            return error_response(
                f"获取ETF K线失败: {e}", "get_etf_kline_data"
            )

    @mcp.tool()
    async def get_cb_realtime_data(
        top_n: int = 50,
        sort_by: str = "成交额",
    ) -> str:
        """
        获取可转债实时行情（全部可转债含转股溢价率）。

        数据源：AKShare bond_zh_cov（东方财富）。
        提供正股价/转股价/转股价值/转股溢价率/信用评级等可转债特有字段。

        Args:
            top_n: 返回前N只可转债，默认50。
            sort_by: 排序字段，默认成交额，可选转股溢价率。

        Returns:
            可转债实时行情 (JSON)，含代码/价格/正股价/转股价/溢价率/评级。
        """
        cache_key = f"cb_realtime:{top_n}:{sort_by}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            result = get_cb_realtime_json(top_n, sort_by)
            output = dict_to_json(result)
            if result.get("bonds"):
                cache.set(cache_key, output, TTL_REALTIME)
            return output
        except Exception as e:
            return error_response(
                f"获取可转债行情失败: {e}", "get_cb_realtime_data"
            )

    @mcp.tool()
    async def get_cb_value_analysis_data(
        symbol: str,
        days: int = 30,
    ) -> str:
        """
        获取可转债价值分析（历史转股溢价率/纯债价值/纯债溢价率曲线）。

        数据源：AKShare bond_zh_cov_value_analysis（东方财富）。
        用于分析可转债估值区间、溢价率趋势。

        Args:
            symbol: 可转债代码，如 "113527"。
            days: 返回最近N天数据，默认30天。

        Returns:
            可转债价值分析 (JSON)，含日期/收盘价/纯债价值/转股价值/溢价率。
        """
        cache_key = f"cb_value:{symbol}:{days}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            result = get_cb_value_analysis_json(symbol, days)
            output = dict_to_json(result)
            if result.get("history"):
                cache.set(cache_key, output, TTL_DAILY)
            return output
        except Exception as e:
            return error_response(
                f"获取可转债价值分析失败: {e}", "get_cb_value_analysis_data"
            )

    # ----------------------------------------------------------------
    # V0.9: 打板层 — 涨停四池 + 情绪速算（a-stock-data 融合）
    # ----------------------------------------------------------------

    @mcp.tool()
    async def get_limit_up_board(board_type: str = "zt") -> str:
        """
        获取涨停板数据（东财 push2ex）。

        支持四种类型：涨停池/炸板池/跌停池/昨日涨停池。

        Args:
            board_type: 板类型，可选 zt(涨停)/zb(炸板)/dt(跌停)/prev_zt(昨日涨停)。

        Returns:
            板数据 (JSON)，含股票列表及对应字段。
        """
        board_type = board_type.lower().strip()
        if board_type not in ["zt", "zb", "dt", "prev_zt"]:
            return error_response(
                f"无效的板类型: {board_type}。可选: zt, zb, dt, prev_zt",
                "get_limit_up_board",
            )

        cache_key = f"limit_up_board:{board_type}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            result = get_limit_up_board_json(board_type)
            output = dict_to_json(result)
            if result.get("data"):
                cache.set(cache_key, output, TTL_REALTIME)
            return output
        except Exception as e:
            return error_response(
                f"获取涨停板数据失败: {e}", "get_limit_up_board"
            )

    @mcp.tool()
    async def get_board_sentiment() -> str:
        """
        获取打板情绪数据（炸板率/连板梯队/晋级率）。

        综合涨停四池数据，计算市场打板情绪指标：炸板率、连板梯队、
        昨日涨停晋级率、平均溢价、热门题材等。

        Returns:
            打板情绪数据 (JSON)，含涨停数/炸板数/跌停数/炸板率/
            连板梯队/晋级率/平均溢价/热门题材。
        """
        cache_key = "board_sentiment"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            result = get_board_sentiment_json()
            output = dict_to_json(result)
            if not result.get("error"):
                cache.set(cache_key, output, TTL_REALTIME)
            return output
        except Exception as e:
            return error_response(
                f"获取打板情绪数据失败: {e}", "get_board_sentiment"
            )

    @mcp.tool()
    async def get_limit_up_insight(code: str = "") -> str:
        """
        获取涨停揭秘数据（同花顺）。

        包含涨停原因题材、封板成功率、板型（一字/换手/T字）、封单额等。

        Args:
            code: 股票代码（可选，不传则返回当日全部涨停揭秘）。

        Returns:
            涨停揭秘数据 (JSON)，含题材原因/封板成功率/板型/封单额/换手率。
        """
        cache_key = f"limit_up_insight:{code or 'all'}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            result = get_limit_up_insight(code)
            output = dict_to_json(result)
            if result.get("data"):
                cache.set(cache_key, output, TTL_DAILY)
            return output
        except Exception as e:
            return error_response(
                f"获取涨停揭秘数据失败: {e}", "get_limit_up_insight"
            )
