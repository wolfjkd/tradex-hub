# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/),

## [3.3.10] - 2026-09-07

### Changed（双源合一 + 深度体检修复）

- **astock_signals 双源合一**：独立仓 `Claw/astock_signals/` 退役，`tradex/src/astock_signals/` 成为唯一主源（补齐 v3.3.2 超时保护/停更检测等落后内容，版本 1.1.1），所有调用统一走框架内主源。
- **P0 计算修复**：`_downside_volatility` 改用标准下行偏差算法（原对负收益以自身均值为中心，Sortino 分母系统性算错）；全正收益策略 Sortino 返回 inf。
- **P1 修复**：
  - `symbol.get_exchange`：可转债 11x(沪)/12x(深)、ETF、沪B(900)、北交所(920) 交易所判定修正；
  - `get_segments_revenue`：symbol 补 `format_em_symbol` 前缀（东财 F10 需带市场标识）+ None 守卫；
  - 逐笔方向：eltdx 真实字段 `side`(buy/sell/neutral) 替代不存在的 `buy_or_sell`（原实时路径 100% 误标 sell），统一归一化 unknown；
  - SmartRouter 故障源半开探测自愈（冷却期后自动复活，防永久拉黑+防雪崩）；
  - 东财限流 `em_client` 加锁（防多线程穿透封 IP）；SSL 全局替换加锁；`register_all_sources`/`register_all_tools` 幂等加固。
- **仓库卫生**：删根 `src/` 空壳目录与 `cn-financial-mcp/` 僵尸目录；删串仓测试 `test_data_router_syntax.py`（测的是另一项目代码）；修复 pytest 合跑 ImportPathMismatchError（移除根 tests/__init__.py）；`config/mcp-servers.json` 3.1.4→3.3.9 同步。
- **测试**：全量 357 passed / 0 failed（此前 6 个失败均修复/清理）；工具数断言 127→129。

## [3.3.9] - 2026-08-18

### Added（数据源扩充 + 本地数据 + 全局直连）

- **全局直连**：`__init__.py` import 时清代理环境变量（HTTP(S)_PROXY 等），国内数据源一律直连，代理只给 git push GitHub。
- **东财限流防封**：新增 `em_client.py`，em_get 统一请求入口（间隔≥1s+随机抖动+会话复用），所有东财接口走限流，避免高频封 IP。
- **东财 slist 板块归属**：`fetch_stock_boards`（个股所属行业/概念/地域 + 龙头股，一次请求拿全）。
- **同花顺数据源**：新增 `ths_fetchers.py`，4 个零鉴权接口（一致预期 EPS / 热点归因 reason / 涨停揭秘 / 热榜）。
- **通达信本地数据**：新增 `tdx_local.py`，读本地 vipdoc .day/.lc5 二进制文件（离线不封 IP），全市场 5900+ 只日线。
- **实时涨跌家数 / 行业涨幅**：`fetch_market_breadth`（push2ex 涨跌分布）+ `fetch_industry_quotes`（push2→push2delay 降级）。

### Added（MCP 工具）

- `get_local_kline` / `get_local_minute`：读通达信本地日线/分钟线（仅回测/历史分析，非盘中实时，盘中实时用实时源）。

### Changed

- 版本三处同步至 3.3.9（VERSION / pyproject.toml / README）。
- 工具数 127→129。

### 验证

- 本地日线实测 5984 条（茅台全历史）；同花顺热点归因 64 只含题材标签；一致预期 EPS 3 年；slist 板块归属 28 板块含龙头。

## [3.3.8] - 2026-08-14

### Added（eltdx 2.0 第二梯队 B 级接入）

按老板规划接入 B 级（有等价源的高精度补充）接口，新增 **6 个 MCP 工具**（工具数 121→127）：

- `eltdx_get_category_quotes`（分类行情：A股涨幅榜/成交额榜/封单榜，实时性强于 akshare）
- `eltdx_get_trading_day`（交易日判定，服务器握手）
- `eltdx_get_opening_match_history`（历史开盘撮合，盘后复盘）
- `eltdx_get_capital_changes`（股本变动历史，复权计算基础）
- `eltdx_get_special_limits_scan`（扫描全市场特殊品种涨跌停）
- `eltdx_get_f10_extra`（F10 通用入口，覆盖估值/题材行情/总评/盈利预测/排名/治理/增减持/主营构成/公告/新闻，通达信编码字段降级源）

### Changed
- 版本三处同步至 3.3.8（VERSION / pyproject.toml / README）。

### 决策
- C 级（服务器文件/连接心跳/旧接口/底层万能口）按老板指示**不接入**。

### 验证
- 非网络全量测试 27 passed / 0 failed。
- 分类行情实测返回实时涨幅榜（北交所 29.97%、创业板 20% 等）。

## [3.3.7] - 2026-08-14

### Added（eltdx 2.0 能力大规模接入 · 第一梯队 S+A 级）

按老板规划，将 eltdx 2.0 的第一梯队（S+A 级）能力接入 tradex，共新增 **19 个 MCP 工具**（工具数 101→121）：

**S 级（推送/盘口，交易看板底座）**
- 新增 `data_sources/eltdx_stream.py`：`EltdxStreamManager` 常驻连接管理器（start/subscribe/poll 增量/snapshot 五档/unsubscribe/health/stop）。
- 关键实测结论：eltdx 2.0 常驻连接/后台读线程/心跳保活/推送帧入队已由 PooledSocketTransport 托管；免费行情站不主动推送，增量靠 refresh_stream(0x0547) 游标机制（cursor=update_time_raw）。
- 新增 `eltdx_get_depth`（五档盘口快照）、`eltdx_stream_health`（流健康状态）。

