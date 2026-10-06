"""上交所龙虎榜文本解析单元测试（exchange_official_fetchers._parse_sse_trade_public）。

2026-09-29 修复 queryLatestBargainRank.do 404 后，fetch_sse_dragon_tiger 改用
showTradePublicFile.do 返回的「每日交易信息」全文，解析逻辑离线可测：
本文件内嵌一段裁剪版真实文本（2026-09-28），覆盖涨跌幅正负、席位块、
板块标题折行、无席位兜底、B股剔除、空板块。
"""
from __future__ import annotations

import pandas as pd

from tradex.data_sources.exchange_official_fetchers import _parse_sse_trade_public

_FIXTURE_LINES = [
    "            上海证券交易所每日交易信息",
    "",
    "交易日期:2026年09月28日",
    "",
    "一、有价格涨跌幅限制的日收盘价格涨幅偏离值达到7%的前五只证券:",
    " 1、A股",
    "        证券代码      证券简称      偏离值%        成交量        成交金额(万元)",
    "    (1)  600340      *ST华幸       11.92%       185170600           23135.90",
    "    (2)  600032      浙江新能      11.74%        60857691           44155.99",
    "",
    "      证券代码: 600340                                                                    证券简称: *ST华幸 ",
    "      ------------------------------------------------------------------------------------------------------",
    "      买入营业部名称:                                                                      累计买入金额(元):",
    "  (1) 华泰证券股份有限公司常州东横街证券营业部                                                    2527981.40",
    "  (2) 东方财富证券股份有限公司拉萨团结路第一证券营业部                                            2511430.00",
    "",
    "      卖出营业部名称:                                                                      累计卖出金额(元):",
    "  (1) 华泰证券股份有限公司上海武定路证券营业部                                                    6765345.00",
    "  (2) 中信建投证券股份有限公司北京望京证券营业部                                                  2785118.00",
    "",
    "      证券代码: 600032                                                                    证券简称: 浙江新能",
    "      ------------------------------------------------------------------------------------------------------",
    "      买入营业部名称:                                                                      累计买入金额(元):",
    "  (1) 沪股通专用                                                                                    46403618.81",
    "",
    "      卖出营业部名称:                                                                      累计卖出金额(元):",
    "  (1) 沪股通专用                                                                                    12752379.96",
    "",
    "二、有价格涨跌幅限制的日收盘价格跌幅偏离值达到7%的前五只证券:",
    " 1、A股",
    "        证券代码      证券简称      偏离值%        成交量        成交金额(万元)",
    "    (1)  600743      华远控股      -8.49%       150224904           34810.34",
    "",
    " 2、B股",
    "",
    " 3、封闭式基金",
    "",
    "三、无价格涨跌幅限制首个交易日的证券:",
    " 1、A股",
    "        证券代码      证券简称      涨跌幅%        成交量        成交金额(万元)",
    "    (1)  600999      测试新材      44.00%         50000000          100000.00",
    "",
    " 2、B股",
    "",
    "四、连续三个交易日内的日均换手率与前五个交易日日均换手率的比值到达30倍,并且该股票、封闭",
    "    式基金连续三个交易日内累计换手率达到20%",
    " 1、A股",
    "",
    " 2、B股",
    "",
    "                                                        上海证券交易所",
    "",
]


def _as_df(lines):
    rows = _parse_sse_trade_public(lines)
    return pd.DataFrame(rows)


def test_basic_rows_and_seats():
    df = _as_df(_FIXTURE_LINES)
    assert not df.empty
    r = df[(df["代码"] == "600340")].iloc[0]
    assert r["名称"] == "*ST华幸"
    assert "涨幅偏离值达到7%" in r["上榜原因"]
    # 净买入 = 买入合计 - 卖出合计
    expect = (2527981.40 + 2511430.00) - (6765345.00 + 2785118.00)
    assert abs(r["净买入"] - expect) < 0.01
    assert "华泰证券股份有限公司常州东横街证券营业部 2,527,981.40" in r["买入席位"]
    assert "中信建投" in r["卖出席位"]


def test_no_duplicate_summary_and_detail_rows():
    df = _as_df(_FIXTURE_LINES)
    # 每只证券每个板块只出现一次（汇总行被席位块覆盖时不再兜底重复）
    dup = df.groupby(["上榜原因", "代码"]).size()
    assert (dup == 1).all()


def test_negative_deviation_row_parsed():
    df = _as_df(_FIXTURE_LINES)
    r = df[(df["代码"] == "600743")].iloc[0]
    assert r["名称"] == "华远控股"
    assert "跌幅偏离值达到7%" in r["上榜原因"]
    assert r["净买入"] == 0.0  # 该 fixture 中此板块无席位块 → 兜底行


def test_summary_only_fallback_kept():
    df = _as_df(_FIXTURE_LINES)
    # 板块三只有汇总行、无席位块 → 兜底一条记录，席位为空
    r = df[(df["代码"] == "600999")].iloc[0]
    assert r["上榜原因"].startswith("无价格涨跌幅限制")
    assert r["买入席位"] == "" and r["卖出席位"] == ""


def test_wrapped_section_title_joined():
    df = _as_df(_FIXTURE_LINES)
    # 板块四标题折行：拼接后必须完整，不允许出现半截标题或页脚残留
    for reason in df["上榜原因"]:
        assert not reason.endswith("封闭")
        assert "上海证券交易所" not in reason
        if "比值到达30倍" in reason:
            assert "累计换手率达到20%" in reason


def test_b_share_filtered():
    df = _as_df(_FIXTURE_LINES)
    # B股(9 开头)被剔除，只保留 A 股(6 开头)
    assert (df["代码"].str.startswith("6")).all()


def test_summary_header_line_not_parsed_as_row():
    df = _as_df(_FIXTURE_LINES)
    # 列头行（证券代码/证券简称/偏离值%）不能被误解析成记录
    assert not df["名称"].str.contains("简称").any()
    assert (df["代码"].str.fullmatch(r"\d{6}")).all()


def test_empty_input():
    assert _as_df([]).empty
