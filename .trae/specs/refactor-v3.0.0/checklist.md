# Checklist — trader-finance-hub v3.0.0 重构验证

> **使用说明**:每个检查点验证完成后打勾。所有检查点必须通过才能发版。

## Phase 1:版本号单一事实来源

- [ ] `VERSION` 文件存在于项目根目录,内容为 `3.0.0`
- [ ] `cn_financial_mcp/__init__.py` 的 `__version__` 从 VERSION 文件读取,值为 `3.0.0`
- [ ] `astock_signals/__init__.py` 的 `__version__` 改为 `1.0.0`
- [ ] `pyproject.toml` 版本号同步为 `3.0.0`
- [ ] 全项目搜索无硬编码 `v2.5.1` / `v0.4.0` / `2.5.1` / `0.4.0`(除 CHANGELOG.md 历史记录外)
- [ ] `python -c "import cn_financial_mcp; print(cn_financial_mcp.__version__)"` 输出 `3.0.0`

## Phase 2:代码重复消除

- [ ] `cn-financial-mcp/src/cn_financial_mcp/utils/em_client.py` 已删除
- [ ] `cn-financial-mcp/src/cn_financial_mcp/utils/__init__.py` 不再导出 em_client
- [ ] 全项目搜索无 `from ..utils.em_client import` 或 `from cn_financial_mcp.utils.em_client import`
- [ ] `python -c "from cn_financial_mcp.tools.signal_data import register"` 无报错
- [ ] `python -c "from cn_financial_mcp.tools.market import register"` 无报错
- [ ] `anti_ban_client.em_get` 不再在锁内 sleep
- [ ] 10 线程并发调用 `em_get` 测试通过,实际间隔 ≥ `EM_MIN_INTERVAL`

## Phase 3:僵尸模块激活

### smart_router 接入
- [ ] `signal_data_flow.py`(或 signal_data.py)中注册了东财/AKShare 双数据源到 SmartRouter
- [ ] `get_fund_flow_signal` 工具走 SmartRouter.route()
- [ ] `get_dragon_tiger_signal` 工具走 SmartRouter.route()
- [ ] `get_industry_comparison_signal` 工具走 SmartRouter.route()
- [ ] `diagnostics.get_data_source_health` 暴露 SmartRouter 健康报告
- [ ] 模拟东财失败时,自动降级到备用源,数据不中断

### tick_store 接入
- [ ] `eltdx_get_ticks` 工具调用后数据自动写入 SQLite
- [ ] `data/tick_store.db` 元数据表有对应 code/trade_date 记录
- [ ] 同一天同一股票的重复请求优先从 TickStore 读取(不发起网络请求)

### ws_server 接入
- [ ] `config.py` 新增 `WS_SERVER_ENABLED` / `WS_PORT` / `WS_TOKEN` 配置项
- [ ] 默认 `WS_SERVER_ENABLED=false`,MCP server 启动时不启动 WebSocket
- [ ] 设置 `WS_SERVER_ENABLED=true` 时,WebSocket 服务器启动
- [ ] `_safe_send` 不再在异常时立即 pop dict,改为标记后统一清理
- [ ] 客户端连接 ws://127.0.0.1:8765 可正常订阅与接收推送

## Phase 4:signal_data.py 拆分

- [ ] `signal_data_base.py` 存在,包含 7 个工具
- [ ] `signal_data_flow.py` 存在,包含 4 个工具
- [ ] `signal_data_etf.py` 存在,包含 2 个工具
- [ ] `signal_data_cb.py` 存在,包含 2 个工具
- [ ] `signal_data_board.py` 存在,包含 5 个工具(含原 limit_up_board 的工具)
- [ ] 原 `signal_data.py` 已删除或改为兼容入口
- [ ] `tests/test_signal_data_mcp.py` 验证拆分后工具数仍为 17
- [ ] `pytest tests/test_signal_data_mcp.py -v` 通过

## Phase 5:旧代码原地重构

### data_manager.py
- [ ] `grep -E "^\s*print\(" src/data_manager.py` 无结果
- [ ] `grep -E "except\s*:" src/data_manager.py` 无结果
- [ ] 所有 public 函数有 Type Hint
- [ ] `if __name__ == "__main__"` 测试代码已删除
- [ ] `except Exception` 处至少有 `logger.exception()`

### market_analyzer.py
- [ ] `grep -E "^\s*print\(" src/market_analyzer.py` 无结果
- [ ] `grep -E "except\s*:" src/market_analyzer.py` 无结果
- [ ] 所有 public 函数有 Type Hint
- [ ] `if __name__ == "__main__"` 测试代码已删除

