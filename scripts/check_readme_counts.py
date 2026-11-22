"""README 计数 vs 实跑计数对比（批次D2②，确定性护栏）。

README badge / 正文宣称的 MCP 工具数、REST 端点数、注册表类型/注册数，
与代码实跑计数逐一对照（审计硬违规 #2/#3 的机械防线：README 77 端点残留、
badge REST-81 漏改、v3.9.1 计数笔误均为本脚本靶子）。

实跑口径：
  - MCP 工具数：注册过程衍生（实例化 FastMCP 走真实注册路径数 _tools，
    同 tests/test_tools_total_count.py；QI-ARCH-02/06，2026-11-18——工具体
    上提模块级后无装饰器可数，AST 账本已退役）
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


def _register_all_tools_full(mcp) -> dict:
    """发现并注册全部工具（跳过 signal_data_* 兼容子模块防重复），不做
    profile 可见性过滤（本机 config/mcp_tool_profile.json=lean 会隐藏 75 个，
    计数须与 profile 无关）。返回 {工具名: tool}。"""
    import importlib
    import pkgutil

    import tradex.tools as tools_pkg

    for _, mod_name, _ in pkgutil.iter_modules(tools_pkg.__path__):
        if mod_name.startswith("signal_data_"):
            continue  # 由 signal_data 兼容入口统一注册，避免重复
        mod = importlib.import_module(f"{tools_pkg.__name__}.{mod_name}")
        if hasattr(mod, "register"):
            mod.register(mcp)
    return mcp._tool_manager._tools


def count_mcp_tools() -> int:
    """MCP 工具数：注册过程衍生计数（QI-ARCH-02/06，2026-11-18）。

    原 AST 数 @mcp.tool() 装饰器——工具体上提模块级后装饰器消失
    （event_driven 试点实证掉数 192→187），改注册衍生（profile 无关全量）。
    """
    sys.path.insert(0, str(SRC))
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("guard-count")
    return len(_register_all_tools_full(mcp))


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
    ("badge Tools", r"badge/Tools-(\d+)-", "mcp"),
    ("数据类型（L34 句式）", r"(\d+) 个数据类型，(\d+) 个数据源注册", "types,regs"),
    ("MCP 工具数", r"(\d+) 个工具", "mcp"),
    ("REST 端点数", r"(\d+) 个端点", "rest"),
    ("REST 端点数（L136 紧凑现势）", r"(\d+) 端点，包裹响应", "rest"),
    ("全量路由图内计数", r"(\d+) 类型 / (\d+) 源", "types,regs"),
    # —— 2026-11-18 QI-STD-02 补：六处计数漂移全漏的结构性盲区（惯犯 #9 防再犯）——
    # L25 简介句式（数字与名词之间夹「MCP/REST」词——原「个工具/个端点」正则抓不到）
    ("MCP 工具数（L25 夹词）", r"(\d+) 个 MCP 工具", "mcp"),
    ("REST 端点数（L25 夹词）", r"(\d+) 个 REST 端点", "rest"),
    # L281 REST 段首句（同夹词形态；与 L25 pattern 重叠属冗余护栏——宁重叠不漏抓）
    ("REST 端点数（L281 夹词）", r"(\d+) 个 REST 端点统一挂在", "rest"),
    # L246 清单标题（括号计数）
    ("MCP 工具清单标题", r"MCP 工具清单（(\d+) 个）", "mcp"),
    # L371 Prometheus 指标注释
    ("Prometheus 工具计数注记", r"已注册 MCP 工具数（(\d+)，随工具可见性", "mcp"),
    # L491 冒烟示例输出
    ("冒烟示例 tools 字段", r'"tools":(\d+)', "mcp"),
    # L516 工具可见性全量口径
    ("工具可见性全量口径", r"缺失 = 全量 (\d+)", "mcp"),
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
