# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/lang/zh-CN/).

---

## [3.5.0] - 2026-09-19

**正式发版**：REST API 阶段一（工单 01-13）+ 阶段二（工单 14-23）合并发版。
两阶段以 commit + push 到 master 保住成果（v3.4.0 阶段一、阶段二无独立版本号），本次合并一次性升 MINOR 到 v3.5.0 正式发版。

### Added — REST API 阶段一（双协议架构 + 44 端点）

- **双协议并存（Direction B）**：新增 44 个 `/api/v1/*` REST 端点 + 129 个 MCP 工具零回归，两者共享同一 service 层（契约一致）。
- **11 个 service 模块**（按业务领域抽纯函数层）：market / fund / price / company / financial / news / industry / indicator / diagnostic / write / metrics；MCP 工具改为薄包装（`json.dumps(service_result)`），REST 路由也薄包装（`envelope_ok(service_result)`）。
- **统一响应包裹** `{code, data, msg}`；错误码 40001/40401/50001/50002/50003；FastAPI 422 自动映射到 40001；新增 502 数据源不可达映射。
- **Pydantic 入参校验**：symbol 6 位 isdigit；period 枚举；look_back_days 范围。
- **REST 端点分布**：行情 4 + 资金 2 + 价格 3 + 公司 4 + 财务 8 + 新闻 3 + 板块 5 + 指标 4 + 诊断 3 + 写操作 7 + 指标导出 2。
- **Prometheus 指标**（10 项）：requests_total / request_duration_seconds(Histogram) / errors_total / data_source_health / data_source_latency_seconds / slow_queries_total / gateway_uptime_seconds / tools_registered / cache_hits_total / cache_misses_total。
  - FastAPI 中间件自动计数（每次请求记录 method/path/code/duration；超 `TRADEX_SLOW_QUERY_MS` 阈值写慢查询日志）。
- **监控看板**（`GET /dashboard` HTML）：商务风格、暗色模式、响应式、手机竖屏友好；JS 每 30s fetch `/api/v1/metrics/json` 更新 DOM；fetch 失败顶部 banner 报错。
- **写操作**（本地文件存储，阶段一不引入数据库）：策略 `data/written/strategies/{毫秒id}.json` 原子写；自选股 `data/written/watchlist.json` 原子替换、去重。

### Added — REST API 阶段二（可观测性 + 并发安全 + 接入友好）

- **数据源健康指标实时化**（工单 14）：SmartRouter 每次路由成功/超时/异常自动上报 `record_data_source()` 到 Prometheus；埋点失败安全（异常不影响路由）。
- **慢查询日志读取端点** `GET /api/v1/metrics/slow-queries`（工单 15）：结构化数组；边界处理（文件不存在返空、超 10MB 只读尾部 100KB、非法行静默跳过）。
- **端点性能聚合 QPS/P50/P95/P99**（工单 16）：内存滑动窗口（默认 1000 条）+ 纯 Python 最近秩线性插值（不依赖 numpy）；`/api/v1/metrics/json` 新增 `endpoint_breakdown`；Dashboard 新增端点性能表。
- **访问日志查询端点** `GET /api/v1/access-log`（工单 19）：支持 `limit` / `path` 前缀过滤；数据源是中间件双写的 SQLite `access_log` 表。
- **访问日志中间件（双写）** `AccessLogMiddleware`（工单 19）：每个请求同时写 SQLite（结构化查询）+ 文件 JSON Lines 审计；建 `access_log` 表 + 2 索引；中间件注册顺序保证被限流请求仍经访问日志。
- **令牌桶三层限流**（工单 20）：全局 600 / 单 IP 60 / 单端点 120 req/min；超阈值返 HTTP 429 + envelope `code=42901` + `Retry-After` header；本机回环白名单。
- **TypeScript + Python 双语言 SDK**（工单 21+22，降级方案）：精简生成器 `scripts/generate_sdk.py` 从 `/openapi.json` 解析端点自动生成；降级原因：本机无 Java/Docker，openapi-generator-cli 跑不起来。

### Changed

- **写操作存储从 JSON 切换为 SQLite（WAL 模式）**（工单 17+18）：
  - 表 `strategies` / `watchlist`，主键 `{毫秒时间戳}-{线程ID}-{随机4位}` 杜绝高并发冲突。
  - 写入用 `BEGIN IMMEDIATE`；连接管理改用 `_cursor()` 上下文管理器显式 close。
  - **首次启动自动迁移**：发现旧 JSON 文件自动导入 SQLite，原文件改名 `.migrated`，写 `data/migration.log`（幂等）。
