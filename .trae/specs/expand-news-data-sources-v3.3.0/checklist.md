# 新闻资讯数据源扩充 v3.3.0 - 检查清单

> 发布前自检，全部 ✓ 方可发版。

## 数据源适用性验证

### akshare 包装函数（8 个）

- [ ] `fetch_baidu_economic_calendar("20260803")` 返回非空 DataFrame
- [ ] `fetch_baidu_trade_notify("20260803", "suspend")` 返回非空 DataFrame
- [ ] `fetch_baidu_trade_notify("20260803", "dividend")` 返回非空 DataFrame
- [ ] `fetch_baidu_trade_notify("20260803", "report_time")` 返回非空 DataFrame
- [ ] `fetch_index_news_sentiment()` 返回非空 DataFrame
- [ ] `fetch_futures_news("全部")` 返回非空 DataFrame
- [ ] `fetch_hot_search_baidu("A股")` 返回非空 DataFrame
- [ ] `fetch_hot_rank_data("rank")` 返回非空 DataFrame
- [ ] `fetch_hot_rank_data("up")` 返回非空 DataFrame
- [ ] `fetch_hot_rank_data("keyword", "SZ000665")` 返回非空 DataFrame
- [ ] `fetch_xueqiu_hot("follow")` 返回非空 DataFrame
- [ ] `fetch_xueqiu_hot("tweet")` 返回非空 DataFrame
- [ ] `fetch_xueqiu_hot("deal")` 返回非空 DataFrame
- [ ] `fetch_fund_hold_data("hold", "基金持仓", "20260331")` 返回非空 DataFrame

### 直连函数（1 个）

- [ ] `fetch_sina_finance_news(20)` 返回 20 行 DataFrame

### 异常处理

- [ ] 9 个新接口的异常处理逻辑正确（失败时返回空 DataFrame，不抛异常）

## SmartRouter 注册完整性

- [ ] `baidu_economic_calendar` → `akshare_baidu_economic` (p=1)
- [ ] `baidu_trade_notify` → `akshare_baidu_notify` (p=1)
- [ ] `index_news_sentiment` → `akshare_index_sentiment` (p=1)
- [ ] `futures_news` → `akshare_futures_news` (p=1)
- [ ] `sina_finance_news` → `sina_direct` (p=1)
- [ ] `hot_search` → `akshare_hot_search` (p=1)
- [ ] `hot_rank` → `akshare_hot_rank` (p=1)
- [ ] `xueqiu_hot` → `akshare_xueqiu_hot` (p=1)
- [ ] `fund_hold` → `akshare_fund_hold` (p=1)
- [ ] 注册表总数从 27 个数据类型增加到 37 个

## MCP 工具功能完整性

### 增强工具

- [ ] `get_financial_calendar("20260803")` 返回财报披露 + 经济数据日历合并结果
- [ ] `search_news("停牌")` 返回结果中包含百度停复牌数据
- [ ] `search_news("分红")` 返回结果中包含百度分红派息数据
- [ ] `search_news` 在数据源失败时自动跳过，不中断搜索

### 新增工具

- [ ] `get_market_sentiment()` 返回指数新闻情绪数据（第91个工具）
- [ ] `get_futures_news("全部")` 返回期货新闻数据（第92个工具）
- [ ] `get_hot_rank()` 返回人气榜数据（第93个工具）
- [ ] `get_hot_keywords("SZ000665")` 返回热门关键词（第94个工具）
- [ ] `get_xueqiu_hot()` 返回雪球热度数据（第95个工具）
- [ ] `get_fund_hold("基金持仓", "20260331")` 返回基金持仓数据（第96个工具）
- [ ] `get_hot_search("A股")` 返回百度热搜排行（第97个工具）

## 缓存策略

- [ ] 日历类数据（baidu_economic/trade_notify）使用 TTL_DAILY（86400s）
- [ ] 新闻类数据（futures/sina/hot_search）使用 TTL_REALTIME（≤120s）
- [ ] 情绪类数据（index_news_sentiment）使用 TTL_REALTIME（300s）
- [ ] 热度类数据（hot_rank/xueqiu_hot）使用 TTL_REALTIME（≤120s）
- [ ] 持仓类数据（fund_hold）使用 TTL_DAILY（86400s）
- [ ] 现有工具的缓存策略不受影响

## 确保可调用

- [ ] 每个新 fetch 函数都有对应的 SmartRouter 注册项
- [ ] 每个新数据类型都有对应的 MCP 工具
- [ ] 每个 MCP 工具都有明确的入参说明和返回格式

## 文档与版本一致性

- [ ] VERSION = 3.3.0
- [ ] CHANGELOG.md 添加 v3.3.0 条目（含新增工具清单和升级指引）
- [ ] README.md 更新工具数 90→97，新增数据源矩阵说明，数据类型 27→37

## 测试回归

- [ ] 9 个新 fetch_fn 单元测试通过
- [ ] SmartRouter 新数据源注册验证通过（10 个新增数据类型）
- [ ] `python -m tradex` 正常启动，97 个工具注册
- [ ] 实战验证：9 个数据源均返回有效数据
- [ ] 现有 350+ 测试用例全部通过，无回归

## 版本发布

- [ ] git commit 完成
- [ ] git tag v3.3.0
- [ ] git push + push tag
- [ ] GitHub Release v3.3.0 发布（含 Release Notes）