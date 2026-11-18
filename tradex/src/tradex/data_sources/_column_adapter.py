"""源列名翻译适配器出口（QI-ARCH-04，2026-11-18 质检整改）。

源返回 DataFrame 的列名形态差异（东财中文 / eltdx·腾讯英文 / 大小写）的
翻译知识，原摊在 4+ 消费点各自手抄 col_map——新加备源要同步改多处（下游
波及面失控）。下沉 data_sources 层单点出口（_NativePanicShield 同理念：
源边界知识归源层，新加备源只改本文件映射表，下游不波及）。

消费点（改造后引此处，不再自持映射）：
  - service/price_service.py  分时分钟线（MINUTE_EN，小写英文目标）
  - tools/analysis_engine.py  OHLCV（OHLCV_EN，首字母大写英文目标）
  - tools/signal_data_base.py 技术指标（OHLCV_EN）
  - service/industry_service.py 新浪板块备源（SECTOR_SINA_COLS 列过滤）
"""

from __future__ import annotations

import pandas as pd

# OHLCV 标准列（首字母大写英文目标——analysis_engine / signal_data_base）
OHLCV_EN = {
    "日期": "Date", "开盘": "Open", "最高": "High",
    "最低": "Low", "收盘": "Close", "成交量": "Volume",
    "date": "Date", "open": "Open", "high": "High",
    "low": "Low", "close": "Close", "volume": "Volume",
}

# 分钟线标准列（小写英文目标——price_service 分时；东财「价格」与 eltdx
# 「price」同指收盘价序列，统一到 close）
MINUTE_EN = {
    "时间": "time", "time": "time",
    "开盘": "open", "open": "open",
    "收盘": "close", "close": "close", "价格": "close", "price": "close",
    "最高": "high", "high": "high",
    "最低": "low", "low": "low",
    "均价": "avg_price", "avg_price": "avg_price",
    "成交量": "volume", "volume": "volume",
    "成交额": "amount", "amount": "amount",
}

# 新浪板块行情备源保留列（列名=目标名，纯过滤无翻译）
SECTOR_SINA_COLS = (
    "板块", "涨跌幅", "涨跌额", "总成交额", "总成交量", "公司家数", "平均价格",
)


def rename_present(df: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    """仅映射 df 中实际存在的列（其余列原样保留）——pandas rename 对
    不存在的键本就静默忽略，过滤版与全量版语义等价，统一走此单点。"""
    return df.rename(columns={k: v for k, v in mapping.items() if k in df.columns})
