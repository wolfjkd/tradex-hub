# tradex-hub v3.1.0 任务拆分

> 共 9 个阶段 / 42 个任务。阶段间存在依赖，需顺序执行；阶段内任务可并行。

## 阶段 0：准备与备份

- [ ] T0.1 创建 git 分支 `refactor/v3.1.0`
- [ ] T0.2 备份当前 v3.0.0 状态（git tag v3.0.0 已存在，确认）
- [ ] T0.3 记录当前 350 测试全绿基线，作为回归对照

## 阶段 1：astock_signals 独立成包

> 先做此阶段，后续改名和 sys.path 清理都依赖它。

- [ ] T1.1 创建 `trae_projects/astock_signals/` 目录
- [ ] T1.2 将 `tradex-hub/src/astock_signals/` 全部内容迁移到 `trae_projects/astock_signals/src/astock_signals/`
- [ ] T1.3 创建 `trae_projects/astock_signals/pyproject.toml`（name=astock_signals, version=1.1.0, 依赖 akshare/eltdx/requests 等）
- [ ] T1.4 `pip install -e trae_projects/astock_signals/` 安装独立包
- [ ] T1.5 验证 `python -c "import astock_signals; print(astock_signals.__version__)"` 在任意目录可用
- [ ] T1.6 删除 `tradex-hub/src/astock_signals/` 旧目录（已迁移）
- [ ] T1.7 清理 `tradex-hub/src/` 下 `eltdx_provider.py` 孤儿模块（同时完成阶段3的孤儿删除）

## 阶段 2：项目改名 tradex-hub / tradex

> 改名工程，涉及代码/配置/文档/规则全量同步。

### 2A 代码与包结构改名
- [ ] T2.1 仓库目录改名 `trader-finance-hub` → `tradex-hub`（本地 git mv）
- [ ] T2.2 Python 包目录改名 `cn-financial-mcp/src/cn_financial_mcp/` → `tradex/src/tradex/`
- [ ] T2.3 更新 `tradex/pyproject.toml`：name=tradex, packages=["src/tradex"]
- [ ] T2.4 全局替换所有 `from cn_financial_mcp` → `from tradex`、`import cn_financial_mcp` → `import tradex`（项目内 43 文件 169 处）
- [ ] T2.5 更新 `tradex/src/tradex/__main__.py` 入口
- [ ] T2.6 更新 `tradex/src/tradex/server.py` 中 server name 为 `tradex`
- [ ] T2.7 `pip install -e tradex/` 重新安装
- [ ] T2.8 验证 `python -m tradex` 正常启动，88 工具注册

### 2B 去 sys.path hack
- [ ] T2.9 清理 `eltdx_data.py` 的 `sys.path.insert(0, _HUB_SRC)` hack（第32-36行），改直接 `from astock_signals.tick_store import TickStore`
- [ ] T2.10 清理 `signal_data_*.py` 中所有 sys.path hack，改正式 import
- [ ] T2.11 全局搜索 `sys.path.insert` 确认无残留路径 hack

### 2C MCP 配置更新
- [ ] T2.12 更新 `~/.trae-cn/mcp.json`：server 名 tradex，command/args/cwd 指向新路径
- [ ] T2.13 更新 `AppData/Roaming/Trae CN/User/mcp.json`：同上
- [ ] T2.14 更新 `tradex-hub/config/mcp-servers.json`：server 名 tradex
- [ ] T2.15 重启 Trae IDE 验证 MCP 服务加载

### 2D trader-data-router 下游适配
- [ ] T2.16 修改 `skills/trader-data-router/data_router.py`：删除 `_import_astock_signals()` 路径探测，改直接 `import astock_signals`
- [ ] T2.17 更新 trader-data-router 的 SKILL.md/README/CHANGELOG 中 `trader-finance-hub` → `tradex-hub` 引用
- [ ] T2.18 验证 trader-data-router skill 命令正常工作

## 阶段 3：数据源升级