- **Prometheus `record_endpoint_call()` 与中间件集成**（工单 16）：`_collect_metrics` 中间件每次请求都调；错误码 `record_request` 也记录 429。
- **`_bootstrap()` 改为惰性 + 模块级锁 + 标志位**：避免模块加载时污染真实数据（测试 fixture 可重置）。

### Fixed

- **Windows 临时目录清理 PermissionError**（工单 18）：sqlite3 `with conn` 只 commit 不 close，导致 WAL 文件被占用；新增 `_cursor()` contextmanager 显式 close + `gc.collect()`。
- **SQLite "database is locked"**（工单 18）：`init_schema()` 内执行 PRAGMA 会并发争锁；改为独立 `setup_conn` 一次性设置。
- **迁移 "no such table: watchlist"**（工单 18）：`migrate_from_json` 漏调 `init_schema()`；改为先建表再迁移。
- **并发 UNIQUE 冲突**（工单 18）：毫秒时间戳同毫秒撞主键；ID 加 `-{threading.get_ident()}-{random.randint(0,9999)}` 后缀解决。
- **TS SDK README f-string 花括号误解析**（工单 21）：`{ TradexClient }` 被 Python f-string 当表达式；改字符串拼接 parts 列表。

### Architecture Decisions

- **Direction B 双协议并存**：MCP 和 REST 共存，共享 service 层（而非独立 REST 服务）。
- **MCP 零回归红线**：129 个 MCP 工具行为不变，每个工单完成后都验证 `tools=129` 不变。
- **service 层薄抽取策略**：数据获取类直接抽纯函数；编排器类复用 tools 顶层辅助函数（避免大改引入回归）；指标类底层已是模块级纯函数直接调用。

### Testing

- 阶段一共 12 个测试文件约 150 用例；阶段二新增约 70 用例（数据源指标 6 + 慢查询 5 + 端点性能 8 + 写操作 12 + 迁移 3 + 并发 5 + 访问日志 7 + 限流 13 + SDK 15），全通过。
- 全量回归 **703 passed / 3 failed（test_industry_rest 联网波动，单独跑全过）/ 7 skipped**。
- 契约一致性：每个工单用 curl 抽查对应 REST 端点返回真实数据 + MCP 工具无回归。

### 升级指引

- 无破坏性变更；既有 MCP 配置无需修改。
- REST 端点默认开放（与 MCP 同端口）；如需关闭可用反向代理白名单 `/api/v1/*`。
- `data/written/` 已在 `.gitignore` 的 `data/` 下覆盖。
- 写操作存储已升级为 SQLite WAL，首次启动自动从旧 JSON 迁移。

---

## [3.3.18] - 2026-09-18

### Fixed — 根因修复 MCP 频繁断连（P0）

- eltdx 3.x Rust 内核（pyo3 native）panic 抛出 `PanicException`（继承 `BaseException`，不被 `except Exception` 捕获），穿透 `SmartRouter.route()` 与 `_safe_call` 杀穿 anyio 事件循环导致 MCP server 干净退出，WorkBuddy 报 `-32000 Connection closed` 且永不重连。触发条件为 v3.3.2 的 8 线程池并发 × v3.3.13 的 eltdx Rust 内核单例（native 非线程安全间歇 panic）。

### Changed — 三层防御（不降级 eltdx）

- **L1** `smart_router.route()`：新增 `except BaseException` 统一兜底按源失败降级；`KeyboardInterrupt`/`SystemExit`/`asyncio.CancelledError` 放行（不吞进程/协程取消语义）。
- **L2** `eltdx_fetchers._NativePanicShield`：全局互斥锁序列化所有 native 调用 + `BaseException→RuntimeError`；`_get_client()` 返回代理，40+ 调用点零改动。
- **L2b** `eltdx_stream`：常驻流第二裸 client 同包盾（共享互斥锁）。
- **L3** `composite_analysis._safe_call`：`except BaseException` 双保险。

### Added

- `tests/test_baseexception_shield.py` 14 条回归测试（先红后绿）。

### 验证

- `pytest -m "not network"`：471 passed / 0 failed。
- 真实 eltdx 10 线程并发零 panic 逃逸；stdio 启动压测 5/5。
- 端到端 `analyze_stock_comprehensive(600519)` 1.6s 完整返回。

---

