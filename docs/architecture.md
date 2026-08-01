# 金融数据中枢 - 架构设计文档

> 最后更新：2026-08-01 | v3.1.0

## 1. 系统概览

tradex-hub 是为 AI Agent（Trae / Claude Code / Cursor）提供 A 股金融数据 MCP 接口的统一数据层。

- **MCP 工具总数**：89 个
- **数据源**：data_sources 数据源层（25 类型 34 源）→ SmartRouter 全量路由（eltdx 主 + AKShare/东财/同花顺备）
- **传输方式**：stdio（本地 MCP Server）
- **包名**：tradex（v3.1.0），astock_signals 独立包 v1.1.0

## 2. 核心组件

### 2.1 MCP 协议层
- **协议**: Model Context Protocol (MCP) 1.0
- **传输**: stdio (本地)
- **框架**: FastMCP (Python)
- **包名**: tradex (v3.1.0)

### 2.2 数据源

| 数据源 | 类型 | 用途 | 优先级 |
|--------|------|------|--------|
| AKShare | Python 库 | 主力数据源：行情/财务/估值/行业/新闻/宏观（42 工具）+ 信号数据中 ETF/可转债/技术指标（6 工具） | P0 |
| eltdx 1.2.0 | TCP 通达信协议 | 独有数据：集合竞价/逐笔/F10/分时/K线（5 工具） | P0 |
| 东财直连 (push2/datacenter) | HTTP | 信号数据：资金流/龙虎榜/行业对比/解禁/概念归属（astock_signals，4 工具） | P1 |
| 同花顺 (hsgtApi/editorial) | HTTP | 信号数据：北向资金/涨停归因/一致预期（astock_signals，3 工具） | P1 |
| 腾讯行情 (qt.gtimg.cn) | HTTP | 个股实时报价（辅助一致预期估值计算） | P2 |

**全量路由架构**（v3.1.0）：25 个数据类型 34 个数据源注册到 SmartRouter，L1 工具统一通过 `SmartRouter.route()` 获取数据，自动健康评分/降级/故障隔离；独占源标记 `exclusive`（详见 §2.8）。eltdx 为行情类第一主源。

### 2.3 模块结构（三层架构）

```
tradex (v3.1.0) ── FastMCP Server, 89 MCP 工具
│
├── data_sources/         — 数据源层（25 类型 34 源，注册到 SmartRouter）
│   ├── registry.py       — 数据源注册表
│   ├── smart_router.py   — SmartRouter（健康评分/自动降级/故障隔离，全量覆盖）
│   └── providers/        — eltdx/AKShare/东财/同花顺/腾讯 等 Provider
│
├── L1 数据获取层（65 工具）— 通过 SmartRouter.route() 统一获取数据
│   ├── company_info.py    (4 工具) — 搜索/概况/竞品
│   ├── price_data.py      (5 工具) — 实时行情/历史K线/分时/市值/列表
│   ├── financial_stmt.py  (8 工具) — 三表+财务指标+增长率+每股+分拆营收
│   ├── valuation.py       (4 工具) — PE/PB/PS历史/分红/机构持仓/分析师评级
│   ├── industry.py        (5 工具) — 行业板块/成分股/概念/板块资金流/行业PE
│   ├── market.py          (5 工具) — 指数快照/资金流/北向/涨跌停/龙虎榜
│   ├── news_events.py     (4 工具) — 个股新闻/财报日历/公告/关键词搜索
│   ├── macro_fx.py        (8 工具) — GDP/CPI/PMI/M2/汇率/国债/两融/增减持
│   ├── signal_data.py     (17 工具) — 涨停/解禁/概念/预期/技术指标/北向/资金流/龙虎/行业/ETF/可转债/涨停板
│   └── eltdx_data.py      (5 工具) — 集合竞价/逐笔/F10/分时/K线
│
├── L2 计算引擎层（8 工具）
│   ├── technical_indicators.py (6 工具) — MA/EMA/MACD/KDJ/RSI/BOLL/ATR 纯函数计算
│   └── performance_metrics.py  (2 工具) — 完整绩效报告/绩效指标清单
│
├── L3 决策支持层（16 工具）
│   ├── signal_generation.py    (3 工具) — 交易信号生成/批量扫描/质量验证
│   ├── factor_analysis.py      (2 工具) — 多因子评分/因子库清单
│   ├── stock_screening.py      (2 工具) — 条件选股/选股条件清单
│   ├── diagnostics.py          (5 工具) — 数据源健康/工具清单/缓存统计/健康检查/数据源看板
│   ├── composite_analysis.py   (3 工具) — 个股综合分析/行业对比/市场总览
│   └── analysis_engine.py      (1 工具) — 技术分析引擎
│
├── dashboard/            — 数据源看板（HTML 可视化，python -m tradex.dashboard，端口 8765）
│
└── utils/
    ├── cache.py     — TTL 内存缓存
    ├── formatter.py — DataFrame → JSON 格式化
    └── symbol.py    — 股票代码标准化
```