- [ ] T3.1 `pip install -U akshare==1.18.81`，更新 `pyproject.toml` 依赖为 `akshare>=1.18.81`
- [ ] T3.2 更新 `eltdx_data.py` 注释 "基于 eltdx 1.0.2" → "基于 eltdx 1.2.0"
- [ ] T3.3 确认 `eltdx_provider.py` 已在 T1.7 删除
- [ ] T3.4 验证 akshare 1.18.81 回归测试通过
- [ ] T3.5 验证 eltdx 1.2.0 API 兼容性（TdxClient 接口无破坏性变更）

## 阶段 4：智能路由全量重写

> 核心工程，65 个 L1 工具接入 SmartRouter。

### 4A SmartRouter 增强
- [ ] T4.1 SmartRouter 新增 `exclusive` 参数支持独占源标记
- [ ] T4.2 SmartRouter.route() 独占源失败时返回错误不降级
- [ ] T4.3 SmartRouter 新增 `get_registry_report()` 返回全量注册表（供看板用）
- [ ] T4.4 SmartRouter 单元测试：独占源/多源降级/akshare独占/全量注册

### 4B 数据源 fetch_fn 抽取
- [ ] T4.5 为每个数据类型抽取 fetch_fn（eltdx 行情类/akshare 全品类/东财HTTP/同花顺HTTP）
- [ ] T4.6 北向资金新增 akshare 备用 fetch_fn（akshare stock_hsgt_north_net_flow_in）
- [ ] T4.7 实时行情新增腾讯 HTTP 兜底 fetch_fn（可选，profit_forecast 也补腾讯）

### 4C L1 工具接入（按模块分组）
- [ ] T4.8 price_data.py（5工具）接入 SmartRouter：realtime_quote/historical_kline/minute_data 等
- [ ] T4.9 eltdx_data.py（5工具）接入 SmartRouter：call_auction/tick_data/f10_profile 标记 exclusive
- [ ] T4.10 company_info.py（4工具）接入：company_info 注册 akshare 单源
- [ ] T4.11 financial_stmt.py（8工具）接入：financial_stmt 注册 akshare 单源
- [ ] T4.12 valuation.py（4工具）接入：valuation 注册 akshare 单源
- [ ] T4.13 industry.py（5工具）接入：industry_data 注册 akshare 单源
- [ ] T4.14 market.py（5工具）接入：market_overview/northbound 等注册多源
- [ ] T4.15 news_events.py（4工具）接入：news_data 注册 akshare 单源
- [ ] T4.16 macro_fx.py（8工具）接入：macro_data 注册 akshare 单源
- [ ] T4.17 signal_data_*.py（17工具）接入：fund_flow/dragon_tiger/industry_comparison 已有，补 northbound/hot_money/lockup_expiry/limit_up_board 等
- [ ] T4.18 验证全部 25 个数据类型注册到 SmartRouter

### 4D 回归
- [ ] T4.19 smart_router 全量集成测试：每个数据类型主源/降级/独占行为
- [ ] T4.20 350 旧测试回归通过

## 阶段 5：HTTP 防封参数可配置

- [ ] T5.1 anti_ban_client 防封参数从硬编码改为读取环境变量（EM_RATE_LIMIT_INTERVAL/EM_JITTER_MAX/EM_MAX_RETRY）
- [ ] T5.2 默认值保持当前行为
- [ ] T5.3 更新 `.env.example` 添加新环境变量说明
- [ ] T5.4 anti_ban_client 单元测试：默认配置/自定义配置

## 阶段 6：数据源看板 + 版本检查

### 6A 版本检查模块
- [ ] T6.1 新增 `tradex/src/tradex/utils/data_source_monitor.py`
- [ ] T6.2 实现 `check_eltdx_version()`：查 GitHub electkismet/eltdx latest release，对比本地
- [ ] T6.3 实现 `check_akshare_version()`：查 PyPI JSON API，对比本地
- [ ] T6.4 实现 `check_all_versions()`：聚合返回所有数据源版本状态
- [ ] T6.5 版本检查单元测试（mock HTTP 响应）

