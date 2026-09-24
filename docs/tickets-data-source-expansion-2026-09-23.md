# Tickets — tradex-hub 数据源大扩充（SP-2026-09-23-001）

> 状态：全部 ready-for-agent · 一次性全部做完，不分批发版
> 关联 Spec：`docs/data-source-gap-analysis-2026-09-23.md`
> 原则：参考实现不依赖第三方包 · 上游独立性验证 · 一主一备（能一主二备更好）· 期货暂不做 · AI 提炼挪到 TradeX 看板
> 工单粒度：每条是一个垂直切片（fetcher + registry 注册 + 工具层 + 冒烟验收），可独立 demo

## 总览矩阵（扩张后预计数据类型 78 → 116，工具数 129 → ~180）

| 当前态 | 扩张后 |
|--------|--------|
| 78 类型 / 102 源 / 129 MCP 工具 | ~116 类型 / ~180 源 / ~180 MCP 工具 |

---

## 工单清单

| ID | 标题 | 垂直切片焦点 | 阻塞 | 完成标准 |
|----|------|--------------|------|----------|
| T01 | 备胎池基础设施：新增 sina_fetchers.py | 单文件，纯 curl_cffi；新浪研报/新浪资金流/新浪 ETF 期权/新浪实时期货 四个 fetch_fn 骨架 | - | 4 个函数返回 DataFrame，失败返空不抛 |
| T02 | 备胎池基础设施：新增 baidu_fetchers.py | 百度股市通带 MA 的 K 线 fetcher | - | 返回 DataFrame，含 open/high/low/close/ma5/ma20 |
| T03 | 备胎池基础设施：新增 baostock_fetchers.py | baostock TCP 客户端封装：估值历史/退市日/ST 名单 | - | 三函数可独立调用，无注册时优雅提示 |
| T04 | 备胎池基础设施：新增 exchange_official_fetchers.py | 沪深交易所官方源：龙虎榜/官方公告/两融明细/交易日历 | - | 函数封装好，零依赖直连交易所官网 |
| T05 | 补缺基础设施：新增 event_driven_fetchers.py | 东财 datacenter 事件驱动 6 件套：业绩预告/机构调研/股东增减持/股票回购/股权质押/IPO 日历 | - | 6 个 fetch_fn，复用 em_client 限流 |
| T06 | 补缺基础设施：新增 index_constituents_fetchers.py | 中证指数官网 + 国证指数官网：成分/权重/估值 | - | 含 .xls 解析（xlrd），独立于 akshare |
| T07 | 补缺基础设施：新增 macro_official_fetchers.py | 人民银行/统计局/中债/中国货币网：社融/PMI/国债收益率/回购定盘/LPR | - | 含 .xls 解析；优先官方一手 |
| T08 | 补缺基础设施：新增 interaction_fetchers.py | 互动易（深市）+ 上证 e 互动（沪市）+ 热榜 | - | 巨潮互动易 + 上交所 e 互动 |
| T09 | 补缺基础设施：新增 wallstreetcn_fetchers.py | 华尔街见闻 7×24 快讯 + 全球宏观日历 | - | 翻页游标支持 |
| T10 | 补缺基础设施：新增 cctv_news_fetchers.py | 央视网新闻联播条目 + 文字稿 | - | 当晚约 20:00 后可拿 |
| T11 | 补缺基础设施：新增 sw_industry_fetchers.py | 申万行业分类变迁史（.xls） | - | 提供 `sw_industry_as_of(code, date)` 历史归属查询 |
| T12 | 产业链资讯：新增 industry_news_sources.json + industry_news_fetchers.py | 冻结版 sources.json（108 源 / 12 赛道） + 12 赛道 RSS 抓取器（纯 urllib + xml.etree） | - | 抓 1 个赛道返回 DataFrame；合规过滤生效；零第三方依赖 |
| T13 | 产业链资讯：新增 tools/industry_news.py（1 工具聚合 12 赛道） | `get_industry_news(track: str, days: int)` 单工具 | T12 | 工具注册进 MCP；track 校验合法；返回结构含赛道/标题/链接/时间/来源 |
| T14 | registry.py 注册 P0 三件套（ETF 期权 + 业绩预告 + 机构调研） | etf_option_tquote / etf_option_greeks / earnings_forecast / institution_survey 四个 data_type 注册 | T01, T05 | SmartRouter 路由表更新；各 type 至少 1 源 |
| T15 | registry.py 注册事件驱动其余 4 件套 | holder_trades / share_buyback / equity_pledge / ipo_calendar | T05, T14 | 4 个 data_type 注册；同上游（东财 datacenter）串行限流验证 |
| T16 | registry.py 注册指数追踪 3 件套 | index_constituents / index_weights / index_valuation | T06 | 中证 + 国证双源；标 `priority=1`（中证一手）/ `priority=100`（国证备） |
| T17 | registry.py 注册宏观 5 件套 | social_financing / pmi / bond_yield_curve / repo_fixing_rate / lpr_history | T07 | 5 个 data_type；官方源标 `priority=1`；保留 akshare 备 |
| T18 | registry.py 注册固收 + 投资者问答 + 华尔街见闻 + 新闻联播 | bond_yield_curve 已注册则跳过；cninfo_irm / sse_e_interaction / wallstreetcn_lives / macro_calendar / cctv_news | T08, T09, T10 | 各 data_type 至少 1 源；优先官方一手 |
| T19 | registry.py 给已有类型加新浪备胎 | research_report 加 sina_research / fund_flow 加 sina_fund_flow / etf_data 加 sina_option 三类备源 | T01, T14 | 各类型至少 2 源；优先级符合「一主一备」语义 |
| T20 | registry.py 给 historical_kline 加百度备胎（第四备源） | historical_kline 注册 baidu_kline，priority=200 | T02 | 切源验证：手动 mock eltdx+akshare+tdx_mcp 全失败时百度可用 |
| T21 | registry.py 给 valuation 加 baostock 独立 TCP 备胎 | valuation 注册 baostock_valuation，priority=200 | T03 | TCP 与 HTTP 双上游；baostock 不支持北交所时优雅降级 |
| T22 | registry.py 给 dragon_tiger 加沪深交易所官方备胎 | dragon_tiger 注册 sse_dragon_tiger + szse_dragon_tiger 双源（官方席位明细） | T04 | 官方源含营业部席位；与 akshare 上游独立 |
| T23 | registry.py 给已有类型加 baostock 备胎 | st_stock_list / delisting_date 加 baostock 备源 | T03 | 解决 ST 与退市日过滤的单一源风险 |
| T24 | tools/ 新增 etf_option.py（2 工具） | get_etf_option_tquote / get_etf_option_greeks | T14 | 工具签名清晰；失败返 error_response |
| T25 | tools/ 新增 event_driven.py（6 工具） | get_earnings_forecast / get_institution_survey / get_holder_trades / get_share_buyback / get_equity_pledge / get_ipo_calendar | T15 | 6 工具聚合到一个模块；复用 cache 装饰器 |
| T26 | tools/ 新增 index_tracking.py（3 工具） | get_index_constituents / get_index_weights / get_index_valuation | T16 | 中证优先；国证备；处理 .xls 解析异常 |
| T27 | tools/ 新增 macro_official.py（5 工具） | get_social_financing / get_pmi / get_bond_yield_curve / get_repo_fixing_rate / get_lpr_history | T17 | 官方一手优先；akshare 备；做日期归一化 |
| T28 | tools/ 新增 investor_interaction.py（2 工具） | get_cninfo_irm / get_sse_e_interaction | T18 | 沪深两市问答分别工具；按代码自动路由 |
| T29 | tools/ 新增 global_market_news.py（3 工具） | get_wallstreetcn_lives / get_macro_calendar / get_cctv_news | T18 | 7×24 快讯 + 全球宏观日历 + 新闻联播 |
| T30 | tools/ 新增 sw_industry_history.py（2 工具） | get_sw_industry_history / get_sw_industry_as_of | T11 | 历史归属按日期查询；首次启动可缓存 .xls |
| T31 | tools/ 新增 backup_source_tools.py（4 工具） | get_sina_research_reports / get_sina_fund_flow / get_baidu_kline / get_baostock_valuation —— 显式调用备源（适合回测/对照） | T19, T20, T21 | 与已有「主源工具」并存；签名注明「备源直取」 |
| T32 | tools/ 新增 exchange_official.py（4 工具） | get_sse_dragon_tiger / get_szse_dragon_tiger / get_cninfo_announcement_backup / get_trading_calendar | T22, T04 | 官方一手；交易日历替换 eltdx 的 trading_day 兜底 |
| T33 | service/ 抽取新领域 service 模块（option_service / event_service / index_service / macro_service / interaction_service） | 薄抽取层，与现有 service 模式对齐 | T24-T32 | 与 MCP 工具共享；契约一致 |
| T34 | api/routes/ 新增对应 REST 端点（option / event / index / macro / interaction / industry_news） | REST 包裹 service 层；统一响应 `{code, data, msg}` | T33 | 端点契约与 MCP 工具对齐；FastAPI Pydantic 校验 |
| T35 | tests/ 全套测试（每 fetcher ≥3 用例 + 路由降级 + 端点契约） | 单元测试覆盖新 fetcher；集成测试覆盖路由；REST 端点契约测试 | T34 | 新增测试 ≥80 用例；全量回归不退化 |
| T36 | dashboard 数据源健康表自动纳入新源 | 监控看板自动展示新数据源健康度（无需改 dashboard 代码） | T35 | 启动网关后访问 /dashboard 看到新源 |
| T37 | MCP_TOOLS.md 文档更新 | 把新工具按业务领域归类补入工具清单 | T35 | 文档与实际工具数对齐 |
| T38 | README.md + CHANGELOG.md 更新（数据源数、工具数、版本号矩阵） | 升 MINOR 到 v3.6.0；CHANGELOG 写明本次扩充范围与上游独立性论证 | T35 | 版本号 3 处同步（README/代码/Tag 暂不发，按老板「阶段性出成功再发版」原则） |
| T39 | 发版前回归冒烟（含工具数断言更新） | 启动网关 → health → 工具数断言 129 → ~180 → 各新工具抽查 | T37, T38 | 全部新工具可调用、旧工具零回归 |
| T40 | 架构文档 architecture.md 同步更新（数据源矩阵、领域模块清单） | 反映新增的 116 类型 / ~180 源 / ~180 工具 / 5+ 新 service 模块 | T38 | 矩阵头注释与代码一致 |

