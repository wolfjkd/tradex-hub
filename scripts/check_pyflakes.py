"""pyflakes F821 未定义名全仓扫描（QI-RETRO-03 确定性护栏）。

QI-BUG-01（fetch_profit_forecast 内 prefix NameError 被组合函数 except 吞成
valuation_note，潜伏数月）与 A⑨ 拆分期间 pyflakes 临时护航实抓 9 处搬运缺漏
共同证明：未定义名类编程错误必须由门机械拦截，不再依赖人肉临时护航。

门口径（信噪比裁决，2026-11-22 施工记录）：
  - 门红条件 = F821 未定义名（pyflakes UndefinedName / UndefinedLocal /
    UndefinedExport 三形态，即 flake8 F821 全集）——NameError 级编程错误，
    零容忍（含语法错误文件：解析失败则 F821 无法核验，同样门红）；
  - 其余告警（F401 unused import、F841 unused variable、f-string 无插值等
    存量 270+ 处）**不挂门**——多为风格/卫生类，挂上即门长红失去信噪比；
    存量清单记台账 QI-BUG-02，另行排单清理，不在本门拦截。

扫描范围：tradex/src（tradex + astock_signals 两包）+ tests + tradex/tests
+ scripts（含 _retired——退役脚本若有 F821 同样门红，退役 ≠ 带病）。
依赖：pyflakes（pyproject dev extra 声明；venv 缺失时门红并提示安装）。

用法：python scripts/check_pyflakes.py  →  退出码 0 零 F821 / 1 有未定义名
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = [
    ROOT / "tradex" / "src",
    ROOT / "tests",
    ROOT / "tradex" / "tests",
    ROOT / "scripts",
]


def find_undefined_names(scan_roots: list[Path]) -> list[str]:
    """扫描 .py 文件返回 F821 报告行列表，空列表 = 零告警。

    位置为「文件:行」相对仓库根（与 check_dep_sync 等同款相对化显示）。
    """
    from pyflakes.checker import Checker
    from pyflakes.messages import UndefinedExport, UndefinedLocal, UndefinedName

    findings: list[str] = []
    for root in scan_roots:
        for f in sorted(root.rglob("*.py")):
            try:
                tree = ast.parse(f.read_text(encoding="utf-8", errors="ignore"))
            except SyntaxError as exc:
                findings.append(f"{f.relative_to(ROOT).as_posix()}:{exc.lineno}: syntax error, F821 无法核验")
                continue
            checker = Checker(tree, filename=str(f))
            for m in checker.messages:
                if isinstance(m, (UndefinedName, UndefinedLocal, UndefinedExport)):
                    findings.append(
                        f"{f.relative_to(ROOT).as_posix()}:{m.lineno}: {m.message % m.message_args}"
                    )
    return findings


def main() -> int:
    findings = find_undefined_names(SCAN_ROOTS)

    if not findings:
        print(f"[OK] 全仓零 F821 未定义名（扫描 {len(SCAN_ROOTS)} 根：tradex/src + tests + tradex/tests + scripts）")
        return 0

    print(f"[FAIL] 发现 {len(findings)} 处未定义名（NameError 级编程错误，零容忍）：")
    for line in findings:
        print(f"  - {line}")
    print("处置：补 import / 修正引用名；组合函数内不得用 except 吞 NameError（见 QI-BUG-01 教训）。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
