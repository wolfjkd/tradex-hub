# 新闻资讯数据源扩充 v3.3.0 - 任务拆分（合并 v3.3.0 + v3.4.0）

> 共 7 个阶段 / 22 个任务。阶段间存在依赖，需顺序执行；阶段内任务可并行。

## 阶段 0：准备

- [ ] T0.1 创建 git 分支 `feature/expand-news-sources-v3.3.0` ✅
- [ ] T0.2 确认 v3.2.0 已发布或已备份 ✅

## 阶段 1：新增 akshare 包装 fetch 函数（8 个）

> 在 `akshare_fetchers.py` 末尾新增。可并行。

- [ ] T1.1 实现 `fetch_baidu_economic_calendar(date, ...)` — 百度经济数据日历
  - 调用 `ak.news_economic_baidu(date=date)`
  - 返回 DataFrame（日期/时间/事件/重要性/前值/预期/公布值）
  - 内置异常处理，失败时返回空 DataFrame

- [ ] T1.2 实现 `fetch_baidu_trade_notify(endpoint, date, ...)` — 百度交易提醒（多 endpoint）
  - endpoint: `suspend` → `ak.news_trade_notify_suspend_baidu(date=date)`
  - endpoint: `dividend` → `ak.news_trade_notify_dividend_baidu(date=date)`
  - endpoint: `report_time` → `ak.news_report_time_baidu(date=date)`
  - 返回统一格式的 DataFrame

- [ ] T1.3 实现 `fetch_index_news_sentiment(**kwargs)` — 指数新闻情绪
  - 调用 `ak.index_news_sentiment_scope()`
  - 返回 DataFrame（指数代码/情感得分/新闻数量等）

- [ ] T1.4 实现 `fetch_futures_news(symbol, ...)` — 期货新闻
  - 调用 `ak.futures_news_shmet(symbol=symbol)`
  - 返回 DataFrame（标题/发布时间/内容）

- [ ] T1.5 实现 `fetch_hot_search_baidu(symbol, date, time, ...)` — 百度热搜股票
  - 调用 `ak.stock_hot_search_baidu(symbol=symbol, date=date, time=time)`
  - symbol: {"全部", "A股", "港股", "美股"}
  - 返回 DataFrame（股票代码/名称/排名/热度值）

- [ ] T1.6 实现 `fetch_hot_rank_data(endpoint, symbol, ...)` — 东财人气榜（多 endpoint，7 合 1）
  - endpoint "rank": `ak.stock_hot_rank_em()`
  - endpoint "up": `ak.stock_hot_up_em()`
  - endpoint "detail": `ak.stock_hot_rank_detail_em(symbol=symbol)`
  - endpoint "realtime": `ak.stock_hot_rank_detail_realtime_em(symbol=symbol)`
  - endpoint "keyword": `ak.stock_hot_keyword_em(symbol=symbol)`
  - endpoint "latest": `ak.stock_hot_rank_latest_em(symbol=symbol)`
  - endpoint "relate": `ak.stock_hot_rank_relate_em(symbol=symbol)`

- [ ] T1.7 实现 `fetch_xueqiu_hot(endpoint, symbol, ...)` — 雪球热度（多 endpoint，3 合 1）
  - endpoint "follow": `ak.stock_hot_follow_xq(symbol=symbol)`
  - endpoint "tweet": `ak.stock_hot_tweet_xq(symbol=symbol)`
  - endpoint "deal": `ak.stock_hot_deal_xq(symbol=symbol)`

- [ ] T1.8 实现 `fetch_fund_hold_data(endpoint, symbol, date, ...)` — 基金持仓（多 endpoint，2 合 1）
  - endpoint "hold": `ak.stock_report_fund_hold(symbol=symbol, date=date)`
  - endpoint "detail": `ak.stock_report_fund_hold_detail(symbol=symbol, date=date)`

## 阶段 2：新增直连 fetch 函数（1 个）

- [ ] T2.1 实现 `fetch_sina_finance_news(num_results, ...)` — 新浪财经新闻直连
  - 调用新浪财经滚动新闻 API：`https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2509&num={num}`
  - 解析 JSON 响应，提取标题/时间/来源/链接
  - 返回 DataFrame（标题/发布时间/来源/链接）
  - 内置异常处理，失败时返回空 DataFrame

## 阶段 3：注册数据源到 SmartRouter

- [ ] T3.1 更新 `data_sources/__init__.py`，导出新函数（如需要）
- [ ] T3.2 更新 `registry.py`，注册 10 个新数据类型：
  - 新增 `baidu_economic_calendar` → `akshare_baidu_economic` (p=1)
  - 新增 `baidu_trade_notify` → `akshare_baidu_notify` (p=1)
  - 新增 `index_news_sentiment` → `akshare_index_sentiment` (p=1)
  - 新增 `futures_news` → `akshare_futures_news` (p=1)
  - 新增 `sina_finance_news` → `sina_direct` (p=1)
  - 新增 `hot_search` → `akshare_hot_search` (p=1)
  - 新增 `hot_rank` → `akshare_hot_rank` (p=1)
  - 新增 `xueqiu_hot` → `akshare_xueqiu_hot` (p=1)
  - 新增 `fund_hold` → `akshare_fund_hold` (p=1)
  - 注册表总数从 27 个数据类型增加到 37 个

