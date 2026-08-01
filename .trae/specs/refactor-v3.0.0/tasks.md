# Tasks — trader-finance-hub v3.0.0 重构

> **执行原则**:每个任务独立可验证,完成后立即打勾。带 `[P0]` 标记的任务为关键路径,必须优先完成。

## Phase 0:基础准备

- [x] Task 1: 创建重构分支并扫描全项目版本号硬编码位置 [P0]
  - [ ] SubTask 1.1: 创建 git 分支 `refactor/v3.0.0`
  - [ ] SubTask 1.2: 用 Grep 扫描所有硬编码版本号(`v2.5.1` / `v0.4.0` / `2.5.1` / `0.4.0`),输出位置清单
  - [ ] SubTask 1.3: 识别所有 `__version__` 赋值位置
  - **验证**:扫描结果文档化,作为 Task 18 的修改清单

## Phase 1:版本号单一事实来源

- [x] Task 2: 创建 VERSION 文件作为版本号唯一来源 [P0]
  - [ ] SubTask 2.1: 在项目根目录创建 `VERSION` 文件,内容 `3.0.0`
  - [ ] SubTask 2.2: 在 `cn-financial-mcp/src/cn_financial_mcp/__init__.py` 中添加 `__version__` 读取逻辑(读取 VERSION 文件)
  - [ ] SubTask 2.3: 在 `src/astock_signals/__init__.py` 中将 `__version__ = "0.4.0"` 改为读取 VERSION 文件并附加子版本(如 `1.0.0`)
  - [ ] SubTask 2.4: 修改 `pyproject.toml`,通过构建脚本注入版本号
  - **验证**:`python -c "import cn_financial_mcp; print(cn_financial_mcp.__version__)"` 输出 `3.0.0`

## Phase 2:代码重复消除

- [x] Task 3: 合并 em_client.py 与 anti_ban_client.py [P0]
  - [ ] SubTask 3.1: 确定依赖方向 — astock_signals 作为基础设施层,保留 `anti_ban_client.py` 作为唯一实现
  - [ ] SubTask 3.2: 删除 `cn-financial-mcp/src/cn_financial_mcp/utils/em_client.py`
  - [ ] SubTask 3.3: 修改 `cn-financial-mcp/src/cn_financial_mcp/utils/__init__.py` 移除 em_client 导出
  - [ ] SubTask 3.4: 全局搜索 `from ..utils.em_client import` 或 `from cn_financial_mcp.utils.em_client import`,改为 `from astock_signals.anti_ban_client import`
  - [ ] SubTask 3.5: 验证所有调用 em_get/em_push2 的工具仍能正常 import
  - **验证**:`python -c "from cn_financial_mcp.tools.signal_data import register"` 无报错

- [x] Task 4: 修复 anti_ban_client 锁内 sleep 并发问题 [P0]
  - [ ] SubTask 4.1: 重构 `em_get` 函数为"锁内计算等待时间→释放锁→sleep→重新加锁更新时间戳"模式
  - [ ] SubTask 4.2: 添加并发测试用例(10 线程同时调用,验证间隔 ≥ EM_MIN_INTERVAL)
  - **验证**:`pytest tests/test_anti_ban_client.py -v` 全部通过

## Phase 3:僵尸模块激活

- [x] Task 5: smart_router 接入 signal_data 主流程 [P1]
  - [ ] SubTask 5.1: 在 `signal_data_base.py`(拆分后)或 `signal_data.py` 中注册东财/AKShare 双数据源到 SmartRouter
  - [ ] SubTask 5.2: 改造 `get_fund_flow_signal` / `get_dragon_tiger_signal` / `get_industry_comparison_signal` 三个工具,优先走 SmartRouter.route()
  - [ ] SubTask 5.3: 在 `diagnostics.py` 的 `get_data_source_health` 工具中暴露 SmartRouter 健康报告
  - **验证**:手动触发东财接口失败(断网或改 URL),验证自动降级到备用源

- [x] Task 6: tick_store 接入 eltdx_get_ticks 工具 [P1]
  - [ ] SubTask 6.1: 修改 `cn-financial-mcp/src/cn_financial_mcp/tools/eltdx_data.py` 的 `eltdx_get_ticks` 工具
  - [ ] SubTask 6.2: 调用 eltdx 获取逐笔数据后,异步写入 TickStore(不阻塞返回)
  - [ ] SubTask 6.3: 添加缓存逻辑 — 同一天同一股票的请求优先从 TickStore 读取
  - **验证**:调用 `eltdx_get_ticks("600519")` 后,检查 `data/tick_store.db` 有对应记录