## [3.3.16–3.3.17] - 2026-09-15（合并批次：依赖约束 + 数据正确性修复）

> 两次同日 PATCH 发版合并。

### Fixed（v3.3.17 依赖与稳定性）

- **`mcp>=1.0.0` 无上限约束（P0，新环境安装必炸）**：mcp 2.x 已移除 `mcp.server.fastmcp.FastMCP`；改为 `mcp>=1.0.0,<2`（pyproject + requirements 两处）。
- **`WS_PORT` 非数字在 import 期崩服务**：改用 `_get_env` 容错转换。
- **requirements.txt 缺 3 个运行时依赖**：`requests`/`stockstats`/`python-dotenv` 补齐。
- **pytest 未来兼容**：class-scoped fixture 由类内实例方法迁至模块级。
- 降级链吞错加日志（10 处）：单源失败属设计预期，debug 级不刷屏但留痕。

### Fixed（v3.3.16 数据正确性修复）

- **机构持仓列错位（影响复盘「机构持仓」章节）**：akshare `stock_report_fund_hold` 按位置硬编码列名，上游东财字段顺序改版导致每列语义全错；改用 `fetch_fund_hold_direct` 绕开 akshare 直取上游 datacenter 按字段名映射；加列错位守卫（`股票代码` 必须全 6 位数字否则抛错）。
- **`get_fund_hold()` 无参调用稳定超时（P1）**：基金持仓 5311 行 ≈ 17s 超过默认单源超时 12s；新增 `_FUND_HOLD_ROUTE_TIMEOUT = 40.0` 单独放宽。
- **退役已永久失效的 `index_news_sentiment` 旧主源**：chinascope 上游已死（返回 HTML 非 JSON），每次调用白失败污染健康分；改用乐咕乐股 `legu_activity` 主源 + 同花顺涨跌分布 `ths_distribution` 备源。

### Changed

- 数据源矩阵规模 101 → 102（新增 `em_zlsj_direct`）；MCP 工具数 129 不变。
- `fund_hold` 由单源升为双源；`fund_hold` 的 `hold` 分支直接 raise 不再兜底返错标数据。

### 验证

- `pytest -m "not network"`：457 passed / 0 failed。
- `get_fund_hold(symbol="基金持仓")` 实测 5311 行、`股票代码` 列 5311/5311 全 6 位数字、0 错位。

---

## [3.3.13–3.3.15] - 2026-09-14（合并批次：上游升级 + 数据源健壮性 + 列错位前置修复）

> 三次同日连续 PATCH 发版，按「合并临近日期的连续发版」原则合并。

### Changed（v3.3.13 上游依赖跨大版本升级）

- **eltdx 2.0.2 → 3.2.2（major，Rust 重写内核）**：3.x 改为 Rust 强类型 + `cp310-abi3` native wheel；tradex 用到的接口面实测无差异。
- **akshare 1.18.91 → 1.18.94（patch）**。
- 数据源看板确认 90 个数据源全健康，两依赖 `has_update=false`。

### Fixed（v3.3.13 兼容性）

- eltdx 3.x 移除 `client.bars.all()`：`fetch_full_kline` 迁移至 `client.bars.get(..., all_pages=True)`。
- eltdx 3.x 移除 `client.helpers.adjusted_kline()`：`fetch_adjusted_kline` 迁移至 `client.bars.get(..., adjust="qfq"/"hfq")`。
- **`fetch_full_kline` 跨页乱序**：分页顺序「最近→更早」，直接拼接使 6389 根 K 线全局乱序；按 `time.timestamp()` 重排。
- **`start_dashboard.bat` 两处缺陷**：解释器探测错误（命中裸解释器未装 tradex）+ 端口未传递；修复后按「项目 .venv → WorkBuddy 托管 → PATH」顺序探测，导出 `TRADEX_DASHBOARD_PORT`。

### Added（v3.3.14 单源类型独立备源）

- 4 个单源类型补独立备源（均选**非东财**厂商）：`company_info` ← 巨潮资讯、`financial_stmt` ← 新浪财经、`valuation` ← eltdx F10、`industry_data` ← 同花顺。
- 数据源矩阵规模 90 → 94；MCP 工具数 129 不变。

### Fixed（v3.3.14 降级链修复）