> v3.1.0 变更：新增 `data_sources/` 数据源层（25 类型 34 源注册到 SmartRouter），L1 工具统一通过 `SmartRouter.route()` 获取数据；astock_signals 独立成包 v1.1.0；新增 `dashboard/` 看板模块（MCP 工具 `get_data_source_dashboard` + HTML 可视化）；diagnostics 4→5 工具，工具总数 88→89。

### 2.4 astock_signals 模块（信号数据后端，v3.1.0 独立成包）

astock_signals 已独立成包 v1.1.0，位于 `trae_projects/astock_signals/`，15 个模块（tradex-hub 通过依赖引入）：

| 模块 | 功能 | 数据源 | v3.1.0 状态 |
|------|------|--------|------------|
| anti_ban_client | 东财防封客户端（节流+Session复用+锁内sleep修复） | — | 统一入口（em_client 已合并） |
| lockup | 限售解禁日历 | 东财 datacenter | 主流程 |
| hot_money | 涨停归因 | 同花顺 editorial | 主流程 |
| concept | 概念/行业/地域板块归属 | 东财 push2delay | 主流程 |
| indicators | 13种技术指标（MACD/RSI/Boll/ATR等） | stockstats + AKShare | 主流程 |
| northbound | 北向资金流向 | 同花顺 hsgtApi | 主流程 |
| fund_flow | 个股资金流向 | 东财 push2 | 主流程 |
| dragon_tiger | 龙虎榜席位明细 | 东财 datacenter | 主流程 |
| industry | 行业横向对比排名 | 东财 push2 | 主流程 |
| etf | ETF 实时行情/历史K线/列表 | AKShare | 主流程 |
| convertible_bond | 可转债实时/价值分析/比价/详情 | AKShare | 主流程 |
| limit_up_board | 涨停板/炸板/跌停分析 | 东财 push2 clist | 主流程（v3.0.0 新增） |
| smart_router | 智能路由引擎（健康评分/自动降级） | — | **已接入主流程**（v3.0.0 激活） |
| tick_store | Tick 数据本地存储（SQLite WAL） | — | **已接入主流程**（v3.0.0 激活） |
| ws_server | WebSocket 实时推送服务器 | — | **已接入主流程**（v3.0.0 激活，可选） |

> v3.0.0 变更：smart_router / tick_store / ws_server 从"独立僵尸模块"激活为"主流程组件"；em_client.py 已删除，统一使用 anti_ban_client；新增 limit_up_board 模块。

### 2.5 eltdx 通达信协议

通过 eltdx 1.2.0 连接通达信私有协议 (TCP 7709)，提供 AKShare 无法覆盖的独有数据：

| 数据 | 延迟 | AKShare 是否有 |
|------|------|---------------|
| 集合竞价 (9:15-9:25) | ~40ms | ❌ 没有 |
| 逐笔成交 | ~45ms | ❌ 没有 |
| F10 资料（题材归因） | ~2200ms | ❌ 没有 |
| 分时数据 | ~40ms | ⚠️ 有但源不同 |
| K线（多周期） | ~80ms | ⚠️ 有但源不同 |

### 2.6 L2 计算引擎层（8 工具）

L2 层提供纯函数计算能力，输入价格/收益数组，输出量化指标，不依赖外部数据源。

| 模块 | 工具数 | 功能 | 算法要点 |
|------|--------|------|---------|
| technical_indicators | 6 | MA/EMA、MACD、KDJ、RSI、BOLL、ATR | SMA 前 n-1 个为 null；EMA 首值用 SMA 初始化；RSI 用 Wilder 平滑法 |
| performance_metrics | 2 | 完整绩效报告（21项指标）、绩效指标清单 | 覆盖收益/风险/风险调整收益/交易质量/费用统计/基准对比 |

**特点**：纯内存计算，无网络 IO，适合回测和实时分析；结果与 Excel/通达信一致。

### 2.7 L3 决策支持层（16 工具）

L3 层基于 L1 数据 + L2 计算结果，组合调用提供交易决策支持。