**A 级（查询类，9 个数据域）**
- `eltdx_get_security_codes`（全市场证券代码表，5552 只A股精确分类）
- `eltdx_get_minute_history`（历史分时 240 点）+ `eltdx_get_buy_sell_strength`（买卖强度）
- `eltdx_get_today_ticks`（当日逐笔）+ `eltdx_get_opening_match`（9:25 开盘撮合）
- `eltdx_get_full_kline`（全量K线）+ `eltdx_get_adjusted_kline`（复权K线）
- `eltdx_get_stock_profile`（全景档案：行情+财务一表）
- `eltdx_get_shortline_indicators`（21 项短线打板指标）
- `eltdx_get_finance_batch`（批量财务）+ `eltdx_get_special_limits`（特殊涨跌停）
- `eltdx_get_finance_report` / `eltdx_get_dividend_financing` / `eltdx_get_company_news` / `eltdx_get_northbound_holding`（F10 基本面，通达信编码字段，降级补充源）
- `eltdx_get_stock_topics`（个股题材）+ `eltdx_get_topic_stocks`（题材成分股）+ `eltdx_get_auction_data`（竞价汇总）

### Changed
- 版本三处同步至 3.3.7（VERSION / pyproject.toml / README）。

### 验证
- 非网络全量测试 27 passed / 0 failed。
- 新增工具逐一端到端实测通过（五档盘口/历史分时/逐笔/复权K线/全景档案/短线指标/批量财务/题材/竞价等均返回真实数据）。

## [3.3.6] - 2026-08-14

### Changed（上游依赖升级）

- **eltdx 1.2.0 → 2.0.2（major breaking change）**：2.0 版移除了旧式 `client.get_quote()/get_kline()/get_minute()/get_trades()` 接口，统一为模块化 API（`client.codes/quotes/bars/minutes/trades/auctions/corporate/resources`）。tradex 唯一旧式调用 `fetch_realtime_quote` 已从 `client.get_quote()` 迁移至 `client.helpers.full_quotes()`（返回 `list[QuoteSnapshot]`，字段与旧接口一致）。
- **akshare 1.18.81 → 1.18.91（patch）**：av 依赖更新至 `akshare>=1.18.91`。
- `tradex/pyproject.toml` 依赖同步为 `akshare>=1.18.91`、`eltdx>=2.0.2`；`tradex/requirements.txt` 同步。
- 版本三处同步至 3.3.6（VERSION / pyproject.toml / README）。

### 验证
- 非网络全量测试：25 passed / 2 failed（2 个失败为预存工具数断言 101≠100，与本次升级无关）。
- eltdx 迁移后无回归。

## [3.3.5] - 2026-08-14

### Fixed（盘后复盘「量能对比」成交额数据源修复）

- **修复 `get_index_volume_compare` 成交额为 null 的问题**：原 `fetch_index_daily_amount` 主源走腾讯 `stock_zh_index_daily_tx`（仅返回成交量、无成交额字段），导致盘后复盘量能柱状图拿不到「成交额(亿元)」。现主源改为**东财 push2his 历史K线直连**（字段 f57=成交额），腾讯降级为备源。
- 新增 `_fetch_index_daily_from_push2his` 辅助函数：curl_cffi 绕过系统代理直连 `push2his.eastmoney.com/api/qt/stock/kline/get`，三指数（sh000001/sz399001/sz399006）均返回真实成交额。
- 版本三处同步至 3.3.5（VERSION / pyproject.toml / README）。

### 验证
- `py_compile` 通过，无回归。
- 三指数 6 日成交额序列验证通过：上证 6401 亿、深证成指 7472 亿、创业板 3583 亿（2026-08-14）。

## [3.3.4] - 2026-08-13

### Added（盘后复动量能对比数据源）

- **新增 `get_index_volume_compare(days=6)` MCP 工具**：返回上证/深证/创业板各自近 `days` 个交易日的日成交额序列（亿元），供盘后复盘「量能对比」柱状图使用。
- 新增数据源 `fetch_index_daily_amount`（akshare `stock_zh_index_daily_tx_js`，含成交额字段），注册路由 `index_daily_amount`（akshare 主源）。

### 验证
- `py_compile` 通过，无回归。

## [3.3.3] - 2026-08-13

### Changed（撤销逐笔方案 + 提示词去逐笔要求）

- **撤销 D(P1) 逐笔盘后数据方案**: 经核实，eltdx 逐笔（trades.history）收盘后服务器关闭当日数据窗口、本地无缓存；通达信盘后数据下载仅含日线/1分钟/5分钟、不含逐笔，且 1/5 分钟线占用大量硬盘，不可行；盘中录制会占用机器资源、可能影响实盘交易，故放弃该路线。
- `eltdx_fetchers.fetch_tick_data` 回退至纯实时取数（移除默认今日 + TickStore 回退死代码，恢复 `no ticks on {date}` 语义）。
- 已删除「盘中逐笔录制」自动化任务，并停用 `scripts/record_ticks.py`（移入 `scripts/_retired/`，未永久删除）。
- **盘后复盘提示词 v3.6 去逐笔**: 模块⑤采集项改为「数据源限制，暂不采集」；模块⑧自选股复盘删除「逐笔分析(eltdx)」维度；已知问题表删除 `eltdx tick` 注释。报告不再因无逐笔而标「暂缺」。

### 验证
- `py_compile` 通过，无回归。

