# 新闻资讯数据源扩充 v3.3.0 Spec（合并 v3.3.0 + v3.4.0）

## Why

v3.2.0 已集成东财个股新闻直连、财联社快讯、巨潮公告三大直连数据源。但仍有大量潜在数据源未被利用：
- akshare 中 4 个百度类新闻/提醒接口
- akshare 中 6 个东财人气榜/热度类接口
- akshare 中 3 个雪球社交媒体热度接口
- akshare 中 2 个基金持仓接口
- akshare 中 1 个百度热搜接口
- 新浪财经 HTTP 直连接口
- 同花顺问财自然语言查询接口（pywencai 可选依赖）
- 同花顺问财 OpenAPI 新闻/公告/研报搜索（iwencai OpenAPI）

扩充这些数据源可以使 `search_news`、`get_financial_calendar` 等工具覆盖更广的资讯范围，并新增市场情绪、人气排行、雪球热度、基金持仓、同花顺问财等全新能力。

## What Changes

### 新增数据源概览

#### 新闻/资讯类（7 个）

| 数据源 | 函数 | 数据类型 | 用途 |
|--------|------|---------|------|
| 百度经济数据日历 | `news_economic_baidu` | `baidu_economic_calendar` | 每日经济数据发布提醒 |
| 百度停复牌提醒 | `news_trade_notify_suspend_baidu` | `baidu_trade_notify` | 股票停复牌信息 |
| 百度分红派息提醒 | `news_trade_notify_dividend_baidu` | `baidu_trade_notify` | 分红派息日程 |
| 百度财报发行时间 | `news_report_time_baidu` | `baidu_trade_notify` | 财报披露时间 |
| 期货新闻（上海有色网） | `futures_news_shmet` | `futures_news` | 大宗商品/期货新闻 |
| 新浪财经新闻 | `fetch_sina_finance_news` | `sina_finance_news` | 全市场财经新闻 |
| 百度热搜股票 | `stock_hot_search_baidu` | `hot_search` | 百度股市通热搜排行 |

#### 情绪/热度类（10 个，合并为 2 个多 endpoint 包装器）

**东财人气榜系列（7 个接口 → 1 个 fetch_hot_rank_data 多 endpoint）**

| endpoint | 原始接口 | 说明 |
|----------|---------|------|
| rank | `stock_hot_rank_em()` | 全市场人气榜 |
| detail | `stock_hot_rank_detail_em(symbol)` | 个股历史趋势及粉丝特征 |
| realtime | `stock_hot_rank_detail_realtime_em(symbol)` | 个股实时变动 |
| keyword | `stock_hot_keyword_em(symbol)` | 个股热门关键词 |
| latest | `stock_hot_rank_latest_em(symbol)` | 个股最新排名 |
| relate | `stock_hot_rank_relate_em(symbol)` | 相关股票 |
| up | `stock_hot_up_em()` | 飙升榜 |

**雪球热度系列（3 个接口 → 1 个 fetch_xueqiu_hot 多 endpoint）**

| endpoint | 原始接口 | 说明 |
|----------|---------|------|
| follow | `stock_hot_follow_xq(symbol)` | 关注排行榜 |
| tweet | `stock_hot_tweet_xq(symbol)` | 讨论排行榜 |
| deal | `stock_hot_deal_xq(symbol)` | 交易排行榜 |

#### 机构持仓类（2 个，合并为 1 个多 endpoint 包装器）

| endpoint | 原始接口 | 说明 |
|----------|---------|------|
| hold | `stock_report_fund_hold(symbol, date)` | 基金/QFII/社保等持仓汇总 |
| detail | `stock_report_fund_hold_detail(symbol, date)` | 单只基金持仓明细 |

#### 指数情绪类（1 个）

| 数据源 | 函数 | 数据类型 | 用途 |
|--------|------|---------|------|
| 指数新闻情绪 | `index_news_sentiment_scope` | `index_news_sentiment` | 市场情绪指标 |

### 新增 fetch 函数清单

**akshare_fetchers.py 新增 7 个函数：**

```python
def fetch_baidu_economic_calendar(date="", **kwargs) -> pd.DataFrame
def fetch_baidu_trade_notify(endpoint="suspend", date="", **kwargs) -> pd.DataFrame
def fetch_index_news_sentiment(**kwargs) -> pd.DataFrame
def fetch_futures_news(symbol="全部", **kwargs) -> pd.DataFrame
def fetch_hot_search_baidu(symbol="A股", date="", time="今日", **kwargs) -> pd.DataFrame
def fetch_hot_rank_data(endpoint="rank", symbol="", **kwargs) -> pd.DataFrame
def fetch_xueqiu_hot(endpoint="follow", symbol="最热门", **kwargs) -> pd.DataFrame
def fetch_fund_hold_data(endpoint="hold", symbol="基金持仓", date="", **kwargs) -> pd.DataFrame
```

**news_fetchers.py 新增 1 个函数：**

```python
def fetch_sina_finance_news(num_results=20, **kwargs) -> pd.DataFrame
```