| 模块 | 工具数 | 功能 |
|------|--------|------|
| signal_generation | 3 | 单票信号生成（5级信号+评分+多指标组合）、批量扫描、信号质量验证（前瞻收益分析） |
| factor_analysis | 2 | 多因子综合评分（5类22因子，Z-Score 标准化）、因子库清单 |
| stock_screening | 2 | 条件选股扫描（5类30+条件，AND 组合）、选股条件清单 |
| diagnostics | 5 | 数据源健康检查、工具清单查询、缓存统计、系统健康检查、数据源看板 |
| composite_analysis | 3 | 个股综合分析、行业横向对比、市场总览分析 |
| analysis_engine | 1 | 技术分析引擎（多指标组合分析） |

**特点**：组合调用 L1+L2 能力，输出结构化决策建议；diagnostics 提供系统自省能力（v3.1.0 新增 `get_data_source_dashboard` 数据源看板）。

### 2.8 SmartRouter 数据源自动选择（v3.1.0 全量覆盖）

`data_sources/` 数据源层将 25 个数据类型、34 个数据源注册条目注册到 SmartRouter，L1 工具统一通过 `SmartRouter.route()` 获取数据。

**选择逻辑**：
1. **健康评分**：每个数据源维护健康分数（基于成功率/延迟/封禁状态）
2. **自动降级**：主源失败或健康分低于阈值时，自动切换到备用源
3. **故障隔离**：连续失败的源被临时隔离，避免拖慢整体响应
4. **延迟感知**：优先选择延迟更低的源
5. **独占源标记**：`exclusive=True` 的源无备用，失败即返回错误（如 eltdx 集合竞价/逐笔/F10）

**数据源矩阵（25 类型 34 源，eltdx 为行情类第一主源）**：

| 数据类型 | 主源（P1） | 备用1（P100） | 兜底（P200） | 独占 |
|---------|-----------|--------------|-------------|------|
| 实时行情 realtime_quote | **eltdx** | akshare | tencent_http | |
| 历史K线 historical_kline | **eltdx** | akshare | | |
| 分时数据 minute_data | **eltdx** | akshare | | |
| 集合竞价 call_auction | eltdx | | | ✅ 是 |
| 逐笔成交 tick_data | eltdx | | | ✅ 是 |
| F10资料 f10_profile | eltdx | | | ✅ 是 |
| 公司信息 company_info | akshare | | | |
| 财务报表 financial_stmt | akshare | | | |
| 估值 valuation | akshare | | | |
| 行业数据 industry_data | akshare | | | |
| 市场总览 market_overview | akshare | | | |
| 新闻数据 news_data | akshare | | | |
| 宏观数据 macro_data | akshare | | | |
| ETF数据 etf_data | akshare | | | |
| 可转债 cb_data | akshare | | | |
| 热门股票 hot_stocks | akshare | | | |
| 个股资金流 fund_flow | em_push2 | akshare | | |
| 龙虎榜 dragon_tiger | em_datacenter | akshare | | |
| 行业对比 industry_comparison | em_push2 | akshare | | |
| 北向资金 northbound | ths_hsgt | akshare | | |
| 涨停归因 hot_money | ths_editorial | | | ✅ 是 |
| 解禁日历 lockup_expiry | em_datacenter | | | ✅ 是 |
| 涨停板 limit_up_board | em_push2_clist | | | ✅ 是 |
| 盈利预测 profit_forecast | akshare | tencent_http | | |
| 概念归属 concept_attribution | em_push2delay | | | |

> 行情类（实时行情/历史K线/分时）以 **eltdx 为第一主源**（郑州节点 TCP 3.5ms），akshare 备用，tencent_http 兜底；eltdx 独占的集合竞价/逐笔/F10 无备用源。

### 2.8.1 数据源看板（v3.1.0 新增）

- **HTML 可视化**：`python -m tradex.dashboard`（端口 8765），查看数据源健康/路由/工具分布
- **MCP 工具**：`get_data_source_dashboard`，供 Agent 对话中查询数据源状态

### 2.9 Tick 数据落盘（tick_store，v3.0.0 激活）

tick_store 模块从"独立僵尸"激活为主流程组件，为 `eltdx_get_ticks` 提供数据落盘能力。

- **存储引擎**：SQLite WAL 模式，按股票代码分表
- **去重策略**：基于 (代码+价格+量+方向+时间窗口) 去重
- **查询接口**：支持时间范围过滤
- **接入点**：`eltdx_get_ticks` 工具调用时自动落盘，后续查询可先读本地再请求远端

### 2.10 WebSocket 实时推送（ws_server，v3.0.0 激活，可选）

ws_server 模块从"独立僵尸"激活为可选推送服务，与 MCP stdio 通道解耦。