## [3.3.2] - 2026-08-13

### Fixed（盘后复盘「多个数据缺失」根因修复，5 类）

- **A(P0) 指数代码解析错乱**: `utils/symbol.py` 新增指数代码白名单（`sh000001`/`sz399001`/`sz399006`/`sh000300`/`sh000688`/`sh000905`/`sz399852`），`get_exchange`/`format_*`/`get_market_name`/`is_valid_a_share_code` 正确识别指数，不再误判成股票（如 `sh000001`→平安银行）。`_get_market_overview_sync` 兼容 akshare(代码/名称) 与 tencent_http(指数名称/最新点位) 两种列名，主源失败降级腾讯后不再 KeyError 被吞 → 模块一三大指数恢复。
- **C(P0) 慢源挂起卡死 MCP**: `astock_signals.smart_router.route()` 新增 `timeout`（默认 12s）线程池包裹，慢源超时即判失败并自动降级下一源；`composite_analysis._safe_call` 同步函数改 `run_in_executor + asyncio.wait_for(30s)`，事件循环不再被阻塞。彻底解决 akshare 无内部 timeout 的 HTTP 调用无限挂起问题。
- **B(P1) 北向资金停更**: `astock_signals.northbound.get_northbound_flow_json` 新增「多日数值一致」检测，冻结值标 `discontinued` 并提示「沪深港通自2024-08-19起已停止披露，仅供参考」；`get_north_bound_flow` 工具明确输出「已停更」而非喂假数。
- **D(P1) 逐笔盘后无数据**: `eltdx_fetchers.fetch_tick_data` 默认交易日为今日，live 取不到时回退 TickStore 库读取（盘中录制、盘后取库）；新增 `scripts/record_ticks.py` 盘中录制脚本，并注册「盘中逐笔录制」自动化（交易时段整点运行）。——注：该 D(P1) 方案已于 3.3.3 撤销（详见 3.3.3）。
- **E(P2) 自动化配置漂移**: 盘后复盘自动化 prompt 从 v3.5 模板改为引用 v3.6（强制串行+健康探针+重试+完整性闸门）。

## [3.3.1] - 2026-08-03

### Fixed
- **get_money_flow**: 4只股票（601868/601390/600170/603077）全部通过 curl_cffi 直连绕过系统代理，修复 ProxyError
- **get_financial_calendar date 过滤失效**: 各源独立过滤后合并，避免 stock_report_disclosure 的2022年旧数据拖垮百度经济日历
- **search_news 稳定性增强**: 个股新闻失败时自动降级到全市场源（财联社+新浪+期货+热搜），不再依赖单源
- **get_sector_fund_flow 字段解析**: 主源东财 push2 接口 curl 56 错误，加 impersonate 仍不可用；新浪备源字段从 4 个扩充到 7 个（板块/涨跌幅/涨跌额/总成交额/总成交量/公司家数/平均价格）
- **get_realtime_quote 外围行情代理失败**: P0 修复，腾讯接口强制直连绕过系统代理
- **get_company_announcements 公告过滤**: P0 修复，_resolve_org_id 兼容带 SH 前缀的代码，Python 端二次过滤
- **pyproject.toml 版本同步**: 从 3.1.4 同步到 3.3.1（与 VERSION 文件一致）


### Changed
- **astock_signals 合并**: 将独立包 astock_signals v1.1.0 源码合并到本仓库，位于 tradex/src/astock_signals/，与 tradex 包统一版本管理
- **pyproject.toml**: packages 新增 src/astock_signals，打包时一同构建

### 验证
- 33 项单元测试通过，1 项跳过（需网络访问），无回归
- 19 项功能验证全部通过（4 只股票资金流 + 4 个新闻源 + 2 个日历源 + 板块资金流备源 + 外围行情 + 公告过滤）

## [3.3.0] - 2026-08-03

### Added
- **新闻资讯数据源扩充：9 个新增数据源**
  - `baidu_economic_calendar`：百度经济数据日历（akshare）
  - `baidu_trade_notify`：百度交易提醒（停复牌/分红派息/财报发行时间，akshare）
  - `index_news_sentiment`：指数新闻情绪评分（akshare）
  - `futures_news`：期货/大宗商品新闻（上海有色网，akshare）
  - `sina_finance_news`：新浪财经新闻直连（HTTP API）
  - `hot_search`：百度股市通热搜股票排行（akshare）
  - `hot_rank`：东方财富人气榜/飙升榜/热门关键词（akshare，7 合 1 多 endpoint）
  - `xueqiu_hot`：雪球关注/讨论/交易热度排行榜（akshare，3 合 1 多 endpoint）
  - `fund_hold`：机构持仓数据（基金/QFII/社保/券商/保险/信托，akshare，2 合 1 多 endpoint）
- **同花顺问财数据源（可选依赖）**：
  - `wencai_query`：同花顺问财自然语言查询（pywencai 可选依赖 + Node.js）
  - `wencai_news`：同花顺问财新闻/公告/研报搜索（iwencai OpenAPI，需 IWENCAI_API_KEY）
- **新增 9 个 MCP 工具（工具数 90 → 99）：**
  - `get_market_sentiment`（第91个）— 指数新闻情绪
  - `get_futures_news`（第92个）— 期货/大宗商品新闻
  - `get_hot_rank`（第93个）— 东财人气榜/飙升榜
  - `get_hot_keywords`（第94个）— 个股热门关键词
  - `get_xueqiu_hot`（第95个）— 雪球关注/讨论/交易热度
  - `get_fund_hold`（第96个）— 机构持仓数据
  - `get_hot_search`（第97个）— 百度热搜股票排行
  - `get_wencai_query`（第98个）— 同花顺问财自然语言查询
  - `get_wencai_news`（第99个）— 同花顺问财新闻/公告/研报搜索
