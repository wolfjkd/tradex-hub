"""全源码 import × pyproject 声明依赖比对（Issue #2 确定性护栏）。

「靠传递依赖侥幸可用」三连（prometheus_client 2026-11-08 新机 uv sync 暴露、
httpx/curl_cffi 2026-11-14 由 Issue #2 用户反馈触发全量审计暴露）的机械防线：
扫 tradex/src/ 两包全部 .py 的 import 语句（**含函数内惰性**——curl_cffi 即
函数内漏网形态），对照 [project].dependencies + 全部 extras 声明集。

判定规则：
  - 白名单包 + 模块顶层裸 import        → FAIL（可选依赖丢了降级保护，新装必炸）
  - 非白名单 + 模块顶层裸 import        → FAIL（新装必炸形态，最严重）
  - 非白名单 + 惰性/try 保护            → FAIL（防新增漏网，需显式决策：补声明或进白名单）
  - 白名单包 + 惰性/try 保护            → 通过（设计内可选依赖）

白名单（设计内可选依赖，import 点已受 try/ImportError 保护，未装时功能降级）：
  baostock   baostock_fetchers.py 顶层 try，失败置 _BAOSTOCK_AVAILABLE=False 返回空
  mootdx     indicators._load_ohlcv_mootdx 函数内 try，仅 source="mootdx" 才走
  pyarrow    akshare_fetchers._is_arrow_escape_invalid 函数内 try，仅 isinstance
             精判用，except ImportError 走类型名兜底

比对口径：PyPI 名 PEP 503 归一（-_. 统一、小写）+ 剥 python- 前缀双候选
（python-dotenv↔dotenv、python-calamine↔calamine）；同仓包 tradex/astock_signals
（与 hatch wheel packages 对齐）及相对 import 跳过。已知边界：类体内 import 按
「新漏网」FAIL（类体在模块加载时执行，仅标签不如顶层裸 import 精确，不放过）。

用法：python scripts/check_undeclared_imports.py  → 退出码 0 全声明 / 1 有漏网
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_ROOTS = [ROOT / "tradex" / "src" / "tradex", ROOT / "tradex" / "src" / "astock_signals"]

# 设计内可选依赖（见模块 docstring 三条依据）；新增需在此写明降级依据
WHITELIST = {"baostock", "mootdx", "pyarrow"}

# 同仓包（与 [tool.hatch.build.targets.wheel] packages 对齐），import 自身非第三方
SELF_PACKAGES = {"tradex", "astock_signals"}


def _norm(name: str) -> str:
    """PEP 503 归一：连续 -_. 折叠为 -、小写。"""
    return re.sub(r"[-_.]+", "-", name).strip().lower()


@dataclass
class ImportSpot:
    module: str  # 顶层模块名
    top_level: bool  # 位于模块体顶层（不在任何复合语句体内）
    protected: bool  # 惰性（函数/lambda 体内）或祖先链有 try——非模块加载即执行
    file: Path
    line: int


def _collect_imports(path: Path) -> list[ImportSpot]:
    """AST 收集单文件的绝对 import（相对 import 跳过），带位置上下文。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        return []

    spots: list[ImportSpot] = []

    def walk(node: ast.AST, top_level: bool, in_try: bool, in_func: bool) -> None:
        for child in ast.iter_child_nodes(node):
            # 仅 Module 的直接子语句算模块顶层；try/函数上下文向下传播
            c_top = top_level and isinstance(node, ast.Module)
            c_try = in_try or isinstance(child, ast.Try)
            c_func = in_func or isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
            protected = c_try or c_func

            if isinstance(child, ast.Import):
                for alias in child.names:
                    spots.append(ImportSpot(alias.name.split(".")[0], c_top, protected, path, child.lineno))
            elif isinstance(child, ast.ImportFrom) and child.level == 0 and child.module:
                spots.append(ImportSpot(child.module.split(".")[0], c_top, protected, path, child.lineno))

            walk(child, c_top, c_try, c_func)

    walk(tree, top_level=True, in_try=False, in_func=False)
    return spots


def _declared_candidates(pyproject: dict) -> set[str]:
    """声明集 → import 名候选（PyPI 归一 + 剥 python- 前缀）。"""
    project = pyproject.get("project", {})
    reqs = list(project.get("dependencies", []))
    for group in (project.get("optional-dependencies", {}) or {}).values():
        reqs.extend(group)
    names = {_norm(re.split(r"[<>=!~;\[]", r.strip(), maxsplit=1)[0]) for r in reqs}
    return names | {n.removeprefix("python-") for n in names}


def find_violations(
    src_roots: list[Path], declared: set[str]
) -> list[tuple[str, str, list[str]]]:
    """核心判定：返回 (标签, 模块名, 位置列表)，空列表 = 全声明。

    位置为「文件:行」原文（不含相对化——相对显示归 main，函数保持可复用/可测）。
    """
    seen: dict[tuple[str, bool, bool], list[str]] = {}

    for root in src_roots:
        for f in sorted(root.rglob("*.py")):
            for spot in _collect_imports(f):
                if spot.module in SELF_PACKAGES:
                    continue
                if spot.module in sys.stdlib_module_names:
                    continue
                if _norm(spot.module) in declared:
                    continue
                key = (spot.module, spot.top_level, spot.protected)
                seen.setdefault(key, [])
                seen[key].append(f"{spot.file.as_posix()}:{spot.line}")

    violations: list[tuple[str, str, list[str]]] = []
    for (module, top_level, protected), locs in sorted(seen.items()):
        if module in WHITELIST:
            if top_level and not protected:
                violations.append(("白名单失效", module, locs))
        elif top_level and not protected:
            violations.append(("必炸形态", module, locs))
        else:
            violations.append(("新漏网", module, locs))
    return violations


def main() -> int:
    pyproject = tomllib.loads((ROOT / "tradex" / "pyproject.toml").read_text(encoding="utf-8"))
    declared = _declared_candidates(pyproject)
    violations = find_violations(SRC_ROOTS, declared)

    if not violations:
        print(f"[OK] 全源码 import 均已声明（白名单可选依赖 {len(WHITELIST)} 个）")
        return 0

    def _rel(loc: str) -> str:
        p, _, line = loc.rpartition(":")
        try:
            return f"{Path(p).relative_to(ROOT).as_posix()}:{line}"
        except ValueError:
            return loc

    print(f"[FAIL] 发现 {len(violations)} 处 import 未声明（传递依赖侥幸形态）：")
    for tag, module, locs in violations:
        print(f"  - [{tag}] `{module}`: {', '.join(_rel(x) for x in locs)}")
    print(
        "处置：补进 pyproject+requirements 双处（check_dep_sync 会跟检），"
        "或确认属设计内可选依赖后写入 WHITELIST 并注明降级依据。"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
