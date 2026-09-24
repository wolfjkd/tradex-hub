# 数据源缺口分析与整合方案

> 日期：2026-09-23 | 作者：老板 + buddy | 状态：决策稿（待拆工单）

## 0. 结论先行（TL;DR）

借鉴两个项目（`simonlin1212/investment-news` + `simonlin1212/a-stock-data`）后，对 tradex-hub（v3.5.1，78 类型 / 102 源实例）的整合分两类：

| 类别 | 项目 | 价值 | 行动 |
|------|------|------|------|
| **互补新维度** | investment-news | 108 个海外英文产业链 RSS / 12 赛道（一一对应 A 股板块）—— tradex-hub **完全没有**「板块催化的全球领先信号」这一层 | **新增**「赛道资讯」数据类型族 |
| **一主一备的备胎池** | a-stock-data | 34 源中约 28 个与 tradex-hub 现有源同族（腾讯/新浪/东财/同花顺/巨潮），可作现有裸类型的第二备胎；另有 ~13 个 tradex-hub **完全没有**的能力 | **补缺 + 加备胎** |

整合策略：**先补缺（新增能力）→ 再加备胎（强化已有类型）→ 最后引入产业链资讯（互补维度）**。三阶段递进，每阶段可独立验证、独立发版。

---

## 1. tradex-hub 现状速览

- 版本 v3.5.1，双协议（129 MCP + 48 REST）
- SmartRouter 注册 **78 个数据类型 / 102 个源实例**，三梯队降级（不封 IP → 低风险 → 限流防封）
- 已有源：eltdx（行情第一主源）/ akshare / tencent_http / ths / cninfo / cls / em（多数降级到 P999）/ tdx_mcp / tdx_local / wencai
- 已知裸类型（仅 1 源或主源被封后无备胎）：
  - `fund_flow`（akshare 单源，东财 push2his 失联）
  - `lockup_expiry`（em_datacenter 独占 P999）
  - `hot_money`（ths_editorial 独占）
  - `limit_up_board` / `concept_attribution` / `market_breadth` / `industry_quotes` / `stock_boards`（已被注释移除，整类型失效）

---

## 2. investment-news 的借鉴价值（互补新维度）

### 2.1 项目本质

- **不是行情数据源**，而是「海外产业链一手资讯 → AI 提炼成中文今日要点 → 浏览器看板」
- 108 个 RSS 源，纯 Python 标准库抓取，零 Key，用户自带大模型（Claude 订阅或 OpenAI 兼容 API）做摘要
- 12 个赛道**一一对应 A 股板块**：

| 赛道 key | 中文名 | 对应 A 股板块 | 代表源（节选） |
|---------|--------|--------------|---------------|
| `ai` | AI/大模型 | AI 算力 / 大模型应用 | OpenAI / DeepMind / arXiv cs.AI / 量子位 / 机器之心 / 新智元 / 智东西 / MIT TechReview / The Verge AI / TechCrunch AI / HuggingFace / KDnuggets / BAIR / Import AI |
| `semi` | 半导体/芯片 | 半导体设备 / 材料 / 芯片设计 | DIGITIMES / SemiAnalysis / SemiEngineering / EE Times / IEEE Spectrum / SemiWiki / Semiconductor Today / Electronics Weekly / All About Circuits |
| `robot` | 机器人/自动化 | 机器人 / 工业自动化 | The Robot Report / IEEE Spectrum Robotics / Robohub / Robotics & Automation News / Robotics Business Review |
| `auto` | 汽车/新能源车 | 新能源车 / 智驾 | Electrek / InsideEVs / The Verge Transport / TechCrunch Transport / CnEVPost |
| `energy` | 能源/新能源 | 光伏 / 储能 / 锂电 / 氢能 | CleanTechnica / Utility Dive / pv magazine / Energy Storage News / OilPrice / Canary Media / PV Tech / Renewable Energy World / 国际能源网 |
| `bio` | 生物医药/健康 | 创新药 / CXO / 医疗器械 | STAT News / Endpoints News / FierceBiotech / FiercePharma / BioPharma Dive / GEN / Nature Biotech |
| `space` | 航天/太空 | 商业航天 | SpaceNews / Space.com / Spaceflight Now / Payload / NASA / NASASpaceflight |
| `security` | 网络安全 | 网安 / 信创 | Krebs on Security / The Hacker News / BleepingComputer / Dark Reading / SecurityWeek |
| `tech` | 科技/互联网 | 互联网 / 软件服务 | TechCrunch / The Verge / Ars Technica / Hacker News / WIRED / Techmeme / 36氪 / 钛媒体 / IT之家 / GitHub Blog / Stratechery / 虎嗅 / 动点科技 / 月光博客 / Solidot / 白鲸出海 |
| `consumer` | 消费电子/数码 | 消费电子 / 数码 | Engadget / 9to5Mac / 9to5Google / GSMArena / Android Authority / DPReview / 少数派 |
| `macro` | 财经/宏观 | 全局宏观 / 大金融 | CNBC / FT / WSJ Markets / MarketWatch / Yahoo Finance / 华尔街见闻 / Finextra / SEC / Federal Reserve / Seeking Alpha / 东方财富股票 / 东方财富资讯 / 经济观察网 |
| `science` | 科学/前沿 | 科研 / 前沿科技 | Nature News / ScienceDaily / Quanta Magazine / New Scientist / Live Science / MIT News / Science News / Ars Technica Science |

