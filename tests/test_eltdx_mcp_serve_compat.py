"""eltdx_data 31 工具出口契约快照（QI-ARCH-17，票 07，2026-11-22）。

**先于工具体上提写入**（硬闸背书，硬约定#3：出口信封形状是下游 TradeX 可见
事实）——金样响应在嵌套工具体（未上提形态）下录制；上提 + mcp_serve 出口
收拢后**不改本文件一字仍全绿** = 31 工具 × 成功/空态/失败三路径逐字节兼容
背书（成功路径经 time 冻结 latency_ms=0.0 确定性化）。

eltdx 三态信封（自有形态，与 error_response 不同，迁移必须保真）：
  成功：json.dumps({"status": "success", "data": ...}, ensure_ascii=False, default=str)
  空态：json.dumps({"status": "no_data", "message": reason}, ensure_ascii=False)
  失败：json.dumps({"status": "error", "error": msg}, ensure_ascii=False)

口径：router/stream/TickStore 全打假 + time 冻结（路由 kwargs 一并断言，锁
参数透传与 FastMCP 默认值填充）；TickStore 缓存路径由
tests/test_tick_store_integration.py 单测，此处不重复。经 FastMCP.call_tool
走真实注册路径。
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest
from mcp.server.fastmcp import FastMCP

from tradex.tools import eltdx_data

NS = SimpleNamespace


def _df(rows):
    return pd.DataFrame(rows)


_DEPTH_RECORD = {'last_price': 10.5, 'pre_close': 10.2, 'open': 10.3, 'high': 10.6, 'low': 10.1, 'total_hand': 12000, 'amount': 1250000.0, 'inside_dish': 6000, 'outer_disc': 6000, 'buy_levels': [[10.49, 100], [10.48, 200]], 'sell_levels': [[10.5, 150], [10.51, 120]]}

_GOLDEN = {'eltdx_get_auction': {'success': '{"status": "success", "data": {"code": "000001", "latency_ms": 0.0, "point_count": 2, "points": [{"time": "09:15:03", "price": 10.5, "matched_volume": 1200, "unmatched_volume": 300}, {"time": "09:15:06", "price": 10.51, "matched_volume": 1350, "unmatched_volume": 150}]}}', 'no_data': '{"status": "no_data", "message": "no auction points"}', 'error': '{"status": "error", "error": "auction query failed: boom"}'}, 'eltdx_get_ticks': {'success': '{"status": "success", "data": {"code": "600170", "date": "20260617", "latency_ms": 0.0, "tick_count": 3, "ticks": [{"time": "09:30:01", "price": 10.5, "volume": 100, "amount": 1050.0, "bs": "buy"}, {"time": "09:30:02", "price": 10.49, "volume": 200, "amount": 2098.0, "bs": "sell"}, {"time": "09:30:03", "price": 10.5, "volume": 50, "amount": 525.0, "bs": "unknown"}]}}', 'no_data': '{"status": "no_data", "message": "no ticks on 20260617"}', 'error': '{"status": "error", "error": "ticks query failed: boom"}'}, 'eltdx_get_f10': {'success': '{"status": "success", "data": {"code": "000001", "latency_ms": 0.0, "profile": {"公司名称": "平安银行", "成立日期": "1987-03-09"}, "hot_topics": [{"题材": "金融科技"}, {"题材": "银行"}], "finance_diagnosis": {"综合评分": "80"}}}', 'error': '{"status": "error", "error": "f10 query failed: boom"}'}, 'eltdx_get_minutes': {'success': '{"status": "success", "data": {"code": "000001", "latency_ms": 0.0, "point_count": 2, "points": [{"time": "09:30", "price": 10.5, "avg_price": 10.45, "volume": 1200.0}, {"time": "09:31", "price": 10.52, "avg_price": 10.46, "volume": 900.0}]}}', 'no_data': '{"status": "no_data", "message": "no minute points"}', 'error': '{"status": "error", "error": "minutes query failed: boom"}'}, 'eltdx_get_kline': {'success': '{"status": "success", "data": {"code": "600170", "period": "day", "latency_ms": 0.0, "bar_count": 1, "bars": [{"date": "2026-06-17", "open": 10.2, "high": 10.6, "low": 10.1, "close": 10.5, "volume": 120000.0, "amount": 1250000.0}]}}', 'no_data': '{"status": "no_data", "message": "no kline bars for period=day"}', 'error': '{"status": "error", "error": "kline query failed: boom"}'}, 'eltdx_get_depth': {'success': '{"status": "success", "data": {"code": "600170", "latency_ms": 0.0, "last_price": 10.5, "pre_close": 10.2, "open": 10.3, "high": 10.6, "low": 10.1, "total_hand": 12000, "amount": 1250000.0, "inside_dish": 6000, "outer_disc": 6000, "buy_levels": [[10.49, 100], [10.48, 200]], "sell_levels": [[10.5, 150], [10.51, 120]]}}', 'no_data': '{"status": "no_data", "message": "no depth data for sh600170"}', 'error': '{"status": "error", "error": "depth query failed: boom"}'}, '_depth_unavailable': '{"status": "error", "error": "eltdx stream client not available"}', 'eltdx_stream_health': {'success': '{"status": "success", "data": {"connected": true, "codes": 2, "buffer_frames": 10, "buffer_bytes": 2048, "dropped": 0}}', 'error': '{"status": "error", "error": "stream health query failed: boom"}'}, 'eltdx_get_security_codes': {'success': '{"status": "success", "data": {"market": "sh", "category": "a_share", "latency_ms": 0.0, "count": 1, "items": [{"code": "600000", "name": "浦发银行", "category": "a_share", "board": "主板"}]}}', 'no_data': '{"status": "no_data", "message": "no securities for market=sh"}', 'error': '{"status": "error", "error": "security codes query failed: boom"}'}, 'eltdx_get_minute_history': {'success': '{"status": "success", "data": {"code": "600170", "trading_date": "20260813", "latency_ms": 0.0, "point_count": 2, "points": [{"time": "09:30", "price": 10.5, "avg_price": 10.45, "volume": 1200.0}, {"time": "09:31", "price": 10.51, "avg_price": 10.46, "volume": 800.0}]}}', 'no_data': '{"status": "no_data", "message": "no minute history for 600170 on 20260813"}', 'error': '{"status": "error", "error": "minute history query failed: boom"}'}, 'eltdx_get_buy_sell_strength': {'success': '{"status": "success", "data": {"code": "600170", "latency_ms": 0.0, "point_count": 2, "points": [{"time": "09:30", "buy": 1200.0, "sell": 800.0}, {"time": "09:31", "buy": 900.0, "sell": 1100.0}]}}', 'no_data': '{"status": "no_data", "message": "no buy/sell strength for 600170"}', 'error': '{"status": "error", "error": "buy/sell strength query failed: boom"}'}, 'eltdx_get_today_ticks': {'success': '{"status": "success", "data": {"code": "600170", "latency_ms": 0.0, "tick_count": 2, "ticks": [{"time": "09:30:01", "price": 10.5, "volume": 100.0, "amount": 1050.0, "side": "buy", "is_opening_match": false}, {"time": "09:30:02", "price": 10.49, "volume": 200.0, "amount": 2098.0, "side": "sell", "is_opening_match": true}]}}', 'no_data': '{"status": "no_data", "message": "no today ticks for 600170"}', 'error': '{"status": "error", "error": "today ticks query failed: boom"}'}, 'eltdx_get_opening_match': {'success': '{"status": "success", "data": {"code": "600170", "latency_ms": 0.0, "time": "09:25:00", "open_price": 10.5, "open_volume": 8000.0, "open_amount": 84000.0, "side": "buy"}}', 'no_data': '{"status": "no_data", "message": "no opening match for 600170"}', 'error': '{"status": "error", "error": "opening match query failed: boom"}'}, 'eltdx_get_full_kline': {'success': '{"status": "success", "data": {"code": "600170", "period": "day", "latency_ms": 0.0, "bar_count": 1, "bars": [{"date": "2026-06-17", "open": 10.2, "high": 10.6, "low": 10.1, "close": 10.5, "volume": 120000.0, "amount": 1250000.0}]}}', 'no_data': '{"status": "no_data", "message": "no full kline for 600170"}', 'error': '{"status": "error", "error": "full kline query failed: boom"}'}, 'eltdx_get_adjusted_kline': {'success': '{"status": "success", "data": {"code": "600170", "period": "day", "adjust": "qfq", "latency_ms": 0.0, "bar_count": 1, "bars": [{"date": "2026-06-17", "open": 10.2, "high": 10.6, "low": 10.1, "close": 10.5, "volume": 120000.0, "amount": 1250000.0}]}}', 'no_data': '{"status": "no_data", "message": "no adjusted kline for 600170"}', 'error': '{"status": "error", "error": "adjusted kline query failed: boom"}'}, 'eltdx_get_stock_profile': {'success': '{"status": "success", "data": {"latency_ms": 0.0, "count": 1, "profiles": [{"code": "600170", "name": "上海建工", "last_price": 2.5, "change_pct": 1.2, "turnover_rate": 0.8, "total_market_value": 22000000000.0, "circulating_market_value": 20000000000.0, "total_shares": 8800000000.0, "circulating_shares": 8000000000.0, "eps": 0.15, "board": "主板"}]}}', 'no_data': '{"status": "no_data", "message": "no stock profile for 600170,000001"}', 'error': '{"status": "error", "error": "stock profile query failed: boom"}'}, 'eltdx_get_shortline_indicators': {'success': '{"status": "success", "data": {"latency_ms": 0.0, "count": 1, "indicators": [{"涨停状态": "涨停", "连板天数": 2, "封单流通比": 0.05}]}}', 'no_data': '{"status": "no_data", "message": "no shortline indicators for 600170"}', 'error': '{"status": "error", "error": "shortline indicators query failed: boom"}'}, 'eltdx_get_finance_batch': {'success': '{"status": "success", "data": {"latency_ms": 0.0, "count": 1, "finances": [{"code": "600170", "total_shares": 8800000000.0, "circulating_shares": 8000000000.0, "total_assets": 60000000000.0, "net_profit": 1500000000.0, "eps": 0.17, "industry": "土木工程建筑业", "ipo_date": "1994-06-28"}]}}', 'no_data': '{"status": "no_data", "message": "no finance data for 600170"}', 'error': '{"status": "error", "error": "finance batch query failed: boom"}'}, 'eltdx_get_special_limits': {'success': '{"status": "success", "data": {"latency_ms": 0.0, "count": 1, "limits": [{"code": "300001", "limit_up_price": 11.0, "limit_down_price": 9.0}]}}', 'no_data': '{"status": "no_data", "message": "no special limits"}', 'error': '{"status": "error", "error": "special limits query failed: boom"}'}, 'eltdx_get_finance_report': {'success': '{"status": "success", "data": {"code": "600170", "report_type": "zcfzb", "latency_ms": 0.0, "columns": ["T001", "T002"], "row_count": 2, "rows": [{"T001": 100.0, "T002": 200.0}, {"T001": 110.0, "T002": 210.0}]}}', 'no_data': '{"status": "no_data", "message": "no finance report for 600170"}', 'error': '{"status": "error", "error": "finance report query failed: boom"}'}, 'eltdx_get_dividend_financing': {'success': '{"status": "success", "data": {"code": "600170", "latency_ms": 0.0, "columns": ["T005", "T006"], "row_count": 1, "rows": [{"T005": "10送2", "T006": "2025-06-01"}]}}', 'no_data': '{"status": "no_data", "message": "no dividend financing for 600170"}', 'error': '{"status": "error", "error": "dividend financing query failed: boom"}'}, 'eltdx_get_company_news': {'success': '{"status": "success", "data": {"code": "600170", "latency_ms": 0.0, "columns": ["T010", "T011"], "row_count": 1, "rows": [{"T010": "研报A", "T011": "2026-06-01"}]}}', 'no_data': '{"status": "no_data", "message": "no company news for 600170"}', 'error': '{"status": "error", "error": "company news query failed: boom"}'}, 'eltdx_get_northbound_holding': {'success': '{"status": "success", "data": {"code": "600170", "latency_ms": 0.0, "columns": ["T020", "T021"], "row_count": 1, "rows": [{"T020": 1000.0, "T021": 500.0}]}}', 'no_data': '{"status": "no_data", "message": "no northbound holding for 600170"}', 'error': '{"status": "error", "error": "northbound holding query failed: boom"}'}, 'eltdx_get_stock_topics': {'success': '{"status": "success", "data": {"code": "600170", "latency_ms": 0.0, "count": 1, "topics": [{"topic_name": "节能环保", "relation_level": 0.9, "reason": "主营环保设备"}]}}', 'no_data': '{"status": "no_data", "message": "no topics for 600170"}', 'error': '{"status": "error", "error": "stock topics query failed: boom"}'}, 'eltdx_get_topic_stocks': {'success': '{"status": "success", "data": {"seed_code": "600170", "topic_name": "", "latency_ms": 0.0, "count": 1, "stocks": [{"code": "000001", "name": "平安银行", "rank": 1, "change_pct": 2.1, "change_pct_3d": 5.0, "change_pct_5d": 7.0, "change_pct_20d": 12.0, "change_pct_60d": 20.0}]}}', 'no_data': '{"status": "no_data", "message": "no topic stocks for 600170"}', 'error': '{"status": "error", "error": "topic stocks query failed: boom"}'}, 'eltdx_get_auction_data': {'success': '{"status": "success", "data": {"code": "600170", "latency_ms": 0.0, "open_price": 10.5, "open_volume": 8000.0, "open_amount": 84000.0, "open_change_pct": 2.9, "pre_close": 10.2}}', 'no_data': '{"status": "no_data", "message": "no auction data for 600170"}', 'error': '{"status": "error", "error": "auction data query failed: boom"}'}, 'eltdx_get_category_quotes': {'success': '{"status": "success", "data": {"category": "沪深a股", "sort_by": "涨幅", "latency_ms": 0.0, "count": 1, "quotes": [{"code": "600170", "last_price": 2.5, "change_pct": 1.2, "amount": 1200000000.0, "bid1": 2.49, "ask1": 2.5, "rise_speed": 0.1}]}}', 'no_data': '{"status": "no_data", "message": "no category quotes for 沪深a股"}', 'error': '{"status": "error", "error": "category quotes query failed: boom"}'}, 'eltdx_get_trading_day': {'success': '{"status": "success", "data": {"server_date": "2026-11-22", "server_datetime": "10:30:00"}}', 'no_data': '{"status": "no_data", "message": "no trading day"}', 'error': '{"status": "error", "error": "trading day query failed: boom"}'}, 'eltdx_get_opening_match_history': {'success': '{"status": "success", "data": {"code": "600170", "trading_date": "20260813", "latency_ms": 0.0, "open_price": 10.5, "open_volume": 8000.0, "open_amount": 84000.0}}', 'no_data': '{"status": "no_data", "message": "no opening match for 600170 on 20260813"}', 'error': '{"status": "error", "error": "opening match history query failed: boom"}'}, 'eltdx_get_capital_changes': {'success': '{"status": "success", "data": {"code": "600170", "latency_ms": 0.0, "count": 1, "changes": [{"date": "2025-06-01", "type": "送股", "shares_before": 8000000000.0, "shares_after": 8800000000.0}]}}', 'no_data': '{"status": "no_data", "message": "no capital changes for 600170"}', 'error': '{"status": "error", "error": "capital changes query failed: boom"}'}, 'eltdx_get_special_limits_scan': {'success': '{"status": "success", "data": {"latency_ms": 0.0, "count": 1, "limits": [{"code": "300001", "limit_up_price": 11.0, "limit_down_price": 9.0}]}}', 'no_data': '{"status": "no_data", "message": "no special limits scan"}', 'error': '{"status": "error", "error": "special limits scan query failed: boom"}'}, 'eltdx_get_f10_extra': {'success': '{"status": "success", "data": {"entry": "valuation", "code": "600170", "latency_ms": 0.0, "columns": ["T007", "T008"], "row_count": 2, "rows": [{"T007": 12.5, "T008": 0.8}, {"T007": 13.0, "T008": 0.9}]}}', 'no_data': '{"status": "no_data", "message": "no f10 data for valuation 600170"}', 'error': '{"status": "error", "error": "f10 extra query failed: boom"}'}}

_CASES = [
    {
        "tool": 'eltdx_get_auction',
        "args": {'code': '000001'},
        "route": ['call_auction', {'code': '000001'}],
        "fixture": NS(points=[NS(time_label='09:15:03', price=10.5, matched_volume=1200, unmatched_volume=300), NS(time_label='09:15:06', price=10.51, matched_volume=1350, unmatched_volume=150)]),
        "nodata": True,
        "err": 'auction query failed',
    },
    {
        "tool": 'eltdx_get_ticks',
        "args": {'code': '600170', 'trading_date': '2026-06-17'},
        "route": ['tick_data', {'code': '600170', 'trading_date': '2026-06-17', 'count': 2000}],
        "fixture": NS(ticks=[NS(time='09:30:01', price=10.5, volume=100, amount=1050.0, side='buy'), NS(time='09:30:02', price=10.49, volume=200, amount=2098.0, side='sell'), NS(time='09:30:03', price=10.5, volume=50, amount=525.0, side='status_1')]),
        "nodata": True,
        "err": 'ticks query failed',
    },
    {
        "tool": 'eltdx_get_f10',
        "args": {'code': '000001'},
        "route": ['f10_profile', {'code': '000001'}],
        "fixture": {'profile_resp': NS(ok=True, first_table=NS(rows=[{'公司名称': '平安银行', '成立日期': '1987-03-09'}])), 'topics_resp': NS(ok=True, first_table=NS(rows=[{'题材': '金融科技'}, {'题材': '银行'}])), 'diag_resp': NS(ok=True, first_table=NS(rows=[{'综合评分': '80'}])), 'code': '000001'},
        "nodata": False,
        "err": 'f10 query failed',
    },
    {
        "tool": 'eltdx_get_minutes',
        "args": {'code': '000001'},
        "route": ['minute_data', {'code': '000001'}],
        "fixture": _df([{'时间': '09:30', '价格': 10.5, '均价': 10.45, '成交量': 1200.0}, {'时间': '09:31', '价格': 10.52, '均价': 10.46, '成交量': 900.0}]),
        "nodata": True,
        "err": 'minutes query failed',
    },
    {
        "tool": 'eltdx_get_kline',
        "args": {'code': '600170'},
        "route": ['historical_kline', {'code': '600170', 'period': 'day', 'count': 100}],
        "fixture": _df([{'日期': '2026-06-17', '开盘': 10.2, '最高': 10.6, '最低': 10.1, '收盘': 10.5, '成交量': 120000.0, '成交额': 1250000.0}]),
        "nodata": True,
        "err": 'kline query failed',
    },
    {
        "tool": 'eltdx_get_depth',
        "args": {'code': 'sh600170'},
        "route": None,
        "fixture": _DEPTH_RECORD,
        "nodata": True,
        "err": 'depth query failed',
    },
    {
        "tool": 'eltdx_stream_health',
        "args": {},
        "route": None,
        "fixture": {'connected': True, 'codes': 2, 'buffer_frames': 10, 'buffer_bytes': 2048, 'dropped': 0},
        "nodata": False,
        "err": 'stream health query failed',
    },
    {
        "tool": 'eltdx_get_security_codes',
        "args": {'market': 'sh', 'category': 'a_share'},
        "route": ['security_codes', {'market': 'sh'}],
        "fixture": _df([{'代码': '600000', '名称': '浦发银行', '类别': 'a_share', '板块': '主板'}, {'代码': '510300', '名称': '沪深300ETF', '类别': 'etf', '板块': '主板'}]),
        "nodata": True,
        "err": 'security codes query failed',
    },
    {
        "tool": 'eltdx_get_minute_history',
        "args": {'code': '600170', 'trading_date': '20260813'},
        "route": ['minute_history', {'code': '600170', 'trading_date': '20260813'}],
        "fixture": _df([{'时间': '09:30', '价格': 10.5, '均价': 10.45, '成交量': 1200.0}, {'时间': '09:31', '价格': 10.51, '均价': 10.46, '成交量': 800.0}]),
        "nodata": True,
        "err": 'minute history query failed',
    },
    {
        "tool": 'eltdx_get_buy_sell_strength',
        "args": {'code': '600170'},
        "route": ['minute_aux', {'code': '600170', 'kind': 'buy_sell_strength'}],
        "fixture": _df([{'时间': '09:30', '买盘': 1200.0, '卖盘': 800.0}, {'时间': '09:31', '买盘': 900.0, '卖盘': 1100.0}]),
        "nodata": True,
        "err": 'buy/sell strength query failed',
    },
    {
        "tool": 'eltdx_get_today_ticks',
        "args": {'code': '600170', 'count': 500},
        "route": ['today_ticks', {'code': '600170', 'count': 500}],
        "fixture": _df([{'时间': '09:30:01', '价格': 10.5, '成交量': 100.0, '成交额': 1050.0, '方向': 'buy', '是否开盘撮合': False}, {'时间': '09:30:02', '价格': 10.49, '成交量': 200.0, '成交额': 2098.0, '方向': 'sell', '是否开盘撮合': True}]),
        "nodata": True,
        "err": 'today ticks query failed',
    },
    {
        "tool": 'eltdx_get_opening_match',
        "args": {'code': '600170'},
        "route": ['opening_match', {'code': '600170'}],
        "fixture": _df([{'时间': '09:25:00', '价格': 10.5, '成交量': 8000.0, '成交额': 84000.0, '方向': 'buy'}]),
        "nodata": True,
        "err": 'opening match query failed',
    },
    {
        "tool": 'eltdx_get_full_kline',
        "args": {'code': '600170'},
        "route": ['full_kline', {'code': '600170', 'period': 'day'}],
        "fixture": _df([{'日期': '2026-06-17', '开盘': 10.2, '最高': 10.6, '最低': 10.1, '收盘': 10.5, '成交量': 120000.0, '成交额': 1250000.0}]),
        "nodata": True,
        "err": 'full kline query failed',
    },
    {
        "tool": 'eltdx_get_adjusted_kline',
        "args": {'code': '600170'},
        "route": ['adjusted_kline', {'code': '600170', 'period': 'day', 'adjust': 'qfq', 'count': 800}],
        "fixture": _df([{'日期': '2026-06-17', '开盘': 10.2, '最高': 10.6, '最低': 10.1, '收盘': 10.5, '成交量': 120000.0, '成交额': 1250000.0}]),
        "nodata": True,
        "err": 'adjusted kline query failed',
    },
    {
        "tool": 'eltdx_get_stock_profile',
        "args": {'codes': '600170,000001'},
        "route": ['stock_profile', {'codes': '600170,000001'}],
        "fixture": _df([{'代码': '600170', '名称': '上海建工', '最新价': 2.5, '涨跌幅': 1.2, '换手率': 0.8, '总市值': 22000000000.0, '流通市值': 20000000000.0, '总股本': 8800000000.0, '流通股本': 8000000000.0, 'EPS': 0.15, '板块': '主板'}]),
        "nodata": True,
        "err": 'stock profile query failed',
    },
    {
        "tool": 'eltdx_get_shortline_indicators',
        "args": {'codes': '600170'},
        "route": ['shortline_indicators', {'codes': '600170'}],
        "fixture": _df([{'涨停状态': '涨停', '连板天数': 2, '封单流通比': 0.05}]),
        "nodata": True,
        "err": 'shortline indicators query failed',
    },
    {
        "tool": 'eltdx_get_finance_batch',
        "args": {'codes': '600170'},
        "route": ['finance_batch', {'codes': '600170'}],
        "fixture": _df([{'代码': '600170', '总股本': 8800000000.0, '流通股本': 8000000000.0, '总资产': 60000000000.0, '净利润': 1500000000.0, '每股收益': 0.17, '行业': '土木工程建筑业', '上市日期': '1994-06-28'}]),
        "nodata": True,
        "err": 'finance batch query failed',
    },
    {
        "tool": 'eltdx_get_special_limits',
        "args": {},
        "route": ['special_limits', {}],
        "fixture": _df([{'代码': '300001', '涨停价': 11.0, '跌停价': 9.0}]),
        "nodata": True,
        "err": 'special limits query failed',
    },
    {
        "tool": 'eltdx_get_finance_report',
        "args": {'code': '600170'},
        "route": ['finance_report', {'code': '600170', 'report_type': 'zcfzb'}],
        "fixture": _df([{'T001': 100.0, 'T002': 200.0}, {'T001': 110.0, 'T002': 210.0}]),
        "nodata": True,
        "err": 'finance report query failed',
    },
    {
        "tool": 'eltdx_get_dividend_financing',
        "args": {'code': '600170'},
        "route": ['dividend_financing', {'code': '600170'}],
        "fixture": _df([{'T005': '10送2', 'T006': '2025-06-01'}]),
        "nodata": True,
        "err": 'dividend financing query failed',
    },
    {
        "tool": 'eltdx_get_company_news',
        "args": {'code': '600170'},
        "route": ['company_news', {'code': '600170'}],
        "fixture": _df([{'T010': '研报A', 'T011': '2026-06-01'}]),
        "nodata": True,
        "err": 'company news query failed',
    },
    {
        "tool": 'eltdx_get_northbound_holding',
        "args": {'code': '600170'},
        "route": ['northbound_holding', {'code': '600170'}],
        "fixture": _df([{'T020': 1000.0, 'T021': 500.0}]),
        "nodata": True,
        "err": 'northbound holding query failed',
    },
    {
        "tool": 'eltdx_get_stock_topics',
        "args": {'code': '600170'},
        "route": ['stock_topics', {'code': '600170'}],
        "fixture": _df([{'题材名': '节能环保', '关联度': 0.9, '入选理由': '主营环保设备'}]),
        "nodata": True,
        "err": 'stock topics query failed',
    },
    {
        "tool": 'eltdx_get_topic_stocks',
        "args": {'code': '600170'},
        "route": ['topic_stocks', {'code': '600170', 'topic_name': ''}],
        "fixture": _df([{'代码': '000001', '名称': '平安银行', '排名': 1, '涨跌幅': 2.1, '3日涨跌幅': 5.0, '5日涨跌幅': 7.0, '20日涨跌幅': 12.0, '60日涨跌幅': 20.0}]),
        "nodata": True,
        "err": 'topic stocks query failed',
    },
    {
        "tool": 'eltdx_get_auction_data',
        "args": {'code': '600170'},
        "route": ['auction_data', {'code': '600170'}],
        "fixture": _df([{'代码': '600170', '开盘价': 10.5, '开盘量': 8000.0, '开盘额': 84000.0, '开盘涨跌幅': 2.9, '昨收': 10.2}]),
        "nodata": True,
        "err": 'auction data query failed',
    },
    {
        "tool": 'eltdx_get_category_quotes',
        "args": {'category': '沪深a股', 'sort_by': '涨幅'},
        "route": ['category_quotes', {'category': '沪深a股', 'sort_by': '涨幅', 'count': 80}],
        "fixture": _df([{'代码': '600170', '现价': 2.5, '涨跌幅': 1.2, '成交额': 1200000000.0, '买一': 2.49, '卖一': 2.5, '涨速': 0.1}]),
        "nodata": True,
        "err": 'category quotes query failed',
    },
    {
        "tool": 'eltdx_get_trading_day',
        "args": {},
        "route": ['trading_day', {}],
        "fixture": _df([{'服务器日期': '2026-11-22', '服务器时间': '10:30:00'}]),
        "nodata": True,
        "err": 'trading day query failed',
    },
    {
        "tool": 'eltdx_get_opening_match_history',
        "args": {'code': '600170', 'trading_date': '20260813'},
        "route": ['opening_match_history', {'code': '600170', 'trading_date': '20260813'}],
        "fixture": _df([{'价格': 10.5, '成交量': 8000.0, '成交额': 84000.0}]),
        "nodata": True,
        "err": 'opening match history query failed',
    },
    {
        "tool": 'eltdx_get_capital_changes',
        "args": {'code': '600170'},
        "route": ['capital_changes', {'code': '600170'}],
        "fixture": _df([{'日期': '2025-06-01', '变动类型': '送股', '变动前股本': 8000000000.0, '变动后股本': 8800000000.0}]),
        "nodata": True,
        "err": 'capital changes query failed',
    },
    {
        "tool": 'eltdx_get_special_limits_scan',
        "args": {},
        "route": ['special_limits_scan', {}],
        "fixture": _df([{'代码': '300001', '涨停价': 11.0, '跌停价': 9.0}]),
        "nodata": True,
        "err": 'special limits scan query failed',
    },
    {
        "tool": 'eltdx_get_f10_extra',
        "args": {'entry': 'valuation', 'code': '600170'},
        "route": ['f10_extra', {'entry': 'valuation', 'code': '600170'}],
        "fixture": _df([{'T007': 12.5, 'T008': 0.8}, {'T007': 13.0, 'T008': 0.9}]),
        "nodata": True,
        "err": 'f10 extra query failed',
    },
]

_NODATA_CASES = [c for c in _CASES if c["nodata"]]

_DEPTH_CASE = next(c for c in _CASES if c["tool"] == "eltdx_get_depth")


class _FakeRouter:
    """_router 假体：按场景返回 fixture / None / 抛 RuntimeError，记录调用。"""

    def __init__(self, scenario, fixture):
        self.scenario = scenario
        self.fixture = fixture
        self.last_call = None

    def route(self, name, **kwargs):
        self.last_call = (name, kwargs)
        if self.scenario == "error":
            raise RuntimeError("boom")
        if self.scenario == "no_data":
            return None, "eltdx"
        return self.fixture, "eltdx"


class _FakeManager:
    """get_stream_manager 假体（depth 快照 / stream_health）。"""

    def __init__(self, scenario, record):
        self.scenario = scenario
        self.record = record

    def start(self):
        return True

    def snapshot(self, codes):
        if self.scenario == "error":
            raise RuntimeError("boom")
        if self.scenario == "no_data":
            return {}
        return {eltdx_data.normalize_code_with_prefix("sh600170"): self.record}

    def health(self):
        if self.scenario == "error":
            raise RuntimeError("boom")
        return self.record


class _UnavailableManager:
    def start(self):
        return False


def _install(monkeypatch, scenario, case):
    """打桩三件套：router / TickStore=None / stream manager + 冻结时钟。"""
    router = _FakeRouter(scenario, case["fixture"])
    monkeypatch.setattr(eltdx_data, "_router", router)
    monkeypatch.setattr(eltdx_data, "_get_tick_store", lambda: None)
    monkeypatch.setattr(eltdx_data, "get_stream_manager", lambda: _FakeManager(scenario, case["fixture"]))
    monkeypatch.setattr(eltdx_data, "time", SimpleNamespace(time=lambda: 1000.0))
    return router


async def _call_tool(mcp, name, args):
    result = await mcp.call_tool(name, dict(args))
    contents = result[0] if isinstance(result, tuple) else result
    return contents[0].text


class TestEltdxExitSnapshot:
    """逐工具出口金样快照（上提前后同形状，迁移时本文件不改）。"""

    @pytest.mark.parametrize("case", _CASES, ids=[c["tool"] for c in _CASES])
    async def test_success_path(self, case, monkeypatch):
        router = _install(monkeypatch, "success", case)
        mcp = FastMCP("eltdx-snapshot")
        eltdx_data.register(mcp)
        out = await _call_tool(mcp, case["tool"], case["args"])
        assert out == _GOLDEN[case["tool"]]["success"], (
            f"{case['tool']} 成功路径快照不符：{out[:160]}"
        )
        if case["route"] is not None:
            assert list(router.last_call) == case["route"], (
                f"{case['tool']} 路由调用漂移：{router.last_call}"
            )

    @pytest.mark.parametrize("case", _NODATA_CASES, ids=[c["tool"] for c in _NODATA_CASES])
    async def test_no_data_path(self, case, monkeypatch):
        _install(monkeypatch, "no_data", case)
        mcp = FastMCP("eltdx-snapshot")
        eltdx_data.register(mcp)
        out = await _call_tool(mcp, case["tool"], case["args"])
        assert out == _GOLDEN[case["tool"]]["no_data"], (
            f"{case['tool']} 空态路径快照不符：{out[:160]}"
        )

    @pytest.mark.parametrize("case", _CASES, ids=[c["tool"] for c in _CASES])
    async def test_error_path(self, case, monkeypatch):
        router = _install(monkeypatch, "error", case)
        mcp = FastMCP("eltdx-snapshot")
        eltdx_data.register(mcp)
        out = await _call_tool(mcp, case["tool"], case["args"])
        assert out == _GOLDEN[case["tool"]]["error"], (
            f"{case['tool']} 失败路径快照不符：{out[:160]}"
        )
        if case["route"] is not None:
            assert list(router.last_call) == case["route"]

    async def test_depth_stream_unavailable(self, monkeypatch):
        """depth 专属：start() False 早退 _err 路径（非异常分支）。"""
        _install(monkeypatch, "success", _DEPTH_CASE)
        monkeypatch.setattr(eltdx_data, "get_stream_manager", lambda: _UnavailableManager())
        mcp = FastMCP("eltdx-snapshot")
        eltdx_data.register(mcp)
        out = await _call_tool(mcp, "eltdx_get_depth", {"code": "sh600170"})
        assert out == _GOLDEN["_depth_unavailable"], f"depth 流不可用快照不符：{out[:160]}"
