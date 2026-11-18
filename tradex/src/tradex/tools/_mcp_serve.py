"""MCP 出口样板单点（QI-ARCH-01，2026-11-18 质检整改施工）。

REST 侧 serve_envelope 同款深化（2026-11-11 拍板统一 REST 错误语义）落到
MCP 侧：工具体「try/服务调用 → json.dumps / except → error_response」手抄
（197 处，两套信封词汇并存）收敛为 mcp_serve 一个出口接缝。

**兼容硬闸（硬约定#3）**：出口信封形状是下游 TradeX 可见事实——mcp_serve
的成功/失败路径返回字符串与原手抄形态逐字节等价（契约快照背书：
tests/test_mcp_serve_compat.py 收拢前写入锁定，收拢后不改仍绿）：

  成功：json.dumps(result, ensure_ascii=False)
  失败：json.dumps({"error": True, "message": f"{fail_detail}: {e}",
        "tool": tool_name}, ensure_ascii=False)
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from ..utils.formatter import error_response


def mcp_serve(
    tool_name: str,
    build: Callable[[], Any],
    fail_detail: str,
    *,
    value_error_detail: str | None = None,
    dump: bool = True,
) -> str:
    """MCP 工具体出口单点。

    Args:
        tool_name: 工具名（error_response 的 tool 字段）
        build: 服务调用回调（无参），返回可 JSON 序列化对象
        fail_detail: 失败文案固定前缀（调用方拼好参数回显，如
            f"获取业绩预告失败 ({symbol})"）——出口统一拼 ": {e}"，
            与原手抄 f"{前缀}: {e}" 逐字节等价
        value_error_detail: （A① 全量补，2026-11-19）可选——双 except 分支
            工具（原「except ValueError → '参数错误' / except Exception →
            '获取XX失败'」形态）的 ValueError 分支文案前缀；None 时
            ValueError 与其他异常同走 fail_detail（单分支工具行为不变）
        dump: True = json.dumps（默认，原 62 处 dumps 形态）；False = 原样
            返回 build() 的 str 结果（df_to_json 等自带格式化形态），
            失败路径仍走 error_response

    Returns:
        工具体应返回的 JSON 字符串
    """
    try:
        result = build()
        if dump:
            return json.dumps(result, ensure_ascii=False)
        return result
    except ValueError as e:  # noqa: BLE001 - MCP 出口统一 error_response 形态
        detail = value_error_detail if value_error_detail is not None else fail_detail
        return error_response(f"{detail}: {e}", tool_name)
    except Exception as e:  # noqa: BLE001
        return error_response(f"{fail_detail}: {e}", tool_name)
