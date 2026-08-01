"""
Shared test fixtures for tradex tests.
"""

import sys
from pathlib import Path

import pytest

# Add src to path so tests can import tradex
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture(autouse=True)
def _ensure_sources_registered():
    """v3.1.0：确保 SmartRouter 注册全部数据源。

    架构变更后 L1 工具通过 SmartRouter.route() 获取数据，
    若注册表为空会抛 "No data source registered" 错误。
    register_all_sources() 内部幂等（_registered 标记），重复调用安全。
    """
    from tradex.data_sources import register_all_sources
    register_all_sources()


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