### eltdx_provider.py
- [ ] `grep -E "except\s*:" src/eltdx_provider.py` 无结果
- [ ] `__init__` / `__enter__` / `__exit__` 等魔术方法有 Type Hint
- [ ] `except Exception` 处至少有 `logger.exception()`
- [ ] 模块文档头部版本号为 v3.0.0 风格

## Phase 6:安全加固

- [ ] `config.py` 中 `MCP_HOST` 默认值为 `127.0.0.1`
- [ ] `__main__.py` 中 `--host` 默认值为 `127.0.0.1`
- [ ] `python -c "from cn_financial_mcp.config import config; print(config.MCP_HOST)"` 输出 `127.0.0.1`
- [ ] README.md 有"外网访问需显式设置 MCP_HOST=0.0.0.0"说明

## Phase 7:文档同步

### architecture.md
- [ ] 头部版本号为 v3.0.0(与 VERSION 文件一致)
- [ ] 工具数为 88
- [ ] 包含 L2 计算引擎层(8 工具)说明
- [ ] 包含 L3 决策支持层(7 工具)说明
- [ ] 包含 diagnostics / composite_analysis / analysis_engine 三个模块说明
- [ ] 包含 smart_router / tick_store / ws_server 接入主流程的架构图
- [ ] 数据源优先级表反映 SmartRouter 接入后的自动选择逻辑

### README.md
- [ ] 头部 Version badge 为 v3.0.0
- [ ] Tools badge 为 88
- [ ] 工具清单总数为 88
- [ ] signal_data 章节工具数为 17
- [ ] 包含 diagnostics 章节(4 工具)
- [ ] 包含 composite_analysis 章节(3 工具)
- [ ] 包含 analysis_engine 章节(1 工具)
- [ ] 版本历史表顶部为 v3.0.0 条目

### CHANGELOG.md
- [ ] 顶部为 v3.0.0 条目
- [ ] 包含 BREAKING CHANGES 段落
- [ ] 包含 Added / Changed / Fixed / Removed 段落
- [ ] 包含"升级指引"段落

## Phase 8:测试体系补齐

- [ ] `tests/test_technical_indicators_calc.py` 存在并通过
- [ ] `tests/test_performance_metrics_calc.py` 存在并通过
- [ ] `tests/test_signal_generation.py` 存在并通过
- [ ] `tests/test_factor_analysis.py` 存在并通过
- [ ] `tests/test_stock_screening.py` 存在并通过
- [ ] `tests/test_smart_router_integration.py` 存在并通过
- [ ] `tests/test_tick_store_integration.py` 存在并通过
- [ ] `tests/test_ws_server_integration.py` 存在并通过
- [ ] `tests/test_anti_ban_client.py` 存在并通过(锁修复后的并发测试)
- [ ] 整体测试覆盖率 ≥ 80%
- [ ] L2/L3 新模块覆盖率 ≥ 90%
- [ ] `pyproject.toml` 包含 `[tool.pytest.ini_options]` 覆盖率阈值配置

## Phase 9:发版前最终验证

- [ ] `pytest tests/ -v` 全部通过(原 66 用例 + 新增用例)
- [ ] `pytest cn-financial-mcp/tests/ -v` 全部通过(原 27 用例)
- [ ] 手动启动 MCP server,`list_all_tools` 返回 88 个工具
- [ ] 手动调用 4 个数据源(AKShare / eltdx / 东财 / 同花顺)各 1 个工具,全部返回数据
- [ ] trader-data-router(Skill 工具)动态导入 astock_signals 无报错
- [ ] git tag `v3.0.0` 已创建并推送
- [ ] GitHub Release v3.0.0 已发布,Release Notes 引用 CHANGELOG
- [ ] 全项目搜索无遗漏的 `v2.5.1` / `v0.4.0` 硬编码(CHANGELOG 历史记录除外)

## 综合质量门控

- [ ] 0 个 P0 问题遗留
- [ ] 0 个 P1 问题遗留(或老板已知悉并批准延后)
- [ ] 所有 BREAKING CHANGES 在 CHANGELOG 中列明
- [ ] 所有新代码有 docstring
- [ ] 所有新函数有 Type Hint
- [ ] 无 `print()` 语句残留(仅 scripts/ 诊断脚本允许)
- [ ] 无 `except Exception` 无 logger 的"吞异常"代码
- [ ] 无硬编码版本号(除 CHANGELOG 历史记录)