### 6B MCP 看板工具
- [ ] T6.6 新增 MCP 工具 `get_data_source_dashboard`（diagnostics.py 或新模块）
- [ ] T6.7 工具返回 JSON：数据源列表/健康评分/延迟/成功率/版本/可用性/独占标记
- [ ] T6.8 集成 health_check + SmartRouter.get_health_report() + check_all_versions()
- [ ] T6.9 MCP 工具测试

### 6C HTML 可视化看板
- [ ] T6.10 新增 `tradex/dashboard/` 目录，放置 HTML 看板资源
- [ ] T6.11 实现 `dashboard_server.py`：轻量 HTTP 服务，调用 MCP 工具返回 JSON，HTML 前端渲染
- [ ] T6.12 HTML 看板：数据源状态卡片（绿/黄/红）、健康评分、延迟、成功率、版本提醒、独占源标记
- [ ] T6.13 自动刷新（30s）+ 手动刷新按钮
- [ ] T6.14 看板启动脚本 `python -m tradex.dashboard` 或独立入口

## 阶段 7：文档与规则同步

### 7A 项目内文档
- [ ] T7.1 更新 VERSION：3.0.0 → 3.1.0
- [ ] T7.2 更新 README.md：项目名 tradex-hub、包名 tradex、工具数、数据源矩阵
- [ ] T7.3 更新 architecture.md：v3.1.0、数据源矩阵、SmartRouter 全量覆盖、看板说明
- [ ] T7.4 更新 CHANGELOG.md：v3.1.0 条目（Breaking + Added + Changed + Fixed + 升级指引）
- [ ] T7.5 更新 tradex/pyproject.toml version=3.1.0
- [ ] T7.6 更新 astock_signals/pyproject.toml version=1.1.0

### 7B 全局规则与记忆 MD
- [ ] T7.7 更新 `user_rules/AGENTS.md`：trader-finance-hub → tradex-hub，cn-financial-mcp → tradex
- [ ] T7.8 更新 `user_rules/MEMORY.md`：项目名/包名/版本/架构图/数据源优先级表
- [ ] T7.9 更新 `user_rules/project_dir_rule.md`：目录结构 tradex-hub
- [ ] T7.10 更新 `memory/user_profile.md`：工具链引用
- [ ] T7.11 更新 `memory/github_repos.md`：仓库名 wolfjkd/tradex-hub
- [ ] T7.12 更新 `memory/version_control_rules.md`（如有引用）
- [ ] T7.13 更新项目 `project_memory.md`：新约束/约定

## 阶段 8：测试回归

- [ ] T8.1 全量 pytest 回归（目标 350+ 用例全绿 + 新增 smart_router/看板/版本检查测试）
- [ ] T8.2 MCP 协议层验证：`python -m tradex` 启动 + initialize + tools/list（88或89工具）+ tools/call
- [ ] T8.3 数据源实战验证：eltdx 主源行情、akshare 备用降级、独占源失败处理
- [ ] T8.4 看板功能验证：HTML 看板渲染、版本检查提醒、自动刷新
- [ ] T8.5 trader-data-router 下游验证：skill 命令正常调用 astock_signals

## 阶段 9：版本发布

> 需老板确认后执行

- [ ] T9.1 git commit v3.1.0 重构
- [ ] T9.2 git tag v3.1.0
- [ ] T9.3 git remote 更新 origin URL（trader-finance-hub → tradex-hub）
- [ ] T9.4 git push + push tag
- [ ] T9.5 GitHub 仓库改名 trader-finance-hub → tradex-hub（老板在 GitHub 设置手动操作）
- [ ] T9.6 GitHub Release v3.1.0（含 Release Notes + 升级指引）
- [ ] T9.7 astock_signals 独立仓库 GitHub Release v1.1.0（如老板决定独立仓库）
- [ ] T9.8 更新 GitHub 仓库描述
