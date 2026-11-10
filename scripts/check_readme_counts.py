"""README 计数 vs 实跑计数对比（批次D2②，确定性护栏）。

README badge / 正文宣称的 MCP 工具数、REST 端点数、注册表类型/注册数，
与代码实跑计数逐一对照（审计硬违规 #2/#3 的机械防线：README 77 端点残留、
badge REST-81 漏改、v3.9.1 计数笔误均为本脚本靶子）。

实跑口径：
  - MCP 工具数：AST 统计 tools/ 下 @mcp.tool 装饰器（同 tests/test_tools_total_count.py）
  - REST 端点数：FastAPI include 后 OpenAPI schema /api/v1 路径数（同 tests/test_rest_count.py）
  - 注册表：register_all_sources() 后 _sources 类型数 / 注册总数

用法：python scripts/check_readme_counts.py   → 0 一致 / 1 漂移
"""

from __future__ import annotations

import ast
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "tradex" / "src"


def count_mcp_tools() -> int:
    """AST 计数 tools/ 下 @mcp.tool(...) 装饰的函数总数。"""
    tools_dir = SRC / "tradex" / "tools"
    total = 0
    for path in sorted(tools_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for dec in node.decorator_list:
                    func = dec.func if isinstance(dec, ast.Call) else dec
                    if isinstance(func, ast.Attribute) and func.attr == "tool":
                        total += 1
    return total


def count_rest_endpoints() -> int:
    """OpenAPI schema 下 /api/v1 路径数（惰性 include 在此物化）。"""
    sys.path.insert(0, str(SRC))
    from fastapi import FastAPI

    from tradex.api import routes as rest_routes

    app = FastAPI(routes=[])
    app.include_router(rest_routes.router, prefix="/api/v1")
    schema = app.openapi()
    return sum(1 for p in schema["paths"] if p.startswith("/api/v1"))


def count_registry() -> tuple[int, int]:
    """(类型数, 注册总数)。"""
    sys.path.insert(0, str(SRC))
    from tradex.data_sources.registry import register_all_sources

    from astock_signals.smart_router import get_router

    register_all_sources()
    router = get_router()
    return len(router._sources), sum(len(v) for v in router._sources.values())


PATTERNS = [
    # (名称, README 提取正则, 实跑值 getter 名)
    ("badge REST", r"badge/REST-(\d+)-", "rest"),
    ("badge Endpoints", r"badge/Endpoints-(\d+)-", "rest"),
    ("数据类型（L34 句式）", r"(\d+) 个数据类型，(\d+) 个数据源注册", "types,regs"),
    ("MCP 工具数", r"(\d+) 个工具", "mcp"),
    ("REST 端点数", r"(\d+) 个端点", "rest"),
    ("REST 端点数（L136 紧凑现势）", r"(\d+) 端点，包裹响应", "rest"),
    ("全量路由图内计数", r"(\d+) 类型 / (\d+) 源", "types,regs"),
]


def main() -> int:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    real = {
        "mcp": count_mcp_tools(),
        "rest": count_rest_endpoints(),
        "types": count_registry()[0],
        "regs": count_registry()[1],
    }
    print(f"[i] 实跑计数: MCP={real['mcp']} REST={real['rest']} "
          f"类型={real['types']} 注册={real['regs']}")

    failures: list[str] = []
    for name, pat, keys in PATTERNS:
        want = keys.split(",")
        for m in re.finditer(pat, readme):
            claimed = [int(x) for x in m.groups()]
            expected = [real[k] for k in want]
            if claimed != expected:
                failures.append(
                    f"{name}: README 宣称 {claimed} != 实跑 {expected} "
                    f"(片段: {m.group(0)[:40]!r})"
                )
    if failures:
        print("[FAIL] README 计数漂移:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("[OK] README 计数与实跑一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
