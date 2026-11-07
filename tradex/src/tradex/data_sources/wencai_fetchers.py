"""
同花顺问财数据源 fetch_fn 包装器。

通过自建 iwencai WAP 通道（主）或 pywencai 库（可选依赖）或 iwencai OpenAPI
访问同花顺问财数据。pywencai 支持自然语言查询选股、财务数据、新闻、公告、研报等。
iwencai OpenAPI 支持新闻、公告、研报的专业搜索。

WAP 通道（2026-11-07 逆向实测，对应交接文档 07/09）：
  - Web 端点 `customized/chart/get-robot-data` 被 openresty TLS 指纹风控，
    携带合法 hexin-v 也 403（pywencai 0.13.1 默认走此端点，开箱必挂）；
  - 移动端端点 `unifiedwap/unified-wap/v2/result/get-robot-data` 只认 hexin-v
    头，form-encoded POST / GET 皆通，返回完整结构化数据；
  - hexin-v token 由 pywencai 随包的 hexin-v.bundle.js（node 执行）现生成，
    算法 0.13.1 仍有效；token 会过期，每次调用现生成；
  - perpage 被服务端硬钳 10 条/页，且 page 参数被忽略（单会话锁页，
    翻页参数/语义分片/getDataList perpage 覆盖均已实测无效）——单次查询
    最多 10 行，全量需求靠消费方二级源合并（同花顺补缺）。

设计原则：
  - pywencai 为可选依赖（本通道只用其 token 生成），未安装时抛 ImportError
    由 SmartRouter 记账降级
  - iwencai OpenAPI 需要 IWENCAI_API_KEY 环境变量
  - 失败时抛异常由 SmartRouter 降级（2026-09-28 审计纪律）；合法响应但
    无数据时返回空 DataFrame
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any

import pandas as pd
import requests

logger = logging.getLogger("tradex.wencai")

# iwencai OpenAPI 配置
IWENCAI_BASE_URL = os.environ.get(
    "IWENCAI_BASE_URL", "https://openapi.iwencai.com"
)
IWENCAI_API_KEY = os.environ.get("IWENCAI_API_KEY", "")

# iwencai WAP 通道配置（2026-11-07 实测）
WENCAI_WAP_URL = (
    "https://www.iwencai.com/unifiedwap/unified-wap/v2/result/get-robot-data"
)
WENCAI_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
WENCAI_TIMEOUT = 30          # 单请求超时（秒）
WENCAI_PAGE_SLEEP = 0.4      # 翻页间隔（秒），温和服务端风控
WENCAI_MAX_PAGES = 30        # 翻页硬上限（当前服务端锁页，通常 1 页即停；未来解锁后保护至 300 行）
_WENCAI_DATE_SUFFIX = re.compile(r"\[\d{8}\]$")  # 列名日期后缀，如 涨停[20261106]


# ============================================================
# 问财查询 — wencai_query (WAP 通道主路，pywencai 仅供 token)
# ============================================================

def _get_hexin_v() -> str:
    """生成 hexin-v 风控 token（复用 pywencai 随包 bundle.js，node 现生成）。

    Raises:
        ImportError: pywencai 未安装（SmartRouter 记账降级）。
        RuntimeError: node 子进程失败 / token 为空。
    """
    from pywencai.headers import get_token  # 延迟导入，保持可选依赖纪律

    token = (get_token() or "").strip()
    if not token:
        raise RuntimeError("hexin-v token 生成失败（node 子进程无输出）")
    return token


def _wencai_wap_session() -> requests.Session:
    """WAP 通道会话。铁律：国内接口直连，禁读 HTTP(S)_PROXY 环境变量。"""
    session = requests.Session()
    session.trust_env = False
    return session


def _wencai_wap_request(
    session: requests.Session,
    token: str,
    query: str,
    query_type: str,
    page: int,
) -> dict[str, Any]:
    """POST WAP 端点取一页原始应答（form-encoded）。

    Raises:
        RuntimeError: 网关返回非 0 状态码（含 -302 缺参 / 风控拒绝）。
        requests.HTTPError: HTTP 层错误（403 等）。
    """
    headers = {
        "hexin-v": token,
        "User-Agent": WENCAI_UA,
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "Origin": "https://www.iwencai.com",
        "Referer": "https://www.iwencai.com/",
    }
    form = {
        "question": query,
        "perpage": "10",  # 服务端硬钳 10，传大值无效（2026-11-07 实测）
        "page": page,
        "secondary_intent": query_type,
        "log_info": '{"input_type":"typewrite"}',
        "source": "Ths_iwencai_Xuangu",
        "version": "2.0",
        "block_list": "",
        "add_info": (
            '{"urp":{"scene":1,"company":1,"business":1},'
            '"contentType":"json","searchInfo":true}'
        ),
    }
    resp = session.post(
        WENCAI_WAP_URL, headers=headers, data=form, timeout=WENCAI_TIMEOUT
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("status_code") != 0:
        raise RuntimeError(
            f"问财WAP返回异常 status_code={payload.get('status_code')} "
            f"msg={payload.get('status_msg')}"
        )
    return payload.get("data") or {}


def _extract_wap_table(data: dict[str, Any]) -> tuple[pd.DataFrame, int | None]:
    """从 WAP 应答提取表格：answer[].txt[].content.components[].data.datas。

    Returns:
        (表格 DataFrame, row_count 总行数或 None)。找不到表格返回 (空表, None)。
    """
    for answer in data.get("answer") or []:
        for txt in answer.get("txt") or []:
            comps = (txt.get("content") or {}).get("components") or []
            for comp in comps:
                comp_data = comp.get("data") or {}
                rows = comp_data.get("datas")
                if isinstance(rows, list) and rows:
                    meta_extra = (comp_data.get("meta") or {}).get("extra") or {}
                    raw_count = meta_extra.get("row_count")
                    try:
                        row_count = int(raw_count) if raw_count is not None else None
                    except (TypeError, ValueError):
                        row_count = None
                    return pd.DataFrame(rows), row_count
    return pd.DataFrame(), None


def _clean_wencai_columns(df: pd.DataFrame) -> pd.DataFrame:
    """清洗问财列名：剥掉日期后缀（如 涨停[20261106] → 涨停），去重复列。"""
    df = df.rename(columns=lambda c: _WENCAI_DATE_SUFFIX.sub("", str(c)))
    return df.loc[:, ~df.columns.duplicated()]


def fetch_wencai_query(
    query: str = "",
    query_type: str = "stock",
    loop: bool = True,
    sort_key: str = "",
    sort_order: str = "desc",
    **kwargs,
) -> pd.DataFrame:
    """同花顺问财自然语言查询（自建 WAP 通道）。

    hexin-v token 由 pywencai 随包 bundle.js 现生成（pywencai 未安装时抛
    ImportError 由 SmartRouter 降级）。

    ⚠️ 已知限制（2026-11-07 实测）：WAP 服务端单会话锁页——perpage 硬钳 10
    条/页，且 page 参数被忽略（重复返回第一批 10 行）。loop=True 的翻页逻辑
    为未来服务端解锁预留（重复页首行指纹检测自动停止）；当前单次查询最多
    返回 10 行。消费方需要全量结果时应做二级源合并（见 shortline_service
    fetch_reasons 的问财+同花顺合并制），不要假设本函数返回全量。

    Args:
        query: 自然语言查询语句，如 "2026年11月6日涨停"
        query_type: 查询类型，可选 {"stock", "fund", "index"}
        loop: 是否翻页取全量（默认 True；受服务端锁页限制，当前与 False 等效）
        sort_key: 排序字段（本地 DataFrame 排序，列不存在时忽略）
        sort_order: 排序方向 {"asc", "desc"}

    Returns:
        DataFrame with query results（列名已剥日期后缀）
    """
    if not query:
        logger.debug("fetch_wencai_query: query is empty")
        return pd.DataFrame()

    try:
        token = _get_hexin_v()
    except ImportError:
        logger.warning(
            "pywencai 未安装，无法生成 hexin-v token。"
            "请执行: pip install pywencai"
        )
        raise  # 失败必须抛出，由 SmartRouter 记账降级（吞成空表会让降级链与健康分全部失效）

    try:
        session = _wencai_wap_session()
        frames: list[pd.DataFrame] = []
        row_count: int | None = None
        prev_first: tuple | None = None
        page = 1
        while page <= WENCAI_MAX_PAGES:
            data = _wencai_wap_request(session, token, query, query_type, page)
            df_page, row_count = _extract_wap_table(data)
            if df_page.empty:
                break
            # WAP 服务端锁页保护（2026-11-07 实测：page 参数被忽略时
            # 每页都返回同一批行，靠首行指纹检测避免无限重复拼接）
            first_sig = tuple(str(v) for v in df_page.iloc[0].tolist())
            if first_sig == prev_first:
                logger.debug(
                    "fetch_wencai_query(%s): page %d repeats page %d, stop",
                    query[:50], page, page - 1,
                )
                break
            prev_first = first_sig
            frames.append(df_page)
            got = sum(len(f) for f in frames)
            if not loop or (row_count is not None and got >= row_count):
                break
            page += 1
            time.sleep(WENCAI_PAGE_SLEEP)

        if not frames:
            logger.debug("fetch_wencai_query(%s): empty", query[:50])
            return pd.DataFrame()

        df = _clean_wencai_columns(pd.concat(frames, ignore_index=True))
        if sort_key and not df.empty and sort_key in df.columns:
            df = df.sort_values(
                sort_key, ascending=(str(sort_order).lower() != "desc")
            )
        elif sort_key:
            logger.debug("fetch_wencai_query: sort_key %r not in columns", sort_key)
        return df
    except Exception as e:
        logger.warning("fetch_wencai_query(%s) failed: %s", query[:50], e)
        raise  # 失败必须抛出，由 SmartRouter 记账降级（吞成空表会让降级链与健康分全部失效）


# ============================================================
# iwencai OpenAPI 新闻搜索 — wencai_news (iwencai 模式)
# ============================================================

def fetch_wencai_news(
    keyword: str = "",
    channel: str = "news",
    limit: int = 20,
    **kwargs,
) -> pd.DataFrame:
    """同花顺问财 OpenAPI 新闻/公告/研报搜索。

    通过 iwencai OpenAPI 搜索财经新闻、公告、研报。
    需要设置环境变量 IWENCAI_API_KEY。

    Args:
        keyword: 搜索关键词
        channel: 搜索频道，可选 {"news": 新闻, "announcement": 公告, "report": 研报}
        limit: 返回条数，默认 20

    Returns:
        DataFrame with columns: 标题, 发布时间, 来源, 摘要, 链接
    """
    if not keyword:
        logger.debug("fetch_wencai_news: keyword is empty")
        return pd.DataFrame()

    if not IWENCAI_API_KEY:
        logger.warning(
            "IWENCAI_API_KEY 未设置，无法使用 iwencai OpenAPI。"
            "请设置环境变量 IWENCAI_API_KEY"
        )
        return pd.DataFrame()

    try:
        import json
        import urllib.request

        url = f"{IWENCAI_BASE_URL}/v1/comprehensive/search"
        payload = {
            "channels": [channel],
            "app_id": "tradex",
            "query": keyword,
        }
        headers = {
            "Authorization": f"Bearer {IWENCAI_API_KEY}",
            "Content-Type": "application/json",
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers=headers, method="POST"
        )

        # 铁律：国内接口直连。默认 opener 会读 HTTP(S)_PROXY 环境变量，必须绕过。
        _opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with _opener.open(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        # 解析响应
        items = result.get("data", {}).get("items", []) or []
        if not items:
            logger.debug("fetch_wencai_news(%s): empty result", keyword)
            return pd.DataFrame()

        articles = []
        for item in items[:limit]:
            articles.append({
                "标题": item.get("title", ""),
                "发布时间": item.get("publish_time", ""),
                "来源": item.get("source", ""),
                "摘要": item.get("summary", ""),
                "链接": item.get("url", ""),
            })

        if not articles:
            return pd.DataFrame()
        return pd.DataFrame(articles)

    except Exception as e:
        logger.warning("fetch_wencai_news(%s) failed: %s", keyword, e)
        raise  # 2026-09-28 审计修复：失败必须抛出，由 SmartRouter 记账降级（吞成空表会让降级链与健康分全部失效）
