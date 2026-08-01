# tradex-hub v3.1.0 数据源治理与改名重构 Spec

## Why

v3.0.0 完成架构重构（三层架构 + 僵尸激活 + 代码去重），但数据源层面仍存在 4 类遗留问题：

1. **eltdx 孤儿模块**：`src/eltdx_provider.py`（EltdxProvider 类）是 v2.0.0 时代的老封装，MCP 工具实际用 `eltdx_data.py` 直连 TdxClient 绕过了它。两套 eltdx 封装并存，老的无人调用，是重构未清理干净的遗留。
2. **智能路由覆盖不全**：smart_router 代码完整（健康评分/降级/隔离/延迟感知），但只覆盖 3 个数据类型（fund_flow/dragon_tiger/industry_comparison），全量 12+ 数据类型中大部分未接入，北向资金等 akshare 有接口却没接备用。
3. **包名与项目名不一致 + sys.path hack**：包名 `cn_financial_mcp`（历史遗留，China Financial MCP）与项目名 `trader-finance-hub` 脱节；`eltdx_data.py` 用 `sys.path.insert` hack 方式 import astock_signals，路径硬编码在改名/迁移时全部失效。
4. **无数据源看板与版本检查**：数据源健康度散落在 health_check 工具里，无可视化看板；eltdx/akshare 版本无自动检查，数据源即时性（比项目代码本身更重要）缺乏监控。

本次重构以 v3.1.0 为契机，完成数据源治理、项目改名、智能路由全量覆盖，建立可持续演进的数据源架构基线。

## What Changes

### BREAKING CHANGES

- **项目改名**：仓库目录 `trader-finance-hub` → `tradex-hub`；Python 包 `cn_financial_mcp` → `tradex`；GitHub 仓库名同步
- **astock_signals 独立成包**：从 `tradex-hub/src/astock_signals/` 独立为 `trae_projects/astock_signals/`，加 pyproject.toml，`pip install -e` 安装；去掉所有 `sys.path.insert` hack
- **所有 L1 工具走 smart_router**：L1 数据获取工具不再直接调用 akshare/eltdx，统一通过 SmartRouter.route() 选择数据源
- **eltdx 升为行情类第一主源**：实时行情/历史K线/分时数据 三个品类，eltdx(TCP) 为主源，akshare 降为备用
- **MCP 工具入口变更**：`python -m cn_financial_mcp` → `python -m tradex`

### 非破坏性变更

- akshare 升级 1.18.80 → 1.18.81
- 删除 `src/eltdx_provider.py` 孤儿模块
- eltdx 版本标注更新（1.0.2 → 1.2.0，实际已是 1.2.0，仅修过时标注）
- 新增数据源看板（MCP 工具 + HTML 可视化）
- 新增数据源版本检查（eltdx GitHub release / akshare PyPI，只提醒不升级）
- HTTP 防封参数可配置化（anti_ban_client 限流间隔/抖动幅度从硬编码改为环境变量）

## Impact

- **Affected code**：全部 L1 工具（65 个）+ astock_signals 全部模块（15 个）+ smart_router 重写
- **Affected packages**：cn_financial_mcp → tradex（包目录+pyproject.toml+所有 import）；astock_signals 独立包
- **Affected configs**：2 份 MCP 配置（.trae-cn/mcp.json + Trae CN User/mcp.json）+ config/mcp-servers.json
- **Affected docs**：README.md / architecture.md / CHANGELOG.md / VERSION / 所有模块 docstring
- **Affected global rules**：user_rules/AGENTS.md、user_rules/MEMORY.md、user_rules/project_dir_rule.md、memory/user_profile.md、memory/github_repos.md、memory/version_control_rules.md、项目 project_memory.md
- **Affected downstream**：trader-data-router（Skill 工具）data_router.py 有硬编码路径 `trader-finance-hub/src`，需改为直接 import astock_signals
- **Affected tests**：tests/ + cn-financial-mcp/tests/ 全部用例需回归 + 新增 smart_router 全量测试 + 看板测试
- **GitHub**：仓库名 wolfjkd/trader-finance-hub → wolfjkd/tradex-hub（git remote 更新）

## ADDED Requirements

### Requirement: 项目改名 tradex-hub / tradex

系统 SHALL 将项目仓库目录改名为 `tradex-hub`，Python 包改名为 `tradex`，GitHub 仓库名同步更新。所有代码 import、pyproject.toml、MCP 配置、文档、全局规则与记忆 MD 文档 SHALL 同步更新。

**寓意**：tradex = trade + eXchange（交易交换）+ eXpress（快速）+ 交叉汇聚点（集成中心）；hub = 中心枢纽。tradex-hub = 交易数据集成中心。

#### Scenario: 包导入
- **WHEN** 开发者执行 `python -m tradex`
- **THEN** MCP 服务正常启动，注册 88 个工具，server name 为 `tradex`

