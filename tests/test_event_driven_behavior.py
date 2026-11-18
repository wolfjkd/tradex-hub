"""A② 行为测试（QI-ARCH-02，2026-11-18 试点）：工具体上提模块级后可直接
import 打桩——替代原「AST 数 @mcp.tool() 字符串」形态（替身测替身）。

响应形状契约由 test_mcp_serve_compat.py 背书（收拢前后逐字节等价），
本文件验证行为语义（mock service → 断言出口 JSON 内容）。
"""

import json
from unittest.mock import patch

from tradex.service import event_service
from tradex.tools.event_driven import (
    get_earnings_forecast,
    get_holder_trades,
    get_institution_survey,
)


class TestEventDrivenBehavior:
    """模块级工具体直接调用（不经 FastMCP 注册路径）。"""

    async def test_direct_import_stub_success(self):
        with patch.object(
            event_service, "get_earnings_forecast", return_value={"items": [1]}
        ):
            out = await get_earnings_forecast(symbol="600519")
        assert json.loads(out) == {"items": [1]}

    async def test_direct_import_stub_error(self):
        def _boom(*a, **kw):
            raise RuntimeError("net down")

        with patch.object(event_service, "get_earnings_forecast", side_effect=_boom):
            out = await get_earnings_forecast(symbol="600519")
        d = json.loads(out)
        assert d["error"] is True
        assert d["message"] == "获取业绩预告失败 (600519): net down"
        assert d["tool"] == "get_earnings_forecast"

    async def test_kwargs_passthrough(self):
        """调用参数原样透传 service（行为测试核心价值）。"""
        seen = {}

        def _fake(*a, **kw):
            seen.update(kw)
            return {}

        with patch.object(event_service, "get_holder_trades", side_effect=_fake):
            await get_holder_trades(symbol="000001", direction="增持", limit=10)
        assert seen["symbol"] == "000001"
        assert seen["direction"] == "增持"
        assert seen["limit"] == 10
