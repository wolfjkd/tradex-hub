"""
Local TDX Data Tools (V3.3.9)

Tools:
  get_local_kline   - 通达信本地日线（离线，不封 IP）
  get_local_minute  - 通达信本地分钟线（离线）

Data source: 通达信本地 vipdoc 二进制文件（.day/.lc5/.lc1），
非网络请求，网络全封/东财被封时仍可用。
本地数据读取能力源自 mootdx（github.com/mootdx/mootdx）。
数据新鲜度取决于通达信最后一次打开更新的时间。
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..data_sources.tdx_local import detect_tdx_dir, fetch_local_kline, fetch_local_minute
from ._mcp_serve import mcp_serve
from ..utils.formatter import df_to_json, dict_to_json, error_response
from ..utils.symbol import normalize_symbol


# （QI-ARCH-02 全量上提，2026-11-19：2 个工具体模块级化；拼接出口走
# dump=False build 内原样；「本地无数据」显式 error_response 保留。）


async def get_local_kline(symbol: str, count: int = 250) -> str:
    """
    获取通达信本地日线数据（离线，不封 IP）。**仅用于回测和历史分析，非盘中实时。**

    ⚠️ 数据新鲜度：本地日线最新到「上一个交易日收盘」，盘中（9:30-15:00）不含当天
    未完成的 K 线，当天数据需等收盘后通达信「盘后数据下载」才写入本地。
    盘中需要实时行情请改用 get_realtime_quote / get_intraday_data。

    读取本地通达信 vipdoc 目录的日线二进制文件，非网络请求，
    在网络全断或东财被封时仍可用（作为历史数据兜底）。

    Args:
        symbol: 6位股票代码，如 "600519"（贵州茅台）、"000001"（平安银行）
        count: 返回最近多少条，默认 250

    Returns:
        本地日线数据 (JSON)，含 date/open/high/low/close/volume/amount。
    """
    symbol = normalize_symbol(symbol)

    def _build() -> str:
        tdx_dir = detect_tdx_dir()
        df = fetch_local_kline(symbol)
        if df.empty:
            return error_response(
                f"本地无 {symbol} 日线数据（通达信目录: {tdx_dir or '未找到'}，检查是否下载过该股数据）",
                "get_local_kline",
            )
        df = df.tail(count)
        info = {"code": symbol, "tdx_dir": str(tdx_dir) if tdx_dir else "", "rows": len(df)}
        return dict_to_json(info) + "\n" + df_to_json(df)

    return mcp_serve("get_local_kline", _build, "读取本地日线失败", dump=False)


async def get_local_minute(symbol: str, period: int = 5, count: int = 200) -> str:
    """
    获取通达信本地分钟线数据（离线，不封 IP）。**仅用于回测和历史分析，非盘中实时。**

    ⚠️ 数据新鲜度：分钟线最新到「通达信最后一次下载的时间」，盘中不实时追加；
    且通达信默认只下载日线，分钟线需手动下载，否则本地无数据。

    Args:
        symbol: 6位股票代码，如 "600519"
        period: 周期，5=5分钟线（默认），1=1分钟线
        count: 返回最近多少条，默认 200

    Returns:
        本地分钟线数据 (JSON)，含 datetime/open/high/low/close/amount/volume。
    """
    symbol = normalize_symbol(symbol)

    def _build() -> str:
        df = fetch_local_minute(symbol, period=period)
        if df.empty:
            return error_response(
                f"本地无 {symbol} {period}分钟线数据（通达信未下载分钟线）",
                "get_local_minute",
            )
        df = df.tail(count)
        info = {"code": symbol, "period": period, "rows": len(df)}
        return dict_to_json(info) + "\n" + df_to_json(df)

    return mcp_serve("get_local_minute", _build, "读取本地分钟线失败", dump=False)


def register(mcp: FastMCP):
    """Register local TDX data tools with the MCP server.

    QI-ARCH-02 全量上提（2026-11-19）：2 工具体模块级，引用注册。"""
    for _fn in (
        get_local_kline,
        get_local_minute,
    ):
        mcp.tool()(_fn)
