# MCP 工具清单

> 本文件由 `scripts/generate_tool_docs.py` 从源码 AST 生成（`tradex/src/tradex/tools/*.py`
> 中带 `@mcp.tool` 装饰器的函数），**请勿手工编辑**。当前版本 **v3.6.1**，共 **168 个工具**。
> 工具增删后重跑脚本即可：`python scripts/generate_tool_docs.py`。

## 总览

| 层级 | 工具数 |
|------|--------|
| L1 数据获取 | 144 |
| L2 计算引擎 | 8 |
| L3 决策支持 | 11 |
| 系统诊断 | 5 |
| **合计** | **168** |

## L1 数据获取（144 个）

### 公司信息（4 个）

| 工具 | 说明 |
|------|------|
| `get_company_info` | 获取A股公司基本信息，包括行业、市值、股本等。 |
| `get_company_profile` | 获取公司主营业务构成和业务描述。 |
| `get_competitors` | 获取同行业公司列表（竞争对手/可比公司）。 |
| `search_stock` | 搜索A股股票，支持名称或代码模糊匹配。 |

### 价格行情（5 个）

| 工具 | 说明 |
|------|------|
| `get_historical_price` | 获取A股股票历史K线数据 (OHLCV)。 |
| `get_intraday_data` | 获取A股股票当日分时数据（1分钟K线）。 |
| `get_market_capitalization` | 获取A股股票的总市值和流通市值。 |
| `get_realtime_quote` | 获取实时行情数据。支持A股6位代码和全球行情代码。 |
| `get_stock_list` | 获取A股完整股票列表，附带行情摘要信息。可按市值筛选。 |

### 板块行业（5 个）

| 工具 | 说明 |
|------|------|
| `get_concept_list` | 获取概念板块列表。 |
| `get_industry_list` | 获取行业板块列表。 |
| `get_industry_pe` | 获取行业板块历史行情数据（可用于计算行业PE估值趋势）。 |
| `get_industry_stocks` | 获取指定行业板块的成分股列表。 |
| `get_sector_fund_flow` | 获取板块资金流向排名。 |

### 财务数据（8 个）

| 工具 | 说明 |
|------|------|
| `get_balance_sheet` | 获取资产负债表（按季度）。 |
| `get_cash_flow_statement` | 获取现金流量表（按季度）。 |
| `get_financial_indicators` | 获取财务分析指标（ROE、毛利率、净利率、资产负债率等）。 |
| `get_financial_line_item` | 从三大财务报表中提取特定财务科目的时间序列数据。 |
| `get_growth_rates` | 获取成长性指标（营收增长率、净利润增长率等）。 |
| `get_income_statement` | 获取利润表（按季度）。 |
| `get_per_share_data` | 获取每股指标（每股收益EPS、每股净资产BPS、每股现金流CFPS等）。 |
| `get_segments_revenue` | 获取公司主营业务构成（按产品/地区分拆营收）。 |

### 估值与持仓（4 个）

| 工具 | 说明 |
|------|------|
| `get_analyst_rating` | 获取分析师评级和盈利预测数据。 |
| `get_dividend_data` | 获取股票历史分红派息详情。 |
| `get_institutional_holdings` | 获取机构持股/十大流通股东数据。 |
| `get_valuation_metrics` | 获取股票历史估值指标（PE、PB、PS等市盈率/市净率/市销率时间序列）。 |

### 新闻公告（14 个）

