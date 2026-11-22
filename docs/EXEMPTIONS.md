# EXEMPTIONS.md — 设计内豁免唯一清单（单一真源）

> **定位**：本仓全部「设计内例外」的唯一登记处。豁免 = 稀少且有书面理由的例外，不是第二张功能清单——加豁免先过老板裁决，改豁免先改这里并同步 AGENTS.md 指针。
> **机械核验**：出口形态（表一）由 `scripts/check_exit_shapes.py`（票 06）AST 枚举比对，漂移即全量门红。
> **来源**：qc-20261117 台账 QI-STD-01/93、qc-20261122 台账 QI-ARCH-17/19、交接文档 17/18、老板裁决（2026-11-18 拍板①② / 2026-11-22 裁决①②③）。

## 表一：mcp_serve 出口手写豁免（9 工具）

> 背景：A①A② 全量推广后 MCP 出口收拢进 `tools/_mcp_serve.py` 单点；以下工具因形态不适配保留手写出口（AST 实测账 **2026-11-22 票 07 后核对**：181 mcp_serve + 8 手写【本表，含 tdx_tq 组 2】+ 3 tdx_mcp 自有骨架 = 192；eltdx_data 31 工具已上提归 mcp_serve 单点、批外清零，QI-ARCH-17 闭环）。

| 工具 | 文件 | 豁免理由 |
|---|---|---|
| composite_analysis 组 3 工具 | composite_analysis.py | async gather + 多分支容错降级语义，mcp_serve 同步 build 不适配（代码注释自证；A⑤ route 收敛（票 13，裁决③）只统一 quote 维度取数口径（改调 price_service.get_realtime_quote），工具体 async 形态不变，本行豁免理由仍成立） |
| get_dividend_data | valuation.py | 多级缓存降级编排，build 单函数不适配（票 13 裁决③后若搬 service，本行同步更新） |
| list_all_tools | diagnostics.py | 内部 await list_tools 协程，同步 build 不适配 |
| health_check | diagnostics.py | 多段 try 诊断语义，逐段独立报健康态 |
| tdx_tq 组 2 工具 | tdx_tq.py | `_route_to_json` 自有单点骨架（避免双出口单点并存，交接文档 18 决策 3） |

**核验纪律**：新增手写出口必须先在本表登记，否则 06 门抓红；登记需给理由并经老板确认。

## 表二：rule 5 空态语义豁免（3 fetcher）

> 背景：AGENTS.md rule 5 要求 fetcher 失败必须抛出由 SmartRouter 记账降级；以下三者未注册进 SmartRouter（registry 无对应类型）、TradeX 直连消费，断源返回诚实空态。

| Fetcher | 位置 | 豁免理由 |
|---|---|---|
| dzh_fetchers（大智慧365 全球指数） | data_sources/dzh_fetchers.py | 未注册 SmartRouter，TradeX 直连；断源返回诚实空态 `{}`（QI-STD-01，2026-11-18 拍板①） |
| fetch_sina_world_index（新浪 znb） | data_sources/sina_fetchers.py | 同上；一旦注册进 SmartRouter 本豁免即失效，必须改抛出语义 |
| fetch_global_index_spot（东财 spot） | data_sources/akshare_em.py | 同上；代码内注明豁免口径（akshare_em.py 空态段） |

### 表二注记：已注册源空态语义盘点——合法空结果保留点（QI-STD-26，2026-11-22 工单 17）

> 背景：rule 11 注册门槛②（2026-11-18 拍板②）空态语义统一批（工单 17）对全 data_sources 已注册源 AST 盘点 74 处静默空态折叠点，**37 处改抛出**（变化清单见台账「工单 17 施工记录」），下列 **37 处保留为合法空结果**（「查询天然无数据」语义交叠处，逐组书面豁免；行号为改后现行）。此注记为点级语义豁免登记，与上表 fetcher 级豁免（未注册）性质不同：保留点所在 fetcher 均已注册，其硬失败（HTTP/JSON/解析炸）仍由外层 except 抛出走降级链。

