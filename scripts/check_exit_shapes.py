"""MCP 出口形态机械核验挂门（QI-RETRO-02，QI-ARCH-17/19/20 根治）。

「出口形态 × 书面豁免」一致性由门机械核验。惯犯①「文档账漂移」三次同类
发现（QI-ARCH-19 手写出口实况 9 vs 书面 4、QI-ARCH-20 dashboard 文档称手写
实况已走 mcp_serve、QI-ARCH-17 eltdx_data 31 工具批外无书面豁免）此前全靠
人肉巡检发现——本脚本 AST 枚举全部 @mcp.tool 注册工具的出口形态，与
docs/EXEMPTIONS.md 表一（唯一真源，运行时解析 MD 行）比对，漂移即 exit 1。

枚举口径（AST 静态，注册形态全覆盖）：
  - 模块级工具体 + register 内引用注册（for 循环 `mcp.tool()(_fn)` /
    直呼 `mcp.tool()(fn)`）；
  - register 内嵌套 `@mcp.tool()` / `@mcp.tool` 闭包（eltdx_data/tdx_mcp 形态）；
  - 模块级 @mcp.tool 装饰（现状零使用，防御性支持）；
  - 同模块多份 `def register` 按 Python 遮蔽语义合并去重（event_driven.py
    历史双 register 实况）；出口形态 = 工具体是否调用 mcp_serve：
    mcp_serve / 手写（handwritten）。

比对口径（双向）：
  - AST 手写出口 → 表一：手写工具所在文件必须有表一行覆盖（单工具行点名
    或「组 N 工具」行计数相等），否则红（新增手写未登记）；
  - 表一 → AST：登记的单工具名必须实况存在且仍为手写，组行计数必须与
    实况手写数相等，否则红（漂移 → 提示清理豁免行）；
  - 已知批外类（表一头部口径注释承载）：eltdx_data.py（31 工具未上提，
    QI-ARCH-17，票 07 施工后必须过本门）、tdx_mcp.py（自有骨架 3 工具）——
    门内白名单只落指针；动这两处先改表一头部再改这里。

用法：python scripts/check_exit_shapes.py [--list]  →  退出码 0 一致 / 1 漂移
  --list  打印全量工具三列清单（工具名 / 出口形态 / 所在文件:行号）后仍按
          比对结果给退出码（人工核对台账用）。
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = ROOT / "tradex" / "src" / "tradex" / "tools"
EXEMPTIONS_MD = ROOT / "docs" / "EXEMPTIONS.md"

# 已知批外类（唯一真源 = EXEMPTIONS.md 表一头部口径注释；这里只落指针）
KNOWN_BATCH_EXEMPT = {
    "eltdx_data.py": "QI-ARCH-17：31 工具未上提，票 07 施工后必须过本门",
    "tdx_mcp.py": "tdx_mcp 自有骨架 3 工具（表一头部口径）",
}

_GROUP_RE = re.compile(r"组\s*(\d+)\s*工具")


@dataclass
class ToolExit:
    file: str
    name: str
    shape: str  # "mcp_serve" | "handwritten"
    line: int


def _call_name(node: ast.AST) -> str | None:
    """点分调用名（mcp.tool / mcp_serve 等），非 Name/Attribute 返回 None。"""
    if isinstance(node, ast.Attribute):
        base = _call_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def _is_mcp_tool_decorator(dec: ast.AST) -> bool:
    """@mcp.tool 或 @mcp.tool()（裸 Attribute 或包一层 Call）。"""
    if isinstance(dec, ast.Call):
        dec = dec.func
    dn = _call_name(dec)
    return dn is not None and dn.startswith("mcp.tool")


def _contains_mcp_serve(fn: ast.AST) -> bool:
    """工具体内是否有 mcp_serve(...) 调用。"""
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            nm = _call_name(n.func)
            if nm == "mcp_serve" or (nm is not None and nm.endswith(".mcp_serve")):
                return True
    return False


def _iter_names(node: ast.AST) -> list[str]:
    """（可嵌套）元组/列表字面量里的 Name 集合。"""
    out: list[str] = []
    if isinstance(node, ast.Name):
        out.append(node.id)
    elif isinstance(node, (ast.Tuple, ast.List)):
        for e in node.elts:
            out.extend(_iter_names(e))
    return out


def enumerate_tool_exits(tools_dir: Path) -> tuple[list[ToolExit], list[str]]:
    """AST 枚举工具出口，返回 (工具列表, 异常报告行)。

    异常报告行 = 无法定形的引用注册名 + 同 (file, name) 形态冲突（正常应为空）。
    """
    tools: dict[tuple[str, str], ToolExit] = {}
    anomalies: list[str] = []

    for f in sorted(tools_dir.glob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8", errors="ignore"))
        module_funcs = {
            n.name: n
            for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

        def classify(file: str, name: str, fn: ast.AST, line: int) -> None:
            shape = "mcp_serve" if _contains_mcp_serve(fn) else "handwritten"
            key = (file, name)
            if key in tools and tools[key].shape != shape:
                anomalies.append(
                    f"{file}:{line} 工具 {name} 同名双定义形态冲突（{tools[key].shape} vs {shape}）"
                )
                return
            tools[key] = ToolExit(file, name, shape, line)

        registers = [
            n
            for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "register"
        ]
        for reg in registers:
            loop_vars: set[str] = set()
            for n in ast.walk(reg):
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n is not reg:
                    for dec in n.decorator_list:
                        if _is_mcp_tool_decorator(dec):
                            classify(f.name, n.name, n, n.lineno)
                elif isinstance(n, ast.For):
                    # for _fn in (a, b, ...): mcp.tool()(_fn)
                    for tv in ast.walk(n.target):
                        if isinstance(tv, ast.Name):
                            loop_vars.add(tv.id)
                    has_reg = any(
                        isinstance(c, ast.Call)
                        and (
                            (isinstance(c.func, ast.Call) and _call_name(c.func.func) == "mcp.tool")
                            or (not isinstance(c.func, ast.Call) and _call_name(c.func) == "mcp.tool")
                        )
                        for c in ast.walk(n)
                    )
                    if has_reg:
                        for nm in _iter_names(n.iter):
                            if nm in module_funcs:
                                fn = module_funcs[nm]
                                classify(f.name, nm, fn, fn.lineno)
                            else:
                                anomalies.append(f"{f.name}: 引用注册 `{nm}` 非本模块定义，AST 无法定形")
                elif isinstance(n, ast.Call):
                    target = n.func
                    direct = None
                    if isinstance(target, ast.Call) and _call_name(target.func) == "mcp.tool":
                        direct = n
                    elif not isinstance(target, ast.Call) and _call_name(target) == "mcp.tool":
                        direct = n
                    if direct is not None:
                        for arg in n.args:
                            if isinstance(arg, ast.Name):
                                if arg.id in loop_vars:
                                    continue  # 注册循环体调用，For 分支已按 iter 解析
                                if arg.id in module_funcs:
                                    fn = module_funcs[arg.id]
                                    classify(f.name, arg.id, fn, fn.lineno)
                                else:
                                    anomalies.append(f"{f.name}: 引用注册 `{arg.id}` 非本模块定义，AST 无法定形")
        # 模块级 @mcp.tool 装饰（register 之外，现状零使用防御性支持）
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name != "register":
                for dec in node.decorator_list:
                    if _is_mcp_tool_decorator(dec):
                        classify(f.name, node.name, node, node.lineno)

    return list(tools.values()), anomalies


def parse_table1(md_path: Path) -> list[tuple[str, str]]:
    """解析 EXEMPTIONS.md 表一 MD 行，返回 [(工具格, 文件格)]。"""
    rows: list[tuple[str, str]] = []
    in_table = False
    for line in md_path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("## 表一"):
            in_table = True
            continue
        if not in_table:
            continue
        if s.startswith("## "):
            break  # 下一节
        if not s.startswith("|"):
            if rows:
                break  # 表体结束（核验纪律段）
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 2 or not cells[0] or cells[0] == "工具":
            continue  # 表头行/空行
        if set(cells[0]) <= set("-: "):
            continue  # 分隔行
        rows.append((cells[0], cells[1]))
    return rows


def main(argv: list[str] | None = None) -> int:
    """argv 显式传 [] 供进程内调用（guard test 裸传参会误读 pytest argv）。"""
    parser = argparse.ArgumentParser(description="MCP 出口形态 × EXEMPTIONS 表一机械核验")
    parser.add_argument("--list", action="store_true", help="打印全量工具三列清单")
    args = parser.parse_args(argv)

    tools, anomalies = enumerate_tool_exits(TOOLS_DIR)
    by_file: dict[str, dict[str, ToolExit]] = {}
    for t in tools:
        by_file.setdefault(t.file, {})[t.name] = t

    violations: list[str] = []

    if args.list:
        print(f"{'工具名':<40} {'出口形态':<12} 所在文件:行号")
        for t in sorted(tools, key=lambda x: (x.file, x.line)):
            print(f"{t.name:<40} {t.shape:<12} {t.file}:{t.line}")

    # A) AST 手写出口 → 表一：未登记即红（已知批外类除外）
    for file, tools_d in sorted(by_file.items()):
        hand = {n for n, t in tools_d.items() if t.shape == "handwritten"}
        if not hand or file in KNOWN_BATCH_EXEMPT:
            continue
        rows = [(tc, fc) for tc, fc in parse_table1(EXEMPTIONS_MD) if fc == file]
        if not rows:
            violations.append(
                f"手写出口未登记：{file} 手写 {len(hand)} 工具（{', '.join(sorted(hand))}）"
                "——先登记 docs/EXEMPTIONS.md 表一并经老板确认，否则门红"
            )

    # B) 表一 → AST：登记漂移即红（提示清理豁免）
    expected: dict[str, dict] = {}
    for tc, fc in parse_table1(EXEMPTIONS_MD):
        entry = expected.setdefault(fc, {"names": set(), "group": 0})
        m = _GROUP_RE.search(tc)
        if m:
            entry["group"] += int(m.group(1))
        else:
            entry["names"].add(tc)

    for file, exp in sorted(expected.items()):
        tools_d = by_file.get(file, {})
        hand = {n for n, t in tools_d.items() if t.shape == "handwritten"}
        for n in sorted(exp["names"] - hand):
            t = tools_d.get(n)
            if t is None:
                violations.append(f"表一登记工具不存在：{file} 的 `{n}`——查改名/删除并清理豁免行")
            else:
                violations.append(f"表一登记漂移：{file} 的 `{n}` 实况已走 {t.shape}——实况正确请清理豁免行")
        extra = hand - exp["names"]
        if len(extra) != exp["group"]:
            violations.append(
                f"表一组行计数漂移：{file} 实况手写 {sorted(extra)}（{len(extra)} 个）"
                f" vs 组行登记 {exp['group']} 个——补登记或清理豁免"
            )

    violations.extend(anomalies)

    n_serve = sum(1 for t in tools if t.shape == "mcp_serve")
    n_hand = len(tools) - n_serve
    n_exempt = sum(
        len({n for n, t in d.items() if t.shape == "handwritten"})
        for f, d in by_file.items()
        if f in KNOWN_BATCH_EXEMPT
    )

    if violations:
        print(f"[FAIL] MCP 出口形态 × EXEMPTIONS 表一漂移 {len(violations)} 处：")
        for v in violations:
            print(f"  - {v}")
        print(f"（AST 实测：{len(tools)} 工具 = {n_serve} mcp_serve + {n_hand} 手写，其中批外类 {n_exempt} 个）")
        print("口径：手写出口必须先登记 EXEMPTIONS.md 表一并经老板确认；已收拢的工具同步清理豁免行。")
        return 1

    print(
        f"[OK] MCP 出口形态与 EXEMPTIONS 表一一致（AST 实测 {len(tools)} 工具 = "
        f"{n_serve} mcp_serve + {n_hand} 手写，批外类 {n_exempt} 个待上提/自有骨架）"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