- **新增数据类型**：数据类型从 27 个增加到 38 个（+11 个）

### Changed
- **get_financial_calendar**：新增百度经济数据日历作为补充源（财报披露 + 经济数据合并）
- **search_news**：全市场搜索新增百度交易提醒 + 期货新闻 + 新浪财经 + 百度热搜
  - 搜索源顺序：财联社快讯 → 巨潮公告 → 百度交易提醒 → 期货新闻 → 新浪财经 → 百度热搜 → 财新网 → CCTV
- **data_sources/__init__.py**：新增 wencai_fetchers 子模块说明
- **data_sources/registry.py**：注册表从 27 个数据类型扩展到 38 个

### 验证
- `python -m tradex` 启动：99 个工具注册
- 9 个 akshare 数据源实战验证均可返回非空数据
- 同花顺问财数据源在 pywencai/API Key 未配置时友好降级（返回空）
- 现有 350+ 测试用例全部通过，无回归

### 升级指引
- `pip install -e . --force-reinstall --no-deps` 重新安装 tradex 包
- 如需使用同花顺问财查询工具：`pip install pywencai`（需 Node.js v16+）
- 如需使用同花顺问财新闻搜索：设置环境变量 `IWENCAI_API_KEY`
- 新工具均在 MCP 客户端重启后自动加载

## [3.2.0] - 2026-08-03

### Added
- **新闻资讯数据源增强：3 个直连数据源**
  - `em_news_direct`：东财 search-api-web JSONP 直连个股新闻，替代 akshare 间接调用
  - `cls_telegraph`：财联社 cls.cn 实时电报，获取全市场 7×24 小时财经快讯
  - `cninfo_direct`：巨潮 cninfo.com.cn 官方全量公告，证监会指定信息披露平台
- **新增 MCP 工具**：`get_telegraph_news`（第 90 个工具）— 全市场实时财经快讯
- **新增数据类型**：`telegraph_news`（实时电报）、`cninfo_announcement`（全量公告）
- **数据源矩阵扩展**：从 25 个数据类型增加到 27 个

### Changed
- **get_stock_news**：数据源从 akshare 间接调用改为 em_news_direct 直连，akshare 降为备源
- **get_company_announcements**：数据源从 akshare 间接调用改为 cninfo_direct 直连
- **search_news**：全市场搜索新增财联社快讯和巨潮公告作为搜索源，搜索源顺序：财联社快讯 → 巨潮公告 → 财新网 → CCTV

### 验证
- `python -m tradex` 启动：90 个工具注册
- `get_stock_news("600519")`：返回东财直连个股新闻
- `get_telegraph_news()`：返回财联社实时快讯
- `get_company_announcements("600519")`：返回巨潮公告
- `search_news("业绩预增")`：多源合并结果

### 升级指引
- `pip install -e . --force-reinstall --no-deps` 重新安装 tradex 包
- 新工具 `get_telegraph_news` 在 MCP 客户端重启后自动加载

## [3.1.4] - 2026-08-02

### Fixed
- **P1: eltdx realtime_quote 语义不完整**
  - 根因：原实现用 `client.bars.get(count=1)` 取 K 线最后一根作为"实时行情"，缺涨跌幅/涨跌额/昨收/内外盘/现手等实时字段
  - 修复：改用 `client.get_quote()` 获取真正的 `QuoteSnapshot`，字段完整：最新价/昨收/今开/最高/最低/涨跌额/涨跌幅/成交量(手)/成交额/内盘/外盘/现手
- **P1: 装饰器注册机制死代码导致 health_check/list_all_tools 误报**
  - 根因：`ToolRegistry` 设计了 `@register_tool` 装饰器双轨制，但无任何工具使用，`_tools` 字典永远为空
  - 影响：`list_all_tools` 返回 `{"status":"empty","total":0}`；`health_check` 永远报 "无装饰器注册工具" 状态为 `degraded`
  - 修复：`list_all_tools` 和 `health_check` 改为从 `mcp.list_tools()` 获取工具列表（v3.1.4 起）
- **P1: architecture.md 文档与代码不符**
  - 根因：文档描述 `data_sources/smart_router.py` 和 `providers/` 子目录，实际不存在
  - 修复：改为实际的 4 个 fetchers 模块结构（eltdx/akshare/http/astock_signals_fetchers.py），注明 SmartRouter 在 astock_signals 包内
- **P1: 源名标识不准**
  - 根因：`etf_data` / `cb_data` 的源名注册为 `"akshare"`，但 fetcher 实际来自 `astock_signals_fetchers`
  - 修复：源名改为 `"astock_signals"`，监控面板显示更准确
- **P2: _client_lock 线程安全**
  - 根因：`_client_lock` 是布尔值标志，多线程下有竞态条件
  - 修复：改用 `threading.Lock()` + 双重检查模式
- **P2: ETF 列名重复 warning**（astock_signals 包）
  - 根因：`ak.fund_etf_spot_em()` 偶尔返回重复列名，触发 pandas warning
  - 修复：在 rename 前加 `df.loc[:, ~df.columns.duplicated()]` 去重