- [x] Task 7: ws_server 作为可选推送服务接入 [P1]
  - [ ] SubTask 7.1: 在 `config.py` 添加 `WS_SERVER_ENABLED` / `WS_PORT` / `WS_TOKEN` 配置项
  - [ ] SubTask 7.2: 在 `__main__.py` 启动时根据配置决定是否启动 WsServer
  - [ ] SubTask 7.3: 修改 `signal_data` 工具的涨停/异动检测,触发时通过 WsServer 推送
  - [ ] SubTask 7.4: 修复 `_safe_send` 删 dict 时序问题(标记删除,统一清理)
  - **验证**:设置 `WS_SERVER_ENABLED=true` 启动 MCP,客户端连接 ws://127.0.0.1:8765 可收到推送

## Phase 4:signal_data.py 拆分

- [x] Task 8: 按品种拆分 signal_data.py 为 5 个子模块 [P1]
  - [ ] SubTask 8.1: 创建 `signal_data_base.py` — 迁移 7 个工具(get_hot_stocks / get_lockup_expiry / get_concept_attribution / get_profit_forecast / get_technical_indicator / list_technical_indicators / list_technical_indicators)
  - [ ] SubTask 8.2: 创建 `signal_data_flow.py` — 迁移 4 个工具(get_northbound_flow_signal / get_fund_flow_signal / get_dragon_tiger_signal / get_industry_comparison_signal)
  - [ ] SubTask 8.3: 创建 `signal_data_etf.py` — 迁移 2 个工具(get_etf_realtime_data / get_etf_kline_data)
  - [ ] SubTask 8.4: 创建 `signal_data_cb.py` — 迁移 2 个工具(get_cb_realtime_data / get_cb_value_analysis_data)
  - [ ] SubTask 8.5: 创建 `signal_data_board.py` — 迁移 5 个工具(get_limit_up_board / get_board_sentiment / get_limit_up_insight 及已有的相关工具)
  - [ ] SubTask 8.6: 删除原 `signal_data.py`,或保留为兼容入口(re-export 5 个子模块的 register)
  - [ ] SubTask 8.7: 更新 `tests/test_signal_data_mcp.py` 验证拆分后工具数仍为 17
  - **验证**:`pytest tests/test_signal_data_mcp.py -v` 通过,工具数 17 不变

## Phase 5:旧代码原地重构

- [x] Task 9: data_manager.py 原地重构 [P1]
  - [ ] SubTask 9.1: 全部 `print()` 替换为 `logging.info/debug/warning`
  - [ ] SubTask 9.2: 补全 Type Hint(函数签名、返回值,共 ~15 处)
  - [ ] SubTask 9.3: 18 处 `except Exception` 细化 — 至少添加 `logger.exception()` 保留堆栈
  - [ ] SubTask 9.4: 删除文件末尾的 `if __name__ == "__main__"` 测试代码(已迁移到 tests/)
  - **验证**:`grep -E "^\s*print\(" src/data_manager.py` 无结果

- [x] Task 10: market_analyzer.py 原地重构 [P1]
  - [ ] SubTask 10.1: 全部 `print()` 替换为 `logging`(20+ 处)
  - [ ] SubTask 10.2: 补全 Type Hint
  - [ ] SubTask 10.3: `except Exception` 细化
  - [ ] SubTask 10.4: 删除 `if __name__ == "__main__"` 测试代码
  - **验证**:`grep -E "^\s*print\(" src/market_analyzer.py` 无结果

- [x] Task 11: eltdx_provider.py 原地重构 [P1]
  - [ ] SubTask 11.1: 补全 Type Hint(__init__ / __enter__ / __exit__ 等,共 ~10 处)
  - [ ] SubTask 11.2: 7 处 `except Exception` 细化
  - [ ] SubTask 11.3: 模块文档更新为 v3.0.0 风格
  - **验证**:`grep -E "except\s*:" src/eltdx_provider.py` 无结果

## Phase 6:安全加固

