# Trader Finance Hub

<p align="center">
  <strong>AI金融数据聚合平台</strong><br/>
  AKShare 封装 · eltdx 通达信协议 · astock_signals 信号模块 · 本地 MCP Server · 61 个工具
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.13+-blue.svg" alt="Python"/>
  <img src="https://img.shields.io/badge/MCP-1.0-green.svg" alt="MCP"/>
  <img src="https://img.shields.io/badge/License-Apache--2.0-yellow.svg" alt="License"/>
  <img src="https://img.shields.io/badge/Data-A股-red.svg" alt="Data Scope"/>
  <img src="https://img.shields.io/badge/Tools-61-orange.svg" alt="MCP Tools"/>
</p>

---

## 项目定位

为 AI Agent（WorkBuddy / Claude Code / Cursor）提供 **A 股金融数据的 MCP 接口**。

**当前数据源**：
- **AKShare**：42 个基础金融工具（行情/财务/估值/行业/新闻/宏观）
- **eltdx 1.0.2**：5 个通达信独有工具（集合竞价/逐笔/F10/分时/K线）
- **信号数据（混合源）**：14 个信号工具，数据来自东财直连 + 同花顺 + AKShare
  - 东财直连：个股资金流/龙虎榜/行业对比/解禁日历/概念归属
  - 同花顺：涨停归因/一致预期/北向资金
  - AKShare：ETF实时+K线/可转债实时+价值分析/技术指标

**不吹牛**：这不是"多源智能路由"，就是两个数据源的 MCP 壳。  
多源聚合是规划目标，代码里还没实现。

---

## 项目架构

```
AI Agent (WorkBuddy / Claude Code / Cursor)
        │  MCP 协议 (stdio)
        ▼
  cn-financial-mcp ── FastMCP Server
        │
        ├── AKShare 封装（42 工具）
        │     ├── company_info (4)   → 搜索/概况/竞品
        │     ├── price_data (4)     → 实时行情/历史K线/市值/列表
        │     ├── financial_stmt (8) → 三表+财务指标+增长率+每股+分拆营收
        │     ├── valuation (4)      → PE/PB/PS历史/分红/机构持仓/分析师评级
        │     ├── industry (5)       → 行业板块/成分股/概念/板块资金流/行业PE
        │     ├── market (5)         → 指数快照/资金流/北向/涨跌停/龙虎榜
        │     ├── news_events (4)    → 个股新闻/财报日历/公告/关键词搜索
        │     └── macro_fx (8)       → GDP/CPI/PMI/M2/汇率/国债/两融/增减持
        │
        ├── 信号数据 — 混合数据源（14 工具）
        │     ├── signal_data (14)   → 涨停归因/解禁/概念/预期/技术指标/北向/资金流/龙虎榜/行业/ETF/可转债
        │     └─ 数据源：东财直连 + 同花顺 + AKShare
        │
        └── eltdx 1.0.2 封装（5 工具）
              ├── 集合竞价 (auction)    — AKShare 无此功能
              ├── 逐笔成交 (ticks)      — AKShare 无此功能
              ├── F10 资料 (f10)        — AKShare 无此功能
              ├── 分时数据 (minutes)    — 与 AKShare 互补
              └── K 线 (kline)          — 与 AKShare 互补
                    └─ 数据源：通达信私有协议 (TCP 7709)
```

## MCP 工具清单（61 个）

### 1. 公司信息（4 个）— `company_info`

| 工具名 | 功能 |
|--------|------|
| `search_stock` | 搜索A股股票，支持名称或代码模糊匹配 |
| `get_company_info` | 公司基本信息：行业、市值、股本、上市日期 |
| `get_company_profile` | 主营业务构成与业务描述 |
| `get_competitors` | 同行业公司列表（竞争对手/可比公司） |

### 2. 行情数据（4 个）— `price_data`

| 工具名 | 功能 |
|--------|------|
| `get_realtime_quote` | 实时行情：最新价/涨跌幅/量/换手率/PE/PB |
| `get_historical_price` | 历史K线（日/周/月，前复权/后复权/不复权） |
| `get_market_capitalization` | 总市值与流通市值 |
| `get_stock_list` | A股全列表，支持按市值筛选 |

### 3. 财务报表（8 个）— `financial_stmt`