- **开关控制**：环境变量 `WS_SERVER_ENABLED=true` 启用，默认关闭
- **推送内容**：行情快照 / 异动提醒 / tick 数据
- **订阅模式**：按股票代码订阅，支持多客户端并发
- **独立性**：不阻塞 MCP 主流程，独立线程运行

### 2.11 数据源版本检查（v3.1.0 新增）

`data_source_monitor.py` 模块提供数据源依赖库的版本检查能力，只提醒不升级。

| 检查项 | 检查方式 | 触发频率 | 行为 |
|--------|---------|---------|------|
| eltdx | GitHub release 比对 | 启动时 + 定时 | 发现新版本仅日志提醒，不自动升级 |
| akshare | PyPI 最新版本比对 | 启动时 + 定时 | 发现新版本仅日志提醒，不自动升级 |

**设计原则**：版本升级由老板手动执行（`pip install -U`），监控系统只负责提示，避免自动升级引入兼容性问题。

## 3. 数据流

```
AI Agent (Trae / Claude Code / Cursor)
        │  MCP 协议 (stdio, JSON-RPC 2.0)
        ▼
  tradex server.py
        │
        ├── 注册 18 个工具模块 → 89 个 MCP 工具
        │
        ├── L1 数据获取层（65 工具）→ SmartRouter.route() 统一路由
        │   └── data_sources/ 数据源层（25 类型 34 源）
        │       ├── eltdx → eltdx TCP 7709 → 通达信私有协议（行情类第一主源）
        │       ├── akshare → akshare 库 → 东财/新浪/腾讯等公开 API
        │       ├── em_push2/em_datacenter → 东财 HTTP 直连
        │       ├── ths_hsgt/ths_editorial → 同花顺 HTTP
        │       └── tencent_http → 腾讯行情 HTTP
        │       （SmartRouter 自动选择：健康评分/降级/隔离/独占源标记）
        │
        ├── L2 计算引擎层（8 工具）
        │   └── 纯函数计算（无网络 IO）→ MA/MACD/KDJ/RSI/BOLL/ATR/绩效指标
        │
        └── L3 决策支持层（16 工具）
            └── 组合调用 L1+L2 → 信号生成/因子分析/选股/诊断/综合分析/技术分析
```

## 4. 与其他组件的关系

| 组件 | 位置 | 关系 |
|------|------|------|
| trader-data-router | 独立项目 | CLI 工具，17 个命令，薄壳调用 astock_signals |
| Wind MCP | 独立项目 | 独立 MCP Server，通过 AI Agent connector 接入 |
| 通达信 MCP | 独立项目 | 独立 connector (tdx-connector) |

## 5. 配置

编辑 MCP 配置文件（如 `~/.trae-cn/mcp.json` 或对应 AI Agent 的配置文件）注册 MCP Server：

```json
{
  "mcpServers": {
    "tradex": {
      "command": "/path/to/venv/Scripts/python.exe",
      "args": ["-m", "tradex"],
      "env": {}
    }
  }
}
```

**v3.0.0 安全默认值变更**：

| 环境变量 | v2.5.1 默认 | v3.0.0 默认 | 说明 |
|---------|------------|------------|------|
| `MCP_HOST` | `0.0.0.0` | `127.0.0.1` | 默认仅监听本地，避免公网暴露；外网部署需显式设置 `MCP_HOST=0.0.0.0` |
| `WS_SERVER_ENABLED` | — | `false` | WebSocket 推送服务默认关闭，按需开启 |

**v3.1.0 HTTP 防封参数环境变量化**（原硬编码参数迁移为环境变量，便于调优）：

| 环境变量 | 默认值 | 说明 |
|---------|-------|------|
| `EM_RATE_LIMIT_INTERVAL` | `1.0` | 东财请求最小间隔（秒），防触发风控 |
| `EM_JITTER_MIN` | `0.3` | 随机抖动下限（秒），模拟人类行为 |
| `EM_JITTER_MAX` | `1.2` | 随机抖动上限（秒），模拟人类行为 |
| `EM_MAX_RETRY` | `3` | 最大重试次数，超过即降级到备用源 |

> v3.0.0 之前这些参数硬编码在 `anti_ban_client` 中；v3.1.0 起统一改为环境变量，运维侧可按需调整而无需改代码。

## 6. 老板网络约束

- 国内 API 禁止走代理（`HTTPS_PROXY`/`HTTP_PROXY` 必须为 None）
- `push2.eastmoney.com` 直连被封 → 使用 `push2delay.eastmoney.com` 镜像
- `datacenter-web.eastmoney.com` 可直连
- 百度 PAE (`finance.pae.baidu.com`) 自 2026-05 起 403，已记录为不可用