- [x] Task 12: MCP_HOST 默认值统一为 127.0.0.1 [P0]
  - [ ] SubTask 12.1: 修改 `config.py` 第 89 行 `MCP_HOST` 默认值为 `127.0.0.1`
  - [ ] SubTask 12.2: 验证 `__main__.py` 第 32 行默认值已为 `127.0.0.1`(应已一致)
  - [ ] SubTask 12.3: 在 README.md 补充说明"外网访问需显式设置 MCP_HOST=0.0.0.0"
  - **验证**:`python -c "from cn_financial_mcp.config import config; print(config.MCP_HOST)"` 输出 `127.0.0.1`

## Phase 7:文档同步

- [x] Task 13: architecture.md 升级到 v3.0.0 [P1]
  - [ ] SubTask 13.1: 头部版本号改为 v3.0.0,工具数改为 88
  - [ ] SubTask 13.2: 补充 L2 计算引擎层(8 工具)和 L3 决策支持层(7 工具)说明
  - [ ] SubTask 13.3: 补充 diagnostics / composite_analysis / analysis_engine 三个模块说明
  - [ ] SubTask 13.4: 补充 smart_router / tick_store / ws_server 接入主流程的架构图
  - [ ] SubTask 13.5: 更新数据源优先级表(反映 SmartRouter 接入后的自动选择逻辑)
  - **验证**:`docs/architecture.md` 头部版本号与 VERSION 文件一致

- [x] Task 14: README.md 工具数纠正与章节补充 [P1]
  - [ ] SubTask 14.1: 头部版本号改为 v3.0.0,Tools badge 改为 88
  - [ ] SubTask 14.2: 工具清单总数改为 88,signal_data 章节改为 17(原 14)
  - [ ] SubTask 14.3: 补充 diagnostics 章节(4 工具:get_data_source_health / list_all_tools / get_cache_stats / health_check)
  - [ ] SubTask 14.4: 补充 composite_analysis 章节(3 工具:analyze_stock_comprehensive / analyze_industry_comparison / analyze_market_overview)
  - [ ] SubTask 14.5: 补充 analysis_engine 章节(1 工具:analyze_technical)
  - [ ] SubTask 14.6: 版本历史表添加 v3.0.0 条目
  - **验证**:README 中工具总数 = `list_all_tools` 返回值

- [x] Task 15: CHANGELOG.md 添加 v3.0.0 重构说明 [P0]
  - [ ] SubTask 15.1: 添加 v3.0.0 条目,包含 BREAKING CHANGES / Added / Changed / Fixed / Removed
  - [ ] SubTask 15.2: 列出所有破坏性变更(版本号统一、模块激活、em_client 合并、signal_data 拆分、MCP_HOST 默认值)
  - [ ] SubTask 15.3: 添加"升级指引"段落,说明从 v2.5.1 升级的注意事项
  - **验证**:CHANGELOG.md 顶部为 v3.0.0 条目

## Phase 8:测试体系补齐

- [x] Task 16: 为 technical_indicators 补纯函数单测 [P1]
  - [ ] SubTask 16.1: 创建 `tests/test_technical_indicators_calc.py`
  - [ ] SubTask 16.2: 测试 `_sma` / `_ema` 已知输入输出对(手算 5 组数据)
  - [ ] SubTask 16.3: 测试 `calculate_ma_ema` 工具的 type 参数(sma/ema/both)
  - [ ] SubTask 16.4: 测试 `calculate_macd` 与通达信对拍(可用历史数据)
  - [ ] SubTask 16.5: 测试 `calculate_kdj` / `calculate_rsi` / `calculate_boll` / `calculate_atr` 边界情况(空数组/数据不足)
  - **验证**:`pytest tests/test_technical_indicators_calc.py -v` 全部通过

- [x] Task 17: 为 performance_metrics / signal_generation / factor_analysis / stock_screening 补单测 [P1]
  - [ ] SubTask 17.1: 创建 `tests/test_performance_metrics_calc.py` — 测试 calculate_performance 21 项指标
  - [ ] SubTask 17.2: 创建 `tests/test_signal_generation.py` — 测试 generate_trading_signal 5 级信号
  - [ ] SubTask 17.3: 创建 `tests/test_factor_analysis.py` — 测试 calculate_factor_score Z-Score 标准化
  - [ ] SubTask 17.4: 创建 `tests/test_stock_screening.py` — 测试 screen_stocks 条件组合
  - **验证**:`pytest tests/test_performance_metrics_calc.py tests/test_signal_generation.py tests/test_factor_analysis.py tests/test_stock_screening.py -v` 全部通过

