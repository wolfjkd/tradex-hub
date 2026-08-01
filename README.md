# tradex-hub

<p align="center">
  <strong>AI金融智能决策中台</strong><br/>
  AKShare 封装 · eltdx 通达信协议 · astock_signals 信号模块 · 量化计算引擎 · SmartRouter 全量路由 · 本地 MCP Server · 89 个工具
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.13+-blue.svg" alt="Python"/>
  <img src="https://img.shields.io/badge/MCP-1.0-green.svg" alt="MCP"/>
  <img src="https://img.shields.io/badge/License-Apache--2.0-yellow.svg" alt="License"/>
  <img src="https://img.shields.io/badge/Data-A股-red.svg" alt="Data Scope"/>
  <img src="https://img.shields.io/badge/Tools-89-orange.svg" alt="MCP Tools"/>
  <img src="https://img.shields.io/badge/Version-3.1.3-blue.svg" alt="Version"/>
</p>

---

## 项目定位

为 AI Agent（WorkBuddy / Claude Code / Cursor）提供 **A 股金融数据 + 量化计算 + 决策支持的 MCP 接口**。

**三层能力模型**：
- **L1 数据获取层**（65个工具）：通过 SmartRouter 统一获取数据（行情/财务/估值/行业/新闻/宏观/涨停板/龙虎榜等）
- **L2 计算引擎层**（8个工具）：技术指标计算6个、绩效指标计算2个
- **L3 决策支持层**（16个工具）：交易信号生成3个、多因子分析2个、条件选股2个、系统诊断5个、综合分析3个、技术分析引擎1个

**数据源架构（v3.1.0）**：
- **data_sources 数据源层**：25 个数据类型，34 个数据源注册到 SmartRouter
- **SmartRouter 全量覆盖**：L1 工具通过 `SmartRouter.route()` 统一获取数据，自动健康评分/降级/故障隔离
- **独占源标记**：集合竞价/逐笔/F10（eltdx 独有）、涨停归因（同花顺独有）、解禁日历（东财独有）等标记为 `exclusive`
- **eltdx 1.2.0**：行情类第一主源（郑州节点，TCP 3.5ms），独有集合竞价/逐笔/F10
- **数据源看板**：`python -m tradex.dashboard`（端口 8765），可视化查看数据源健康/路由/工具分布；MCP 工具 `get_data_source_dashboard` 可在 Agent 对话中查询

**v3.1.0 更新**：项目改名 tradex-hub（包名 tradex），astock_signals 独立成包 v1.1.0，SmartRouter 全量覆盖 25 数据类型 34 源，新增数据源看板（MCP 工具 `get_data_source_dashboard` + HTML 可视化），工具数 88→89。详见 `docs/architecture.md`。

---

## 项目架构

```
AI Agent (WorkBuddy / Claude Code / Cursor)
        │  MCP 协议 (stdio)
        ▼
  tradex ── FastMCP Server
        │
        ├── AKShare 封装（43 工具）
        │     ├── company_info (4)   → 搜索/概况/竞品
        │     ├── price_data (5)     → 实时行情/历史K线/分时/市值/列表
        │     ├── financial_stmt (8) → 三表+财务指标+增长率+每股+分拆营收
        │     ├── valuation (4)      → PE/PB/PS历史/分红/机构持仓/分析师评级
        │     ├── industry (5)       → 行业板块/成分股/概念/板块资金流/行业PE
        │     ├── market (5)         → 指数快照/资金流/北向/涨跌停/龙虎榜
        │     ├── news_events (4)    → 个股新闻/财报日历/公告/关键词搜索
        │     └── macro_fx (8)       → GDP/CPI/PMI/M2/汇率/国债/两融/增减持
        │
        ├── 信号数据 — 混合数据源（17 工具）
        │     ├── signal_data (17)   → 涨停归因/解禁/概念/预期/技术指标/北向/资金流/龙虎榜/行业/ETF/可转债/涨停板
        │     └─ 数据源：东财直连 + 同花顺 + AKShare
        │
        └── eltdx 1.2.0 封装（5 工具）
              ├── 集合竞价 (auction)    — AKShare 无此功能
              ├── 逐笔成交 (ticks)      — AKShare 无此功能
              ├── F10 资料 (f10)        — AKShare 无此功能
              ├── 分时数据 (minutes)    — 与 AKShare 互补
              └── K 线 (kline)          — 与 AKShare 互补
                    └─ 数据源：通达信私有协议 (TCP 7709)
```

