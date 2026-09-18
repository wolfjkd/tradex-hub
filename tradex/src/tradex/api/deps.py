"""REST 层共享依赖（阶段一工单 01 占位）。

阶段一只占位，具体实现后续工单按需补：
- 认证（TRADEX_API_TOKEN）
- 限流（slowapi）
- 通用依赖注入
"""

from __future__ import annotations

import os


def is_auth_enabled() -> bool:
    """是否启用 API Token 认证（env TRADEX_API_TOKEN 非空则启用）。"""
    return bool(os.environ.get("TRADEX_API_TOKEN", "").strip())


def get_rate_limit_per_minute() -> int:
    """每分钟每 IP 限流次数（0=关闭，env TRADEX_RATE_LIMIT）。"""
    try:
        return int(os.environ.get("TRADEX_RATE_LIMIT", "0"))
    except ValueError:
        return 0