- **akshare 备源 period 未归一化导致降级链断裂**：eltdx 认 `day/week/month`，akshare 认 `daily/weekly/monthly`；新增 `_normalize_ak_period()` 反向归一化。
- **`HTTP_PROXY=""` 拦不住系统代理**：`requests.getproxies()` 空环境变量会回退读 Windows 注册表代理，国内数据源被 Clash 拦截；显式设 `NO_PROXY=*` 短路注册表读取。
- **`_bar_sort_key` 静默降级污染回测首行**：收窄异常捕获，命中返 `float('inf')` 排末尾 + 记 warning 日志。

### Added（v3.3.15 补 7 个独立备源）

- 7 个类型补独立备源（避免同生共死）：`baidu_economic_calendar` / `baidu_trade_notify` / `hot_rank` / `hot_search` / `xueqiu_hot` / `index_news_sentiment` / `industry_comparison`。
- 数据源矩阵规模 94 → 101；数据类型 78 不变；MCP 工具数 129 不变。

### Fixed（v3.3.15 静默数据丢失）

- **`fetch_fund_hold_data` 默认日期恒空表**：Q2/Q3 算出 `20260631` 这类不存在日期；改用 `_prev_quarter_end()` 真实月末（实测修复后返 5311 行）。
- **8 个 fetch_fn 静默吞异常**：`except Exception: return pd.DataFrame()` 让 SmartRouter 把「上游挂了」判定为「成功返空表」—— 既不降级也不计健康度；改为 `raise`。
- **`fetch_index_news_sentiment` 的 SSL 兜底从未生效**：原 patch urllib 但 akshare 内部走 requests；改 requests 层注入后发现上游已永久失效，故改用乐咕乐股（v3.3.16 完成迁移）。
- **`industry_comparison` 同生共死**：主源 `em_push2` 与备源 akshare 同属东财 push2 族同时死；补同花顺 `ths_flow` 作跨上游备源。

### 验证

- `pytest -m "not network"`：450 passed / 0 failed（基线 418 + 新增 32）。
- 联网冒烟实测：`fund_hold` 5311 行（修复前恒空）、`index_news_sentiment` 降级 legu_activity 12 行、`industry_comparison` 降级 ths_flow 20 行（主备双源同时失败被救回）。

---

## [3.3.12] - 2026-09-08

### Added — HTTP 网关原生支持（免 supergateway）

- **`python -m tradex --http` 统一 HTTP 网关**：单端口同时提供三种端点：
  - `POST /mcp` — Streamable HTTP 主端点（MCP 2025 新标准传输，新版 Dify / LangChain / Claude 远程客户端首选），基于 mcp SDK 原生 `streamable_http_app()`。
  - `GET /sse` + `POST /messages/` — legacy SSE 兼容端点。
  - `GET /health` — 轻量健康检查，不触发数据源网络探测。
- **Host 校验可配（DNS rebinding 防护）**：新增 `apply_transport_security()` + CLI `--allowed-hosts` / env `MCP_ALLOWED_HOSTS`。

### Fixed

- docker-compose healthcheck 探测 `/mcp` 在 SSE transport 下必 404 → 改探测 `/health`。

### 验证

- 手工 E2E：官方 mcp Python client 完整会话（initialize → list_tools=129 → 真实调用 health_check）。
- 新增 `tests/test_http_server.py`；全量 398 passed / 0 failed。

---

## [3.3.10–3.3.11] - 2026-09-07（合并批次：双源合一 + P2 技术债全清）

> 两次同日发版合并。

### Changed（v3.3.11 P2 技术债全清）

- **指标算法单一实现收敛**：MACD/KDJ/RSI/BOLL/ATR/MA/EMA 收敛到 `technical_indicators.py` 模块级函数，`signal_generation.py` 删 4 组重复实现改复用同一实现。
- **EMA 种子对齐通达信**：递归首值改 X[0]，输出自首根起全有效。
- **K 线缓冲真正保留**：`_load_ohlcv` 与 `get_technical_indicator` 不再截断预热缓冲（look_back_days+60）。
- **eltdx period 归一化**：`daily/weekly/monthly → day/week/month`，消除命名不符导致主源静默降级 akshare。
- **eltdx_stream 代理清理改连接级**；**版本比较语义化**（数字元组比较）；**市场代码识别鲁棒**（含北交所 920）；**删死代码** `utils/fallback.py`。

### Changed（v3.3.10 双源合一 + 深度体检修复）