### 验证
- `python -m pytest tests -q`：334 passed
- `python -m pytest tradex/tests -q`：33 passed, 1 skipped
- 端到端实测 `get_realtime_quote`：返回完整字段（涨跌额-11.16/涨跌幅-0.82/昨收/内盘/外盘/现手）
- 端到端实测 `health_check`：status 从 `degraded` 变为 `healthy`（issues=[]，tools.total=89）
- 端到端实测 `list_all_tools`：status 从 `empty` 变为 `ok`（total=89）

### 升级指引
- `pip install -e . --force-reinstall --no-deps` 重新安装 tradex 包
- astock_signals 包本地源码已修复（editable 安装直接生效），无需重新发版

## [3.1.3] - 2026-08-02

### Fixed
- **P0 bug：SmartRouter 参数名不匹配导致 eltdx 主源永远失败**
  - 根因：`SmartRouter.route(**kwargs)` 原样转发参数，但不同 fetcher 参数名不一致（eltdx 用 `code=`，akshare/http 行情类用 `symbol=`），导致工具层 `route("realtime_quote", symbol=...)` 传 `symbol=` 时，eltdx fetcher 收到 `code=""` 失败，SmartRouter 一直降级到 akshare 全量快照（14 秒 vs eltdx 200ms）
  - 修复：所有行情/信号类 fetcher 同时接受 `symbol` 和 `code`，内部归一化（`code = code or symbol` 或 `symbol = symbol or code`）
  - 影响 fetcher：`eltdx_fetchers.py`（6 函数）、`akshare_fetchers.py`（3 函数）、`http_fetchers.py`（2 函数）、`astock_signals_fetchers.py`（8 函数）
- **P0 bug：eltdx KlineBar 字段映射错误**
  - 根因：`eltdx_fetchers.py` 用 `getattr(b, "date", None)` 和 `getattr(b, "volume", None)`，但 eltdx 1.2.0 的 `KlineBar` 实际字段是 `time` 和 `volume_lots`
  - 现象：`eltdx_get_kline` 工具返回 `date="None"`、`volume=0.0`
  - 修复：字段映射改为 `time`（日期）和 `volume_lots`（成交量）

### Added
- 新增 `tests/test_fetcher_param_compat.py`：17 个参数归一化回归测试
  - 覆盖 eltdx/akshare/http/astock_signals 四类 fetcher 的 symbol/code 兼容性
  - 覆盖 KlineBar 字段映射（time/volume_lots）
  - 覆盖 SmartRouter 端到端参数路由（含降级场景）

### 验证
- `python -m pytest tests -q`：334 passed（317 旧 + 17 新）
- `python -m pytest tradex/tests -q`：33 passed, 1 skipped
- 端到端实测：`get_realtime_quote(symbol=600519)` 路由到 eltdx 主源（200ms，单股返回，成交量 55127.52）
- 端到端实测：`get_historical_price(symbol=600519)` 路由到 eltdx 主源，日期/成交量字段正确

### 升级指引
- 无需手动操作，`pip install -e . --force-reinstall --no-deps` 重新安装 tradex 包即可
- eltdx 主源现在真正生效，行情类查询性能提升约 70 倍（14s → 200ms）

## [3.1.2] - 2026-08-02

### Removed
- 删除 `src/` 目录（v2.x 遗留死代码）：
  - `src/__init__.py`：引用 `data_manager`，链式依赖已删的 `eltdx_provider`，导致 `import src` 失败
  - `src/data_manager.py`：v2.x 多数据源管理器，引用已删除的 `src/eltdx_provider`（v3.1.0 删除），功能已被 tradex 包的 `data_sources/` + SmartRouter 替代
  - `src/market_analyzer.py`：v2.0 全市场分析引擎，功能已被 tradex 包的 `analysis_engine.py` 等替代
- 版本号 3 处同步调整：`src/__init__.py` 删除后，版本号来源变为 `VERSION` 文件（单一事实来源）+ `tradex/pyproject.toml` + `tradex/src/tradex/__init__.py`（动态读 VERSION）

### Changed
- `tradex/src/tradex/tools/diagnostics.py` 的 `_get_router()`：移除 `from src.astock_signals.smart_router import get_router` 的 fallback 死代码（`src/astock_signals/` 在 v3.1.0 已删除独立成包），简化为直接 `from astock_signals.smart_router import get_router`

### 验证
- `import tradex` 正常（v3.1.2）
- `_get_router()` 返回 SmartRouter 对象（astock_signals 独立包导入正常）
- tests: 317 passed
- tradex/tests: 33 passed, 1 skipped
- 无 warning

### 升级指引
- 无需手动操作，`src/` 目录删除不影响 tradex 包运行（tradex 是独立包）

## [3.1.1] - 2026-08-02

### Fixed
- 注册 pytest `network` marker：消除 tradex/tests 中 4 个 `PytestUnknownMarkWarning`
- 根因：`tradex/pyproject.toml` 有独立 `[tool.pytest.ini_options]`，pytest 运行 tradex/tests 时 rootdir=tradex/ 读取 tradex/pyproject.toml 而非根配置
- 修复：在根 `pyproject.toml` 和 `tradex/pyproject.toml` 同时注册 `markers = ["network: ..."]`

### 升级指引
- 无需手动操作，配置文件随版本更新

## [3.1.0] - 2026-08-02