| 组 | 位置（处数） | 保留理由 |
|---|---|---|
| 查询天然无数据（per-stock 记录型） | event_driven_fetchers.py 六函数 raw 空分支（6） | 业绩预告/调研/增减持/回购/质押/IPO 按股查询，无记录=常态答案；单源 pri=999 无降级目标 |
| 镜像死分支（防御不可达） | event_driven 六函数 `if not rows`（6）＋ chinabond :218、wscn lives :111、wencai_news :337、szse 交易日历 :448、sse 两融 :334（5） | rows 与 raw 一一镜像无过滤，raw 空已先行处理 |
| 查询天然无数据（公告） | news_fetchers.py cninfo :287/:319、exchange_official_fetchers.py szse 公告 :500（3） | per-stock 公告查询，无公告股票合法空 |
| 接口设计日期过滤 | exchange_official_fetchers.py sse 龙虎榜 :205、szse 龙虎榜 :262（2） | 数据未发布/该日无榜=合法暂态（代码注释自证） |
| 查询天然无数据（两融） | exchange_official_fetchers.py sse :321、szse :371（2） | 按日期查询，非交易日/未发布合法空 |
| 查询天然无数据 | sw_industry_fetchers.py as-of subset.empty :131（1） | as-of 区间无记录=查询答案（history.empty 毒缓存断源面已改抛出，见 QI-STD-27） |
| 查询天然无数据 | baostock_fetchers.py 退市日期 :195（1） | 存续股无退市日期=该工具正常答案 |
| 能力边界 | baostock_fetchers.py :106/:175（2） | bs_code None = 不支持该市场（北交所），「此源无此码数据」诚实 |
| 查询天然无数据 | baostock_fetchers.py 估值 :140（1） | 日期窗零行合法；下游 PE>0 过滤把空当合法消费 |
| 搜索无结果 | wencai_fetchers.py :246/:324（2） | 问财「无匹配」一等答案；shortline_service 显式消费空表=触发同花顺兜底信号 |
| 输入校验（非源状态） | wencai_fetchers.py :203/:286（2） | 空 query/keyword = 调用方空参，非断源/错码/无数据三类 |
| 本地数据态 | tdx_local.py :136/:216（2） | 单票本地无 .day/.lc5 文件=「本地无该票数据」诚实答案（源态 tdxdir 缺失已改抛出） |
| 过滤后空=查询答案 | wallstreetcn_fetchers.py 宏观日历 :186（1） | min_importance 过滤后空=「该时段无该级别事件」 |

（合计 6+6+3+2+2+1+1+2+1+2+2+2+5+1 = 37 ✓；新增保留点须先在此登记并经老板确认，同表一纪律。）

## 表三：rule 7 裸 get/set 缓存豁免（范围：df_to_json 序列化场景）

> 背景：裁决②（2026-11-22 老板拍板）——rule 7 收紧，裸 get/set 豁免范围**仅限 tools 层 `df_to_json` 序列化字符串缓存**；其余一切手写 get/set 一律迁移 `cache.get_or_set`（迁移施工 = 工单 09 试点 → 10 全量）。

| 场景 | 豁免理由 |
|---|---|
| tools 层 df_to_json 字符串缓存（裸 get/set） | df_to_json 自带格式化序列化，factory 闭包形态与其不匹配；属序列化边界而非缓存策略问题 |

**范围外即违规**：dict/list/对象等非 df_to_json 缓存走裸 get/set = 违反 rule 7，09/10 迁移清单之外新出现的按门纪律处理。

### 表三注记：QI-ARCH-10 全仓实测盘点（2026-11-22，工单 09/10 施工）

> 实测 68 处手写 get/set × 20 文件（P1 估 65 处 ×17 文件，以施工实测为准）。迁移 13 处后，保留组全部登记如下——豁免范围外的裸 get/set grep 以本清单为准判零。