- **astock_signals 双源合一**：独立仓 `Claw/astock_signals/` 退役，`tradex/src/astock_signals/` 成为唯一主源 v1.1.1。
- **P0 计算修复**：`_downside_volatility` 改用标准下行偏差算法（原 Sortino 分母系统性算错）；全正收益策略 Sortino 返回 inf。
- **P1 修复**：可转债/ETF/北交所交易所判定、逐笔方向（eltdx 真实字段 `side` 替代不存在的 `buy_or_sell`）、SmartRouter 故障源半开探测自愈、东财限流加锁。
- **仓库卫生**：删根 `src/` 空壳、`cn-financial-mcp/` 僵尸目录、串仓测试；修复 pytest ImportPathMismatchError。
- 全量 357 passed / 0 failed；工具数断言 127→129。

---

## [3.3.9] - 2026-08-18

### Added — 数据源扩充 + 本地数据 + 全局直连

- **全局直连**：`__init__.py` import 时清代理环境变量，国内数据源一律直连。
- **东财限流防封**：新增 `em_client.py` 统一请求入口（间隔≥1s + 随机抖动 + 会话复用）。
- **东财 slist 板块归属**、**同花顺数据源**（4 个零鉴权接口）、**通达信本地数据**（读 vipdoc .day/.lc5 二进制）。
- 新增 `get_local_kline` / `get_local_minute` MCP 工具（读本地日线/分钟线）。
- 工具数 127 → 129。

---

## [3.3.7–3.3.8] - 2026-08-14（合并批次：eltdx 2.0 大规模接入）

> eltdx 2.0 第一梯队（S+A 级）+ 第二梯队（B 级）两次同日发版合并。

### Added（v3.3.7 第一梯队 S+A 级，19 个工具）

- **S 级（推送/盘口）**：新增 `eltdx_stream.py` 常驻连接管理器；`eltdx_get_depth`（五档盘口快照）、`eltdx_stream_health`。
- **A 级（9 个数据域）**：`eltdx_get_security_codes` / `eltdx_get_minute_history` / `eltdx_get_buy_sell_strength` / `eltdx_get_today_ticks` / `eltdx_get_opening_match` / `eltdx_get_full_kline` / `eltdx_get_adjusted_kline` / `eltdx_get_stock_profile` / `eltdx_get_shortline_indicators` / `eltdx_get_finance_batch` / `eltdx_get_special_limits` / `eltdx_get_finance_report` / `eltdx_get_dividend_financing` / `eltdx_get_company_news` / `eltdx_get_northbound_holding` / `eltdx_get_stock_topics` / `eltdx_get_topic_stocks` / `eltdx_get_auction_data`。
- 工具数 101 → 121。

### Added（v3.3.8 第二梯队 B 级，6 个工具）

- `eltdx_get_category_quotes`（分类行情涨幅/成交额/封单榜）、`eltdx_get_trading_day`、`eltdx_get_opening_match_history`、`eltdx_get_capital_changes`、`eltdx_get_special_limits_scan`、`eltdx_get_f10_extra`（F10 通用入口覆盖估值/题材/盈利预测等）。
- 工具数 121 → 127。

### 决策

- C 级（服务器文件/连接心跳/旧接口/底层万能口）按老板指示不接入。

---

## [3.3.6] - 2026-08-14

### Changed — 上游依赖升级

- **eltdx 1.2.0 → 2.0.2（major breaking change）**：2.0 移除旧式 `client.get_quote()` 等接口，统一为模块化 API；`fetch_realtime_quote` 迁移至 `client.helpers.full_quotes()`。
- **akshare 1.18.81 → 1.18.91**。

---

## [3.3.3–3.3.5] - 2026-08-13–14（合并批次：盘后复盘数据缺失根因修复 + 量能对比）

> 三次连续 PATCH 发版合并。

### Added（v3.3.4 量能对比）

- 新增 `get_index_volume_compare(days=6)` MCP 工具：返回三指数近 N 日成交额序列（亿元），供盘后复盘量能对比柱状图。
- 新增数据源 `fetch_index_daily_amount`（腾讯接口含成交额字段）。

### Fixed（v3.3.5 量能对比成交额为 null）

- `get_index_volume_compare` 主源走腾讯只返成交量无成交额；改主源为东财 push2his 历史K线直连（字段 f57=成交额），腾讯降级为备源。

### Changed（v3.3.3 撤销逐笔方案 + 提示词去逐笔）

- 撤销 D(P1) 逐笔盘后数据方案：eltdx 收盘后服务器关闭数据窗口、本地无缓存、盘中录制会占资源影响实盘。
- `eltdx_fetchers.fetch_tick_data` 回退至纯实时取数；盘后复盘提示词 v3.6 去逐笔要求。