## 阶段 4：更新 MCP 工具

- [ ] T4.1 增强 `get_financial_calendar` — 新增百度经济数据日历补充源
  - 先获取 `stock_report_disclosure`（财报披露）
  - 再获取 `baidu_economic_calendar`（经济数据）
  - 合并两个 DataFrame 返回

- [ ] T4.2 增强 `search_news` — 新增百度交易提醒 + 期货新闻 + 新浪财经 + 百度热搜
  - 搜索源顺序：财联社快讯 → 巨潮公告 → 百度交易提醒 → 期货新闻 → 新浪财经 → 百度热搜 → 财新网 → CCTV
  - 统一合并后分词搜索过滤

- [ ] T4.3 新增 `get_market_sentiment` 工具（第91个）
  - 路由走 `index_news_sentiment` 类型
  - 参数：无
  - 缓存策略：TTL_REALTIME（300s）
  - 返回指数新闻情绪数据 JSON

- [ ] T4.4 新增 `get_futures_news` 工具（第92个）
  - 路由走 `futures_news` 类型
  - 参数：symbol（默认 "全部"）
  - 缓存策略：TTL_REALTIME（300s）
  - 返回期货新闻列表 JSON

- [ ] T4.5 新增 `get_hot_rank` 工具（第93个）
  - 路由走 `hot_rank` 类型
  - 参数：endpoint（默认 "rank"），symbol
  - 返回东财人气榜数据 JSON

- [ ] T4.6 新增 `get_hot_keywords` 工具（第94个）
  - 路由走 `hot_rank` 类型，固定 endpoint="keyword"
  - 参数：symbol（必填，格式 "SZ000665"）
  - 返回个股热门关键词 JSON

- [ ] T4.7 新增 `get_xueqiu_hot` 工具（第95个）
  - 路由走 `xueqiu_hot` 类型
  - 参数：endpoint（默认 "follow"），symbol（默认 "最热门"）
  - 返回雪球热度数据 JSON

- [ ] T4.8 新增 `get_fund_hold` 工具（第96个）
  - 路由走 `fund_hold` 类型
  - 参数：endpoint（默认 "hold"），symbol（默认 "基金持仓"），date
  - 缓存策略：TTL_DAILY（86400s）
  - 返回机构持仓数据 JSON

- [ ] T4.9 新增 `get_hot_search` 工具（第97个）
  - 路由走 `hot_search` 类型
  - 参数：symbol（默认 "A股"），date，time（默认 "今日"）
  - 返回百度热搜排行 JSON

## 阶段 5：文档与版本同步

- [ ] T5.1 更新 VERSION：3.2.0 → 3.3.0
- [ ] T5.2 更新 CHANGELOG.md：v3.3.0 条目（Added + Changed + 升级指引）
- [ ] T5.3 更新 README.md：工具数 90→97，新增数据源矩阵说明，数据类型 27→37

## 阶段 6：测试回归

- [ ] T6.1 单元测试：9 个新 fetch_fn 的异常处理逻辑
- [ ] T6.2 集成测试：SmartRouter 新数据源注册验证（10 个新增数据类型）
- [ ] T6.3 实战验证：
  - `get_financial_calendar("20260803")` 返回财报 + 经济数据
  - `get_market_sentiment()` 返回情绪数据
  - `get_futures_news("全部")` 返回期货新闻
  - `get_hot_rank()` 返回人气榜
  - `get_hot_keywords("SZ000665")` 返回热门关键词
  - `get_xueqiu_hot()` 返回雪球热度
  - `get_fund_hold("基金持仓", "20260331")` 返回基金持仓
  - `get_hot_search("A股")` 返回热搜排行
  - `search_news("停牌")` 包含百度停复牌结果
- [ ] T6.4 MCP 协议层验证：`python -m tradex` 启动 + 97 个工具注册
- [ ] T6.5 现有 350+ 测试用例全部通过，无回归

## 任务依赖关系

| 任务 | 依赖 | 说明 |
|------|------|------|
| T3.1, T3.2 | T1.1-T1.8, T2.1 | 注册需要 fetch_fn 已存在 |
| T4.1-T4.9 | T3.2 | 工具需要数据源已注册 |
| T5.1, T5.2, T5.3 | T4.1-T4.9 | 文档需要在代码完成后更新 |
| T6.1-T6.5 | T5.1, T5.2, T5.3 | 测试需要在代码和文档完成后 |

## 可并行工作

| 并行组 | 任务 | 说明 |
|--------|------|------|
| 组 A | T1.1 ~ T1.8 | 8 个 fetch 函数可并行实现 |
| 组 B | T2.1 | 独立于组 A，可并行 |
| 组 C | T4.3 ~ T4.9 | 7 个新工具可并行实现 |