**A 组｜df_to_json 序列化串缓存（裁决②豁免内，保留，28 处；票 13 后实况 26 处——news_events 1 + price_data 1 随编排迁 service，见各行注记）**

| 文件 | 处数 | 说明 |
|---|---|---|
| tools/macro_fx.py | 8 | 全部 df_to_json 串缓存 |
| tools/news_events.py | 10 | 全部 df_to_json 串缓存（票 13 后：get_financial_calendar 1 处已迁 news_service get_or_set 对象缓存） |
| tools/valuation.py | 4 | 全部 df_to_json 串缓存（get_dividend_data 双分支各一 set） |
| tools/exchange_official.py | 1 | df_to_json 串缓存 |
| tools/kpl.py | 3 | get_kpl_limit_up / get_kpl_boards / get_kpl_bidding（df_to_json，含条件 TTL 变体） |

**B 组｜非 df_to_json 串缓存，get_or_set 不可保真迁移（保留待裁决，22 处）**

| 文件 | 处数 | 不适配理由 |
|---|---|---|
| tools/signal_data_base.py | 5 | dict_to_json/json.dumps 串缓存 + miss 路线经 `mcp_serve(dump=dict_to_json)`/默认 dump 双重编码、hit 路线单编码直返（**原态 hit/miss 线上格式不一致**，QI-BUG-03 待裁决）；其中 2 处另有内容条件缓存 |
| tools/signal_data_etf.py | 2 | 同上双重编码不对称 + 条件缓存 |
| tools/signal_data_board.py | 3 | 同上 + get_limit_up_board 条件缓存含 WsServer 推送副作用 |
| tools/signal_data_cb.py | 2 | 同上双重编码不对称 + 条件缓存 |
| tools/signal_data_flow.py | 3 | 同上双重编码不对称（get_fund_flow_signal / get_dragon_tiger_signal / get_industry_comparison_signal） |
| tools/analysis_engine.py | 1 | analyze_technical 同上双重编码不对称 |
| tools/signal_data_flow.py（get_northbound_flow_signal） | 1 | 运行时类型依赖序列化器（dict→dict_to_json / DataFrame→df_to_json 双分支），命中丢类型信息不可保真迁移 |
| tools/tdx_tq.py | 1 | `_route_to_json` 骨架按运行时类型选 df_to_json/dict_to_json，命中丢类型信息不可保真迁移 |
| tools/tdx_mcp.py | 3 | 同上骨架（`_router_route_cached`）+ 3 工具体前置 get |

> B 组小计 22 = 双重编码组 16（signal_data_base 5 + etf 2 + board 3 + cb 2 + flow 3 + analysis_engine 1，QI-BUG-03）+ 类型依赖/多级编排组 6（flow.northbound 1 + market_capitalization 1 + tdx_tq 1 + tdx_mcp 3）。**票 13 更新（2026-11-22）**：market_capitalization 1 处已随编排迁 service（price_service.get_market_capitalization，get_or_set 对象缓存 + 出口运行时判型序列化，TTL_REALTIME 仅内存层无历史串还原面），脱离本组实况清单——**票 13 后实况小计 21**（类型依赖/多级编排组余 5），实况 grep 判零以本行注记为准。

**C 组｜dict 对象缓存但 get_or_set 同步 factory 契约不适配（保留待裁决，5 处）**

| 文件 | 处数 | 不适配理由 |
|---|---|---|
| service/diagnostic_service.py | 2 | analyze_stock_comprehensive / analyze_market_overview 的取数体为 `await asyncio.gather(...)`，get_or_set factory 为同步回调，协程不可等待（误用会缓存未 await 的 coroutine 对象） |
| tools/composite_analysis.py | 3 | 同上（async gather / await _safe_call 编排体） |