### Fixed（v3.3.2 盘后复盘「多个数据缺失」根因修复，5 类）

- **A(P0) 指数代码解析错乱**：`utils/symbol.py` 新增指数代码白名单，`sh000001` 等不再误判成股票。
- **C(P0) 慢源挂起卡死 MCP**：SmartRouter `route()` 新增 timeout（默认 12s）线程池包裹；`composite_analysis._safe_call` 同步函数改 `run_in_executor + asyncio.wait_for(30s)`。
- **B(P1) 北向资金停更**：`get_northbound_flow_json` 新增「多日数值一致」检测，冻结值标 `discontinued` 并提示「已停止披露」。
- **E(P2) 自动化配置漂移**：盘后复盘自动化 prompt 从 v3.5 模板改为引用 v3.6。

---

## [3.3.0–3.3.1] - 2026-08-03（合并批次：新闻资讯大扩充 + 代理穿透修复）

> 两次同日发版合并。

### Added（v3.3.0 新闻资讯数据源扩充，9 个新源 + 9 个新工具，工具数 90→99）

- 百度经济日历 / 百度交易提醒 / 指数新闻情绪 / 期货新闻 / 新浪财经 / 百度热搜 / 东财人气榜 / 雪球热度 / 机构持仓。
- 同花顺问财可选依赖（pywencai + IWENCAI_API_KEY）。
- 数据类型从 27 增至 38 个。

### Fixed（v3.3.1 代理穿透修复，P0）

- 4 只股票 `get_money_flow` 用 curl_cffi 直连绕过系统代理，修复 ProxyError。
- `get_realtime_quote` 外围行情代理失败 P0 修复：腾讯接口强制直连。
- `get_company_announcements` 公告过滤 P0 修复：`_resolve_org_id` 兼容带 SH 前缀的代码。
- `get_financial_calendar` date 过滤失效修复。
- **astock_signals 合并**：独立包源码合并到本仓库 `tradex/src/astock_signals/`，统一版本管理。

---

## [3.2.0] - 2026-08-03

### Added — 新闻资讯增强：3 个直连数据源

- `em_news_direct`（东财 search-api-web JSONP 直连）、`cls_telegraph`（财联社实时电报）、`cninfo_direct`（巨潮官方全量公告）。
- 新增 `get_telegraph_news`（第 90 个工具）— 全市场实时财经快讯。
- 数据类型从 25 增至 27。

---

## [3.1.0–3.1.4] - 2026-08-02（合并批次：改名重构 + SmartRouter 主源修复 + 死代码清理）

> 五次同日连续发版合并（含 3.1.0 重大改名重构）。

### BREAKING CHANGES（v3.1.0）

- 项目改名：`trader-finance-hub` → `tradex-hub`，Python 包 `cn_financial_mcp` → `tradex`，GitHub 仓库名同步。
- astock_signals 独立成包：从 `tradex-hub/src/astock_signals/` 独立为 `trae_projects/astock_signals/`。
- 所有 L1 工具走 SmartRouter（不再直接 import akshare/eltdx）。
- eltdx 升为行情类第一主源（实时/历史K线/分时），akshare 降为备用。
- MCP 工具入口 `python -m cn_financial_mcp` → `python -m tradex`。

### Added（v3.1.0）

- 数据源看板 `get_data_source_dashboard`（JSON + HTML 单页）。
- SmartRouter 独占源标记 `exclusive=True`（集合竞价/逐笔/F10/涨停归因等 6 个独占源不降级）。
- data_sources 数据源层：25 数据类型 34 源注册。
- HTTP 防封参数环境变量化：EM_RATE_LIMIT_INTERVAL / EM_JITTER_MIN / EM_JITTER_MAX / EM_MAX_RETRY。
- 工具数 88 → 89（+1 看板工具）。

### Fixed（v3.1.3 P0 SmartRouter 主源永远失败）

- **根因**：`SmartRouter.route(**kwargs)` 原样转发参数，但 eltdx 用 `code=`、akshare/http 用 `symbol=`，传 `symbol=` 时 eltdx 收到 `code=""` 失败，SmartRouter 一直降级到 akshare 全量快照（14s vs eltdx 200ms）。所有 fetcher 同时接受 `symbol` 和 `code` 内部归一化。
- **eltdx KlineBar 字段映射错误**：`date` 实际是 `time`、`volume` 实际是 `volume_lots`。