### 2.2 与 tradex-hub 的关系

- **完全互补**：tradex-hub 的新闻层（个股新闻 / 财联社电报 / 巨潮公告 / 新浪财经）都是 **A 股内部信号**，没有任何「海外一手产业链源 → 板块催化」这一层
- 老板的交易场景：**题材股 / 题材轮动** —— 全球产业链信号往往是 A 股板块行情的**领先指标**（OpenAI 发模型 → 算力板块异动；Tesla 发布会 → 智驾板块；NVIDIA 财报 → AI 芯片）
- 整合定位：**新增「赛道资讯」数据类型族**，挂在 news 领域下，不替换现有新闻源

### 2.3 整合方案（推荐）

不直接搬整个 investment-news 项目（它带浏览器看板和 AI 提炼，是终端产物）。借鉴方式：

1. **把 108 个 RSS 源清单搬过来** → 作为 `data_sources/industry_news_sources.json`（赛道 → 源列表的映射表）
2. 新增 fetcher 模块 `data_sources/industry_news_fetchers.py`：
   - 每个 fetcher 抓某个赛道的若干 RSS（纯 urllib + xml.etree，零依赖）
   - 合规过滤（剔除博彩/加密/色情）
   - 返回 DataFrame（赛道、标题、链接、发布时间、来源、原文摘要）
3. 注册到 SmartRouter，新增 12 个数据类型：`industry_news_ai` / `industry_news_semi` / ... / `industry_news_science`
4. 工具层加 12 个 MCP 工具：`get_industry_news_ai` 等，或合并成一个 `get_industry_news(track: str)` 工具（推荐后者，节省工具数）
5. **不做 AI 提炼**（那是 investment-news 的产物，tradex-hub 只负责「数据」，下游让老板的复盘自动化 / Obsidian 笔记 / AI Agent 自行消化）

### 2.4 优先级建议

- 第一批（高价值赛道，老板常关注）：`ai` / `semi` / `auto` / `energy` —— 4 个赛道 ~50 源
- 第二批（补齐板块）：`robot` / `bio` / `space` / `security` —— 4 个赛道 ~30 源
- 第三批（兜底）：`tech` / `consumer` / `macro` / `science` —— 4 个赛道 ~30 源

---

## 3. a-stock-data 的借鉴价值（一主一备 + 补缺）

### 3.1 项目本质

- **87 个端点 / 34 个数据源 / 15 层架构**，与 tradex-hub 同属「A 股全栈数据」，重叠度高
- 卖点：除 iwencai 外零 Key，纯 HTTP 直连（除 mootdx / baostock 是 TCP 库）
- 与 tradex-hub 的根本差异：
  - a-stock-data 是**单文件 SKILL.md + 内嵌 Python**（给 AI 编程助手用，无服务端）
  - tradex-hub 是**双协议服务**（MCP + REST，带健康检查/降级/限流/可观测性）
  - **架构上 tradex-hub 更先进**，但 a-stock-data 的**端点覆盖更广**（87 vs tradex-hub 的 ~78 类型）