| 工具名 | 功能 |
|--------|------|
| `get_income_statement` | 利润表（按季度，默认8期） |
| `get_balance_sheet` | 资产负债表（按季度，默认8期） |
| `get_cash_flow_statement` | 现金流量表（按季度，默认8期） |
| `get_financial_line_item` | 从三表中提取特定科目时间序列（如"营业总收入"） |
| `get_financial_indicators` | ROE/毛利率/净利率/资产负债率等多维度指标 |
| `get_growth_rates` | 营收增长率/净利润增长率等成长性指标 |
| `get_per_share_data` | 每股指标：EPS / BPS / CFPS |
| `get_segments_revenue` | 主营构成：按产品/地区分拆营收与毛利率 |

### 4. 估值分析（4 个）— `valuation`

| 工具名 | 功能 |
|--------|------|
| `get_valuation_metrics` | PE/PB/PS 历史时间序列（默认100交易日） |
| `get_dividend_data` | 历史分红派息：每股派息/除权日/登记日 |
| `get_institutional_holdings` | 十大流通股东/机构持股变动 |
| `get_analyst_rating` | 分析师评级/目标价/预测EPS |

### 5. 行业板块（5 个）— `industry`

| 工具名 | 功能 |
|--------|------|
| `get_industry_list` | 行业板块列表（涨跌幅/领涨股） |
| `get_industry_stocks` | 指定行业所有成分股 |
| `get_concept_list` | 概念板块列表（华为/ChatGPT/芯片等） |
| `get_sector_fund_flow` | 板块资金流向排名（行业/概念/地域，今日/5日/10日） |
| `get_industry_pe` | 行业板块历史行情（可用于行业PE估值趋势） |

### 6. 市场总览（5 个）— `market`

| 工具名 | 功能 |
|--------|------|
| `get_market_overview` | 主要指数实时快照（上证/深证/创业板/科创50/沪深300） |
| `get_money_flow` | 个股资金流向：主力/超大单/大单/中单/小单 |
| `get_north_bound_flow` | 北向资金净流入（沪股通+深股通） |
| `get_limit_up_down` | 当日涨停/跌停股票池（封单额/连板天数） |
| `get_dragon_tiger` | 龙虎榜：机构与游资买卖席位 |

### 7. 新闻公告（4 个）— `news_events`

| 工具名 | 功能 |
|--------|------|
| `get_stock_news` | 个股相关新闻资讯 |
| `get_financial_calendar` | 财报披露时间表 |
| `get_company_announcements` | 上市公司公告 |
| `search_news` | 按关键词搜索新闻（可限定个股范围） |

### 8. 宏观衍生（8 个）— `macro_fx`

| 工具名 | 功能 |
|--------|------|
| `get_macro_gdp` | 中国GDP（季度，含三次产业） |
| `get_macro_cpi` | CPI消费者价格指数（月度，同比/环比） |
| `get_macro_pmi` | PMI采购经理指数（制造业/非制造业/分项） |
| `get_macro_money_supply` | M0/M1/M2 货币供应量（月度，同比增速） |
| `get_fx_rate` | 外汇汇率（美元/欧元/英镑/日元/港币兑人民币） |
| `get_bond_yield_curve` | 国债收益率曲线（1/3/5/7/10/30年） |
| `get_margin_trading` | 融资融券余额（市场汇总/个股） |
| `get_insider_trading` | 股东/高管增减持（内部交易） |

### 9. A股信号+品种（14 个）— `signal_data`

| 工具名 | 功能 | 数据源 |
|--------|------|--------|
| `get_hot_stocks` | 涨停股票+人工标注的主题归因 | 同花顺 editorial |
| `get_lockup_expiry` | 限售解禁日历（历史+未来90天） | 东方财富 datacenter |
| `get_concept_attribution` | 概念/行业/地域板块归属 | 东方财富 / 百度 |
| `get_profit_forecast` | 分析师一致预期EPS + Forward PE/PEG | 同花顺 |
| `get_technical_indicator` | 13种技术指标（MACD/RSI/布林带/ATR等） | AKShare + stockstats |
| `list_technical_indicators` | 列出所有支持的技术指标及说明 | — |
| `get_northbound_flow_signal` | 北向资金流向（沪深股通） | 同花顺 hsgtApi |
| `get_fund_flow_signal` | 个股资金流向（主力/大中小单） | 东财 push2 |
| `get_dragon_tiger_signal` | 龙虎榜席位明细+机构动向 | 东财 datacenter |
| `get_industry_comparison_signal` | 行业横向对比排名 | 东财 push2 |
| `get_etf_realtime_data` 🆕 | ETF实时行情（IOPV/折价率/换手率） | AKShare fund_etf_spot_em |
| `get_etf_kline_data` 🆕 | ETF历史K线（日/周/月，支持复权） | AKShare fund_etf_hist_em |
| `get_cb_realtime_data` 🆕 | 可转债实时行情（溢价率/转股价/评级） | AKShare bond_zh_cov |
| `get_cb_value_analysis_data` 🆕 | 可转债价值分析（溢价率历史曲线） | AKShare bond_zh_cov_value_analysis |

