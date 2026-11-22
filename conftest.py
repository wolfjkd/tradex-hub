"""Pytest 共享 fixtures — tradex-hub 全仓单点（QI-ARCH-12，2026-11-22 两树合并）。

原双树 conftest（tests/conftest.py 80 行 + tradex/tests/conftest.py 48 行）合并此单点：
- sys.path 注入 <root>/tradex/src 单点（原两份同目标不同拼法）；
- `_tool_visibility_full` autouse 原两份逐字节同款手抄 → 收敛一份；
- `_ensure_sources_registered` autouse 原 tradex/tests 树专属 → 以 request.path
  守卫锁作用域（非 tradex/tests 用例直接 return），逐用例行为与合并前等价；
- 树专属 fixture（mock_akshare / sample_etf_df / sample_cb_df / tmp_tick_db /
  sample_tick_data / sample_symbols / mcp_server）上收全仓可见——现无用例请求
  不可解析 fixture，可见性扩大零解析变化。

import 模式不变（合并只动 conftest，不动模块命名/收集面）：
- tests/ 无 __init__.py → rootless，模块名 test_*，pytest prepend <root>/tests；
- tradex/tests/ 有 __init__.py → 包名 tests（包根 tradex/，pytest prepend
  <root>/tradex），REST 测试经 `from tests._rest_test_base import` 用基座；
- 两树 test 文件 basename 零冲突（2026-11-22 comm 实测）。
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# 确保 tradex/src 在 Python path 中（v3.3.9+：原指向根 src/ 空目录，已修正）。
# 根 src/astock_signals 已并入 tradex/src/，运行包经 editable 安装或此处注入均可。
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "tradex", "src"))

# tradex/tests 树根（_ensure_sources_registered 的作用域守卫锚点）
_TRADEX_TESTS_ROOT = Path(__file__).resolve().parent / "tradex" / "tests"


@pytest.fixture(autouse=True)
def _tool_visibility_full(monkeypatch):
    """测试默认关闭工具可见性过滤（MCP_TOOL_PROFILE 指向不存在路径），
    保证 test_server/test_tools_total_count 等工具数基线断言与本地 profile 无关；
    可见性专项测试自行覆盖此 env。（原双树 conftest 同款手抄，QI-ARCH-12 收敛单点。）"""
    monkeypatch.setenv("MCP_TOOL_PROFILE", "Z:/__no_such_profile__.json")


@pytest.fixture(autouse=True)
def _ensure_sources_registered(request):
    """v3.1.0：确保 SmartRouter 注册全部数据源（作用域锁 tradex/tests 树）。

    架构变更后 L1 工具通过 SmartRouter.route() 获取数据，
    若注册表为空会抛 "No data source registered" 错误。
    register_all_sources() 内部幂等（_registered 标记），重复调用安全。

    QI-ARCH-12 合并注记：原 fixture 只定义在 tradex/tests/conftest.py（目录作用域），
    移根后加 request.path 守卫保持逐用例等价——tests/ 树用例不触发注册副作用。
    """
    if not request.path.is_relative_to(_TRADEX_TESTS_ROOT):
        return
    from tradex.data_sources import register_all_sources
    register_all_sources()


# ---- 原 tests/conftest.py 树专属 fixtures（上收全仓可见） ----


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
        "债券简称": ["维格转债", "帝尔转债", "靖远煤电"],
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


# ---- 原 tradex/tests/conftest.py 树专属 fixtures（上收全仓可见） ----


@pytest.fixture
def sample_symbols():
    """Common test stock symbols."""
    return {
        "pingan": "000001",      # 平安银行 (Shenzhen main)
        "moutai": "600519",      # 贵州茅台 (Shanghai main)
        "catl": "300750",        # 宁德时代 (ChiNext)
        "smic": "688981",        # 中芯国际 (STAR)
    }


@pytest.fixture
def mcp_server():
    """Get the MCP server instance with all tools registered."""
    from tradex.server import mcp
    return mcp
