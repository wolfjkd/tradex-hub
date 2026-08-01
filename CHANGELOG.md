# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/),

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