### 3.2 真正的「补缺」（tradex-hub 完全没有的）

按价值排序（P0 = 老板交易常用，P3 = 边缘）：

| 优先级 | 数据类型 | a-stock-data 实现 | 主要来源 | 应用场景 |
|--------|---------|------------------|---------|---------|
| **P0** | **ETF 期权 T 型报价 / 希腊字母 / IV** | `sina_option_tquote` / `sina_option_greeks` | 新浪财经期权 | 期权交易必需 |
| **P0** | **业绩预告** | `earnings_forecast(code, report_date)` | 东财 datacenter | 财报季事件驱动 |
| **P0** | **机构调研** | `institution_survey(code, start, end)` | 东财 datacenter | 主力动向追踪 |
| **P1** | **中证 / 国证指数成分与权重** | `index_constituents` / `index_weights` | 中证指数 / 国证指数官网 | 指数追踪 / 被动投资 |
| **P1** | **中证指数 PE 与股息率** | `index_valuation(index_code)` | 中证指数官网 | 指数估值 |
| **P1** | **华尔街见闻 7×24 全球快讯 + 全球宏观日历** | `wallstreetcn_lives(channel, cursor)` / `macro_calendar(start, end, country)` | 华尔街见闻 API | 海外宏观领先信号 |
| **P1** | **期货日行情 + 持仓排名 + 商品/股指期权** | `futures_daily` / `options_daily` / `futures_position_rank` | 五家期货交易所（上期所/上期能源/郑商所/中金所/广期所） | 期货大宗对冲 |
| **P1** | **新浪实时期货 + A50 期指 + 上金所现货** | `futures_realtime` / `a50_futures` / `sge_spot` | 新浪财经 / 上金所 | 夜盘 / 外盘关联 |
| **P1** | **互动易（深市）+ 上证 e 互动（沪市）** | `cninfo_irm(code)` / `sse_e_interaction(code)` | 巨潮 / 上交所 | 投资者问答挖掘 |
| **P1** | **中债国债/信用债收益率曲线** | `chinabond_yield_curve(start, end, curve)` | 中债 | 固收 / 利率信号 |
| **P1** | **中国货币网回购定盘利率 FR/FDR** | `repo_fixing_rates(kind)` | 中国货币网 | 流动性监控 |
| **P2** | **央视新闻联播文字稿** | `cctv_news(date, with_content)` | 央视网 | 政策信号 |
| **P2** | **股东增减持 + 股票回购 + 股权质押 + 新股日历** | `holder_trades` / `share_buyback` / `equity_pledge` / `ipo_calendar` | 东财 datacenter | 事件驱动 4 件套 |
| **P2** | **申万行业分类变迁史** | `sw_industry_history` / `sw_industry_as_of` | 申万研究 | 历史行业归属 |
| **P2** | **baostock 估值历史 + 上市退市日 + ST 名单** | `baostock_valuation_history` / `baostock_stock_basic` / `st_stock_list` | baostock / 东财 | 历史回测 / 退市票过滤 |
| **P3** | **深交所官方整月交易日历** | `trading_calendar(year, month)` | 深交所 | 回测日历 |
| **P3** | **新浪研报列表** | `sina_research_reports(code, page)` | 新浪财经 | 研报第二来源 |

合计约 **17 类「补缺」**（其中 P0 有 3 类，P1 有 8 类，P2 有 5 类，P3 有 2 类）。

### 3.3 「一主一备」的备胎搭配（强化已有类型）

a-stock-data 的若干实现可作为 tradex-hub 现有类型的**第二备胎**（优先级 >100，主力失效时启用）：