### BREAKING CHANGES
- 项目改名：仓库目录 `trader-finance-hub` → `tradex-hub`，Python 包 `cn_financial_mcp` → `tradex`，GitHub 仓库名同步
- astock_signals 独立成包：从 `tradex-hub/src/astock_signals/` 独立为 `trae_projects/astock_signals/`（pip install -e 安装）
- 所有 L1 工具走 SmartRouter：L1 数据获取工具不再直接 import akshare/eltdx，统一通过 SmartRouter.route() 选择数据源
- eltdx 升为行情类第一主源：实时行情/历史K线/分时数据，eltdx(TCP) 为主源，akshare 降为备用
- MCP 工具入口变更：`python -m cn_financial_mcp` → `python -m tradex`

### Added
- 数据源看板：MCP 工具 `get_data_source_dashboard` 返回 JSON + HTML 单页可视化（`python -m tradex.dashboard`，端口 8765）
- 数据源版本检查模块 `data_source_monitor.py`：eltdx GitHub release + akshare PyPI 版本检查（只提醒不升级）
- SmartRouter 独占源标记（exclusive=True）：集合竞价/逐笔成交/F10/涨停归因/解禁日历/涨停板 6 个独占源失败不降级
- SmartRouter `get_registry_report()` 方法：返回全量注册表供看板使用
- data_sources 数据源层：akshare_fetchers / eltdx_fetchers / http_fetchers / astock_signals_fetchers / registry，25 数据类型 34 源注册
- HTTP 防封参数环境变量化：EM_RATE_LIMIT_INTERVAL / EM_JITTER_MIN / EM_JITTER_MAX / EM_MAX_RETRY
- anti_ban_client 新增 set_jitter_range() / set_max_retry() 函数

### Changed
- akshare 升级 1.18.80 → 1.18.81
- eltdx 版本标注更新 1.0.2 → 1.2.0
- 25 个数据类型全量注册到 SmartRouter（原仅 3 个）
- 89 个 MCP 工具（原 88，+1 看板工具）
- MCP_HOST 默认值 0.0.0.0 → 127.0.0.1（安全默认）
- trader-data-router 下游适配：删除 sys.path 路径探测，直接 import astock_signals
- quantterminal/tfhub_service.py 迁移：从已删除的 eltdx_provider 改为 eltdx.TdxClient 直调

### Removed
- 删除 `src/eltdx_provider.py` 孤儿模块（v2.0.0 时代老封装，无人调用）
- 删除所有 `sys.path.insert` hack（8 个文件，改正式 import astock_signals）
- 删除 `src/astock_signals/` 旧目录（已迁移为独立包）

### 升级指引
1. `pip install -e trae_projects/astock_signals/`（安装独立包）
2. `pip install -e tradex-hub/tradex/`（重装改名后的 tradex 包）
3. 更新 MCP 配置：server 名改为 `tradex`，args 改为 `["-m", "tradex"]`
4. `pip install -U akshare==1.18.81`
5. 访问数据源看板：`python -m tradex.dashboard`

## [3.0.0] - 2026-08-01

### BREAKING CHANGES
- 版本号统一：tradex v2.5.1 → v3.0.0，astock_signals v0.4.0 → v1.0.0，新增 VERSION 文件作为单一事实来源
- 模块激活：smart_router / tick_store / ws_server 从"独立僵尸"变为"主流程组件"
- 代码重复消除：删除 utils/em_client.py，统一使用 astock_signals.anti_ban_client
- 文件拆分：signal_data.py 拆分为 5 个子模块（signal_data_base/flow/etf/cb/board）
- 安全默认值：MCP_HOST 默认值从 0.0.0.0 改为 127.0.0.1

### Added
- VERSION 文件作为版本号单一事实来源
- L2 计算引擎层：technical_indicators（6 工具）、performance_metrics（2 工具）
- L3 决策支持层：signal_generation（3）、factor_analysis（2）、stock_screening（2）、diagnostics（4）、composite_analysis（3）、analysis_engine（1）
- smart_router 接入数据源自动选择
- tick_store 接入 eltdx_get_ticks 数据落盘
- ws_server 作为可选推送服务（WS_SERVER_ENABLED 控制）
- anti_ban_client 锁内 sleep 并发修复
- tests/test_anti_ban_client.py 并发测试

### Changed
- 旧代码原地重构：data_manager.py / market_analyzer.py / eltdx_provider.py（print→logging、Type Hint、except 细化）
- architecture.md 升级到 v3.0.0，补充 L2/L3 三层架构说明
- README.md 工具数纠正为 88

### Fixed
- em_client.py 与 anti_ban_client.py 代码重复导致节流计数分裂
- anti_ban_client.em_get 锁内 sleep 高并发阻塞
- MCP_HOST 默认 0.0.0.0 公网暴露风险
- architecture.md 严重过时（v2.3.0）
- README 工具数不一致（80 vs 实际 88）

### Removed
- utils/em_client.py（与 anti_ban_client.py 重复）
- 硬编码版本号（改为从 VERSION 文件读取）

### 升级指引
- 从 v2.5.1 升级到 v3.0.0 注意事项：
  1. 如果代码 import 了 em_client，改为 import astock_signals.anti_ban_client
  2. MCP_HOST 默认改为 127.0.0.1，外网部署需显式设置 MCP_HOST=0.0.0.0
  3. signal_data.py 已拆分为 5 个子模块，但兼容入口保留，旧 import 仍可用
  4. astock_signals __version__ 从 0.4.0 升到 1.0.0

## [2.5.1] - 2026-08-01

### Added
- eltdx K线数据接口：新增 `KlineBar`/`KlineData` 数据类 + `get_kline()` 方法（通达信TCP协议直连）
- `.coverage` 加入 `.gitignore`

### Fixed
- 修复 eltdx_provider.py 缺少 K 线数据获取能力