## MCP 工具清单（89 个）

### 1. 公司信息（4 个）— `company_info`

| 工具名 | 功能 |
|--------|------|
| `search_stock` | 搜索A股股票，支持名称或代码模糊匹配 |
| `get_company_info` | 公司基本信息：行业、市值、股本、上市日期 |
| `get_company_profile` | 主营业务构成与业务描述 |
| `get_competitors` | 同行业公司列表（竞争对手/可比公司） |

### 2. 行情数据（5 个）— `price_data`

| 工具名 | 功能 |
|--------|------|
| `get_realtime_quote` | 实时行情：最新价/涨跌幅/量/换手率/PE/PB |
| `get_historical_price` | 历史K线（日/周/月，前复权/后复权/不复权） |
| `get_intraday_data` | 分时数据（当日分时走势/分钟K线） |
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

### 9. A股信号+品种（17 个）— `signal_data`

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
| `get_limit_up_board` 🆕 v3.0.0 | 涨停板/炸板/跌停股票池（封单额/连板天数） | 东财 push2 clist |
| `get_board_sentiment` 🆕 v3.0.0 | 打板情绪速算（涨停/炸板/跌停情绪指标） | 本地计算 |
| `get_limit_up_insight` 🆕 v3.0.0 | 涨停揭秘（题材归因/封单强度/资金流向） | 同花顺 limit_up_detail |

### 10. eltdx 通达信独有（5 个）— `eltdx_data`

| 工具名 | 功能 | 延迟 | AKShare 是否有 |
|--------|------|------|---------------|
| `eltdx_get_auction` | 集合竞价（9:15-9:25撮合过程） | ~40ms | ❌ 没有 |
| `eltdx_get_ticks` | 逐笔成交（价格/量/买卖方向） | ~45ms | ❌ 没有 |
| `eltdx_get_f10` | F10资料（公司概况/题材归因/财务诊断） | ~2200ms | ❌ 没有 |
| `eltdx_get_minutes` | 分时数据（1分钟K线） | ~40ms | ⚠️ 有但源不同 |
| `eltdx_get_kline` | K线（日/周/月/5m/15m/30m/60m） | ~80ms | ⚠️ 有但源不同 |

### 11. 技术指标计算（6 个）— `technical_indicators` 🆕 V2.5.0

纯函数实现，输入价格数组，输出与 Excel/通达信一致的指标值。

| 工具名 | 功能 | 算法 |
|--------|------|------|
| `calculate_ma_ema` | MA/EMA 均线计算 | SMA前n-1个为null；EMA首值用SMA初始化 |
| `calculate_macd` | MACD 指标计算 | DIF=EMA(fast)-EMA(slow)；DEA=EMA(DIF)；MACD柱=2*(DIF-DEA) |
| `calculate_kdj` | KDJ 随机指标 | RSV=(C-LLV)/(HHV-LLV)*100；K=2/3前K+1/3 RSV；D=2/3前D+1/3 K；J=3K-2D |
| `calculate_rsi` | RSI 相对强弱指数 | Wilder 平滑法；RSI=100-100/(1+平均涨幅/平均跌幅) |
| `calculate_boll` | BOLL 布林带 | 中轨=SMA；上下轨=中轨±k*std；带宽+ Percent B |
| `calculate_atr` | ATR 平均真实波幅 | TR=max(H-L,\|H-前C\|,\|L-前C\|)；ATR=EMA(TR) |

### 12. 绩效指标计算（2 个）— `performance_metrics` 🆕 V2.5.0