| tradex-hub 类型 | 现有源 | a-stock-data 提供的备源 | 上游差异（关键） |
|----------------|--------|----------------------|----------------|
| `historical_kline` | eltdx + akshare + tdx_mcp | **百度股市通带 MA 的 K 线**（`baidu_kline_with_ma`） | 百度与腾讯/akshare 不同上游，**真正独立的第三备胎** |
| `research_report` | tdx_mcp 的 `wenda_report_query`（单一） | **新浪研报列表**（`sina_research_reports`） | 新浪与通达信完全不同上游 |
| `company_announcement` | `cninfo_direct`（单一） | **深交所官方公告**（深市）+ 东财公告（沪市）+ PDF | 巨潮被封时的官方备胎 |
| `realtime_quote` | eltdx + akshare + tencent + tdx_mcp | **百度股市通实时报价** | 第四备胎，覆盖百度上游 |
| `valuation` | akshare + eltdx | **baostock 估值历史** | baostock 是独立 TCP 源，与东财系无关 |
| `financial_stmt` | akshare + sina（已配） | （已配，无需补） | — |
| `dragon_tiger` | em_datacenter(P999) + akshare | **沪深交易所官方龙虎榜**（含营业部席位） | 官方源，非东财系 |
| `fund_flow` | akshare（裸源，东财被封） | **新浪日度资金流**（`fund_flow_backup`） | 新浪独立上游，解决裸源问题 |
| `industry_comparison` | akshare + ths_flow | （已配 ths_flow，无需补） | — |

### 3.4 整合优先级排序

按「价值 × 实现成本」综合排序：

#### 第一批（高价值 + 低成本，先做）

1. **新浪研报列表** → 给 `research_report` 加第二备源（破解单源风险）
2. **百度股市通带 MA 的 K 线** → 给 `historical_kline` 加第四备源
3. **沪深交易所官方龙虎榜** → 给 `dragon_tiger` 加官方备源
4. **新浪日度资金流** → 解决 `fund_flow` 裸源问题
5. **baostock 估值历史 + 退市日 + ST 名单** → 给 `valuation` 加独立备源 + 新增退市票过滤能力
6. **新浪 ETF 期权 T 型报价 + 希腊字母 + IV** → 新增 `etf_option_tquote` / `etf_option_greeks` 两个全新数据类型

#### 第二批（中价值）

7. **业绩预告 + 机构调研 + 股东增减持 + 回购 + 股权质押 + IPO 日历** → 新增事件驱动 6 件套
8. **中证/国证指数成分 + 权重 + 估值** → 新增指数追踪 3 件套
9. **华尔街见闻 7×24 + 全球宏观日历** → 新增海外宏观 2 件套
10. **互动易 + 上证 e 互动** → 新增投资者问答 2 件套
11. **中债收益率曲线 + 货币网回购定盘** → 新增固收 2 件套
12. **五家期货所日行情 + 持仓排名 + 商品期权** → 新增期货大宗族

#### 第三批（低价值或需较大改造）

13. **新浪实时期货 + A50 + 上金所现货** → 夜盘大宗补充
14. **央视新闻联播文字稿** → 政策信号
15. **申万行业变迁史** → 历史回测辅助
16. **深交所官方交易日历** → 替代 eltdx 的 `trading_day`

---

## 4. 推荐路线图（按老板「发版不要太频繁，阶段性出成功再考虑发一次版」原则）

### 阶段一（建议 v3.6.0，~2-3 周）：产业链资讯 + 高价值补缺

- 引入 investment-news 的 12 赛道 108 源 → 新增 `industry_news_*` 类型族（合并为 1 个工具 `get_industry_news(track)`）
- 补 P0 三件套：ETF 期权、业绩预告、机构调研
- 加 6 个备胎：新浪研报、百度 K 线、官方龙虎榜、新浪资金流、baostock 估值、新浪财报备源
- 新增数据类型数：~6 + 新工具数：~10
- 版本号升 MINOR（v3.5.1 → v3.6.0）

### 阶段二（建议 v3.7.0，~3-4 周）：事件驱动 + 指数追踪

- 事件驱动 6 件套（业绩预告等）
- 指数追踪 3 件套（中证/国证成分 + 权重 + 估值）
- 海外宏观 2 件套（华尔街见闻）
- 投资者问答 2 件套（互动易 + 上证 e 互动）
- 固收 2 件套（中债 + 货币网）
- 新增数据类型数：~15