### 分类注册到 SmartRouter

新增 10 个数据类型，注册表从 27 个数据类型增加到 37 个：

| 数据类型 | 源名 | priority | 说明 |
|----------|------|----------|------|
| `baidu_economic_calendar` | `akshare_baidu_economic` | 1 | 百度经济日历 |
| `baidu_trade_notify` | `akshare_baidu_notify` | 1 | 百度交易提醒 |
| `index_news_sentiment` | `akshare_index_sentiment` | 1 | 指数情绪 |
| `futures_news` | `akshare_futures_news` | 1 | 期货新闻 |
| `sina_finance_news` | `sina_direct` | 1 | 新浪财经直连 |
| `hot_search` | `akshare_hot_search` | 1 | 百度热搜 |
| `hot_rank` | `akshare_hot_rank` | 1 | 东财人气榜 |
| `xueqiu_hot` | `akshare_xueqiu_hot` | 1 | 雪球热度 |
| `fund_hold` | `akshare_fund_hold` | 1 | 基金持仓 |

### MCP 工具变更

**增强工具（2 个）：**

| 工具 | 增强内容 |
|------|----------|
| `get_financial_calendar` | 新增百度经济数据日历作为补充源（财报披露 + 经济日历合并） |
| `search_news` | 新增百度交易提醒 + 期货新闻 + 新浪财经 + 百度热搜作为搜索源 |

**新增工具（7 个）：**

| # | 工具名 | 数据类型 | 说明 |
|---|--------|---------|------|
| 91 | `get_market_sentiment` | `index_news_sentiment` | 指数新闻情绪 |
| 92 | `get_futures_news` | `futures_news` | 期货/大宗商品新闻 |
| 93 | `get_hot_rank` | `hot_rank` | 东财人气榜/飙升榜 |
| 94 | `get_hot_keywords` | `hot_rank` (endpoint=keyword) | 个股热门关键词 |
| 95 | `get_xueqiu_hot` | `xueqiu_hot` | 雪球关注/讨论/交易热度 |
| 96 | `get_fund_hold` | `fund_hold` | 机构持仓数据 |
| 97 | `get_hot_search` | `hot_search` | 百度热搜股票排行 |

工具数：90 → 97（+7 个新工具）

### 确保可调用设计

每个新增数据源必须满足以下条件才算"可调用"：
1. ✅ 有 fetch 函数（异常处理，失败返回空 DataFrame）
2. ✅ 注册到 SmartRouter
3. ✅ 有对应的 MCP 工具暴露给用户
4. ✅ 缓存策略合理
5. ✅ 实战验证返回非空数据

### 缓存策略

| 数据类型 | TTL | 说明 |
|----------|-----|------|
| 日历类（baidu_economic/trade_notify） | TTL_DAILY (86400s) | 日频数据 |
| 新闻类（futures/sina/hot_search） | TTL_REALTIME (120s) | 实时数据 |
| 情绪类（index_news_sentiment） | TTL_REALTIME (300s) | 短周期 |
| 热度类（hot_rank/xueqiu_hot） | TTL_REALTIME (120s) | 实时数据 |
| 持仓类（fund_hold） | TTL_DAILY (86400s) | 季度数据 |

## Impact

- 受影响的代码：
  - `tradex/src/tradex/data_sources/akshare_fetchers.py` — 新增 8 个 fetch 函数（含多 endpoint 包装器）
  - `tradex/src/tradex/data_sources/news_fetchers.py` — 新增 1 个直连 fetch 函数
  - `tradex/src/tradex/data_sources/__init__.py` — 导出新函数（如需要）
  - `tradex/src/tradex/data_sources/registry.py` — 注册 10 个新数据类型
  - `tradex/src/tradex/tools/news_events.py` — 增强 2 个工具 + 新增 7 个工具
- 工具数：90 → 97（+7 个新工具）
- 数据类型：27 → 37（+10 个新数据类型）

## ADDED Requirements

### Requirement: 百度数据源集成

The system SHALL integrate 4 百度股市通新闻/提醒数据源 via akshare。

#### Scenario: 经济数据日历
- **WHEN** 调用 `get_financial_calendar` 且指定日期
- **THEN** 返回该日期的经济数据发布日程（含前值/预期/公布值）

#### Scenario: 停复牌提醒
- **WHEN** 调用 `search_news` 搜索停牌/复牌相关关键词
- **THEN** 返回匹配的停复牌公告信息

#### Scenario: 分红派息提醒
- **WHEN** 调用 `search_news` 搜索分红/派息相关关键词
- **THEN** 返回匹配的分红派息日程

#### Scenario: 财报发行时间
- **WHEN** 调用 `get_financial_calendar` 或 `search_news` 搜索财报
- **THEN** 返回匹配的财报披露时间数据

### Requirement: 指数新闻情绪

The system SHALL provide a new tool `get_market_sentiment` 获取指数新闻情绪数据。

#### Scenario: 获取市场情绪
- **WHEN** 用户调用 `get_market_sentiment()`
- **THEN** 返回当前市场情绪指标数据

