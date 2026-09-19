# tradex-hub SDK（客户端库）

> 自动生成（基于精简生成器，工单 21-22 降级方案）。

## TypeScript 客户端

```bash
# 安装（依赖 node-fetch 或浏览器 fetch）
cp -r sdk/typescript ./your-project/tradex-sdk
```

```typescript
import { TradexClient } from './tradex-sdk';

const client = new TradexClient('http://127.0.0.1:8000');
// 函数名从 operationId 提取第一段（如 quote_api_v1_price_quote_get → quote）
const result = await client.quote(query={ symbol: '600519' });
console.log(result.data.quote);
```

## Python 客户端

```bash
pip install requests
cp -r sdk/python/tradex_client ./your-project/
```

```python
from tradex_client import TradexClient

client = TradexClient('http://127.0.0.1:8000')
result = client.quote(query={'symbol': '600519'})
print(result['data']['quote'])
```

## 端点列表（46 个）

| Method | Path | Summary |
|--------|------|---------|
| GET | `/api/v1/ping` | Ping |
| GET | `/api/v1/market/overview` | Overview |
| GET | `/api/v1/market/global` | Global Quote |
| GET | `/api/v1/market/limit-up-down` | Limit Up Down |
| GET | `/api/v1/market/dragon-tiger` | Dragon Tiger |
| GET | `/api/v1/fund/flow` | Flow |
| GET | `/api/v1/fund/northbound` | Northbound |
| GET | `/api/v1/price/quote` | Quote |
| GET | `/api/v1/price/kline` | Kline |
| GET | `/api/v1/price/intraday` | Intraday |
| GET | `/api/v1/company/search` | Search |
| GET | `/api/v1/company/info` | Info |
| GET | `/api/v1/company/profile` | Profile |
| GET | `/api/v1/company/competitors` | Competitors |
| GET | `/api/v1/financial/income` | Income |
| GET | `/api/v1/financial/balance` | Balance |
| GET | `/api/v1/financial/cashflow` | Cashflow |
| GET | `/api/v1/financial/line-item` | Line Item |
| GET | `/api/v1/financial/indicators` | Indicators |
| GET | `/api/v1/financial/growth` | Growth |
| GET | `/api/v1/financial/per-share` | Per Share |
| GET | `/api/v1/financial/segments` | Segments |
| GET | `/api/v1/news/stock` | Stock |
| GET | `/api/v1/news/announcements` | Announcements |
| GET | `/api/v1/news/search` | Search |
| GET | `/api/v1/industry/list` | List Industries |
| GET | `/api/v1/industry/stocks` | Stocks |
| GET | `/api/v1/industry/concepts` | Concepts |
| GET | `/api/v1/industry/fund-flow` | Fund Flow |
| GET | `/api/v1/industry/pe` | Pe |
| GET | `/api/v1/indicator/macd` | Macd |
| GET | `/api/v1/indicator/kdj` | Kdj |
| GET | `/api/v1/indicator/rsi` | Rsi |
| GET | `/api/v1/indicator/boll` | Boll |
| GET | `/api/v1/diagnostic/stock` | Stock |
| GET | `/api/v1/diagnostic/market` | Market |
| GET | `/api/v1/diagnostic/technical` | Technical |
| POST | `/api/v1/write/strategy` | Create Strategy |
| GET | `/api/v1/write/strategy/list` | List Strategies |
| GET | `/api/v1/write/strategy/{sid}` | Get Strategy |
| DELETE | `/api/v1/write/strategy/{sid}` | Delete Strategy |
| POST | `/api/v1/write/watchlist` | Add To Watchlist |
| GET | `/api/v1/write/watchlist/list` | List Watchlist |
| DELETE | `/api/v1/write/watchlist/{symbol}` | Remove From Watchlist |
| GET | `/api/v1/metrics/json` | Metrics Json |
| GET | `/api/v1/metrics/slow-queries` | Slow Queries |