---

## 阻塞关系图（关键路径）

```
基础设施层（T01-T11，可并行）
  ├── T01 sina_fetchers           ──┐
  ├── T02 baidu_fetchers          ──┤
  ├── T03 baostock_fetchers       ──┤
  ├── T04 exchange_official       ──┤
  ├── T05 event_driven_fetchers   ──┤
  ├── T06 index_constituents      ──┤
  ├── T07 macro_official          ──┤
  ├── T08 interaction_fetchers    ──┤
  ├── T09 wallstreetcn_fetchers   ──┤
  ├── T10 cctv_news_fetchers      ──┤
  ├── T11 sw_industry_fetchers    ──┤
  └── T12 industry_news_*         ──┘
                                    │
注册层（T14-T23，依赖基础设施）   │
                                    │
工具层（T24-T32，依赖注册）         │
                                    │
服务/路由层（T33-T34，依赖工具）    │
                                    │
测试/文档/发版（T35-T40，依赖前面） │
```

**关键路径**：T01-T11 并行 → T14-T23 并行 → T24-T32 并行 → T33 → T34 → T35 → T39

---

## 上游独立性论证（避免假双源重蹈 v3.3.14 覆辙）

| 类型 | 主源 | 备源 1 | 备源 2 | 上游独立性 |
|------|------|--------|--------|-----------|
| historical_kline | eltdx (TCP) | akshare (HTTP 抓东财) | tdx_mcp (官方 MCP) | + **baidu** (HTTP) ✓ 四源四上游 |
| research_report | tdx_mcp | **sina** (HTTP) | — | ✓ 独立 |
| fund_flow | akshare（裸源风险） | **sina** (HTTP) | — | ✓ 解决裸源 |
| dragon_tiger | akshare | **sse/szse 官方** | em_datacenter (P999) | ✓ 官方一手 |
| valuation | akshare | eltdx | **baostock (TCP)** | ✓ TCP 独立通道 |
| etf_option | **sina** | — | — | 单源但新浪期权接口稳定 |
| bond_yield_curve | **chinabond** (官方) | akshare | — | ✓ 官方一手 |
| macro_calendar | **wallstreetcn** | akshare_baidu_economic | — | ✓ 独立 |
| cctv_news | **央视网** | — | — | 单源但官方一手 |
| industry_news | **RSS 直连 108 源** | — | — | 多源天然分散 |