| 工具 | 说明 |
|------|------|
| `get_company_announcements` | 获取上市公司公告。v3.2.0 起直连巨潮 cninfo.com.cn，信息更全更及时。 |
| `get_financial_calendar` | 获取上市公司财报披露时间表和经济数据日历。v3.3.0 新增百度经济数据日历补充源。 |
| `get_fund_hold` | 获取机构持仓数据（基金/QFII/社保/券商/保险/信托）。v3.3.0 新增。 |
| `get_futures_news` | 获取期货/大宗商品相关新闻。v3.3.0 新增。 |
| `get_hot_keywords` | 获取指定股票的东方财富热门关联关键词。v3.3.0 新增。 |
| `get_hot_rank` | 获取东方财富个股人气榜数据。v3.3.0 新增。 |
| `get_hot_search` | 获取百度股市通热搜股票排行。v3.3.0 新增。 |
| `get_market_sentiment` | 获取指数新闻情绪数据，反映市场整体情绪倾向。v3.3.0 新增。 |
| `get_stock_news` | 获取个股相关新闻资讯。v3.2.0 起直连东财 search-api-web，更稳定。 |
| `get_telegraph_news` | 获取全市场实时财经快讯（财联社7×24小时电报）。v3.2.0 新增。 |
| `get_wencai_news` | 同花顺问财新闻/公告/研报搜索（需设置 IWENCAI_API_KEY 环境变量）。v3.3.0 新增。 |
| `get_wencai_query` | 同花顺问财自然语言查询（需安装 pywencai 和 Node.js）。v3.3.0 新增。 |
| `get_xueqiu_hot` | 获取雪球沪深股市热度排行榜数据。v3.3.0 新增。 |
| `search_news` | 按关键词搜索财经新闻资讯。 |

### 市场总览与资金（7 个）

| 工具 | 说明 |
|------|------|
| `get_dragon_tiger` | 获取龙虎榜数据（机构和游资活跃买卖记录）。 |
| `get_global_market_quote` | 获取全球市场行情快照。v3.3.1 新增，通过腾讯接口批量获取。 |
| `get_index_volume_compare` | 获取三大指数（上证/深证/创业板）近 days 个交易日的量能序列，用于盘后复盘「量能对比」柱状图。 |
| `get_limit_up_down` | 获取当日涨停板或跌停板股票池。 |
| `get_market_overview` | 获取A股主要指数实时行情快照。 |
| `get_money_flow` | 获取个股资金流向数据。 |
| `get_north_bound_flow` | 获取北向资金（沪股通+深股通）净流入数据。 |

### 宏观与两融（8 个）

| 工具 | 说明 |
|------|------|
| `get_bond_yield_curve` | 获取中国国债收益率曲线数据。 |
| `get_fx_rate` | 获取外汇汇率数据。 |
| `get_insider_trading` | 获取股东/高管增减持（内部交易）数据。 |
| `get_macro_cpi` | 获取中国CPI消费者价格指数数据（月度）。 |
| `get_macro_gdp` | 获取中国GDP数据（季度）。 |
| `get_macro_money_supply` | 获取中国货币供应量数据（M0/M1/M2，月度）。 |
| `get_macro_pmi` | 获取中国PMI采购经理指数数据（月度）。 |
| `get_margin_trading` | 获取融资融券数据（两融余额）。 |

### 宏观官方源（统计局 / 中债）（2 个）

| 工具 | 说明 |
|------|------|
| `get_bond_yield_curve_official` | 获取国债/信用债收益率曲线（中债官方一手，3月~30年）。 |
| `get_pmi` | 获取 PMI 数据（国家统计局，制造业 + 非制造业）。 |

### 信号数据 · 基础（6 个）

| 工具 | 说明 |
|------|------|
| `get_concept_attribution` | 获取个股所属概念/行业/地域板块。 |
| `get_hot_stocks` | 获取涨停股票及主题归因（同花顺 editorial 人工标注）。 |
| `get_lockup_expiry` | 获取个股限售解禁日历。 |
| `get_profit_forecast` | 获取分析师一致预期EPS及Forward PE/PEG估值。 |
| `get_technical_indicator` | 计算个股技术指标。 |
| `list_technical_indicators` | 列出所有支持的技术指标及其说明。 |

### 信号数据 · 资金流与龙虎榜（4 个）

| 工具 | 说明 |
|------|------|
| `get_dragon_tiger_signal` | 获取个股龙虎榜数据（上榜记录 + 买卖席位 + 机构动向）。 |
| `get_fund_flow_signal` | 获取个股资金流向（主力/大单/中单/小单/超大单净流入）。 |
| `get_industry_comparison_signal` | 获取行业横向对比排名（全行业涨跌幅/上涨下跌家数/领涨股）。 |
| `get_northbound_flow_signal` | 获取北向资金流向（沪深股通）。 |

### 信号数据 · 涨停板与情绪（3 个）

| 工具 | 说明 |
|------|------|
| `get_board_sentiment` | 获取打板情绪数据（炸板率/连板梯队/晋级率）。 |
| `get_limit_up_board` | 获取涨停板数据（东财 push2ex）。 |
| `get_limit_up_insight` | 获取涨停揭秘数据（同花顺）。 |