### Fixed（v3.1.4 P1）

- eltdx realtime_quote 语义不完整：改用 `client.get_quote()` 获取真正 `QuoteSnapshot`（含涨跌幅/涨跌额/昨收/内外盘/现手）。
- 装饰器注册机制死代码导致 `health_check`/`list_all_tools` 误报：改为从 `mcp.list_tools()` 取工具列表。
- architecture.md 文档与代码不符：改为实际 4 个 fetchers 模块结构。
- `_client_lock` 线程安全：布尔值改 `threading.Lock()` 双重检查。

### Removed（v3.1.2）

- 删除 `src/` 目录（v2.x 遗留死代码）：`src/__init__.py` 链式依赖已删的 `eltdx_provider`；`src/data_manager.py` / `src/market_analyzer.py` 功能已被 tradex 包替代。
- 删除所有 `sys.path.insert` hack（8 个文件）。

---

## [3.0.0] - 2026-08-01

### BREAKING CHANGES — 三层架构确立

- 版本号统一：tradex v2.5.1 → v3.0.0，astock_signals v0.4.0 → v1.0.0，新增 VERSION 文件作为单一事实来源。
- 模块激活：smart_router / tick_store / ws_server 从"独立僵尸"变为"主流程组件"。
- 代码重复消除：删 `utils/em_client.py`，统一用 `astock_signals.anti_ban_client`。
- 文件拆分：signal_data.py 拆分为 5 个子模块。
- 安全默认值：MCP_HOST 默认 0.0.0.0 → 127.0.0.1（防公网暴露）。

### Added

- **L2 计算引擎层**：technical_indicators（6 工具）、performance_metrics（2 工具）。
- **L3 决策支持层**：signal_generation（3）、factor_analysis（2）、stock_screening（2）、diagnostics（4）、composite_analysis（3）、analysis_engine（1）。
- smart_router 接入数据源自动选择；tick_store 接入 eltdx_get_ticks 落盘；ws_server 可选推送。

### Fixed

- em_client.py 与 anti_ban_client.py 代码重复导致节流计数分裂。
- anti_ban_client.em_get 锁内 sleep 高并发阻塞。
- MCP_HOST 默认 0.0.0.0 公网暴露风险。
- architecture.md 严重过时（v2.3.0）；README 工具数不一致（80 vs 实际 88）。

---

## [2.5.0–2.5.1] - 2026-07-26 ~ 08-01（合并批次：智能决策中台升级 + eltdx K线接入）

### Added（v2.5.0 智能决策中台，15 个新工具，工具数 65→80）

- **P0 技术指标计算模块**（6 个）：calculate_ma_ema / calculate_macd / calculate_kdj / calculate_rsi / calculate_boll / calculate_atr。
- **P0 绩效指标计算模块**（2 个）：calculate_performance（21 项指标）、list_performance_metrics。
- **P1 信号生成模块**（3 个）：generate_trading_signal（5 级信号 + 评分 + 多指标组合）、scan_stocks_for_signals、validate_signal_quality。
- **P2 因子分析模块**（2 个）：calculate_factor_score（5 类 22 因子 Z-Score 标准化）、get_factor_catalog。
- **P2 条件选股模块**（2 个）：screen_stocks（5 类 30+ 条件 AND 组合）、get_screening_conditions。
- 定位升级：从「数据中台」升级为「智能决策中台」；新增 L2 计算引擎层和 L3 决策支持层。

### Added（v2.5.1 eltdx K线接入）

- 新增 `KlineBar` / `KlineData` 数据类 + `get_kline()` 方法（通达信 TCP 协议直连）。

---

## [2.4.0] - 2026-07-23

### Fixed — 6 个核心接口失败修复

- get_money_flow：改用东财 push2 直连 API，保留 AKShare 兜底。
- get_market_overview：改用新浪财经主源，东财兜底。
- get_sector_fund_flow：增加同花顺作为备用数据源。
- get_technical_indicator：K 线数据源增加腾讯备用。
- get_north_bound_flow：添加日期排序确保最新数据在前。
- get_margin_trading：增加东财市场汇总接口作为主源。
- 新增 `em_client.py` 东财防封客户端；工具数 61 → 65（+3 涨停板工具）。

---

## [2.3.0–2.3.2] - 2026-06-24 ~ 29（合并批次：ETF/可转债/智能路由 + 文档修复）

### Added（v2.3.0 三大模块 + 智能路由，工具数 57→61）