#### Scenario: MCP 配置
- **WHEN** Trae IDE 加载 MCP 配置
- **THEN** `~/.trae-cn/mcp.json` 中 server 名为 `tradex`，command 为 `python`，args 为 `["-m", "tradex"]`，cwd 指向新包目录

#### Scenario: 全局规则同步
- **WHEN** 改名完成
- **THEN** AGENTS.md / MEMORY.md / project_dir_rule.md / user_profile.md / github_repos.md 中所有 `trader-finance-hub` → `tradex-hub`，`cn_financial_mcp` → `tradex`，`cn-financial-mcp` → `tradex`

#### Scenario: trader-data-router 下游适配
- **WHEN** trader-data-router skill 调用 astock_signals
- **THEN** 不再通过 `sys.path` 硬编码路径，直接 `import astock_signals`（astock_signals 已独立成包）

### Requirement: astock_signals 独立成包

系统 SHALL 将 `tradex-hub/src/astock_signals/` 独立为 `trae_projects/astock_signals/`，添加 pyproject.toml，通过 `pip install -e` 安装。所有 `sys.path.insert` hack SHALL 移除，改为正式 `import astock_signals`。

#### Scenario: 独立包安装
- **WHEN** 开发者执行 `cd trae_projects/astock_signals && pip install -e .`
- **THEN** astock_signals 作为独立包安装，`import astock_signals` 在任意目录可用

#### Scenario: 去 sys.path hack
- **WHEN** eltdx_data.py 等 MCP 工具需要调用 tick_store
- **THEN** 直接 `from astock_signals.tick_store import TickStore`，不再有 `sys.path.insert(0, _HUB_SRC)` 代码

#### Scenario: trader-data-router 适配
- **WHEN** trader-data-router 的 data_router.py 调用 astock_signals
- **THEN** 删除 `_import_astock_signals()` 函数中的路径探测逻辑，直接 `import astock_signals`

### Requirement: eltdx 第一主源定位 + 孤儿删除

系统 SHALL 将 eltdx（TCP 7709 通达信协议）定位为行情类数据的第一主数据源，覆盖实时行情/历史K线/分时数据三个品类。`src/eltdx_provider.py` 孤儿模块 SHALL 删除。

#### Scenario: 行情类数据优先 eltdx
- **WHEN** 调用实时行情/历史K线/分时数据工具
- **THEN** SmartRouter 优先选择 eltdx 源（priority=1），失败降级 akshare（priority=100）

#### Scenario: 独占数据源
- **WHEN** 调用集合竞价/逐笔成交/F10 资料
- **THEN** 仅 eltdx 源可用（exclusive=True），失败返回错误不降级

#### Scenario: 孤儿删除
- **WHEN** 重构完成
- **THEN** `src/eltdx_provider.py` 不存在，无任何代码 import EltdxProvider

### Requirement: akshare 升级与第二主源定位

系统 SHALL 将 akshare 升级到 1.18.81，定位为第二主数据源（行情类做 eltdx 备用，非行情类做主源）。pyproject.toml 依赖 SHALL 更新为 `akshare>=1.18.81`。

#### Scenario: 版本升级
- **WHEN** 执行 `pip install -U akshare==1.18.81`
- **THEN** akshare 版本为 1.18.81，所有 akshare 工具回归测试通过

#### Scenario: 非行情类主源
- **WHEN** 调用财务报表/估值/行业/新闻/宏观工具
- **THEN** SmartRouter 选择 akshare 源（eltdx 无此能力，akshare 为唯一源）

### Requirement: 智能路由全量重写

系统 SHALL 将所有 L1 数据获取工具（65 个）接入 SmartRouter，每个数据类型注册到 router。独占数据源 SHALL 标记 `exclusive=True`，失败不降级。HTTP 直连源 SHALL 作为最后兜底（priority=200+）。

**完整数据源矩阵**：

| 数据类型 | priority=1 主源 | priority=100 备源 | priority=200 兜底 | exclusive |
|---------|----------------|-------------------|-------------------|-----------|
| realtime_quote 实时行情 | eltdx | akshare | 腾讯HTTP | |
| historical_kline 历史K线 | eltdx | akshare | | |
| minute_data 分时数据 | eltdx | akshare | | |
| call_auction 集合竞价 | eltdx | | | **是** |
| tick_data 逐笔成交 | eltdx | | | **是** |
| f10_profile F10资料 | eltdx | | | **是** |
| company_info 公司信息 | akshare | | | |
| financial_stmt 财务报表 | akshare | | | |
| valuation 估值数据 | akshare | | | |
| industry_data 行业数据 | akshare | | | |
| market_overview 市场总览 | akshare | | | |
| news_data 新闻数据 | akshare | | | |
| macro_data 宏观数据 | akshare | | | |
| etf_data ETF | akshare | | | |
| cb_data 可转债 | akshare | | | |
| fund_flow 个股资金流 | 东财push2 | akshare | | |
| dragon_tiger 龙虎榜 | 东财datacenter | akshare | | |
| industry_comparison 行业对比 | 东财push2 | akshare | | |
| northbound 北向资金 | 同花顺hsgt | akshare | | |
| hot_money 涨停归因 | 同花顺editorial | | | **是** |
| lockup_expiry 解禁日历 | 东财datacenter | | | **是** |
| limit_up_board 涨停板 | 东财push2 clist | | | **是** |
| hot_stocks 热门股 | akshare | | | |
| profit_forecast 盈利预测 | akshare | 腾讯HTTP | | |
| concept_attribution 概念归属 | 东财push2delay | | | |