## [2.5.0] - 2026-07-26

### Added - 智能决策中台升级（15个新工具）
本次升级将 Trader Finance Hub 从「数据中台」升级为「智能决策中台」，
新增量化计算工具组（quant_tools），提供技术指标计算、绩效分析、
信号生成、因子分析、条件选股五大能力。

#### P0：技术指标计算模块（6个工具）— `technical_indicators.py`
- `calculate_ma_ema` - MA/EMA 均线计算（纯函数，输入价格数组）
- `calculate_macd` - MACD 指标计算（DIF/DEA/MACD柱）
- `calculate_kdj` - KDJ 随机指标（K/D/J值）
- `calculate_rsi` - RSI 相对强弱指数（Wilder 平滑法）
- `calculate_boll` - BOLL 布林带（含带宽/%B）
- `calculate_atr` - ATR 平均真实波幅

#### P0：绩效指标计算模块（2个工具）— `performance_metrics.py`
- `calculate_performance` - 完整绩效报告（21项指标）
  覆盖收益/风险/风险调整收益/交易质量/费用统计/基准对比
- `list_performance_metrics` - 绩效指标清单查询

#### P1：信号生成模块（3个工具）— `signal_generation.py`
- `generate_trading_signal` - 单票信号（5级信号+评分+多指标组合）
- `scan_stocks_for_signals` - 批量扫描信号（按评分排序）
- `validate_signal_quality` - 信号前瞻收益验证

#### P2：因子分析模块（2个工具）— `factor_analysis.py`
- `calculate_factor_score` - 多因子综合评分（5类22因子，Z-Score标准化）
- `get_factor_catalog` - 因子库清单查询

#### P2：条件选股模块（2个工具）— `stock_screening.py`
- `screen_stocks` - 条件选股扫描（5类30+条件，AND组合）
- `get_screening_conditions` - 选股条件清单查询

### Changed
- `server.py`: 注册5个新工具模块，工具总数 65 → 80
- 升级定位：从「数据中台」升级为「智能决策中台」
- 架构升级：新增「计算引擎层」(L2) 和「决策支持层」(L3)

### Fixed
- 修正 README.md 工具数不一致问题（实际65个，README标61个）

## [2.4.0] - 2026-07-23

### Fixed
- 修复6个核心接口失败问题（东财风控导致的 Connection aborted）
- get_money_flow: 改用东财push2直连API，保留AKShare兜底
- get_market_overview: 改用新浪财经作为主源，东财兜底
- get_sector_fund_flow: 增加同花顺作为备用数据源
- get_technical_indicator: K线数据源增加腾讯备用
- get_north_bound_flow: 添加日期排序，确保最新数据在前
- get_margin_trading: 增加东财市场汇总接口作为主源

### Changed
- 新增 em_client.py: 从astock_signals提取东财push2防封客户端到MCP utils
- astock_signals/__init__.py: ETF/可转债模块改为延迟导入，避免akshare缺失导致整个包无法导入
- 工具总数: 61 → 65（新增3个涨停板工具）

## [2.3.2] - 2026-06-29

### Changed
- 清理 workbuddy 遗留路径，4个硬编码文件改为相对路径/项目目录
- 删除 .workbuddy/ 目录及遗留文件
- 更新 config/mcp-servers.json，移除 WorkBuddy 引用
- 新增 limit_up_board.py 涨停板分析模块

## [2.3.1] - 2026-06-24

### Fixed
- 修复文档与代码不一致的4个高优先级问题
- 修复README.md版本/工具数与代码不一致（57→61工具）
- 修复architecture.md架构文档严重过时，全面更新为当前架构
- 修复signal_data.py内部注释不一致（工具数量和编号）
- 修复astock_signals/__init__.py模块清单不全（11→14个模块）
- 修复tradex/README.md严重过时（42→61工具）
- 修复tradex/tests/test_server.py测试过时（42→61工具）
- 修复README.md数据源描述不准确（AKShare 50→56工具）

### Changed
- 文档全面更新，准确反映v2.3.0版本的实际架构
- 测试用例更新，验证61个工具的正确注册
- 新增文档修复报告（docs/documentation-fix-report.md）

## [2.3.0] - 2026-06-24

### Added
- 新增 `astock_signals/etf.py` — ETF 数据模块（实时行情/历史K线/ETF列表，AKShare fund_etf_spot_em/fund_etf_hist_em/fund_etf_category_sina）
- 新增 `astock_signals/convertible_bond.py` — 可转债数据模块（实时行情/价值分析/比价表/详情，AKShare bond_zh_cov/bond_zh_cov_value_analysis/bond_cov_comparison/bond_zh_cov_info）
- 新增 `astock_signals/smart_router.py` — 智能路由引擎（健康评分/自动降级/延迟感知/故障隔离）
- 新增 `astock_signals/tick_store.py` — Tick 数据本地存储（SQLite WAL模式/分表/去重/时间过滤）
- 新增 `astock_signals/ws_server.py` — WebSocket 实时推送服务器（行情/异动/tick推送，按代码订阅）
- 新增 4 个 MCP 工具：`get_etf_realtime_data` / `get_etf_kline_data` / `get_cb_realtime_data` / `get_cb_value_analysis_data`
- Router 新增 3 个 thin CLI 命令：`etf` / `cb` / `tickstore`（14 → 17 命令）
- 新增 69 个 pytest 测试用例，全部通过

