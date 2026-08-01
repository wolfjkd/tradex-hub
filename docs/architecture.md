# 金融数据中枢 - 架构设计文档

> 最后更新：2026-08-01 | v3.0.0

## 1. 系统概览

trader-finance-hub 是为 AI Agent（Trae / Claude Code / Cursor）提供 A 股金融数据 MCP 接口的统一数据层。

- **MCP 工具总数**：88 个
- **数据源**：AKShare（主） + eltdx 通达信协议 + 东财直连 + 同花顺
- **传输方式**：stdio（本地 MCP Server）

## 2. 核心组件

### 2.1 MCP 协议层
- **协议**: Model Context Protocol (MCP) 1.0
- **传输**: stdio (本地)
- **框架**: FastMCP (Python)
- **包名**: cn-financial-mcp (v3.0.0)

### 2.2 数据源

| 数据源 | 类型 | 用途 | 优先级 |
|--------|------|------|--------|
| AKShare | Python 库 | 主力数据源：行情/财务/估值/行业/新闻/宏观（42 工具）+ 信号数据中 ETF/可转债/技术指标（6 工具） | P0 |
| eltdx 1.0.2 | TCP 通达信协议 | 独有数据：集合竞价/逐笔/F10/分时/K线（5 工具） | P0 |
| 东财直连 (push2/datacenter) | HTTP | 信号数据：资金流/龙虎榜/行业对比/解禁/概念归属（astock_signals，4 工具） | P1 |
| 同花顺 (hsgtApi/editorial) | HTTP | 信号数据：北向资金/涨停归因/一致预期（astock_signals，3 工具） | P1 |
| 腾讯行情 (qt.gtimg.cn) | HTTP | 个股实时报价（辅助一致预期估值计算） | P2 |

**一主一备架构**：每个数据类型至少有 1 主 + 1 备，主力源失败时自动降级到备用源。v3.0.0 起 SmartRouter 接管该降级逻辑（详见 §2.8）。

### 2.3 模块结构（三层架构）

```
cn-financial-mcp (v3.0.0) ── FastMCP Server, 88 MCP 工具
│
├── L1 数据获取层（65 工具）
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
├── L3 决策支持层（15 工具）
│   ├── signal_generation.py    (3 工具) — 交易信号生成/批量扫描/质量验证
│   ├── factor_analysis.py      (2 工具) — 多因子评分/因子库清单
│   ├── stock_screening.py      (2 工具) — 条件选股/选股条件清单
│   ├── diagnostics.py          (4 工具) — 数据源健康/工具清单/缓存统计/健康检查
│   ├── composite_analysis.py   (3 工具) — 个股综合分析/行业对比/市场总览
│   └── analysis_engine.py      (1 工具) — 技术分析引擎
│
└── utils/
    ├── cache.py     — TTL 内存缓存
    ├── formatter.py — DataFrame → JSON 格式化
    └── symbol.py    — 股票代码标准化
```

### 2.4 astock_signals 模块（信号数据后端）

位于 `src/astock_signals/`，v1.0.0，15 个模块：

| 模块 | 功能 | 数据源 | v3.0.0 状态 |
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

通过 eltdx 1.0.2 连接通达信私有协议 (TCP 7709)，提供 AKShare 无法覆盖的独有数据：

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

### 2.7 L3 决策支持层（15 工具）

L3 层基于 L1 数据 + L2 计算结果，组合调用提供交易决策支持。

| 模块 | 工具数 | 功能 |
|------|--------|------|
| signal_generation | 3 | 单票信号生成（5级信号+评分+多指标组合）、批量扫描、信号质量验证（前瞻收益分析） |
| factor_analysis | 2 | 多因子综合评分（5类22因子，Z-Score 标准化）、因子库清单 |
| stock_screening | 2 | 条件选股扫描（5类30+条件，AND 组合）、选股条件清单 |
| diagnostics | 4 | 数据源健康检查、工具清单查询、缓存统计、系统健康检查 |
| composite_analysis | 3 | 个股综合分析、行业横向对比、市场总览分析 |
| analysis_engine | 1 | 技术分析引擎（多指标组合分析） |

**特点**：组合调用 L1+L2 能力，输出结构化决策建议；diagnostics 提供系统自省能力。

### 2.8 SmartRouter 数据源自动选择（v3.0.0 激活）

smart_router 模块从"独立僵尸"激活为主流程组件，为信号数据工具提供自动数据源选择。

**选择逻辑**：
1. **健康评分**：每个数据源维护健康分数（基于成功率/延迟/封禁状态）
2. **自动降级**：主源失败或健康分低于阈值时，自动切换到备用源
3. **故障隔离**：连续失败的源被临时隔离，避免拖慢整体响应
4. **延迟感知**：优先选择延迟更低的源

**数据源优先级表（SmartRouter 接管后）**：

| 数据类型 | 首选（P0） | 备用（P1） | 自动降级触发条件 |
|---------|-----------|-----------|-----------------|
| 个股资金流 | 东财 push2 | AKShare | push2 返回 429/封禁 |
| 龙虎榜 | 东财 datacenter | AKShare | datacenter 超时 |
| 行业对比 | 东财 push2 | AKShare | push2 健康分 < 60 |
| 北向资金 | 同花顺 hsgtApi | AKShare | hsgtApi 不可达 |
| 涨停归因 | 同花顺 editorial | — | 无备用（独有数据） |
| 解禁日历 | 东财 datacenter | — | 无备用（独有数据） |
| 涨停板/炸板 | 东财 push2 clist | — | 无备用（独有数据） |
| ETF 行情 | AKShare | — | 无备用 |
| 可转债 | AKShare | — | 无备用 |
| 集合竞价 | eltdx | — | 无备用（独有数据） |
| 逐笔成交 | eltdx | — | 无备用（独有数据） |
| F10 资料 | eltdx | — | 无备用（独有数据） |

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

## 3. 数据流

```
AI Agent (Trae / Claude Code / Cursor)
        │  MCP 协议 (stdio, JSON-RPC 2.0)
        ▼
  cn-financial-mcp server.py
        │
        ├── 注册 18 个工具模块 → 88 个 MCP 工具
        │
        ├── L1 数据获取层（65 工具）
        │   ├── AKShare 工具 → akshare 库 → 东财/新浪/腾讯等公开 API
        │   ├── eltdx 工具 → eltdx TCP 7709 → 通达信私有协议
        │   └── signal_data 工具 → astock_signals 模块 → 东财/同花顺 HTTP 直连
        │       └── SmartRouter 自动选择数据源（健康评分/降级/隔离）
        │
        ├── L2 计算引擎层（8 工具）
        │   └── 纯函数计算（无网络 IO）→ MA/MACD/KDJ/RSI/BOLL/ATR/绩效指标
        │
        └── L3 决策支持层（15 工具）
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
    "cn-financial-mcp": {
      "command": "/path/to/venv/Scripts/python.exe",
      "args": ["-m", "cn_financial_mcp"],
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

## 6. 老板网络约束

- 国内 API 禁止走代理（`HTTPS_PROXY`/`HTTP_PROXY` 必须为 None）
- `push2.eastmoney.com` 直连被封 → 使用 `push2delay.eastmoney.com` 镜像
- `datacenter-web.eastmoney.com` 可直连
- 百度 PAE (`finance.pae.baidu.com`) 自 2026-05 起 403，已记录为不可用
