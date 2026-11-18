"""A①+A② MCP 出口收拢契约快照（QI-ARCH-01/02，2026-11-18 试点 event_driven）。

**先于收拢写入**（硬闸背书：逐工具响应兼容 = 硬约定#3，出口信封形状是下游
TradeX 可见事实）。经 FastMCP.call_tool 走真实注册路径调用工具体——收拢
（工具体上提模块级 + mcp_serve 出口）**不改本文件一字仍全绿** = 逐工具响应
兼容背书；收拢后另加行为测试（import 打桩）在 test_event_driven_behavior.py。

形状（对照手抄原样）：
  成功：json.dumps(service_result, ensure_ascii=False) 逐字节
  失败：json.dumps({"error": True, "message": f"<文案> (<args>): {e}",
        "tool": "<工具名>"}, ensure_ascii=False)
"""

import json
from unittest.mock import patch

import pytest

from mcp.server.fastmcp import FastMCP

from tradex.service import event_service
from tradex.tools import event_driven as ev

# (工具名, 调用参数, service 函数名, 固定成功数据, 失败文案前缀)
_SNAPSHOT = [
    (
        "get_earnings_forecast",
        {"symbol": "600519", "report_date": "2024-12-31", "limit": 50},
        "get_earnings_forecast",
        {"items": [{"name": "贵州茅台", "type": "预增"}], "count": 1},
        "获取业绩预告失败 (600519)",
    ),
    (
        "get_institution_survey",
        {"symbol": "600519", "start_date": "", "end_date": "", "limit": 50},
        "get_institution_survey",
        {"items": [], "count": 0},
        "获取机构调研失败 (600519)",
    ),
    (
        "get_holder_trades",
        {"symbol": "600519", "direction": "增持", "start_date": "", "end_date": "", "limit": 50},
        "get_holder_trades",
        {"items": [{"holder": "张三"}]},
        "获取股东增减持失败 (600519)",
    ),
    (
        "get_share_buyback",
        {"symbol": "600519", "progress": "实施中", "limit": 50},
        "get_share_buyback",
        {"items": [], "count": 0},
        "获取股票回购失败 (600519)",
    ),
    (
        "get_equity_pledge",
        {"symbol": "600519", "date": "", "limit": 50},
        "get_equity_pledge",
        {"items": [{"ratio": 12.3}]},
        "获取股权质押失败 (600519)",
    ),
    (
        "get_ipo_calendar",
        {"start_date": "", "end_date": "", "limit": 50},
        "get_ipo_calendar",
        {"items": [{"code": "301999"}]},
        "获取新股日历失败",
    ),
]


async def _call_tool(name: str, args: dict):
    mcp = FastMCP("snapshot-compat")
    ev.register(mcp)
    return await mcp.call_tool(name, args)


def _text(result) -> str:
    """call_tool 返回（tuple: (contents, meta)）取首个 TextContent 文本。"""
    contents = result[0] if isinstance(result, tuple) else result
    return contents[0].text


class TestEventDrivenSnapshot:
    """逐工具响应兼容快照（收拢前后同形状，本文件收拢时不改）。"""

    @pytest.mark.parametrize(
        "tool,args,svc,fixture,fail_prefix", _SNAPSHOT, ids=[s[0] for s in _SNAPSHOT]
    )
    async def test_success_path(self, tool, args, svc, fixture, fail_prefix):
        with patch.object(event_service, svc, return_value=fixture):
            out = _text(await _call_tool(tool, dict(args)))
        assert out == json.dumps(fixture, ensure_ascii=False), (
            f"{tool} 成功路径快照不符：{out[:120]}"
        )

    @pytest.mark.parametrize(
        "tool,args,svc,fixture,fail_prefix", _SNAPSHOT, ids=[s[0] for s in _SNAPSHOT]
    )
    async def test_error_path(self, tool, args, svc, fixture, fail_prefix):
        def _boom(*a, **kw):
            raise RuntimeError("boom")

        with patch.object(event_service, svc, side_effect=_boom):
            out = _text(await _call_tool(tool, dict(args)))
        expected = json.dumps(
            {"error": True, "message": f"{fail_prefix}: boom", "tool": tool},
            ensure_ascii=False,
        )
        assert out == expected, f"{tool} 失败路径快照不符：{out[:120]}"

    async def test_dual_branch_value_error_semantics(self):
        """A① 全量补（2026-11-19）：双 except 分支工具的 ValueError 语义——
        value_error_detail 参数承载「参数错误」文案（原手抄形态逐字节等价）。"""
        from unittest.mock import patch as _patch

        from tradex.data_sources import em_client

        client = await _make_client()

        def _ve(*a, **kw):
            raise ValueError("date 越界")

        with _patch.object(em_client, "fetch_unusual_fluctuation", side_effect=_ve):
            out = _text(
                await client.call_tool(
                    "get_unusual_fluctuation", {"trade_date": "2026-13-01"}
                )
            )
        expected = json.dumps(
            {"error": True, "message": "参数错误: date 越界", "tool": "get_unusual_fluctuation"},
            ensure_ascii=False,
        )
        assert out == expected, f"ValueError 分支快照不符：{out[:120]}"

    async def test_dual_branch_generic_error_semantics(self):
        """双 except 工具的非 ValueError 走 fail_detail 主文案。"""
        from unittest.mock import patch as _patch

        from tradex.data_sources import em_client

        client = await _make_client()

        def _boom(*a, **kw):
            raise RuntimeError("em 挂了")

        with _patch.object(em_client, "fetch_unusual_fluctuation", side_effect=_boom):
            out = _text(
                await client.call_tool("get_unusual_fluctuation", {"trade_date": ""})
            )
        expected = json.dumps(
            {"error": True, "message": "获取监管异动失败: em 挂了", "tool": "get_unusual_fluctuation"},
            ensure_ascii=False,
        )
        assert out == expected, f"Exception 分支快照不符：{out[:120]}"


async def _make_client():
    mcp = FastMCP("snapshot-compat-dual")
    ev.register(mcp)
    return mcp