### 信号数据 · ETF（2 个）

| 工具 | 说明 |
|------|------|
| `get_etf_kline_data` | 获取ETF历史K线数据。 |
| `get_etf_realtime_data` | 获取ETF实时行情（全部ETF按成交额/涨跌幅排序）。 |

### 信号数据 · 可转债（2 个）

| 工具 | 说明 |
|------|------|
| `get_cb_realtime_data` | 获取可转债实时行情（全部可转债含转股溢价率）。 |
| `get_cb_value_analysis_data` | 获取可转债价值分析（历史转股溢价率/纯债价值/纯债溢价率曲线）。 |

### eltdx 通达信协议专有（31 个）

| 工具 | 说明 |
|------|------|
| `eltdx_get_adjusted_kline` | 获取股票复权 K 线（eltdx，v3.3.7 新增）。 |
| `eltdx_get_auction` | 获取股票集合竞价数据（eltdx 独有，AKShare 无此功能）。 |
| `eltdx_get_auction_data` | 获取股票竞价汇总（eltdx helpers，v3.3.7 新增）。 |
| `eltdx_get_buy_sell_strength` | 获取股票日内买卖强度数据（eltdx 独有，v3.3.7 新增）。 |
| `eltdx_get_capital_changes` | 获取股本变动历史（eltdx，v3.3.7 新增，B 级）。 |
| `eltdx_get_category_quotes` | 获取分类行情列表（eltdx，v3.3.7 新增，B 级）。 |
| `eltdx_get_company_news` | 获取公司资讯/研报（eltdx F10，v3.3.7 新增）。 |
| `eltdx_get_depth` | 获取股票五档盘口快照（买1-5 / 卖1-5，eltdx 常驻连接）。 |
| `eltdx_get_dividend_financing` | 获取股票分红融资历史（eltdx F10，v3.3.7 新增）。 |
| `eltdx_get_f10` | 获取股票 F10 资料（eltdx 独有，AKShare 无此功能）。 |
| `eltdx_get_f10_extra` | 获取 F10 额外资料（eltdx 通用入口，v3.3.7 新增，B 级）。 |
| `eltdx_get_finance_batch` | 获取股票批量财务字段（eltdx 独有，v3.3.7 新增）。 |
| `eltdx_get_finance_report` | 获取通达信财务报表（eltdx F10，v3.3.7 新增）。 |
| `eltdx_get_full_kline` | 获取股票全量历史 K 线（eltdx，v3.3.7 新增）。 |
| `eltdx_get_kline` | 获取股票 K 线数据（SmartRouter 路由，优先 eltdx 数据源）。 |
| `eltdx_get_minute_history` | 获取股票历史分时数据（eltdx 独有，v3.3.7 新增）。 |
| `eltdx_get_minutes` | 获取股票当日分时数据（SmartRouter 路由，优先 eltdx 数据源）。 |
| `eltdx_get_northbound_holding` | 获取沪深股通持股变化（eltdx F10，v3.3.7 新增）。 |
| `eltdx_get_opening_match` | 获取股票当日 9:25 开盘撮合（eltdx 独有，v3.3.7 新增）。 |
| `eltdx_get_opening_match_history` | 获取历史开盘撮合（eltdx，v3.3.7 新增，B 级）。 |
| `eltdx_get_security_codes` | 获取全市场证券代码表（eltdx 精确分类，v3.3.7 新增）。 |
| `eltdx_get_shortline_indicators` | 获取股票短线打板指标（eltdx 独有，v3.3.7 新增）。 |
| `eltdx_get_special_limits` | 获取特殊品种涨跌停参考价（eltdx 独有，v3.3.7 新增）。 |
| `eltdx_get_special_limits_scan` | 扫描全市场特殊涨跌停参考价（eltdx，v3.3.7 新增，B 级）。 |
| `eltdx_get_stock_profile` | 获取股票全景档案（eltdx 独有，v3.3.7 新增）。 |
| `eltdx_get_stock_topics` | 获取个股关联全部题材（eltdx helpers，v3.3.7 新增）。 |
| `eltdx_get_ticks` | 获取股票逐笔成交数据（eltdx 独有，AKShare 无此功能）。 |
| `eltdx_get_today_ticks` | 获取股票当日逐笔成交明细（eltdx 独有，v3.3.7 新增）。 |
| `eltdx_get_topic_stocks` | 获取题材成分股排名（eltdx helpers，v3.3.7 新增）。 |
| `eltdx_get_trading_day` | 获取当前交易日（eltdx，v3.3.7 新增，B 级）。 |
| `eltdx_stream_health` | 查询 eltdx 常驻连接管理器健康状态。 |