#### Scenario: 多源降级
- **WHEN** 调用 fund_flow 工具，东财 push2 返回 429
- **THEN** SmartRouter 自动降级到 akshare，记录东财源失败，健康评分下降

#### Scenario: 独占源失败
- **WHEN** 调用 call_auction 工具，eltdx 连接失败
- **THEN** 返回错误，不尝试降级（exclusive=True）

#### Scenario: akshare 独占品类
- **WHEN** 调用 financial_stmt 工具
- **THEN** SmartRouter 选择 akshare 源（唯一注册源），失败返回错误

#### Scenario: 北向资金补备用
- **WHEN** 调用 northbound 工具，同花顺 hsgtApi 不可达
- **THEN** SmartRouter 降级到 akshare 北向资金接口

#### Scenario: 全量注册
- **WHEN** MCP 服务启动
- **THEN** SmartRouter 注册表包含全部 25 个数据类型，每个类型至少 1 个源

### Requirement: HTTP 防封参数可配置

系统 SHALL 将 anti_ban_client 的防封参数（限流间隔/抖动幅度/最大重试）从硬编码改为环境变量配置，默认值保持当前行为。

#### Scenario: 默认配置
- **WHEN** 未设置环境变量
- **THEN** 防封参数使用默认值（与当前行为一致）

#### Scenario: 自定义配置
- **WHEN** 设置 `EM_RATE_LIMIT_INTERVAL=2.0` 等环境变量
- **THEN** anti_ban_client 按自定义参数限流

### Requirement: 数据源看板（MCP 工具 + HTML 可视化）

系统 SHALL 新增 MCP 工具 `get_data_source_dashboard` 返回数据源健康/版本/统计 JSON，同时提供独立 HTML 看板可视化展示。看板 SHALL 调用 health_check + 版本检查模块。

#### Scenario: MCP 工具调用
- **WHEN** AI Agent 调用 `get_data_source_dashboard`
- **THEN** 返回 JSON，包含：数据源列表、每个源的健康评分/延迟/成功率、版本信息、可用性状态

#### Scenario: HTML 看板
- **WHEN** 老板打开 HTML 看板
- **THEN** 可视化展示所有数据源状态（绿/黄/红）、健康评分趋势、延迟、成功率，自动刷新（30s）

#### Scenario: 独占源标记
- **WHEN** 看板渲染集合竞价数据源
- **THEN** 标记为"独占源"，显示"无备用，故障即不可用"

### Requirement: 数据源版本检查（只提醒不升级）

系统 SHALL 新增 `data_source_monitor.py` 模块，定期检查 eltdx（GitHub release）和 akshare（PyPI）的官方最新版本，对比本地版本，有新版时在看板和 health_check 中提醒。系统 SHALL NOT 自动升级任何数据源包。

#### Scenario: eltdx 版本检查
- **WHEN** 看板或 health_check 触发版本检查
- **THEN** 查询 GitHub `electkismet/eltdx` latest release tag，对比本地 1.2.0，有新版则提醒"eltdx 有新版 X.X.X，当前 1.2.0，建议手动升级"

#### Scenario: akshare 版本检查
- **WHEN** 看板或 health_check 触发版本检查
- **THEN** 查询 PyPI `https://pypi.org/pypi/akshare/json` latest version，对比本地版本，有新版则提醒

#### Scenario: 不自动升级
- **WHEN** 检测到新版
- **THEN** 仅提醒，不执行 pip install，避免破坏项目稳定性

## Non-Goals

- 不重构 L2/L3 层（已稳定）
- 不新增 MCP 工具数量（保持 88 个，仅改 smart_router 工具 + 看板工具，看板工具计入 88 之内或新增为 89）
- 不改动 eltdx 本地克隆源码（仅升级 pip 包版本标注）
- 不自动化 GitHub 仓库改名（需老板手动在 GitHub 设置里改）
- 不修改历史自动化任务报告（盘后复盘/早盘准备等历史快照保持原样）

## Version Bump

- VERSION: 3.0.0 → 3.1.0
- astock_signals: 1.0.0 → 1.1.0（独立成包首次发版）