### 阶段三（建议 v3.8.0，按需）：期货大宗 + 兜底

- 期货大宗族（五家期货所）
- 新浪实时期货 + A50 + 上金所
- 央视新闻联播
- 申万行业变迁史
- 深交所官方交易日历
- 新增数据类型数：~10

三阶段合计：**约 40 个新数据类型 / 50+ 新 MCP 工具**。完成后 tradex-hub 工具数从 129 升至 ~180，数据类型数从 78 升至 ~118。

---

## 5. 整合时的实现注意事项

### 5.1 借鉴方式：**参考实现而非依赖**

- 不引入 investment-news 或 a-stock-data 作为 Python 依赖（它们是独立项目，作者随时可能改接口）
- **借鉴方式 = 学方法（URL、参数、签名、解析）+ 自己实现 fetcher**
- 每个 fetcher 在 `data_sources/` 下新增文件，注册到 `registry.py`，遵循 tradex-hub 的 fetch_fn 签名约定

### 5.2 SmartRouter 注册约定

```python
# 补缺类型（全新能力）：作为主源 priority=1
router.register("etf_option_tquote", "sina_option", fetch_xxx, priority=1)

# 加备胎（已有类型）：作为第二备源 priority=100 或第三备源 priority=200
router.register("historical_kline", "baidu", fetch_baidu_kline, priority=200)
```

### 5.3 上游独立性验证（避免「假双源」）

历史教训（v3.3.14 / v3.3.15）：曾出现「双源名实同上游」（akshare + 东财 push2his 其实都走东财），主源被封时备源同时失效。

借鉴 a-stock-data 时**必须验证上游独立性**：
- 新浪 vs 东财：独立 ✓
- 百度 vs 腾讯：独立 ✓
- baostock vs akshare：独立（前者 TCP，后者 HTTP）✓
- 沪深交易所 vs 东财 datacenter：独立（前者官方、后者聚合）✓
- 中证指数官网 vs akshare：独立（前者一手、后者抓前者）→ 中证一手优先

### 5.4 反爬与限流

a-stock-data 文档强调东财系接口有访问频率风控，**所有东财调用统一经 `em_get()` 串行限流防封**。
tradex-hub 已有 `em_client.py`（含节流 + Session 复用），借鉴时复用同一客户端即可。

### 5.5 数据格式对齐

- 所有 fetcher 统一返回 `pd.DataFrame`（与 tradex-hub 现有约定一致）
- 工具层用 `df_to_json` 序列化，字段命名沿用中文（与 akshare 习惯对齐）
- 失败时返空 DataFrame，不抛异常（容错设计）

---

## 6. 待老板拍板的开放问题

1. **阶段一的范围**：是否同意先把 investment-news 的 12 赛道 + P0 三件套（ETF 期权/业绩预告/机构调研）打包进 v3.6.0？还是只做其中一部分？
2. **产业链资讯是否引入 AI 提炼**：investment-news 自带「今日要点 + 中文翻译」AI 流程，tradex-hub 是否要做？（推荐不做，让下游自动化 / Obsidian 笔记 / AI Agent 自己消化；tradex-hub 保持「纯数据层」定位）
3. **期货大宗的优先级**：老板目前主要做 A 股 T+0，期货大宗是否真要排进阶段二？还是延后到阶段三甚至不做？
4. **iwencai API Key**：a-stock-data 强调 iwencai 是唯一需要 Key 的源；tradex-hub 现有 wencai_query 走的是 `pywencai` 库（零 Key），是否需要再加一层 iwencai OpenAPI 备胎？
5. **sources.json 的更新机制**：investment-news 的 108 源清单会随作者更新而变化，tradex-hub 抄过来后是冻结还是定期同步？（推荐冻结，避免上游改动连带破坏）

---

## 附：参考链接

- investment-news: https://github.com/simonlin1212/investment-news
- a-stock-data: https://github.com/simonlin1212/a-stock-data
- tradex-hub 现有架构：`docs/architecture.md`
- tradex-hub 数据源注册表：`tradex/src/tradex/data_sources/registry.py`