---

## 风险点与缓解

| 风险 | 缓解 |
|------|------|
| 新增 .xls 解析依赖（中证/国证/申万/人行） | 用 xlrd（已是 akshare 依赖），不引入新包 |
| 互动易 / e互动 反爬 | 复用 em_client 的节流 + Session 复用模式；限流 ≥1s |
| 中证指数官网偶尔返回 HTML 而非 .xls | fetcher 内做 content-type 校验，失败返空 DataFrame 不抛 |
| 工具数从 129 → ~180，单进程 MCP 启动变慢 | 启动耗时预计 +1~2s（薄包装），可接受 |
| 测试覆盖工作量大 | 每 fetcher 至少 3 用例（成功/失败/空）；优先批量用 `pytest.parametrize` |
| 文档维护成本 | 工具数自动化生成（已有 MCP_TOOLS.md 流程）；矩阵头改一次 |

---

## 工单模板（参考，按本表执行）

```markdown
# T<NN>: <标题>

**What to build:** 用户视角这条工单让什么 work（端到端行为），不是按层列实现清单。

**Blocked by:** T<NN>, T<NN> 或 "None（可立即开工）"

**Status:** ready-for-agent

- [ ] 验收标准 1（如：fetcher 函数存在且可独立调用）
- [ ] 验收标准 2（如：注册到 SmartRouter 后路由可达）
- [ ] 验收标准 3（如：失败时返空 DataFrame 不抛异常）
- [ ] 验收标准 4（如：测试用例 ≥3 条通过）
```

---

## 不做的事（明确排除）

- ❌ 期货大宗相关（老板指示暂不做）：上期所/上期能源/郑商所/中金所/广期所日行情、新浪实时期货、A50、上金所现货、商品期权
- ❌ 产业链资讯 AI 提炼（挪到 TradeX 看板项目，tradex-hub 只交付原始 RSS 数据）
- ❌ iwencai OpenAPI（需 Key，与 wencai_query 的 pywencai 重复价值不大）
- ❌ 真实发版（按老板「阶段性出成功再发版」原则，本次只 commit + push 保成果，版本号 bump + tag 留到积累更多改动后再发）
- ❌ 引入任何新的第三方 Python 包（除已有 xlrd）

---

*wolfjkd · 2026-09-23 · 一次性扩充，循迹弹并行*
