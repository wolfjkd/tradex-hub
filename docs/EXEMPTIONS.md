# EXEMPTIONS.md — 设计内豁免唯一清单（单一真源）

> **定位**：本仓全部「设计内例外」的唯一登记处。豁免 = 稀少且有书面理由的例外，不是第二张功能清单——加豁免先过老板裁决，改豁免先改这里并同步 AGENTS.md 指针。
> **机械核验**：出口形态（表一）由 `scripts/check_exit_shapes.py`（票 06）AST 枚举比对，漂移即全量门红。
> **来源**：qc-20261117 台账 QI-STD-01/93、qc-20261122 台账 QI-ARCH-17/19、交接文档 17/18、老板裁决（2026-11-18 拍板①② / 2026-11-22 裁决①②③）。

## 表一：mcp_serve 出口手写豁免（9 工具）

> 背景：A①A② 全量推广后 MCP 出口收拢进 `tools/_mcp_serve.py` 单点；以下工具因形态不适配保留手写出口（149 走 mcp_serve + 9 手写 + tdx 自有骨架 5 + eltdx_data 待上提 = 192，以 06 门 AST 实测为准）。

| 工具 | 文件 | 豁免理由 |
|---|---|---|
| composite_analysis 组 3 工具 | composite_analysis.py | async gather + 多分支容错降级语义，mcp_serve 同步 build 不适配（代码注释自证；裁决③后若 A⑤ 收拢改变形态，本行同步更新） |
| get_dividend_data | valuation.py | 多级缓存降级编排，build 单函数不适配（票 13 裁决③后若搬 service，本行同步更新） |
| get_market_capitalization | price_data.py | 多级缓存降级编排，build 单函数不适配（票 13 裁决③后若搬 service，本行同步更新） |
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

## 表三：rule 7 裸 get/set 缓存豁免（范围：df_to_json 序列化场景）

> 背景：裁决②（2026-11-22 老板拍板）——rule 7 收紧，裸 get/set 豁免范围**仅限 tools 层 `df_to_json` 序列化字符串缓存**；其余一切手写 get/set 一律迁移 `cache.get_or_set`（迁移施工 = 工单 09 试点 → 10 全量）。

| 场景 | 豁免理由 |
|---|---|
| tools 层 df_to_json 字符串缓存（裸 get/set） | df_to_json 自带格式化序列化，factory 闭包形态与其不匹配；属序列化边界而非缓存策略问题 |

**范围外即违规**：dict/list/对象等非 df_to_json 缓存走裸 get/set = 违反 rule 7，09/10 迁移清单之外新出现的按门纪律处理。

## 变更记录

| 日期 | 变更 |
|---|---|
| 2026-11-22 | 初版（票 03，qc-20261122）：三张表登记 + 裁决②收紧范围落表三；composite/dividend/market_cap 三行标注「随裁决③收拢同步更新」 |
