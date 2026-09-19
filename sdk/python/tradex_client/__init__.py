"""tradex_client SDK (工单 22 降级方案)。"""

from __future__ import annotations
import requests
from typing import Any

__version__ = "1.0.0"
__all__ = ["TradexClient", "__version__"]


class TradexClient:
    def __init__(self, base_url: str = 'http://127.0.0.1:8000', timeout: float = 30.0):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self._session = requests.Session()

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        url = self.base_url + path
        r = self._session.request(method, url, timeout=self.timeout, **kwargs)
        r.raise_for_status()
        return r

    @staticmethod
    def _unwrap(r: requests.Response) -> dict:
        body = r.json()
        if body.get('code') != 0:
            raise Exception(f"tradex error: code={body.get('code')} msg={body.get('msg')}")
        return body

    def ping(self) -> dict:
        """Ping"""
        r = self._request('get', '/api/v1/ping')
        return self._unwrap(r)

    def overview(self) -> dict:
        """Overview"""
        r = self._request('get', '/api/v1/market/overview')
        return self._unwrap(r)

    def global_quote(self, *, query: dict | None = None) -> dict:
        """Global Quote"""
        params = query or {}
        r = self._request('get', '/api/v1/market/global', params=params)
        return self._unwrap(r)

    def limit_up_down(self, *, query: dict | None = None) -> dict:
        """Limit Up Down"""
        params = query or {}
        r = self._request('get', '/api/v1/market/limit-up-down', params=params)
        return self._unwrap(r)

    def dragon_tiger(self, *, query: dict | None = None) -> dict:
        """Dragon Tiger"""
        params = query or {}
        r = self._request('get', '/api/v1/market/dragon-tiger', params=params)
        return self._unwrap(r)

    def flow(self, *, query: dict | None = None) -> dict:
        """Flow"""
        params = query or {}
        r = self._request('get', '/api/v1/fund/flow', params=params)
        return self._unwrap(r)

    def northbound(self) -> dict:
        """Northbound"""
        r = self._request('get', '/api/v1/fund/northbound')
        return self._unwrap(r)

    def quote(self, *, query: dict | None = None) -> dict:
        """Quote"""
        params = query or {}
        r = self._request('get', '/api/v1/price/quote', params=params)
        return self._unwrap(r)

    def kline(self, *, query: dict | None = None) -> dict:
        """Kline"""
        params = query or {}
        r = self._request('get', '/api/v1/price/kline', params=params)
        return self._unwrap(r)

    def intraday(self, *, query: dict | None = None) -> dict:
        """Intraday"""
        params = query or {}
        r = self._request('get', '/api/v1/price/intraday', params=params)
        return self._unwrap(r)

    def search(self, *, query: dict | None = None) -> dict:
        """Search"""
        params = query or {}
        r = self._request('get', '/api/v1/company/search', params=params)
        return self._unwrap(r)

    def info(self, *, query: dict | None = None) -> dict:
        """Info"""
        params = query or {}
        r = self._request('get', '/api/v1/company/info', params=params)
        return self._unwrap(r)

    def profile(self, *, query: dict | None = None) -> dict:
        """Profile"""
        params = query or {}
        r = self._request('get', '/api/v1/company/profile', params=params)
        return self._unwrap(r)

    def competitors(self, *, query: dict | None = None) -> dict:
        """Competitors"""
        params = query or {}
        r = self._request('get', '/api/v1/company/competitors', params=params)
        return self._unwrap(r)

    def income(self, *, query: dict | None = None) -> dict:
        """Income"""
        params = query or {}
        r = self._request('get', '/api/v1/financial/income', params=params)
        return self._unwrap(r)

    def balance(self, *, query: dict | None = None) -> dict:
        """Balance"""
        params = query or {}
        r = self._request('get', '/api/v1/financial/balance', params=params)
        return self._unwrap(r)

    def cashflow(self, *, query: dict | None = None) -> dict:
        """Cashflow"""
        params = query or {}
        r = self._request('get', '/api/v1/financial/cashflow', params=params)
        return self._unwrap(r)

    def line_item(self, *, query: dict | None = None) -> dict:
        """Line Item"""
        params = query or {}
        r = self._request('get', '/api/v1/financial/line-item', params=params)
        return self._unwrap(r)

    def indicators(self, *, query: dict | None = None) -> dict:
        """Indicators"""
        params = query or {}
        r = self._request('get', '/api/v1/financial/indicators', params=params)
        return self._unwrap(r)

    def growth(self, *, query: dict | None = None) -> dict:
        """Growth"""
        params = query or {}
        r = self._request('get', '/api/v1/financial/growth', params=params)
        return self._unwrap(r)

    def per_share(self, *, query: dict | None = None) -> dict:
        """Per Share"""
        params = query or {}
        r = self._request('get', '/api/v1/financial/per-share', params=params)
        return self._unwrap(r)

    def segments(self, *, query: dict | None = None) -> dict:
        """Segments"""
        params = query or {}
        r = self._request('get', '/api/v1/financial/segments', params=params)
        return self._unwrap(r)

    def stock(self, *, query: dict | None = None) -> dict:
        """Stock"""
        params = query or {}
        r = self._request('get', '/api/v1/news/stock', params=params)
        return self._unwrap(r)

    def announcements(self, *, query: dict | None = None) -> dict:
        """Announcements"""
        params = query or {}
        r = self._request('get', '/api/v1/news/announcements', params=params)
        return self._unwrap(r)

    def search(self, *, query: dict | None = None) -> dict:
        """Search"""
        params = query or {}
        r = self._request('get', '/api/v1/news/search', params=params)
        return self._unwrap(r)

    def list_industries(self) -> dict:
        """List Industries"""
        r = self._request('get', '/api/v1/industry/list')
        return self._unwrap(r)

    def stocks(self, *, query: dict | None = None) -> dict:
        """Stocks"""
        params = query or {}
        r = self._request('get', '/api/v1/industry/stocks', params=params)
        return self._unwrap(r)

    def concepts(self) -> dict:
        """Concepts"""
        r = self._request('get', '/api/v1/industry/concepts')
        return self._unwrap(r)

    def fund_flow(self, *, query: dict | None = None) -> dict:
        """Fund Flow"""
        params = query or {}
        r = self._request('get', '/api/v1/industry/fund-flow', params=params)
        return self._unwrap(r)

    def pe(self, *, query: dict | None = None) -> dict:
        """Pe"""
        params = query or {}
        r = self._request('get', '/api/v1/industry/pe', params=params)
        return self._unwrap(r)

    def macd(self, *, query: dict | None = None) -> dict:
        """Macd"""
        params = query or {}
        r = self._request('get', '/api/v1/indicator/macd', params=params)
        return self._unwrap(r)

    def kdj(self, *, query: dict | None = None) -> dict:
        """Kdj"""
        params = query or {}
        r = self._request('get', '/api/v1/indicator/kdj', params=params)
        return self._unwrap(r)

    def rsi(self, *, query: dict | None = None) -> dict:
        """Rsi"""
        params = query or {}
        r = self._request('get', '/api/v1/indicator/rsi', params=params)
        return self._unwrap(r)

    def boll(self, *, query: dict | None = None) -> dict:
        """Boll"""
        params = query or {}
        r = self._request('get', '/api/v1/indicator/boll', params=params)
        return self._unwrap(r)

    def stock(self, *, query: dict | None = None) -> dict:
        """Stock"""
        params = query or {}
        r = self._request('get', '/api/v1/diagnostic/stock', params=params)
        return self._unwrap(r)

    def market(self) -> dict:
        """Market"""
        r = self._request('get', '/api/v1/diagnostic/market')
        return self._unwrap(r)

    def technical(self, *, query: dict | None = None) -> dict:
        """Technical"""
        params = query or {}
        r = self._request('get', '/api/v1/diagnostic/technical', params=params)
        return self._unwrap(r)

    def create_strategy(self, body: dict) -> dict:
        """Create Strategy"""
        r = self._request('post', '/api/v1/write/strategy', json=body)
        return self._unwrap(r)

    def list_strategies(self) -> dict:
        """List Strategies"""
        r = self._request('get', '/api/v1/write/strategy/list')
        return self._unwrap(r)

    def get_strategy(self, sid: str) -> dict:
        """Get Strategy"""
        r = self._request('get', '/api/v1/write/strategy/{sid}')
        return self._unwrap(r)

    def delete_strategy(self, sid: str) -> dict:
        """Delete Strategy"""
        r = self._request('delete', '/api/v1/write/strategy/{sid}')
        return self._unwrap(r)

    def add_to_watchlist(self, body: dict) -> dict:
        """Add To Watchlist"""
        r = self._request('post', '/api/v1/write/watchlist', json=body)
        return self._unwrap(r)

    def list_watchlist(self) -> dict:
        """List Watchlist"""
        r = self._request('get', '/api/v1/write/watchlist/list')
        return self._unwrap(r)

    def remove_from_watchlist(self, symbol: str) -> dict:
        """Remove From Watchlist"""
        r = self._request('delete', '/api/v1/write/watchlist/{symbol}')
        return self._unwrap(r)

    def metrics_json(self) -> dict:
        """Metrics Json"""
        r = self._request('get', '/api/v1/metrics/json')
        return self._unwrap(r)

    def slow_queries(self, *, query: dict | None = None) -> dict:
        """Slow Queries"""
        params = query or {}
        r = self._request('get', '/api/v1/metrics/slow-queries', params=params)
        return self._unwrap(r)

