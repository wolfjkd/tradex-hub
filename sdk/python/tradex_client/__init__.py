"""tradex_client SDK (工单 22 降级方案)。"""

from __future__ import annotations
import requests
from typing import Any

__version__ = '2.0.0'

class TradexClient:
    def __init__(self, base_url: str = 'http://127.0.0.1:8000', timeout: float = 30.0):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self._session = requests.Session()
        # 直连本地网关：requests 默认 trust_env=True 会读 HTTP(S)_PROXY
        self._session.trust_env = False

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

    def market_overview(self) -> dict:
        """Overview"""
        r = self._request('get', '/api/v1/market/overview')
        return self._unwrap(r)

    def market_global(self, *, query: dict | None = None) -> dict:
        """Global Quote"""
        params = query or {}
        r = self._request('get', '/api/v1/market/global', params=params)
        return self._unwrap(r)

    def market_limit_up_down(self, *, query: dict | None = None) -> dict:
        """Limit Up Down"""
        params = query or {}
        r = self._request('get', '/api/v1/market/limit-up-down', params=params)
        return self._unwrap(r)

    def market_dragon_tiger(self, *, query: dict | None = None) -> dict:
        """Dragon Tiger"""
        params = query or {}
        r = self._request('get', '/api/v1/market/dragon-tiger', params=params)
        return self._unwrap(r)

    def fund_flow(self, *, query: dict | None = None) -> dict:
        """Flow"""
        params = query or {}
        r = self._request('get', '/api/v1/fund/flow', params=params)
        return self._unwrap(r)

    def fund_northbound(self) -> dict:
        """Northbound"""
        r = self._request('get', '/api/v1/fund/northbound')
        return self._unwrap(r)

    def price_quote(self, *, query: dict | None = None) -> dict:
        """Quote"""
        params = query or {}
        r = self._request('get', '/api/v1/price/quote', params=params)
        return self._unwrap(r)

    def price_kline(self, *, query: dict | None = None) -> dict:
        """Kline"""
        params = query or {}
        r = self._request('get', '/api/v1/price/kline', params=params)
        return self._unwrap(r)

    def price_intraday(self, *, query: dict | None = None) -> dict:
        """Intraday"""
        params = query or {}
        r = self._request('get', '/api/v1/price/intraday', params=params)
        return self._unwrap(r)

    def company_search(self, *, query: dict | None = None) -> dict:
        """Search"""
        params = query or {}
        r = self._request('get', '/api/v1/company/search', params=params)
        return self._unwrap(r)

    def company_info(self, *, query: dict | None = None) -> dict:
        """Info"""
        params = query or {}
        r = self._request('get', '/api/v1/company/info', params=params)
        return self._unwrap(r)

    def company_profile(self, *, query: dict | None = None) -> dict:
        """Profile"""
        params = query or {}
        r = self._request('get', '/api/v1/company/profile', params=params)
        return self._unwrap(r)

    def company_competitors(self, *, query: dict | None = None) -> dict:
        """Competitors"""
        params = query or {}
        r = self._request('get', '/api/v1/company/competitors', params=params)
        return self._unwrap(r)

    def financial_income(self, *, query: dict | None = None) -> dict:
        """Income"""
        params = query or {}
        r = self._request('get', '/api/v1/financial/income', params=params)
        return self._unwrap(r)

    def financial_balance(self, *, query: dict | None = None) -> dict:
        """Balance"""
        params = query or {}
        r = self._request('get', '/api/v1/financial/balance', params=params)
        return self._unwrap(r)

    def financial_cashflow(self, *, query: dict | None = None) -> dict:
        """Cashflow"""
        params = query or {}
        r = self._request('get', '/api/v1/financial/cashflow', params=params)
        return self._unwrap(r)

    def financial_line_item(self, *, query: dict | None = None) -> dict:
        """Line Item"""
        params = query or {}
        r = self._request('get', '/api/v1/financial/line-item', params=params)
        return self._unwrap(r)

    def financial_indicators(self, *, query: dict | None = None) -> dict:
        """Indicators"""
        params = query or {}
        r = self._request('get', '/api/v1/financial/indicators', params=params)
        return self._unwrap(r)

    def financial_growth(self, *, query: dict | None = None) -> dict:
        """Growth"""
        params = query or {}
        r = self._request('get', '/api/v1/financial/growth', params=params)
        return self._unwrap(r)

    def financial_per_share(self, *, query: dict | None = None) -> dict:
        """Per Share"""
        params = query or {}
        r = self._request('get', '/api/v1/financial/per-share', params=params)
        return self._unwrap(r)

    def financial_segments(self, *, query: dict | None = None) -> dict:
        """Segments"""
        params = query or {}
        r = self._request('get', '/api/v1/financial/segments', params=params)
        return self._unwrap(r)

    def news_stock(self, *, query: dict | None = None) -> dict:
        """Stock"""
        params = query or {}
        r = self._request('get', '/api/v1/news/stock', params=params)
        return self._unwrap(r)

    def news_announcements(self, *, query: dict | None = None) -> dict:
        """Announcements"""
        params = query or {}
        r = self._request('get', '/api/v1/news/announcements', params=params)
        return self._unwrap(r)

    def news_search(self, *, query: dict | None = None) -> dict:
        """Search"""
        params = query or {}
        r = self._request('get', '/api/v1/news/search', params=params)
        return self._unwrap(r)

    def industry_list(self) -> dict:
        """List Industries"""
        r = self._request('get', '/api/v1/industry/list')
        return self._unwrap(r)

    def industry_stocks(self, *, query: dict | None = None) -> dict:
        """Stocks"""
        params = query or {}
        r = self._request('get', '/api/v1/industry/stocks', params=params)
        return self._unwrap(r)

    def industry_concepts(self) -> dict:
        """Concepts"""
        r = self._request('get', '/api/v1/industry/concepts')
        return self._unwrap(r)

    def industry_fund_flow(self, *, query: dict | None = None) -> dict:
        """Fund Flow"""
        params = query or {}
        r = self._request('get', '/api/v1/industry/fund-flow', params=params)
        return self._unwrap(r)

    def industry_pe(self, *, query: dict | None = None) -> dict:
        """Pe"""
        params = query or {}
        r = self._request('get', '/api/v1/industry/pe', params=params)
        return self._unwrap(r)

    def indicator_macd(self, *, query: dict | None = None) -> dict:
        """Macd"""
        params = query or {}
        r = self._request('get', '/api/v1/indicator/macd', params=params)
        return self._unwrap(r)

    def indicator_kdj(self, *, query: dict | None = None) -> dict:
        """Kdj"""
        params = query or {}
        r = self._request('get', '/api/v1/indicator/kdj', params=params)
        return self._unwrap(r)

    def indicator_rsi(self, *, query: dict | None = None) -> dict:
        """Rsi"""
        params = query or {}
        r = self._request('get', '/api/v1/indicator/rsi', params=params)
        return self._unwrap(r)

    def indicator_boll(self, *, query: dict | None = None) -> dict:
        """Boll"""
        params = query or {}
        r = self._request('get', '/api/v1/indicator/boll', params=params)
        return self._unwrap(r)

    def diagnostic_stock(self, *, query: dict | None = None) -> dict:
        """Stock"""
        params = query or {}
        r = self._request('get', '/api/v1/diagnostic/stock', params=params)
        return self._unwrap(r)

    def diagnostic_market(self) -> dict:
        """Market"""
        r = self._request('get', '/api/v1/diagnostic/market')
        return self._unwrap(r)

    def diagnostic_technical(self, *, query: dict | None = None) -> dict:
        """Technical"""
        params = query or {}
        r = self._request('get', '/api/v1/diagnostic/technical', params=params)
        return self._unwrap(r)

    def post_write_strategy(self, body: dict) -> dict:
        """Create Strategy"""
        r = self._request('post', '/api/v1/write/strategy', json=body)
        return self._unwrap(r)

    def write_strategy_list(self) -> dict:
        """List Strategies"""
        r = self._request('get', '/api/v1/write/strategy/list')
        return self._unwrap(r)

    def write_strategy_by_sid(self, sid: str) -> dict:
        """Get Strategy"""
        r = self._request('get', '/api/v1/write/strategy/{sid}')
        return self._unwrap(r)

    def delete_write_strategy_by_sid(self, sid: str) -> dict:
        """Delete Strategy"""
        r = self._request('delete', '/api/v1/write/strategy/{sid}')
        return self._unwrap(r)

    def post_write_watchlist(self, body: dict) -> dict:
        """Add To Watchlist"""
        r = self._request('post', '/api/v1/write/watchlist', json=body)
        return self._unwrap(r)

    def write_watchlist_list(self) -> dict:
        """List Watchlist"""
        r = self._request('get', '/api/v1/write/watchlist/list')
        return self._unwrap(r)

    def delete_write_watchlist_by_symbol(self, symbol: str) -> dict:
        """Remove From Watchlist"""
        r = self._request('delete', '/api/v1/write/watchlist/{symbol}')
        return self._unwrap(r)

    def metrics_json(self) -> dict:
        """Metrics Json"""
        r = self._request('get', '/api/v1/metrics/json')
        return self._unwrap(r)

    def metrics_slow_queries(self, *, query: dict | None = None) -> dict:
        """Slow Queries"""
        params = query or {}
        r = self._request('get', '/api/v1/metrics/slow-queries', params=params)
        return self._unwrap(r)

    def access_log(self, *, query: dict | None = None) -> dict:
        """List Access Log"""
        params = query or {}
        r = self._request('get', '/api/v1/access-log', params=params)
        return self._unwrap(r)

    def event_earnings_forecast(self, *, query: dict | None = None) -> dict:
        """Earnings Forecast"""
        params = query or {}
        r = self._request('get', '/api/v1/event/earnings-forecast', params=params)
        return self._unwrap(r)

    def event_institution_survey(self, *, query: dict | None = None) -> dict:
        """Institution Survey"""
        params = query or {}
        r = self._request('get', '/api/v1/event/institution-survey', params=params)
        return self._unwrap(r)

    def event_holder_trades(self, *, query: dict | None = None) -> dict:
        """Holder Trades"""
        params = query or {}
        r = self._request('get', '/api/v1/event/holder-trades', params=params)
        return self._unwrap(r)

    def event_share_buyback(self, *, query: dict | None = None) -> dict:
        """Share Buyback"""
        params = query or {}
        r = self._request('get', '/api/v1/event/share-buyback', params=params)
        return self._unwrap(r)

    def event_equity_pledge(self, *, query: dict | None = None) -> dict:
        """Equity Pledge"""
        params = query or {}
        r = self._request('get', '/api/v1/event/equity-pledge', params=params)
        return self._unwrap(r)

    def event_ipo_calendar(self, *, query: dict | None = None) -> dict:
        """Ipo Calendar"""
        params = query or {}
        r = self._request('get', '/api/v1/event/ipo-calendar', params=params)
        return self._unwrap(r)

    def macro_pmi(self) -> dict:
        """Pmi"""
        r = self._request('get', '/api/v1/macro/pmi')
        return self._unwrap(r)

    def macro_bond_yield_curve(self, *, query: dict | None = None) -> dict:
        """Bond Yield Curve"""
        params = query or {}
        r = self._request('get', '/api/v1/macro/bond-yield-curve', params=params)
        return self._unwrap(r)

    def macro_sw_industry_history(self, *, query: dict | None = None) -> dict:
        """Sw Industry History"""
        params = query or {}
        r = self._request('get', '/api/v1/macro/sw-industry-history', params=params)
        return self._unwrap(r)

    def macro_sw_industry_as_of(self, *, query: dict | None = None) -> dict:
        """Sw Industry As Of"""
        params = query or {}
        r = self._request('get', '/api/v1/macro/sw-industry-as-of', params=params)
        return self._unwrap(r)

    def industry_news_get(self, *, query: dict | None = None) -> dict:
        """Get News"""
        params = query or {}
        r = self._request('get', '/api/v1/industry-news/get', params=params)
        return self._unwrap(r)

    def industry_news_tracks(self) -> dict:
        """Tracks"""
        r = self._request('get', '/api/v1/industry-news/tracks')
        return self._unwrap(r)