**D 组｜已迁移（13 处）**：service/market_service.py 7（工单 09 试点）+ service/diagnostic_service.py 1（analyze_technical）+ service/bigcaps_service.py 1（out=/store= 形态）+ service/price_service.py 1 + service/turnover_service.py 2（out=/store= + 降级原因串 store 闸门）+ tools/kpl.py 1（get_kpl_sentiment）——键/TTL/None 不缓存语义逐一保真，见台账「机械迁移模式」。

**D 组续（票 13，QI-ARCH-14，2026-11-22，编排随迁 3 处）**：service/price_service.py get_market_capitalization（双 Tier 降级，factory 返回 dict/DataFrame 对象 + None 不缓存 + 出口运行时判型序列化，原 B 组「混合串缓存」形态对象化保真）+ service/price_service.py get_stock_list（df_to_json 截断改出口重放）+ service/news_service.py get_financial_calendar（date_cols 关键词猜测过滤编排随迁，空 df 缓存/None 早退两态保真）。同步退役表一 get_market_capitalization 手写豁免行（9→8，出口归 mcp_serve 单点）。


## 变更记录

| 日期 | 变更 |
|---|---|
| 2026-11-22 | 初版（票 03，qc-20261122）：三张表登记 + 裁决②收紧范围落表三；composite/dividend/market_cap 三行标注「随裁决③收拢同步更新」 |
| 2026-11-22 | 表一头注 AST 实测勘误（票 06，check_exit_shapes.py 挂门实测）：原式「9 手写 + tdx 自有骨架 5 + eltdx_data」重复计 tdx_tq 组 2（既在本表 9 行内又计入 5）；实测账 149 mcp_serve + 9 手写 + 3 tdx_mcp + 31 eltdx_data = 192，与 9 行表逐一对上、无 ±1 出入 |
| 2026-11-22 | 表三注记（票 09/10，QI-ARCH-10）：全仓实测 68 处 × 20 文件盘点落档——A 组 df_to_json 豁免 28 保留；B 组非 df_to_json 串缓存 22 保留待裁决（双重编码组 16 = QI-BUG-03 + 类型依赖/多级 6）；C 组 async 编排体 5 保留待裁决；D 组迁移 13（试点 market_service 7 + 全量批 6） |
| 2026-11-22 | 票 13（QI-ARCH-14，裁决③缓存语义统一）：表一退役 get_market_capitalization 手写豁免行（编排上收 price_service 后归 mcp_serve 单点，9→8 行，实测账 150+8+3+31=192 不变）；composite 行注记更新（A⑤ route 收敛不改 async 形态，豁免理由仍成立）；表三注记 A 组 28→26、B 组 market_capitalization 行迁出（get_or_set 对象缓存保真）、D 组续记编排随迁 3 处 |
| 2026-11-22 | 票 07（QI-ARCH-17，裁决①不豁免走分支 B 上提）：eltdx_data 31 工具工具体上提模块级 + mcp_serve 出口收拢（dump=False 直返自有 _ok/_no_data/_err 三态信封，逐字节保真），表一头注实测账 150+8+3+31=192 → **181+8+3=192，eltdx_data 批外清零**；豁免零新增（31 工具全部迁入 mcp_serve，无 async/异构豁免项）；契约快照 tests/test_eltdx_mcp_serve_compat.py 92 用例锁定；check_exit_shapes.py 白名单同步摘除 eltdx_data.py 批外项 |
| 2026-11-22 | 票 17（QI-STD-26，rule 11 拍板②空态语义统一批）：**表二新增注记**「已注册源合法空结果保留点」37 处（14 组逐组理由）——rule 5 空态批对全注册源盘点 74 折叠点，37 改抛出（commits 973038d/462b5b7/f85e009）+ 37 保留点书面化于此；上表 3 fetcher 级豁免原样不动（未注册，不在改造范围）；降级链验证 tests/test_empty_state_unify.py 9 用例，全量门 1453P/0F（gate-batchB6.txt） |