### Requirement: 期货新闻

The system SHALL provide a new tool `get_futures_news` 获取期货/大宗商品新闻。

#### Scenario: 获取期货新闻
- **WHEN** 用户调用 `get_futures_news(symbol="全部")`
- **THEN** 返回期货/大宗商品相关新闻

### Requirement: 新浪财经新闻直连

The system SHALL provide a new data source `fetch_sina_finance_news` 通过新浪财经 HTTP API 获取全市场财经新闻。

#### Scenario: 获取新浪财经新闻
- **WHEN** 调用 `fetch_sina_finance_news(num_results=20)`
- **THEN** 返回新浪财经最新新闻列表

### Requirement: 百度热搜排行

The system SHALL provide a new tool `get_hot_search` 获取百度股市通热搜股票排行。

#### Scenario: 获取热搜排行
- **WHEN** 用户调用 `get_hot_search(symbol="A股")`
- **THEN** 返回百度股市通热搜股票列表

### Requirement: 东财人气榜

The system SHALL provide a new tool `get_hot_rank` 获取东方财富个股人气榜数据。

#### Scenario: 获取人气榜
- **WHEN** 用户调用 `get_hot_rank(endpoint="rank")`
- **THEN** 返回东财全市场人气榜

### Requirement: 热门关键词

The system SHALL provide a new tool `get_hot_keywords` 获取个股热门关键词。

#### Scenario: 获取热门关键词
- **WHEN** 用户调用 `get_hot_keywords(symbol="SZ000665")`
- **THEN** 返回该股票的热门关联关键词

### Requirement: 雪球热度

The system SHALL provide a new tool `get_xueqiu_hot` 获取雪球社交媒体热度数据。

#### Scenario: 获取雪球热度
- **WHEN** 用户调用 `get_xueqiu_hot(endpoint="follow")`
- **THEN** 返回雪球沪深股市关注排行榜

### Requirement: 基金持仓

The system SHALL provide a new tool `get_fund_hold` 获取机构持仓数据。

#### Scenario: 获取基金持仓
- **WHEN** 用户调用 `get_fund_hold(symbol="基金持仓", date="20260331")`
- **THEN** 返回基金/社保/QFII等机构持仓汇总

## ADDED Requirements Details

### 新浪财经新闻直连详情

#### fetch_sina_finance_news(num_results=20)
- 接口：`https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2509&num={num}`
- 返回字段：新闻标题、发布时间、来源、链接
- 缓存：TTL_REALTIME（120s）
- 异常处理：失败返回空 DataFrame

### 百度热搜详情

#### stock_hot_search_baidu(symbol="A股", date="", time="今日")
- symbol: {"全部", "A股", "港股", "美股"}
- time: {"今日", "1小时"}
- 返回字段：股票代码、股票名称、热搜排名、热度值
- 缓存：TTL_REALTIME（120s）

### 东财人气榜详情

#### fetch_hot_rank_data(endpoint, symbol)
- endpoint "rank": 全市场人气榜（无参数）
- endpoint "up": 飙升榜（无参数）
- endpoint "detail/detail_realtime/latest/relate/keyword": 需 symbol（格式 "SZ000665"）
- 缓存：TTL_REALTIME（120s）

### 雪球热度详情

#### fetch_xueqiu_hot(endpoint, symbol)
- symbol: {"最热门", "沪深股市", "创业板", "科创板"}
- endpoint "follow": 关注排行榜
- endpoint "tweet": 讨论排行榜
- endpoint "deal": 交易排行榜
- 缓存：TTL_REALTIME（120s）

### 基金持仓详情

#### fetch_fund_hold_data(endpoint, symbol, date)
- symbol: {"基金持仓", "QFII持仓", "社保持仓", "券商持仓", "保险持仓", "信托持仓"}
- date: 财报日期，格式 "YYYYMMDD"（如 "20260331"）
- endpoint "hold": 汇总持仓
- endpoint "detail": 单只基金持仓明细（symbol 为基金代码）
- 缓存：TTL_DAILY（86400s）

## MODIFIED Requirements

### Requirement: get_financial_calendar 增强

原有 `get_financial_calendar` 仅依赖 akshare 的 `stock_report_disclosure`。v3.3.0 新增百度经济数据日历作为补充：

- 主源：`stock_report_disclosure`（akshare）— 财报披露时间
- 补充源：`news_economic_baidu`（akshare）— 经济数据发布日历
- 合并返回：两个源的 DataFrame 合并后去重排序

### Requirement: search_news 增强

v3.3.0 在现有多源搜索基础上新增：

- 新增百度交易提醒数据：`baidu_trade_notify`
- 新增期货新闻：`futures_news`
- 新增新浪财经新闻：`sina_finance_news`
- 新增百度热搜：`hot_search`

搜索源顺序：财联社快讯 → 巨潮公告 → 百度交易提醒 → 期货新闻 → 新浪财经 → 百度热搜 → 财新网 → CCTV

## REMOVED Requirements

无。