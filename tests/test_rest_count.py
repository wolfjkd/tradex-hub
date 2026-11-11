"""REST 端点计数断言（批次D2③）。

Spec 轴发现：MCP/类型/注册计数有 63 个断言护着，REST 81→82 全靠手改
——badge 81 就是这么漏的。本测试把 REST 端点数纳入计数断言家族。

口径：FastAPI include 后 OpenAPI schema /api/v1 前缀路径数（与
scripts/check_readme_counts.py 同口径）。计数变化（加/删端点）时：
同步更新此处断言、README badge/正文、CHANGELOG 计数行——四处一体。
"""

import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "tradex" / "src"))


def _rest_path_count() -> int:
    from fastapi import FastAPI

    from tradex.api import routes as rest_routes

    app = FastAPI(routes=[])
    app.include_router(rest_routes.router, prefix="/api/v1")
    schema = app.openapi()
    return sum(1 for p in schema["paths"] if p.startswith("/api/v1"))


class TestRestEndpointCount:
    def test_rest_endpoint_count(self):
        """REST 端点数护栏：83（2026-11-11 裁决①：+GET /macro/index-constituents）。"""
        assert _rest_path_count() == 83
