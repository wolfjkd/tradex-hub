# 金融数据中枢 - 架构设计文档

> 最后更新：2026-06-24 | v2.3.0

## 1. 系统概览

trader-finance-hub 是为 AI Agent（Trae / Claude Code / Cursor）提供 A 股金融数据 MCP 接口的统一数据层。

- **MCP 工具总数**：61 个
- **数据源**：AKShare（主） + eltdx 通达信协议 + 东财直连 + 同花顺
- **传输方式**：stdio（本地 MCP Server）

## 2. 核心组件

### 2.1 MCP 协议层
- **协议**: Model Context Protocol (MCP) 1.0
- **传输**: stdio (本地)
- **框架**: FastMCP (Python)
- **包名**: cn-financial-mcp (v2.3.0)

### 2.2 数据源

| 数据源 | 类型 | 用途 | 优先级 |
|--------|------|------|--------|
| AKShare | Python 库 | 主力数据源：行情/财务/估值/行业/新闻/宏观（42 工具）+ 信号数据中 ETF/可转债/技术指标（6 工具） | P0 |
| eltdx 1.0.2 | TCP 通达信协议 | 独有数据：集合竞价/逐笔/F10/分时/K线（5 工具） | P0 |
| 东财直连 (push2/datacenter) | HTTP | 信号数据：资金流/龙虎榜/行业对比/解禁/概念归属（astock_signals，4 工具） | P1 |
| 同花顺 (hsgtApi/editorial) | HTTP | 信号数据：北向资金/涨停归因/一致预期（astock_signals，3 工具） | P1 |
| 腾讯行情 (qt.gtimg.cn) | HTTP | 个股实时报价（辅助一致预期估值计算） | P2 |

**一主一备架构**：每个数据类型至少有 1 主 + 1 备，主力源失败时自动降级到备用源。

### 2.3 模块结构

```
cn-financial-mcp (v2.3.0) ── FastMCP Server, 61 MCP 工具
│
├── tools/
│   ├── company_info.py    (4 工具) — 搜索/概况/竞品
│   ├── price_data.py      (4 工具) — 实时行情/历史K线/市值/列表
│   ├── financial_stmt.py  (8 工具) — 三表+财务指标+增长率+每股+分拆营收
│   ├── valuation.py       (4 工具) — PE/PB/PS历史/分红/机构持仓/分析师评级
│   ├── industry.py        (5 工具) — 行业板块/成分股/概念/板块资金流/行业PE
│   ├── market.py          (5 工具) — 指数快照/资金流/北向/涨跌停/龙虎榜
│   ├── news_events.py     (4 工具) — 个股新闻/财报日历/公告/关键词搜索
│   ├── macro_fx.py        (8 工具) — GDP/CPI/PMI/M2/汇率/国债/两融/增减持
│   ├── signal_data.py    (14 工具) — 涨停/解禁/概念/预期/技术指标/北向/资金流/龙虎/行业/ETF/可转债
│   └── eltdx_data.py      (5 工具) — 集合竞价/逐笔/F10/分时/K线
│
└── utils/
    ├── cache.py     — TTL 内存缓存
    ├── formatter.py — DataFrame → JSON 格式化
    └── symbol.py    — 股票代码标准化
```

### 2.4 astock_signals 模块（信号数据后端）

位于 `src/astock_signals/`，v0.3.0，14 个模块：

| 模块 | 功能 | 数据源 |
|------|------|--------|
| anti_ban_client | 东财防封客户端（节流+Session复用） | — |
| lockup | 限售解禁日历 | 东财 datacenter |
| hot_money | 涨停归因 | 同花顺 editorial |
| concept | 概念/行业/地域板块归属 | 东财 push2delay |
| indicators | 13种技术指标（MACD/RSI/Boll/ATR等） | stockstats + AKShare |
| northbound | 北向资金流向 | 同花顺 hsgtApi |
| fund_flow | 个股资金流向 | 东财 push2 |
| dragon_tiger | 龙虎榜席位明细 | 东财 datacenter |
| industry | 行业横向对比排名 | 东财 push2 |
| etf | ETF 实时行情/历史K线/列表 | AKShare |
| convertible_bond | 可转债实时/价值分析/比价/详情 | AKShare |
| smart_router | 智能路由引擎（健康评分/自动降级） | — |
| tick_store | Tick 数据本地存储（SQLite WAL） | — |
| ws_server | WebSocket 实时推送服务器 | — |

### 2.5 eltdx 通达信协议

通过 eltdx 1.0.2 连接通达信私有协议 (TCP 7709)，提供 AKShare 无法覆盖的独有数据：

| 数据 | 延迟 | AKShare 是否有 |
|------|------|---------------|
| 集合竞价 (9:15-9:25) | ~40ms | ❌ 没有 |
| 逐笔成交 | ~45ms | ❌ 没有 |
| F10 资料（题材归因） | ~2200ms | ❌ 没有 |
| 分时数据 | ~40ms | ⚠️ 有但源不同 |
| K线（多周期） | ~80ms | ⚠️ 有但源不同 |

## 3. 数据流

```
AI Agent (Trae / Claude Code / Cursor)
        │  MCP 协议 (stdio, JSON-RPC 2.0)
        ▼
  cn-financial-mcp server.py
        │
        ├── 注册 10 个工具模块 → 61 个 MCP 工具
        │
        ├── AKShare 工具 → akshare 库 → 东财/新浪/腾讯等公开 API
        ├── eltdx 工具 → eltdx TCP 7709 → 通达信私有协议
        └── signal_data 工具 → astock_signals 模块 → 东财/同花顺 HTTP 直连
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

## 6. 老板网络约束

- 国内 API 禁止走代理（`HTTPS_PROXY`/`HTTP_PROXY` 必须为 None）
- `push2.eastmoney.com` 直连被封 → 使用 `push2delay.eastmoney.com` 镜像
- `datacenter-web.eastmoney.com` 可直连
- 百度 PAE (`finance.pae.baidu.com`) 自 2026-05 起 403，已记录为不可用