### 本地数据（通达信盘后文件）（2 个）

| 工具 | 说明 |
|------|------|
| `get_local_kline` | 获取通达信本地日线数据（离线，不封 IP）。**仅用于回测和历史分析，非盘中实时。** |
| `get_local_minute` | 获取通达信本地分钟线数据（离线，不封 IP）。**仅用于回测和历史分析，非盘中实时。** |

### 通达信官方 MCP（tdx_mcp）（3 个）

| 工具 | 说明 |
|------|------|
| `natural_lang_screener` | 自然语言条件选股（通达信官方 MCP）。 |
| `query_macro_indicator` | 宏观数据查询（通达信问财 wenda_macro_query）。 |
| `research_report` | 券商研报查询（通达信问财 wenda_report_query）。 |

### 通达信 TQ 本地源（2 个）

| 工具 | 说明 |
|------|------|
| `get_l2_stats` | 当日 L2 统计查询（通达信 TQ 本地源，独占数据）。 |
| `run_tdx_formula` | 通达信内置公式批量计算（TQ 本地源公式生态桥）。 |

### 独立备源（新浪 / 百度 / baostock）（4 个）

| 工具 | 说明 |
|------|------|
| `get_baidu_kline` | 【备源直取】百度股市通带 MA 的 K 线。 |
| `get_baostock_valuation` | 【备源直取】baostock 估值历史（TCP 协议，零鉴权）。 |
| `get_sina_fund_flow` | 【备源直取】新浪财经个股资金流向（日度）。 |
| `get_sina_research_reports` | 【备源直取】新浪财经研报列表。 |

### 交易所与巨潮官方（4 个）

| 工具 | 说明 |
|------|------|
| `get_cninfo_announcement_backup` | 【官方备源】深交所官方公告（与巨潮信息网独立）。 |
| `get_sse_dragon_tiger` | 【官方一手】上交所龙虎榜（含营业部席位明细）。 |
| `get_szse_dragon_tiger` | 【官方一手】深交所龙虎榜。 |
| `get_trading_calendar` | 【官方一手】深交所交易日历（整月）。 |

### 事件驱动（东财 datacenter）（17 个）

| 工具 | 说明 |
|------|------|
| `get_block_trade_daily_stat` | 获取大宗交易每日统计（按股票汇总成交笔数、总额等）。 |
| `get_block_trade_detail` | 获取大宗交易明细（按日期范围筛选个股大宗交易记录）。 |
| `get_block_trade_market_stat` | 获取大宗交易市场每日总览（全市场汇总）。 |
| `get_dragon_tiger_branch_rank` | 龙虎榜营业部排行（按周期统计：近1月/3月/6月/1年）。 |
| `get_dragon_tiger_detail` | 龙虎榜上榜个股详情（含 D1/D2/D5/D10 上榜后股价表现跟踪）。 |
| `get_dragon_tiger_institution` | 龙虎榜机构买卖统计（机构席位层面，按日期范围）。 |
| `get_dragon_tiger_seat_detail` | 个股某日龙虎榜席位明细（买入榜 + 卖出榜合并）。 |
| `get_dragon_tiger_stock_stats` | 个股龙虎榜上榜次数统计（按周期聚合：1月/3月/6月/1年）。 |
| `get_earnings_forecast` | 获取个股业绩预告（预增/预减/扭亏/续亏/预亏等）。 |
| `get_equity_pledge` | 获取股权质押情况（质押机构、质押数量、质押比例）。 |
| `get_holder_trades` | 获取股东增减持记录（重要股东 / 高管的买卖动向）。 |
| `get_institution_survey` | 获取机构调研记录（哪些机构调研了该股票）。 |
| `get_ipo_calendar` | 获取新股申购日历（未来 N 天可申购新股清单）。 |
| `get_margin_account_info` | 获取全市场融资融券账户统计（按日）。 |
| `get_margin_target_list` | 获取融资融券标的明细（当日可融资/可融券清单）。 |
| `get_share_buyback` | 获取股票回购方案与进度。 |
| `get_unusual_fluctuation` | 获取交易所「股票交易异常波动」监管预警列表（监管异动）。 |