- [x] Task 18: 集成测试 — SmartRouter / TickStore / WsServer [P1]
  - [ ] SubTask 18.1: 创建 `tests/test_smart_router_integration.py` — 测试数据源自动降级
  - [ ] SubTask 18.2: 创建 `tests/test_tick_store_integration.py` — 测试 eltdx_get_ticks 数据落盘
  - [ ] SubTask 18.3: 创建 `tests/test_ws_server_integration.py` — 测试 WebSocket 启停与推送
  - **验证**:三个集成测试通过

- [x] Task 19: 测试覆盖率达标 [P1]
  - [ ] SubTask 19.1: 安装 `pytest-cov`
  - [ ] SubTask 19.2: 运行 `pytest --cov=cn_financial_mcp --cov=astock_signals --cov-report=term-missing`
  - [ ] SubTask 19.3: 识别覆盖率 < 80% 的模块,补充测试用例
  - [ ] SubTask 19.4: 在 `pyproject.toml` 添加 `[tool.pytest.ini_options]` 配置覆盖率阈值
  - **验证**:整体覆盖率 ≥ 80%,L2/L3 新模块 ≥ 90%

## Phase 9:发版

- [x] Task 20: 全量回归测试 [P0]
  - [ ] SubTask 20.1: 运行 `pytest tests/ -v` — 93 个旧用例全部通过
  - [ ] SubTask 20.2: 运行 `pytest cn-financial-mcp/tests/ -v` — 27 个旧用例全部通过
  - [ ] SubTask 20.3: 运行新增的所有测试文件 — 全部通过
  - [ ] SubTask 20.4: 手动启动 MCP server,调用 `list_all_tools` 确认 88 个工具可见
  - [ ] SubTask 20.5: 验证 trader-data-router(Skill 工具)动态导入 astock_signals 不报错
  - **验证**:测试报告 0 失败 0 错误

- [ ] Task 21: 创建 git tag v3.0.0 [P0]
  - [ ] SubTask 21.1: 合并 `refactor/v3.0.0` 到 main
  - [ ] SubTask 21.2: 创建 git tag `v3.0.0`
  - [ ] SubTask 21.3: 推送 tag 到远程
  - **验证**:`git tag -l v3.0.0` 存在

- [ ] Task 22: 创建 GitHub Release v3.0.0 [P0]
  - [ ] SubTask 22.1: 在 GitHub 创建 Release,tag 为 v3.0.0
  - [ ] SubTask 22.2: Release Notes 引用 CHANGELOG.md 的 v3.0.0 条目
  - [ ] SubTask 22.3: 添加"升级指引"段落
  - **验证**:GitHub Release 页面可见 v3.0.0

# Task Dependencies

- **Task 2**(VERSION 文件)→ **Task 13/14/15**(文档同步)— 文档需引用新版本号
- **Task 3**(em_client 合并)→ **Task 5**(SmartRouter 接入)— SmartRouter 需要统一的数据源客户端
- **Task 4**(锁内 sleep 修复)→ **Task 5**(SmartRouter 接入)— 高并发依赖修复后的限流
- **Task 8**(signal_data 拆分)→ **Task 5/6**(SmartRouter / TickStore 接入)— 接入点在拆分后的子模块
- **Task 16-19**(测试)可与 **Task 9-12**(旧代码重构/安全加固)**并行**
- **Task 20**(回归测试)依赖所有前置任务完成
- **Task 21-22**(发版)依赖 Task 20 通过

# Parallelizable Work

以下任务组可并行执行:
- **Group A**(Phase 1-2):Task 2 + Task 3 + Task 4(版本号 + em_client + 锁修复)
- **Group B**(Phase 5):Task 9 + Task 10 + Task 11(三个旧文件重构,互不依赖)
- **Group C**(Phase 8):Task 16 + Task 17 + Task 18(测试编写,互不依赖)
- **Group D**(Phase 7):Task 13 + Task 14 + Task 15(文档同步,互不依赖)
