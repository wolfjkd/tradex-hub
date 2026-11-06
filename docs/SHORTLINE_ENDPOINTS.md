# 短线端点 CATALOG

> 本文件由 `scripts/gen_shortline_catalog.py` 依据 `tradex.shortline.meta` 声明生成，请勿手改。

- schema_version: **1.0**
- 端点数量: **12**
- 声明校验: 全绿

| 端点 id | 标题 | 阶段 | 缓存策略 | 来源 | 合规 | MCP 工具 | REST 路径 | 状态 |
|---|---|---|---|---|---|---|---|---|
| shortline.bigcaps | 大市值名单 | anytime | hourly（3600s） | sina_bigcaps（备源：akshare_em） | cn-public | get_shortline_bigcaps | /api/v1/shortline/bigcaps | implemented |
| shortline.board_ladder | 连板天梯 | close | closed_long（604800s） | akshare_em(zt/zb/dt/prev_zt) | cn-public | get_shortline_board_ladder | /api/v1/shortline/board-ladder | implemented |
| shortline.close_fetch | 收盘定稿落库 | postclose | none（不缓存） | akshare_em(zt/zb/dt/prev_zt) | cn-public | shortline_close_fetch | /api/v1/shortline/close-fetch | implemented |
| shortline.cycle | 情绪周期 | close | closed_long（604800s） | shortline_store + akshare_em(zt/zb/dt/prev_zt) | cn-public | get_shortline_cycle | /api/v1/shortline/cycle | implemented |
| shortline.daily | 每日读数 | close | closed_long（604800s） | akshare_em(zt/zb/dt/prev_zt) | cn-public | get_shortline_daily | /api/v1/shortline/daily | implemented |
| shortline.emotion | 情绪四项 | close | closed_long（604800s） | akshare_em(zt/zb/dt/prev_zt) | cn-public | get_shortline_emotion | /api/v1/shortline/emotion | implemented |
| shortline.history | 收盘历史回读 | anytime | closed_long（604800s） | shortline_store | cn-public | get_shortline_history | /api/v1/shortline/history | implemented |
| shortline.ladder | 昨日梯队 | close | closed_long（604800s） | akshare_em(zt/zb/dt/prev_zt) | cn-public | get_shortline_ladder | /api/v1/shortline/ladder | implemented |
| shortline.live | 盘中情绪 | intraday | live_15s（15s） | akshare_em(zt/zb/dt/prev_zt) | cn-public | get_shortline_live | /api/v1/shortline/live | implemented |
| shortline.settled | 昨日涨停股当日表现 | close | closed_long（604800s） | akshare_em(zt/zb/dt/prev_zt) | cn-public | get_shortline_settled | /api/v1/shortline/settled | implemented |
| shortline.structure | 涨停结构 | close | closed_long（604800s） | akshare_em(zt/zb/dt/prev_zt) | cn-public | get_shortline_structure | /api/v1/shortline/structure | implemented |
| shortline.turnover_top | 全市场成交额榜 | postclose | package_long（2592000s） | tdx_official（备：category_quotes 实时榜） | cn-public | get_shortline_turnover_top | /api/v1/shortline/turnover-top | implemented |

## 口径说明

### `shortline.bigcaps` — 大市值名单

总市值 ≥ 门槛（默认 500 亿）的 A 股名单。主源新浪 bigcaps，失败切东财全市场快照；1 小时缓存；返回 as_of / source / compliance，停牌或缺市值的票不丢整只、写原因。

- 参数：min_mktcap_yi, limit ｜ 产出字段：as_of, source, threshold_yi, count, stocks, unpriced, source_note ｜ 计算函数：`tradex.service.bigcaps_service:get_bigcaps`

### `shortline.board_ladder` — 连板天梯

今日连板天梯 + 低一层没接上的票去向（晋级/炸板/走弱）。

- 参数：date ｜ 产出字段：levels, missed ｜ 计算函数：`tradex.shortline.compute:board_ladder`

### `shortline.close_fetch` — 收盘定稿落库

幂等收盘取数：把当日定稿读数落本机（对抗东财四池约一个月保留期）。同一日重复调用不重复写；partial 不覆盖 final。

