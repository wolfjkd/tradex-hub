"""news_service：新闻/公告类业务逻辑层（工单 06 抽出）。

从 tools/news_events.py 的 @mcp.tool() 装饰器内抽出 3 个核心业务函数：
- get_stock_news（个股新闻）
- get_company_announcements（公司公告）
- search_news（关键词搜索）

news_events.py 还有 12+ 个其它工具（telegraph/calendar/sentiment/futures_news/
hot_rank/hot_keywords/xueqiu_hot/fund_hold/hot_search/wencai_query/wencai_news
等），暂不抽层（不在工单 06 范围）。
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from ..data_sources import get_router
from ..utils.cache import TTL_DAILY, TTL_REALTIME, cache
from ..utils.formatter import df_to_json, df_to_records, slim_df
from ..utils.symbol import normalize_symbol

logger = logging.getLogger(__name__)
_router = get_router()


def _df_to_records(df: pd.DataFrame, max_rows: int | None = None) -> list[dict]:
    return df_to_records(df, max_rows=max_rows)


# 各新闻子源列名不一致，按语义归一到统一字段（顺序即优先级）
_NEWS_TITLE_ALIASES = ("标题", "新闻标题", "名称")
_NEWS_TIME_ALIASES = ("发布时间", "时间")
_NEWS_DATE_ALIASES = ("发布日期", "日期")
_NEWS_SOURCE_ALIASES = ("文章来源", "来源")
_NEWS_URL_ALIASES = ("新闻链接", "链接", "url", "URL")
_NEWS_SUMMARY_ALIASES = ("内容", "新闻内容", "摘要", "说明")


_SOURCE_TAG_COL = "_tradex_来源"


def _tag_source(df: pd.DataFrame, source: str) -> pd.DataFrame:
    """给子源加上来源标记列。

    瘦身会丢掉原始宽表，来源也随之丢失；在合并前打一列标记，
    归一后就能填进 来源 字段，不至于让调用方分不清新闻出自哪家。
    """
    tagged = df.copy()
    tagged[_SOURCE_TAG_COL] = str(source or "")
    return tagged


def _first_text(record: dict, aliases: tuple[str, ...]) -> str:
    """按别名顺序取第一个非空文本值，顺手过滤 NaN/NaT 的字符串残留。"""
    for key in aliases:
        value = record.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text and text.lower() not in ("nan", "nat", "none"):
            return text
    return ""


def _unify_news_record(record: dict) -> dict:
    """把任意子源的一行归一成统一的 5 字段。

    输出字段固定为 标题/时间/来源/链接/摘要 —— 不再输出源表里的其余 40 列。
    """
    time_text = _first_text(record, _NEWS_TIME_ALIASES)
    date_text = _first_text(record, _NEWS_DATE_ALIASES)

    if time_text and len(time_text) >= 16 and "-" in time_text:
        stamp = time_text                      # 已是完整时间戳（新浪/期货）
    elif date_text and time_text:
        stamp = f"{date_text} {time_text}"     # 财联社：日期与时刻分两列
    else:
        stamp = time_text or date_text

    # 去掉 ISO 的 T 与 +08:00 尾巴，统一成 "YYYY-MM-DD HH:MM:SS" 便于阅读与比较
    if stamp:
        stamp = stamp.replace("T", " ").split("+")[0].strip()
        if stamp.endswith("Z"):
            stamp = stamp[:-1].strip()
        stamp = stamp[:19] if len(stamp) >= 19 else stamp

    return {
        "标题": _first_text(record, _NEWS_TITLE_ALIASES),
        "时间": stamp,
        "来源": _first_text(record, _NEWS_SOURCE_ALIASES)
        or _first_text(record, (_SOURCE_TAG_COL,)),
        "链接": _first_text(record, _NEWS_URL_ALIASES),
        "摘要": _first_text(record, _NEWS_SUMMARY_ALIASES),
    }


def get_stock_news(symbol: str) -> dict[str, Any]:
    """个股相关新闻资讯。

    Args:
        symbol: 6 位股票代码。

    Returns:
        dict：含 news（list，最多 30 条，每条固定 5 字段：
        标题/时间/来源/链接/摘要）。

    Raises:
        Exception: 数据源异常。
    """
    symbol = normalize_symbol(symbol)

    def _factory() -> dict[str, Any]:
        df, _src = _router.route("news_data", symbol=symbol)
        # 与 search_news 用同一套归一：两个新闻工具的返回结构必须一致，
        # 否则调用方要按工具分别适配字段（2026-10-30 专项重构统一）
        records = [
            _unify_news_record(rec)
            for rec in _df_to_records(_tag_source(df, _src), max_rows=30)
        ]
        return {"symbol": symbol, "news": records, "source": _src}

    return cache.get_or_set(f"stock_news:{symbol}", _factory, TTL_REALTIME)


def get_company_announcements(symbol: str = "", num_results: int = 30) -> dict[str, Any]:
    """上市公司公告。

    Args:
        symbol: 6 位股票代码；为空则获取全市场最新公告。
        num_results: 最大返回条数，默认 30。

    Returns:
        dict：含 announcements（list）。

    Raises:
        Exception: 数据源异常。
    """
    if symbol:
        symbol = normalize_symbol(symbol)

    def _factory() -> dict[str, Any]:
        df, _src = _router.route("cninfo_announcement", symbol=symbol)
        df = df.head(num_results)
        records = _df_to_records(df)
        return {
            "symbol": symbol or "全市场",
            "announcements": records,
            "count": len(records),
            "source": _src,
        }

    return cache.get_or_set(f"announcements:{symbol}:{num_results}", _factory, TTL_DAILY)


def search_news(
    keyword: str, symbol: str = "", num_results: int = 20
) -> dict[str, Any]:
    """按关键词搜索财经新闻。

    纯新闻搜索，不含公告。多源聚合（财联社/新浪/百度交易提醒/期货新闻/百度热搜）。

    Args:
        keyword: 搜索关键词（多个用空格或逗号分隔）。
        symbol: 可选 6 位股票代码，限定搜索范围。
        num_results: 最大返回条数，默认 20。

    Returns:
        dict：含 keyword/news（list）。

    Raises:
        Exception: 数据源异常。
    """
    def _factory() -> dict[str, Any]:
        nonlocal symbol  # 工厂内归一化重赋值（闭包内赋值须显式声明）
        all_dfs: list[pd.DataFrame] = []

        if symbol:
            symbol = normalize_symbol(symbol)
            try:
                df, _src = _router.route("news_data", symbol=symbol)
                if df is not None and not df.empty:
                    all_dfs.append(_tag_source(df, _src))
            except Exception as exc:
                logger.debug("个股新闻源失败(%s): %s", symbol, exc)

        if not all_dfs:
            # 多源全市场
            for source_cmd in [
                ("telegraph_news", {"num_results": num_results}),
                ("sina_finance_news", {"num_results": 20}),
                ("futures_news", {"symbol": "全部"}),
                ("hot_search", {"symbol": "A股"}),
            ]:
                try:
                    route_type, kwargs = source_cmd
                    df, _src = _router.route(route_type, **kwargs)
                    if df is not None and not df.empty:
                        all_dfs.append(_tag_source(df, _src))
                except Exception as exc:
                    logger.debug("%s 源失败: %s", route_type, exc)
            # 百度交易提醒（多个 endpoint）
            try:
                for ep in ["suspend", "dividend", "report_time"]:
                    df, _src = _router.route("baidu_trade_notify", endpoint=ep, date="")
                    if df is not None and not df.empty:
                        all_dfs.append(_tag_source(df, _src))
            except Exception as exc:
                logger.debug("百度交易提醒源失败: %s", exc)

        if not all_dfs:
            return {"keyword": keyword, "symbol": symbol, "news": [], "count": 0}

        combined = pd.concat(all_dfs, ignore_index=True)

        # 各子源 schema 不同，直接 union 会得到 40+ 列、绝大多数为 NaN 的宽表
        # （单条约 500 字节无效负载，纯烧 LLM 上下文）。先归一到统一字段再过滤。
        records = [_unify_news_record(rec) for rec in _df_to_records(combined)]

        keywords = [
            kw.strip() for kw in keyword.replace(",", " ").replace("，", " ").split()
            if kw.strip()
        ]

        def _match(record: dict, kws: list[str]) -> bool:
            haystack = f"{record['标题']} {record['摘要']}".lower()
            return any(kw.lower() in haystack for kw in kws)

        matched = [r for r in records if _match(r, keywords)] if keywords else records
        # 过滤后为空 → 退回未过滤结果（宁可给全量，也不返回空列表让上层误判无新闻）
        news = (matched or records)[:num_results]

        return {
            "keyword": keyword,
            "symbol": symbol,
            "news": news,
            "count": len(news),
        }

    return cache.get_or_set(
        f"search_news:{keyword}:{symbol}:{num_results}", _factory, TTL_REALTIME
    )


def get_financial_calendar(date: str = "") -> pd.DataFrame | None:
    """财报披露时间表 + 百度经济数据日历（双源聚合编排，QI-ARCH-14 票 13
    自 tools/news_events.py 上收；date_cols 关键词猜测过滤逻辑同批收进）。

    双源：
      Source 1: 财报披露时间（news_data/stock_report_disclosure，akshare 不传
        period 避免格式错误）；
      Source 2: 百度经济数据日历（baidu_economic_calendar）。
    日期后过滤：各源独立过滤后合并（避免 2022 年旧数据拖垮百度经济日历）。

    缓存语义（裁决③统一，2026-11-22）：get_or_set 对象缓存——factory 返回
    合并后 DataFrame 直存（含空 df：与原「过滤后全丢弃 → set 空串」一致），
    None（两源均无数据）不缓存，与原「早退空态先于 set」等价。出口
    df_to_json(max_rows=50) 确定性重放，与原串缓存逐路径等价。

    Args:
        date: 查询日期，格式 "YYYYMMDD"。默认为空获取最新一期。

    Returns:
        合并过滤后的 DataFrame（可能为空 df）；None：两源均无数据（调用方
        重建空态）。
    """
    def _factory() -> pd.DataFrame | None:
        all_dfs: list[pd.DataFrame] = []
        # Source 1: 财报披露时间（akshare 不传 period，避免格式错误）
        try:
            df1, _src1 = _router.route("news_data", endpoint="stock_report_disclosure")
            if df1 is not None and not df1.empty:
                all_dfs.append(df1)
        except Exception as exc:
            # em_news_direct 无 symbol 时会失败，自动降级到 akshare
            logger.debug("财报披露源失败: %s", exc)
        # Source 2: 百度经济数据日历（v3.3.0 新增）
        try:
            df2, _src2 = _router.route("baidu_economic_calendar", date=date)
            if df2 is not None and not df2.empty:
                all_dfs.append(df2)
        except Exception as exc:
            logger.debug("百度经济日历源失败: %s", exc)

        if not all_dfs:
            return None  # 两源均无数据：不缓存（原态早退空串先于 set）

        # 日期后过滤：各源独立过滤后合并（避免2022年旧数据拖垮百度经济日历）
        if date:
            date_fmt = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
            filtered_dfs = []
            for df in all_dfs:
                date_cols = [
                    c for c in df.columns
                    if any(k in c for k in ["日期", "date", "Date", "时间", "披露", "预约", "变更", "首次", "实际"])
                ]
                matched = False
                for col in date_cols:
                    try:
                        mask = df[col].astype(str).str.contains(date_fmt, na=False)
                        if not mask.any():
                            mask = df[col].astype(str).str.contains(date, na=False)
                        if mask.any():
                            filtered_dfs.append(df[mask])
                            matched = True
                            break
                    except Exception:
                        continue
                # 如果该源没有匹配数据的列，全量保留（如百度经济日历的日期列不在 date_cols 里）
                if not matched:
                    # 尝试正则匹配所有列
                    for col in df.columns:
                        try:
                            mask = df[col].astype(str).str.contains(date_fmt, na=False)
                            if mask.any():
                                filtered_dfs.append(df[mask])
                                matched = True
                                break
                        except Exception:
                            continue
                    if not matched:
                        pass  # 无匹配，丢弃该源
            combined = pd.concat(filtered_dfs, ignore_index=True) if filtered_dfs else pd.DataFrame()
        else:
            combined = pd.concat(all_dfs, ignore_index=True)
            combined = slim_df(combined)

        return combined

    return cache.get_or_set(f"fin_calendar:{date}", _factory, TTL_DAILY)