### 10. eltdx 通达信独有（5 个）— `eltdx_data`

| 工具名 | 功能 | 延迟 | AKShare 是否有 |
|--------|------|------|---------------|
| `eltdx_get_auction` | 集合竞价（9:15-9:25撮合过程） | ~40ms | ❌ 没有 |
| `eltdx_get_ticks` | 逐笔成交（价格/量/买卖方向） | ~45ms | ❌ 没有 |
| `eltdx_get_f10` | F10资料（公司概况/题材归因/财务诊断） | ~2200ms | ❌ 没有 |
| `eltdx_get_minutes` | 分时数据（1分钟K线） | ~40ms | ⚠️ 有但源不同 |
| `eltdx_get_kline` | K线（日/周/月/5m/15m/30m/60m） | ~80ms | ⚠️ 有但源不同 |

---

## 安装

### 1. 克隆项目

```bash
git clone https://github.com/wolfjkd/trader-finance-hub.git
cd trader-finance-hub
```

### 2. 创建独立 venv（推荐）

```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或 venv\Scripts\activate  # Windows
```

### 3. 安装 cn-financial-mcp

```bash
cd cn-financial-mcp
pip install hatchling editables
pip install --no-build-isolation -e .
```

### 4. 安装运行时依赖

```bash
pip install akshare mcp pandas pydantic eltdx
```

---

## 配置到 AI Agent

编辑 MCP 配置文件（如 `~/.trae-cn/mcp.json` 或对应 AI Agent 的配置文件）：

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

保存后重启 AI Agent，连接器页面 `cn-financial-mcp` 应显示绿色。

---

## 验证

重启后在对话里测试：

```
查中国能建（601868）K线
```

AI 会调用 `mcp__cn-financial-mcp__eltdx_get_kline`，返回 100 根日 K 线。

---

## 已知限制

1. **eltdx 逐笔数据不带时间字段**（`time: null`），只有价格/量/方向
2. **eltdx F10 延迟高**（~2 秒），但数据独有（题材归因是 AKShare 没有的）
3. **没有智能路由**：每个工具写死一个数据源，不会自动择优
4. **Wind/通达信 MCP 不在本项目里**：通过独立 MCP Server 或 AI Agent 的 connector 系统接入

---

## 版本历史

| 版本 | 日期 | 内容 |
|------|------|------|
| v2.3.0 | 2026-06-24 | 新增 ETF/可转债/智能路由/Tick存储/WebSocket 5 个模块，4 个新 MCP 工具（ETF实时+K线/可转债实时+价值分析），61 工具就绪；router 扩展至 17 命令 |
| v2.2.0 | 2026-06-23 | 新增 astock_signals 4 个模块（北向资金/个股资金流/龙虎榜/行业对比），4 个新 MCP 工具，57 工具就绪 |
| v2.1.0 | 2026-06-22 | 新增 A 股信号数据模块：涨停归因/解禁日历/概念归属/一致预期/技术指标，6 个新 MCP 工具，53 工具就绪 |
| v2.0.1 | 2026-06-17 | 集成 eltdx 5 个工具；修复 pyproject.toml hatchling 配置；47 工具全跑通 |
| v2.0.0 | 2026-06-04 | eltdx 通达信协议集成（原 `eltdx_provider.py`） |
| v1.0.0 | 2026-06-02 | 全市场综合分析引擎 |
| v0.1.0 | 2026-06-01 | 项目初始化；集成 cn-financial-mcp |

---

## 许可

Apache-2.0 License

---

## 作者

**郭良勇 (wolfjkd)** — A股T0日内交易员
