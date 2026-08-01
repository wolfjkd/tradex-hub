# tradex-hub v3.1.0 检查清单

> 发布前自检，全部 ✓ 方可发版。

## 改名完整性

- [ ] 仓库目录已改名 tradex-hub
- [ ] Python 包目录已改名 tradex（cn_financial_mcp 不再存在）
- [ ] `python -m tradex` 正常启动，88 工具注册
- [ ] server name 为 `tradex`
- [ ] 项目内无 `cn_financial_mcp` / `cn-financial-mcp` 残留引用
- [ ] 项目内无 `trader-finance-hub` 残留引用（除历史 CHANGELOG 条目）
- [ ] MCP 配置 2 份已更新（.trae-cn/mcp.json + Trae CN User/mcp.json）
- [ ] config/mcp-servers.json 已更新
- [ ] trader-data-router 无 `trader-finance-hub/src` 路径硬编码

## astock_signals 独立包

- [ ] trae_projects/astock_signals/ 独立目录存在
- [ ] astock_signals/pyproject.toml 存在（name=astock_signals, version=1.1.0）
- [ ] `pip install -e astock_signals/` 安装成功
- [ ] `python -c "import astock_signals"` 在任意目录可用
- [ ] tradex-hub/src/astock_signals/ 旧目录已删除
- [ ] 项目内无 `sys.path.insert` 路径 hack 残留
- [ ] eltdx_provider.py 孤儿已删除

## 数据源升级

- [ ] akshare 版本 1.18.81
- [ ] pyproject.toml 依赖 `akshare>=1.18.81`
- [ ] eltdx 版本标注为 1.2.0（无 1.0.2 残留）
- [ ] eltdx 1.2.0 API 兼容性验证通过

## 智能路由全量覆盖

- [ ] SmartRouter 支持 exclusive 独占源标记
- [ ] 25 个数据类型全部注册到 SmartRouter
- [ ] 独占源（call_auction/tick_data/f10_profile/hot_money/lockup_expiry/limit_up_board）失败不降级
- [ ] 多源数据类型（fund_flow/dragon_tiger/industry_comparison/northbound 等）降级正常
- [ ] 北向资金 akshare 备用已接入
- [ ] eltdx 为行情类第一主源（realtime_quote/historical_kline/minute_data）
- [ ] HTTP 直连源 priority=200+ 作为兜底

## HTTP 防封可配置

- [ ] anti_ban_client 防封参数支持环境变量配置
- [ ] 默认值与 v3.0.0 行为一致
- [ ] .env.example 已添加新环境变量说明

## 数据源看板

- [ ] MCP 工具 get_data_source_dashboard 返回完整 JSON
- [ ] HTML 看板可视化渲染正常
- [ ] 看板显示数据源状态/健康评分/延迟/成功率/版本/独占标记
- [ ] 看板自动刷新（30s）
- [ ] 版本检查模块工作正常（eltdx GitHub + akshare PyPI）
- [ ] 版本检查只提醒不自动升级

## 文档与规则同步

- [ ] VERSION = 3.1.0
- [ ] tradex/pyproject.toml version=3.1.0
- [ ] astock_signals/pyproject.toml version=1.1.0
- [ ] README.md 更新（项目名/包名/工具数/数据源矩阵）
- [ ] architecture.md 更新（v3.1.0/数据源矩阵/SmartRouter 全量/看板）
- [ ] CHANGELOG.md 添加 v3.1.0 条目（含升级指引）
- [ ] AGENTS.md 更新（项目名/包名引用）
- [ ] MEMORY.md 更新（版本汇总/架构图/数据源优先级表）
- [ ] project_dir_rule.md 更新（目录结构）
- [ ] user_profile.md 更新（工具链引用）
- [ ] github_repos.md 更新（仓库名）
- [ ] project_memory.md 更新（新约束/约定）

## 测试回归

- [ ] 全量 pytest 通过（350+ 用例 + 新增测试）
- [ ] MCP 协议层验证通过（initialize/tools/list/tools/call）
- [ ] 数据源实战验证（eltdx 主源/akshare 备用/独占源失败）
- [ ] 看板功能验证
- [ ] trader-data-router 下游验证

## 版本发布

- [ ] git commit 完成
- [ ] git tag v3.1.0
- [ ] git remote URL 更新（tradex-hub）
- [ ] git push + push tag
- [ ] GitHub 仓库改名（老板手动）
- [ ] GitHub Release v3.1.0 发布（含 Release Notes）
- [ ] GitHub 仓库描述更新