### 全球资讯与宏观日历（3 个）

| 工具 | 说明 |
|------|------|
| `get_cctv_news` | 获取央视新闻联播条目 + 文字稿（政策信号挖掘）。 |
| `get_macro_calendar` | 获取全球宏观日历（公布值/预期/前值）。 |
| `get_wallstreetcn_lives` | 获取华尔街见闻 7×24 全球财经快讯。 |

### 产业链资讯（106 源）（2 个）

| 工具 | 说明 |
|------|------|
| `get_industry_news` | 获取产业链资讯（海外英文 RSS 直连，按赛道聚合，对应 A 股板块）。 |
| `list_industry_tracks` | 列出所有可用的产业链资讯赛道（12 个，对应 A 股板块）+ 当前冻结版源总数。 |

### 申万行业变迁史（2 个）

| 工具 | 说明 |
|------|------|
| `get_sw_industry_as_of` | 查询股票在指定日期所属的申万行业（历史回测用，避免未来函数）。 |
| `get_sw_industry_history` | 获取申万行业分类变迁史（含所有股票在不同时期的行业归属）。 |

## L2 计算引擎（8 个）

### 技术指标计算（6 个）

| 工具 | 说明 |
|------|------|
| `calculate_atr` | 计算 ATR 平均真实波幅。 |
| `calculate_boll` | 计算布林带（BOLL）上轨、中轨、下轨。 |
| `calculate_kdj` | 计算 KDJ 随机指标（K、D、J 值）。 |
| `calculate_ma_ema` | 计算 MA(简单移动平均) / EMA(指数移动平均) 均线。 |
| `calculate_macd` | 计算 MACD 指标（DIF、DEA、MACD柱）。 |
| `calculate_rsi` | 计算 RSI 相对强弱指数（Wilder 平滑法）。 |

### 绩效指标（2 个）

| 工具 | 说明 |
|------|------|
| `calculate_performance` | 计算完整的策略绩效指标。 |
| `list_performance_metrics` | 列出所有支持的绩效指标清单。 |

## L3 决策支持（11 个）

### 交易信号生成（3 个）

| 工具 | 说明 |
|------|------|
| `generate_trading_signal` | 基于多指标组合生成单票交易信号。 |
| `scan_stocks_for_signals` | 批量扫描多只股票的交易信号。 |
| `validate_signal_quality` | 验证信号质量（前瞻收益分析）。 |

### 多因子分析（2 个）

| 工具 | 说明 |
|------|------|
| `calculate_factor_score` | 多因子综合评分。 |
| `get_factor_catalog` | 获取因子库清单。 |

### 条件选股（2 个）

| 工具 | 说明 |
|------|------|
| `get_screening_conditions` | 获取支持的选股条件清单。 |
| `screen_stocks` | 条件选股扫描。 |

### 综合分析（3 个）

| 工具 | 说明 |
|------|------|
| `analyze_industry_comparison` | 行业对比分析 — 个股指标 vs 同行业均值。 |
| `analyze_market_overview` | 市场全景分析 — 大盘指数 + 板块资金 + 涨跌停统计。 |
| `analyze_stock_comprehensive` | 个股综合分析 — 一次调用获取完整分析视图。 |

### 技术分析引擎（1 个）

| 工具 | 说明 |
|------|------|
| `analyze_technical` | 5 维度技术分析引擎（均线/趋势/量价/筹码/形态）。 |

## 系统诊断（5 个）

### 健康检查与可观测性（5 个）

| 工具 | 说明 |
|------|------|
| `get_cache_stats` | 返回两级缓存（内存 + 文件）的统计信息。 |
| `get_data_source_dashboard` | 获取数据源看板数据（JSON）。 |
| `get_data_source_health` | 返回各数据源的健康状态。 |
| `health_check` | 系统健康检查。 |
| `list_all_tools` | 返回所有已注册工具的清单。 |

---

工具调用方式见 [README.md](../README.md#mcp-工具清单168-个)。
