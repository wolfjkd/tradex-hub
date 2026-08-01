# trader-finance-hub v3.0.0 架构重构 Spec

## Why

项目自 v0.1.0 起经过 11 个版本的"缝缝补补、东拼西凑",积累三类根本性问题:

1. **架构臃肿**:三个基础设施模块(smart_router/tick_store/ws_server)代码完整但未接入主流程,形成"僵尸代码";signal_data.py 单文件 800+ 行注册 17 个工具;旧代码(data_manager/market_analyzer/eltdx_provider)与新架构并存,职责重叠。
2. **版本号分裂**:README v2.5.1 / architecture.md v2.3.0 / astock_signals `__version__` v0.4.0,无单一事实来源,各模块各自为战。
3. **代码重复**:`em_client.py` 与 `anti_ban_client.py` 几乎完全重复(5 个函数一字不差),节流计数互相独立导致实际请求频率翻倍。

本次重构以 v3.0.0 大版本为契机,做破坏性清理与统一,建立可持续演进的架构基线。

## What Changes

### BREAKING CHANGES

- **版本号统一**:cn-financial-mcp v2.5.1 → v3.0.0,astock_signals v0.4.0 → v1.0.0
- **模块激活**:smart_router / tick_store / ws_server 从"独立僵尸"变为"主流程组件"
- **代码重复消除**:`utils/em_client.py` 与 `astock_signals/anti_ban_client.py` 合并为一套实现
- **文件拆分**:`signal_data.py` 按品种拆分为 5 个子模块
- **安全默认值**:`MCP_HOST` 默认值从 `0.0.0.0` 改为 `127.0.0.1`

### 非破坏性变更

- 版本号单一事实来源:新增 `VERSION` 文件,所有位置从此处读取
- 旧代码原地重构:print→logging、补 Type Hint、细化 except Exception
- 文档同步:architecture.md 升级到 v3.0.0,README 工具数纠正
- 测试补齐:L2/L3 新增 15 个量化工具补纯函数单测

## Impact

- **Affected code**:全部(88 个 MCP 工具 + 15 个 astock_signals 模块 + 5 个 utils)
- **Affected docs**:README.md / architecture.md / CHANGELOG.md / 所有模块 docstring 中的版本号
- **Affected configs**:pyproject.toml / .mcp.json / config.py
- **Affected tests**:tests/ + cn-financial-mcp/tests/ 全部用例需回归
- **下游影响**:trader-data-router(Skill 工具)动态导入 astock_signals,需验证向后兼容

## ADDED Requirements

### Requirement: 版本号单一事实来源

系统 SHALL 在项目根目录维护 `VERSION` 文件,作为唯一的版本号来源。所有位置(README.md、代码硬编码、`__init__.py`、pyproject.toml)SHALL 通过读取该文件或构建时注入获取版本号,禁止硬编码。

#### Scenario: 版本号查询
- **WHEN** 开发者需要确认项目版本
- **THEN** 查看 `VERSION` 文件即可,所有其他位置版本号与该文件一致

#### Scenario: 版本号变更
- **WHEN** 升级版本号
- **THEN** 只修改 `VERSION` 文件,CI/构建脚本自动同步到所有位置

### Requirement: 僵尸模块激活 — smart_router 接入主流程

系统 SHALL 将 `astock_signals/smart_router.py` 接入 signal_data 工具的数据源选择链路,使其从"独立僵尸"变为"主流程组件"。

#### Scenario: 数据源自动选择
- **WHEN** signal_data 工具调用东财接口失败
- **THEN** SmartRouter 自动降级到备用数据源(AKShare 或同花顺),记录健康评分

#### Scenario: 健康评分感知
- **WHEN** 某数据源连续失败 5 次
- **THEN** 评分归零,后续请求跳过该源,直到定时恢复

### Requirement: 僵尸模块激活 — tick_store 接入 eltdx 逐笔数据

系统 SHALL 在 `eltdx_get_ticks` 工具中集成 `TickStore`,实现逐笔数据自动落盘。

#### Scenario: 逐笔数据自动存储
- **WHEN** 用户调用 `eltdx_get_ticks("600519")`
- **THEN** 数据返回的同时自动写入 SQLite,元数据表记录 code/trade_date/row_count

#### Scenario: 历史数据查询
- **WHEN** 用户再次请求同一天同一股票的逐笔数据
- **THEN** 优先从本地 SQLite 读取,避免重复网络请求

### Requirement: 僵尸模块激活 — ws_server 作为可选推送服务

系统 SHALL 将 `astock_signals/ws_server.py` 作为可选推送服务,通过环境变量 `WS_SERVER_ENABLED=true` 控制启停。

#### Scenario: 默认关闭
- **WHEN** 未设置 `WS_SERVER_ENABLED` 环境变量
- **THEN** WebSocket 服务器不启动,MCP server 正常运行

#### Scenario: 显式启用
- **WHEN** 设置 `WS_SERVER_ENABLED=true` 且 `WS_TOKEN=my_secret`
- **THEN** MCP server 启动时同步启动 WebSocket 服务器,客户端可订阅推送

### Requirement: signal_data.py 按品种拆分

系统 SHALL 将 `signal_data.py`(800+ 行,17 个工具)按品种拆分为 5 个子模块,每个子模块职责单一。