- 参数：date, force ｜ 产出字段：date, status, written, missing_reasons, schema_version ｜ 计算函数：`tradex.shortline.store:close_fetch`

### `shortline.cycle` — 情绪周期

近 N 日涨停数 / 最高板 / 炸板率合成窗口分位。窗口数据来自收盘定稿落库；缺天不给 0，写 missing_reason。

- 参数：days ｜ 产出字段：window, percentile, metrics ｜ 计算函数：`tradex.shortline.compute:cycle`

### `shortline.daily` — 每日读数

涨停数 / 最高板 / 炸板率 / 昨日涨停今日中位 / 1进2。昨日涨停今日中位=昨日涨停股今日涨跌幅中位数；1进2=昨日首板今日涨停。

- 参数：date ｜ 产出字段：limit_up_count, max_board, break_rate, prev_median, first_to_second ｜ 计算函数：`tradex.shortline.compute:daily`

### `shortline.emotion` — 情绪四项

赚钱效应 / 晋级率 / 连板溢价 / 梯队断层。赚钱效应=昨日涨停股今日上涨占比；晋级率=昨日涨停今日仍涨停占比；连板溢价=昨日连板股今日均涨幅−昨日首板今日均涨幅；梯隊断层=今日梯队缺失层级。

- 参数：date ｜ 产出字段：money_effect, promotion_rate, premium, ladder_gap ｜ 计算函数：`tradex.shortline.compute:emotion`

### `shortline.history` — 收盘历史回读

读取已落库的定稿读数（按日期或区间），覆盖已积累的全部交易日。

- 参数：date, days ｜ 产出字段：count, dates, records, missing_dates ｜ 计算函数：`tradex.shortline.store:history`

### `shortline.ladder` — 昨日梯队

昨日全部涨停股按连板数排（连板高度 + 各层名单）。

- 参数：date ｜ 产出字段：levels, stocks ｜ 计算函数：`tradex.shortline.compute:ladder`

### `shortline.live` — 盘中情绪

此刻涨停 / 炸板 / 跌停家数、封板率、1进2。盘中读数标 partial，最多缓存 15 秒。

- 参数：无 ｜ 产出字段：limit_up, broken, limit_down, seal_rate, first_to_second ｜ 计算函数：`tradex.shortline.compute:live`

### `shortline.settled` — 昨日涨停股当日表现

昨日涨停股今日表现明细（涨停样本原料）：代码/名称/连板数/今日涨跌幅/成交额。

- 参数：date ｜ 产出字段：count, stocks ｜ 计算函数：`tradex.shortline.compute:settled`

### `shortline.structure` — 涨停结构

涨停结构（板块/制度占比）+ 四池上游字段清单（防假断点）。

- 参数：date ｜ 产出字段：structure, upstream_fields, missing_reason ｜ 计算函数：`tradex.shortline.compute:structure`

### `shortline.turnover_top` — 全市场成交额榜

收盘后下载通达信官网盘后包（g4day，约 2.7MB，17:00 后发布），解析全市场日线含成交额，产出成交额前 N；包未发布/下载失败时降级为实时榜并标「此刻榜」。当日榜与历史榜由 kind / as_of 区分。

- 参数：date, limit, kind ｜ 产出字段：kind, date, as_of, source, count, stocks, degradation ｜ 计算函数：`tradex.service.turnover_service:get_turnover_top`

## 缓存策略总表

| 策略 | TTL | 落文件缓存 | partial 可缓存 | 说明 |
|---|---|---|---|---|
| closed_long | 604800s | 是 | 否 | 已收盘结果长期缓存（7 天，落文件缓存） |
| hourly | 3600s | 是 | 否 | 最多缓存 1 小时 |
| live_15s | 15s | 否 | 是 | 盘中读数最多缓存 15 秒、不落文件；partial 允许缓存（15 秒后自然失效） |
| none | — | 否 | 否 | 不缓存（写操作 / 必须实时） |
| package_long | 2592000s | 是 | 否 | 按交易日的盘后包长期缓存（30 天） |