- **ETF 数据模块** `astock_signals/etf.py`：实时行情 / 历史 K 线 / ETF 列表。
- **可转债数据模块** `astock_signals/convertible_bond.py`：实时行情 / 价值分析 / 比价表 / 详情。
- **智能路由引擎** `astock_signals/smart_router.py`：健康评分 / 自动降级 / 延迟感知 / 故障隔离。
- **Tick 存储** `astock_signals/tick_store.py`：SQLite WAL 模式 / 分表 / 去重。
- **WebSocket 推送** `astock_signals/ws_server.py`：行情/异动/tick 按代码订阅。
- 新增 4 个 MCP 工具：`get_etf_realtime_data` / `get_etf_kline_data` / `get_cb_realtime_data` / `get_cb_value_analysis_data`。
- Router 新增 3 个 CLI 命令：`etf` / `cb` / `tickstore`；69 个 pytest 用例全过。

### Fixed（v2.3.1 文档与代码不一致）

- README 版本/工具数与代码不一致（57→61）；architecture.md 严重过时全面更新；signal_data.py 注释不一致；astock_signals 模块清单不全（11→14）；测试用例更新。

### Changed（v2.3.2）

- 清理 workbuddy 遗留路径；删除 `.workbuddy/` 目录；更新 `config/mcp-servers.json`；新增 `limit_up_board.py` 涨停板分析模块。

---

## [2.1.0–2.2.0] - 2026-06-22 ~ 23（合并批次：信号数据模块移植）

> 两次相邻日期发版合并。

### Added（v2.2.0 4 个信号模块，工具数 53→57）

- `astock_signals/northbound.py` 北向资金流向（同花顺 hsgtApi + 本地 CSV 缓存）。
- `astock_signals/fund_flow.py` 个股资金流向（东财 push2 实时 + push2his 历史 20 天）。
- `astock_signals/dragon_tiger.py` 龙虎榜席位明细（东财 datacenter + 机构动向）。
- `astock_signals/industry.py` 行业横向对比（东财 push2 行业排名）。
- 新增 4 个 MCP 工具；一主一备架构落地（AKShare 主力源，astock_signals 东财直连备用）。

### Added（v2.1.0 astock_signals 移植 + 6 工具，工具数 47→53）

- `anti_ban_client.py` 东财 HTTP 防封限流（Session 复用 + 串行限流 + 随机抖动）。
- `hot_money.py` 涨停归因（同花顺 editorial，含主题频次）。
- `lockup.py` 限售解禁日历（东财 datacenter）。
- `concept.py` 个股概念/行业/地域板块归属。
- `indicators.py` 13 种技术指标（MACD/RSI/Boll/ATR/KDJ/MFI 等，stockstats 引擎）。
- 新增 6 个 MCP 工具：`get_hot_stocks` / `get_lockup_expiry` / `get_concept_attribution` / `get_profit_forecast` / `get_technical_indicator` / `list_technical_indicators`。

### Fixed

- `get_profit_forecast` 从 `pd.read_html`（JS 渲染失败）改为正则精准匹配 `<thead>/<tbody>`。

---

## [2.0.0] - 2026-06-01

### Added — eltdx 通达信行情协议集成

- 集成 eltdx 通达信行情协议，提供独有数据源（集合竞价 / 逐笔成交 / F10 资料）。
- 新增开盘前分析模块、资金流向分析模块、个股筛选模块。
- 更新数据源矩阵和 CLI 命令。
- eltdx 集成版本 1.0.2；竞价数据延迟 ~114ms、逐笔 ~150ms、F10 ~200ms。

### Changed

- 智能路由策略：独有数据类型（竞价/逐笔/F10）固定使用 eltdx。
- 数据源评分模型考虑独有数据源不可替代性。

---

## [1.0.0] - 2026-05-01

### Added — 初始版本发布

- 多源 MCP 数据聚合平台架构；智能路由系统（trader-data-router）。
- 本地知识库（SQLite + 语义搜索）；定时任务系统；统一 MCP 协议层。
- 支持通达信 MCP、Wind MCP、东财 MCP、腾讯接口。
- 全市场综合分析引擎（market_analyzer.py）；新闻聚合引擎（4 源聚合）。
- 同花顺数据集成（29 个 THS 函数）。
- 分析模型：四象限、信息熵、情绪时钟。
- CLI 命令行工具；完整项目文档和使用示例。
- Apache-2.0 开源许可证。
- Python 3.10+ 兼容；MCP 协议 1.0 支持。