#### Scenario: 拆分后结构
- **WHEN** 查看工具目录
- **THEN** 看到以下文件结构:
  - `signal_data_base.py`(信号数据基础:涨停归因/解禁/概念/预期/技术指标,7 工具)
  - `signal_data_flow.py`(资金流类:北向/个股资金流/龙虎榜/行业对比,4 工具)
  - `signal_data_etf.py`(ETF 类:实时/K线,2 工具)
  - `signal_data_cb.py`(可转债类:实时/价值分析,2 工具)
  - `signal_data_board.py`(涨停板类:涨停池/炸板/跌停/情绪/揭秘,5 工具 — V2.3.2 已存在,本次归位)

#### Scenario: 工具数无损
- **WHEN** 拆分完成后调用 `list_all_tools`
- **THEN** 返回的工具总数与拆分前一致(17 个 signal_data 工具)

### Requirement: em_client 代码重复消除

系统 SHALL 合并 `cn_financial_mcp/utils/em_client.py` 与 `astock_signals/anti_ban_client.py` 为一套实现,消除 5 个重复函数。

#### Scenario: 单一实现
- **WHEN** 查看代码
- **THEN** 东财节流逻辑只有一处实现,另一处通过 import 复用

#### Scenario: 节流计数统一
- **WHEN** MCP 工具与 astock_signals 模块并发调用东财接口
- **THEN** 共享同一个 `_em_last_call` 时间戳,实际请求频率不超过 `EM_MIN_INTERVAL`

### Requirement: 限流锁内 sleep 修复

系统 SHALL 修复 `anti_ban_client.em_get` 的锁内 sleep 问题,改为"锁内计算等待时间→释放锁→sleep→重新加锁更新时间戳"模式。

#### Scenario: 高并发不阻塞
- **WHEN** 10 个线程同时调用 `em_get`
- **THEN** 线程按 `EM_MIN_INTERVAL` 间隔串行执行,但等待期间不持有锁,其他线程可进入计算阶段

### Requirement: 测试体系补齐 — L2/L3 纯函数单测

系统 SHALL 为 v2.5.0 新增的 15 个 L2/L3 量化计算工具补纯函数单元测试,整体测试覆盖率 ≥ 80%。

#### Scenario: 技术指标测试
- **WHEN** 运行 `pytest tests/test_technical_indicators.py`
- **THEN** 6 个工具(MA/EMA/MACD/KDJ/RSI/BOLL/ATR)均有已知输入输出对验证

#### Scenario: 覆盖率达标
- **WHEN** 运行 `pytest --cov=cn_financial_mcp --cov=astock_signals`
- **THEN** 整体覆盖率 ≥ 80%,L2/L3 新模块覆盖率 ≥ 90%

### Requirement: 安全默认值统一

系统 SHALL 将 `MCP_HOST` 默认值统一为 `127.0.0.1`,禁止默认暴露到公网。

#### Scenario: config.py 与 __main__.py 一致
- **WHEN** 查看 `config.py` 和 `__main__.py`
- **THEN** 两处默认值均为 `127.0.0.1`,需要外网访问时通过环境变量显式配置

## MODIFIED Requirements

### Requirement: 旧代码原地重构

`src/data_manager.py` / `src/market_analyzer.py` / `src/eltdx_provider.py` 三个旧文件 SHALL 进行原地重构,不改变对外 API,仅修复内部质量问题。

#### 修改点
- `print()` 语句全部替换为 `logging`
- 补全 Type Hint(函数签名、返回值)
- `except Exception` 细化为具体异常类型,至少添加 `logger.exception()` 保留堆栈
- 模块文档更新为 v3.0.0 风格

#### Scenario: 重构后无 print
- **WHEN** 在三个旧文件中搜索 `^\s*print\(`
- **THEN** 无匹配结果

#### Scenario: 重构后无 bare except
- **WHEN** 在三个旧文件中搜索 `except\s*:`
- **THEN** 无匹配结果

### Requirement: 文档同步

`docs/architecture.md` SHALL 升级到 v3.0.0,补充 L2/L3 三层架构说明、88 个工具完整清单、smart_router/tick_store/ws_server 接入说明。

`README.md` SHALL 修正工具数为实际数量(88),补充 diagnostics / composite_analysis / analysis_engine 三个模块共 8 个工具的章节。

#### Scenario: architecture.md 版本同步
- **WHEN** 查看 `docs/architecture.md` 头部
- **THEN** 版本号为 v3.0.0,工具数为 88

#### Scenario: README 工具数准确
- **WHEN** 查看 `README.md` 工具清单
- **THEN** 工具总数与 `list_all_tools` 返回值一致

## REMOVED Requirements

### Requirement: 硬编码版本号

**Reason**: 版本号分散在 README.md / 代码 / `__init__.py` / pyproject.toml 四处,容易不一致(已发生:README v2.5.1 vs architecture.md v2.3.0)。

**Migration**: 所有硬编码版本号改为从 `VERSION` 文件读取或构建时注入。

### Requirement: utils/em_client.py 独立实现

**Reason**: 与 `astock_signals/anti_ban_client.py` 完全重复,导致节流计数分裂,维护陷阱。

**Migration**: 删除 `utils/em_client.py`,改为 `from astock_signals.anti_ban_client import em_get, em_push2, ...`;或反向:`anti_ban_client.py` 改为 `from cn_financial_mcp.utils.em_client import ...`。选择依赖方向时优先"astock_signals 作为基础设施层,被 MCP utils 依赖"。

### Requirement: MCP_HOST 默认 0.0.0.0

**Reason**: 默认监听所有网卡,HTTP 模式启动时存在公网暴露风险。

**Migration**: 默认改为 `127.0.0.1`,需要外网访问时通过 `MCP_HOST=0.0.0.0` 显式配置。