| 工具名 | 功能 |
|--------|------|
| `calculate_performance` | 完整绩效报告（21项指标）：收益/风险/风险调整收益/交易质量/费用统计/基准对比 |
| `list_performance_metrics` | 列出所有支持的绩效指标及计算公式 |

### 13. 信号生成（3 个）— `signal_generation` 🆕 V2.5.0

| 工具名 | 功能 |
|--------|------|
| `generate_trading_signal` | 单票交易信号生成（5级信号+评分+多指标组合） |
| `scan_stocks_for_signals` | 批量扫描股票信号（按评分排序） |
| `validate_signal_quality` | 信号质量验证（前瞻收益分析） |

### 14. 因子分析（2 个）— `factor_analysis` 🆕 V2.5.0

| 工具名 | 功能 |
|--------|------|
| `calculate_factor_score` | 多因子综合评分（5类22因子，Z-Score 标准化） |
| `get_factor_catalog` | 获取因子库清单（估值/盈利/成长/动量/质量 5 大类） |

### 15. 条件选股（2 个）— `stock_screening` 🆕 V2.5.0

| 工具名 | 功能 |
|--------|------|
| `screen_stocks` | 条件选股扫描（5类30+条件，AND 组合） |
| `get_screening_conditions` | 获取支持的选股条件清单 |

### 16. 系统诊断（5 个）— `diagnostics` 🆕 v3.0.0

系统自省与运维诊断工具，不依赖外部数据源。

| 工具名 | 功能 |
|--------|------|
| `get_data_source_health` | 数据源健康检查（各数据源成功率/延迟/封禁状态） |
| `list_all_tools` | 列出所有已注册的 MCP 工具及模块归属 |
| `get_cache_stats` | 缓存统计（命中率/容量/TTL 过期情况） |
| `health_check` | 系统整体健康检查（模块状态/数据源/缓存综合诊断） |
| `get_data_source_dashboard` 🆕 v3.1.0 | 数据源看板（25 类型 34 源的健康/路由/工具分布，供 Agent 对话查询） |

### 17. 综合分析（3 个）— `composite_analysis` 🆕 v3.0.0

组合调用 L1 数据 + L2 计算结果，输出多维度综合分析报告。

| 工具名 | 功能 |
|--------|------|
| `analyze_stock_comprehensive` | 个股综合分析（基本面+技术面+资金面+估值综合评分） |
| `analyze_industry_comparison` | 行业横向对比分析（多维度排名+景气度评估） |
| `analyze_market_overview` | 市场总览分析（指数/资金/情绪/板块轮动综合研判） |

### 18. 技术分析引擎（1 个）— `analysis_engine` 🆕 v3.0.0

| 工具名 | 功能 |
|--------|------|
| `analyze_technical` | 技术分析引擎（多指标组合分析，输出趋势/支撑压力/买卖信号综合研判） |

---

## 安装

### 1. 克隆项目

```bash
git clone https://github.com/wolfjkd/tradex-hub.git
cd tradex-hub
```

### 2. 创建独立 venv（推荐）

```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或 venv\Scripts\activate  # Windows
```

### 3. 安装 astock_signals 独立包（v1.1.0）

astock_signals 已从 tradex-hub 独立成包，需先安装：

```bash
pip install -e astock_signals/
```

> 或从 GitHub 克隆：`git clone https://github.com/wolfjkd/astock_signals.git && pip install -e astock_signals/`

### 4. 安装 tradex

```bash
cd tradex
pip install hatchling editables
pip install --no-build-isolation -e .
```

### 5. 安装运行时依赖

```bash
pip install "akshare>=1.18.81" mcp pandas pydantic "eltdx>=1.2.0"
```

---

## 配置到 AI Agent

编辑 MCP 配置文件（如 `~/.trae-cn/mcp.json` 或对应 AI Agent 的配置文件）：

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

保存后重启 AI Agent，连接器页面 `tradex` 应显示绿色。

---

## 验证

重启后在对话里测试：

```
查中国能建（601868）K线
```

AI 会调用 `mcp__tradex__eltdx_get_kline`，返回 100 根日 K 线。

---

## 已知限制

