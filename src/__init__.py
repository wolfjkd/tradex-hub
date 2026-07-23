# trader-finance-hub: AI投研数据底座
# 核心引擎: market_analyzer.py (新闻+THS+分析模型)
# 数据源管理: data_manager.py (多数据源自动降级)

__version__ = '2.4.0'

from .data_manager import (
    DataFetcherManager,
    DataProvider,
    EltdxDataProvider,
    TencentDataProvider,
    AkShareDataProvider,
    get_global_manager,
)

__all__ = [
    'DataFetcherManager',
    'DataProvider',
    'EltdxDataProvider',
    'TencentDataProvider',
    'AkShareDataProvider',
    'get_global_manager',
]