### Changed
- astock_signals 版本 0.2.0 → 0.3.0，模块数 9 → 14（含 smart_router/tick_store/ws_server）
- tradex 版本 2.2.0 → 2.3.0，MCP 工具数 57 → 61（信号数据 10 → 14）
- signal_data.py V0.7 → V0.8，工具数 10 → 14

### Testing
- 测试套件：69 个测试用例，0 失败
- 覆盖率：新模块 80-91%（smart_router 91%、tick_store 90%、etf 81%、convertible_bond 89%）

## [2.2.0] - 2026-06-23

The format is based on [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/lang/zh-CN/).

### Added
- 新增 `astock_signals/northbound.py` — 北向资金流向模块（同花顺 hsgtApi，含本地 CSV 缓存历史）
- 新增 `astock_signals/fund_flow.py` — 个股资金流向模块（东财 push2 实时 + push2his 历史 20 天）
- 新增 `astock_signals/dragon_tiger.py` — 龙虎榜席位明细模块（东财 datacenter，含机构动向）
- 新增 `astock_signals/industry.py` — 行业横向对比模块（东财 push2 行业排名）
- 新增 4 个 MCP 工具：`get_northbound_flow_signal` / `get_fund_flow_signal` / `get_dragon_tiger_signal` / `get_industry_comparison_signal`
- 所有新模块均提供 `_json` 版本返回结构化 dict，供 MCP 工具和 CLI 共用

### Changed
- `astock_signals/__init__.py` 版本升至 0.2.0，导出 9 个模块（原 5 → 现 9）
- `signal_data.py` 版本升至 V0.7，工具数从 6 增至 10
- `tradex` 版本升至 2.2.0，MCP 工具总数 53 → 57
- README 更新工具清单和版本历史

### Architecture
- 一主一备架构落地：AKShare 版 money_flow / north_bound / dragon_tiger 为主力源，astock_signals 东财直连为备用源
- 新模块复用 `anti_ban_client` 的 `em_get` / `em_datacenter` / `em_push2_fund_flow` / `em_push2his_fund_flow`，统一封控

## [2.1.0] - 2026-06-22

### Added
- 新增 `astock_signals/` 信号数据模块（5个文件），移植自 TradingAgents-astock 项目
- `anti_ban_client.py` — 东方财富 HTTP 防封限流客户端（Session 复用 + 串行限流 + 随机抖动）
- `hot_money.py` — 涨停归因接口（同花顺 editorial，含主题频次统计）
- `lockup.py` — 限售解禁日历接口（东财 datacenter RPT_LIFT_STAGE，含风险提示）
- `concept.py` — 个股概念/行业/地域板块归属（push2delay 镜像 + 地域板块反查策略）
- `indicators.py` — 13种技术指标计算（MACD/RSI/Boll/ATR/KDJ/MFI 等，stockstats 引擎）
- 新增 6 个 MCP 工具：`get_hot_stocks` / `get_lockup_expiry` / `get_concept_attribution` / `get_profit_forecast` / `get_technical_indicator` / `list_technical_indicators`
- `get_profit_forecast` 支持分析师一致预期 EPS + Forward PE + PEG + PE 消化年限

### Changed
- `server.py` 注册 signal_data 工具模块（53 工具全部就绪）
- 清理 `server.py` 中误导性的 V0.x 内部注释，改为中文功能描述

### Fixed
- `get_profit_forecast` 从 `pd.read_html`（JS 渲染 SPA 解析失败）改为正则精准匹配 `<thead>/<tbody>`

## [2.0.0] - 2026-06-01

### Added
- 集成eltdx通达信行情协议，提供独有数据源
- 新增集合竞价数据接口（开盘前竞价撮合详情）
- 新增逐笔成交数据接口（每笔成交明细）
- 新增F10资料数据接口（公司概况/热点题材/财务诊断）
- 新增开盘前分析模块（基于集合竞价数据预判热点板块）
- 新增资金流向分析模块（基于逐笔成交识别主力资金动向）
- 新增个股筛选模块（基于F10资料快速筛选投资价值）
- 更新数据源矩阵，新增eltdx独有数据源对比表
- 更新CLI命令，新增eltdx独有数据分析命令

### Changed
- 优化智能路由策略，独有数据类型（竞价/逐笔/F10）固定使用eltdx
- 更新数据源评分模型，考虑独有数据源的不可替代性
- 完善项目文档，添加eltdx独有数据源说明

### Technical Details
- eltdx集成版本：1.0.2
- eltdx许可：仅限个人学习、协议研究和非商业研究使用
- 竞价数据延迟：~114ms
- 逐笔成交延迟：~150ms
- F10资料延迟：~200ms

### Notes
- eltdx提供腾讯接口无法覆盖的独有数据类型
- 独有数据对T0日内交易有重要价值
- 保持对原有数据源（腾讯/Wind/东财）的兼容

## [1.0.0] - 2026-05-01

### Added
- 初始版本发布
- 多源MCP数据聚合平台架构
- 智能路由系统（trader-data-router）
- 本地知识库（SQLite+语义搜索）
- 定时任务系统
- 统一MCP协议层
- 支持通达信MCP、Wind MCP、东财MCP、腾讯接口
- 全市场综合分析引擎（market_analyzer.py）
- 新闻聚合引擎（4源聚合）
- 同花顺数据集成（29个THS函数）
- 分析模型：四象限、信息熵、情绪时钟
- CLI命令行工具
- 完整的项目文档和使用示例
- Apache-2.0开源许可证

### Technical Details
- Python 3.10+兼容
- MCP协议1.0支持
- 数据源覆盖：A股、宏观、行业
- 分析模型：四象限、熵共识、情绪时钟