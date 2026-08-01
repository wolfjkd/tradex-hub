"""
Pytest 共享 fixtures — tradex-hub 测试套件。
"""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock

# 确保 src 在 Python path 中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


@pytest.fixture
def mock_akshare(monkeypatch):
    """Mock akshare 模块（避免真实网络请求）。"""
    mock_ak = MagicMock()
    monkeypatch.setitem(sys.modules, "akshare", mock_ak)
    return mock_ak


@pytest.fixture
def sample_etf_df():
    """ETF 样例 DataFrame。"""
    import pandas as pd
    return pd.DataFrame({
        "代码": ["513500", "159915", "510300"],
        "名称": ["标普500ETF", "创业板ETF", "沪深300ETF"],
        "最新价": [1.850, 2.100, 4.200],
        "涨跌幅": [0.55, -0.30, 0.12],
        "成交量": [5000000, 3000000, 8000000],
        "成交额": [9250000, 6300000, 33600000],
        "换手率": [5.2, 3.1, 1.8],
    })


@pytest.fixture
def sample_cb_df():
    """可转债样例 DataFrame。"""
    import pandas as pd
    return pd.DataFrame({
        "债券代码": ["113527", "123121", "127060"],
        "债券简称": ["维格转债", "帝尔转债", "靖远转债"],
        "正股代码": ["603518", "300776", "000552"],
        "正股简称": ["锦泓集团", "帝尔激光", "靖远煤电"],
        "正股价": [8.50, 120.00, 5.80],
        "转股价": [8.00, 85.00, 6.50],
        "转股价值": [106.25, 141.18, 89.23],
        "债现价": [115.500, 180.000, 105.000],
        "转股溢价率": [8.70, 27.50, 17.67],
        "信用评级": ["AA", "AA-", "AA+"],
    })


@pytest.fixture
def tmp_tick_db(tmp_path):
    """临时 tick SQLite 数据库路径。"""
    return str(tmp_path / "test_ticks.db")


@pytest.fixture
def sample_tick_data():
    """样例 tick 数据。"""
    return [
        {"time": "09:30:01", "price": 1800.0, "volume": 100, "amount": 180000.0,
         "direction": "买", "bid1": 1799.90, "ask1": 1800.00},
        {"time": "09:30:02", "price": 1800.10, "volume": 200, "amount": 360020.0,
         "direction": "卖", "bid1": 1799.80, "ask1": 1800.10},
        {"time": "09:30:03", "price": 1799.90, "volume": 150, "amount": 269985.0,
         "direction": "买", "bid1": 1799.90, "ask1": 1800.00},
    ]
