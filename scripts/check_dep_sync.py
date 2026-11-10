"""pyproject↔requirements 依赖集合对比（批次D2①，确定性护栏）。

审计硬违规 #1（prometheus_client 只进 pyproject、requirements 漏同步）的
机械防线。比对 tradex/pyproject.toml 与 tradex/requirements.txt 的**包名集合**
（大小写/连字符归一，忽略版本约束）：

  - 运行时依赖（[project].dependencies）：双处必须一致（缺任一侧即 FAIL）；
  - extras 组：requirements 已覆盖该组 ≥1 包 → 该组整体必须齐全
    （http 组已有 uvicorn/starlette → fastapi 缺失会 FAIL；dev/ws 组零覆盖不纳管）。

用法：python scripts/check_dep_sync.py   → 退出码 0 一致 / 1 漂移
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _norm(req: str) -> str:
    """要求行 → 归一包名（去版本约束/ extras / 环境标记）。"""
    name = re.split(r"[<>=!~;\[]", req.strip(), maxsplit=1)[0]
    return name.strip().lower().replace("_", "-")


def main() -> int:
    pyproject = tomllib.loads(
        (ROOT / "tradex" / "pyproject.toml").read_text(encoding="utf-8")
    )
    runtime = pyproject.get("project", {}).get("dependencies", [])
    self_name = _norm(pyproject.get("project", {}).get("name", "tradex"))

    rqset: set[str] = set()
    for line in (ROOT / "tradex" / "requirements.txt").read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            rqset.add(_norm(s))
    rqset.discard(self_name)

    # extras 组纳管规则：requirements 已覆盖该组 ≥1 包 → 该组整体必须齐全
    extras: list[str] = []
    for group_deps in (pyproject.get("project", {}).get("optional-dependencies", {}) or {}).values():
        names = {_norm(d) for d in group_deps}
        if names & rqset:
            extras.extend(group_deps)

    pyset = {_norm(d) for d in runtime + extras} - {self_name}

    missing_in_req = sorted(pyset - rqset)
    missing_in_py = sorted(rqset - pyset)

    if not missing_in_req and not missing_in_py:
        print(f"[OK] 依赖双处一致（pyproject 纳管集 {len(pyset)} 个）")
        return 0

    if missing_in_req:
        print("[FAIL] pyproject 有而 requirements 缺（硬违规#1 形态）:")
        for n in missing_in_req:
            print(f"  - {n}")
    if missing_in_py:
        print("[FAIL] requirements 有而 pyproject 缺:")
        for n in missing_in_py:
            print(f"  - {n}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