1. **eltdx 逐笔数据不带时间字段**（`time: null`），只有价格/量/方向
2. **eltdx F10 延迟高**（~2 秒），但数据独有（题材归因是 AKShare 没有的）
3. **SmartRouter 全量覆盖**（v3.1.0）：L1 工具通过 `SmartRouter.route()` 统一获取数据，自动健康评分/降级/故障隔离，25 数据类型 34 源
4. **Wind/通达信 MCP 不在本项目里**：通过独立 MCP Server 或 AI Agent 的 connector 系统接入

---

## 版本历史

| 版本 | 日期 | 内容 |
|------|------|------|
| v3.1.3 | 2026-08-02 | 修复 P0 bug：SmartRouter 参数名不匹配导致 eltdx 主源永远失败降级 akshare（行情类 fetcher 统一兼容 symbol/code）；修复 eltdx KlineBar 字段映射（date→time, volume→volume_lots），新增 17 个参数归一化回归测试 |
| v3.1.2 | 2026-08-02 | 删除 v2.x 遗留 `src/` 目录（data_manager/market_analyzer，依赖已删的 eltdx_provider），清理 diagnostics.py 的 `src.astock_signals` fallback 死代码 |
| v3.1.1 | 2026-08-02 | 修复 pytest warning：注册 `network` marker（根 + tradex pyproject.toml），消除 tradex/tests 4 个 PytestUnknownMarkWarning |
| v3.1.0 | 2026-08-02 | 项目改名 tradex-hub（包名 cn_financial_mcp→tradex），astock_signals 独立成包 v1.1.0，SmartRouter 全量覆盖 25 数据类型 34 源，data_sources 数据源层接入，新增数据源看板（`python -m tradex.dashboard` 端口 8765 + MCP 工具 `get_data_source_dashboard`），工具数 88→89 |
| v3.0.0 | 2026-08-01 | 架构大重构:版本号单一事实来源、僵尸模块激活、em_client 合并、signal_data 拆分、MCP_HOST 安全加固 |
| v2.5.1 | 2026-08-01 | eltdx 新增 K 线数据接口（KlineBar/KlineData + get_kline()）；.coverage 加入 .gitignore |
| v2.5.0 | 2026-07-26 | 智能决策中台升级：新增15个量化计算工具（技术指标6/绩效2/信号3/因子2/选股2），工具数65→80，从数据中台升级为智能决策中台 |
| v2.4.0 | 2026-07-23 | 修复6个核心接口（东财风控封禁），新增em_client防封客户端，ETF/可转债改为延迟导入，工具数61→65 |
| v2.3.2 | 2026-06-29 | 清理 workbuddy 遗留路径，新增涨停板分析模块 |
| v2.3.1 | 2026-06-24 | 文档修复与版本管理优化（4处不一致修正） |
| v2.3.0 | 2026-06-24 | 新增 ETF/可转债/智能路由/Tick存储/WebSocket 5 个模块，4 个新 MCP 工具（ETF实时+K线/可转债实时+价值分析），61 工具就绪；router 扩展至 17 命令 |
| v2.2.0 | 2026-06-23 | 新增 astock_signals 4 个模块（北向资金/个股资金流/龙虎榜/行业对比），4 个新 MCP 工具，57 工具就绪 |
| v2.1.0 | 2026-06-22 | 新增 A 股信号数据模块：涨停归因/解禁日历/概念归属/一致预期/技术指标，6 个新 MCP 工具，53 工具就绪 |
| v2.0.1 | 2026-06-17 | 集成 eltdx 5 个工具；修复 pyproject.toml hatchling 配置；47 工具全跑通 |
| v2.0.0 | 2026-06-04 | eltdx 通达信协议集成（原 `eltdx_provider.py`） |
| v1.0.0 | 2026-06-02 | 全市场综合分析引擎 |
| v0.1.0 | 2026-06-01 | 项目初始化；集成 tradex |

---

## 许可

Apache-2.0 License

---

## 作者

**郭良勇 (wolfjkd)** — A股T0日内交易员
