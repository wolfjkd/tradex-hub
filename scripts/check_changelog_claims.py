"""CHANGELOG 版本段措辞 vs git log 史实核验（批次D2④，确定性护栏）。

发版流程缺口（审计复盘 #3）：v3.9.1 CHANGELOG 自称「零代码维护版」，
实际该版本区间含 6 个代码提交——措辞对照史实从未被机械核验。

核验规则（对每个「有对应 git tag 的版本段」）：
  1. 段内出现「零代码 / 本版无代码改动 / 无代码提交」类宣称，
     而区间内实有**代码提交**（触及 .py/.toml/.lock/requirements 的提交）→ FAIL；
  2. 段内宣称「N 个代码提交」而实数不符 → FAIL；
  3. 纯文档提交（README/CHANGELOG/docs/*.md）不计入代码提交。

用法：
  python scripts/check_changelog_claims.py            # 核验全部带 tag 版本段
  python scripts/check_changelog_claims.py --selftest # 内置 v3.9.1 失实样例自证
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = ROOT / "CHANGELOG.md"

ZERO_CODE_PAT = re.compile(r"零代码|本版无代码改动|无代码提交|零代码维护")
CODE_COUNT_PAT = re.compile(r"实含\s*(\d+)\s*个代码提交")
# 承载小节标题（### Fixed/Added/Changed/代码变更 等）——双向核验的「有承载」判据
SECTION_HEADER_PAT = re.compile(r"^### ", re.M)
# 代码文件后缀（.lock 单独出现不算代码——依赖元数据 chore，如 ec07154 移除 uv.lock）
CODE_EXTS = {".py", ".toml", ".cfg", ".ini"}


def is_code_commit(files: list[str]) -> bool:
    """提交是否触及代码文件（.lock 不算；requirements.txt 算；docs/md 不算）。"""
    return any(
        Path(f).suffix.lower() in CODE_EXTS or f.endswith("requirements.txt")
        for f in files
    )


def section_claims(text: str) -> dict:
    """从版本段文本提取措辞宣称。

    「零代码」若出现在勘误语境（段内含「勘误」或已改口宣称具体代码提交数），
    不再视为有效宣称——按「宣称 N 个代码提交」的计数分支核验。
    """
    m = CODE_COUNT_PAT.search(text)
    corrected = ("勘误" in text) or (m is not None)
    zero = bool(ZERO_CODE_PAT.search(text)) and not corrected
    return {"zero_code": zero, "claimed_code_commits": int(m.group(1)) if m else None}


def verify_section(claims: dict, code_commits: int) -> list[str]:
    """措辞宣称 vs 史实核验（纯函数，可单测）。返回违规列表。"""
    errors: list[str] = []
    if claims["zero_code"] and code_commits > 0:
        errors.append(f"宣称零代码但区间实有 {code_commits} 个代码提交")
    claimed = claims["claimed_code_commits"]
    if claimed is not None and claimed != code_commits:
        errors.append(f"宣称 {claimed} 个代码提交但区间实有 {code_commits} 个")
    return errors


def verify_coverage(text: str, code_commits: int) -> list[str]:
    """双向核验（QI-SPEC-03 盲区③）：区间实有代码提交但段内无任何承载小节
    （### Fixed/Added/Changed/代码变更…）→「有史实无宣称」，FAIL。

    QI-SPEC-01 即此形态（批次 A 九项修复 CHANGELOG 零承载）——单向核验
    （只查宣称 vs 史实）对「漏记」永不报，双向补齐。粒度 = 段级整段零承载
    （逐提交粒度会误伤批次内多 commit 合并叙述，不做）。
    """
    if code_commits > 0 and not SECTION_HEADER_PAT.search(text):
        return [
            f"区间实有 {code_commits} 个代码提交但段内无任何承载小节（有史实无宣称）"
        ]
    return []


def git(*args: str) -> str:
    out = subprocess.run(
        ["git", *args], capture_output=True, text=True, encoding="utf-8",
        cwd=ROOT, check=True,
    )
    return out.stdout


def git_code_commits(rev_range: str) -> int:
    """区间内触及代码文件的提交数（--name-only 逐提交判定）。"""
    log = git("log", "--name-only", "--format=@%h@", rev_range)
    count = 0
    for block in re.split(r"^@[^@]*@$", log, flags=re.M):
        files = [l.strip() for l in block.strip().splitlines() if l.strip()]
        if files and is_code_commit(files):
            count += 1
    return count


def parse_sections() -> list[tuple[str | None, str]]:
    """CHANGELOG → [(版本号或 None, 段文本)]。

    版本段 = ## [vX.Y.Z] ...（核验区间 prev_tag..tag）；
    「待发版」段 = ## 待发版 ...（无 tag，核验区间 = 最新 tag..HEAD——
    QI-SPEC-03 盲区①：原版无 tag 段直接跳过，「待发版」期漏记永不报）；
    其他无版本号段（如批次史实补记）不核验。
    """
    text = CHANGELOG.read_text(encoding="utf-8")
    parts = re.split(r"\n## ", text)
    out = []
    for part in parts[1:]:
        m = re.match(r"\[?v?(\d+\.\d+\.\d+)\]?", part)
        if m:
            out.append((m.group(1), part))
        elif part.startswith("待发版"):
            out.append((None, part))
    return out


def main() -> int:
    if "--selftest" in sys.argv:
        # 样例 1（原 v3.9.1 失实，2026-11-10 审计实证）：宣称零代码、实含 6 个代码提交
        claims = {"zero_code": True, "claimed_code_commits": None}
        errors = verify_section(claims, code_commits=6)
        if not errors:
            print("[SELFTEST-FAIL] 零代码失实样例未被报错——核验逻辑失效")
            return 1
        print(f"[SELFTEST-OK] 零代码失实样例被正确报错: {errors[0]}")
        # 样例 2（QI-SPEC-01 修前形态）：段无承载小节但区间实有代码提交
        errors2 = verify_coverage("- 批次修复按原 commit message 一句带过\n", code_commits=9)
        if not errors2:
            print("[SELFTEST-FAIL] 有史实无宣称样例未被报错——双向核验失效")
            return 1
        print(f"[SELFTEST-OK] QI-SPEC-01 修前形态（整段零承载）被正确报错: {errors2[0]}")
        # 样例 3（防误伤）：有承载小节不报
        errors3 = verify_coverage("### Fixed\n- 某修复说明\n", code_commits=9)
        if errors3:
            print(f"[SELFTEST-FAIL] 有承载段被误报: {errors3}")
            return 1
        print("[SELFTEST-OK] 有承载段不误报")
        return 0

    sections = parse_sections()
    tags = set(
        t.strip() for t in git("tag", "--list").splitlines() if t.strip()
    )
    tag_re = {re.sub(r"^v", "", t): t for t in tags if re.fullmatch(r"v?\d+\.\d+\.\d+", t)}
    tags_sorted = sorted(
        (tuple(int(x) for x in re.sub(r"^v", "", t).split(".")), t) for t in tag_re.values()
    )
    latest_tag = tags_sorted[-1][1] if tags_sorted else None

    failures: list[str] = []
    checked = 0
    for ver, text in sections:
        if ver is None:
            # 待发版段（QI-SPEC-03 盲区①）：区间 = 最新 tag..HEAD
            if latest_tag is None:
                continue
            code_commits = git_code_commits(f"{latest_tag}..HEAD")
            errors = verify_section(section_claims(text), code_commits) + verify_coverage(
                text, code_commits
            )
            checked += 1
            if errors:
                failures.append(
                    f"待发版 ({latest_tag}..HEAD, 代码提交 {code_commits}): " + "; ".join(errors)
                )
            continue
        tag = tag_re.get(ver)
        if tag is None:
            continue  # 无 tag 的其他段跳过
        idx = next(i for i, (_, t) in enumerate(tags_sorted) if t == tag)
        if idx == 0:
            continue  # 首个 tag 无前界
        prev_tag = tags_sorted[idx - 1][1]
        code_commits = git_code_commits(f"{prev_tag}..{tag}")
        errors = verify_section(section_claims(text), code_commits) + verify_coverage(
            text, code_commits
        )
        checked += 1
        if errors:
            failures.append(f"v{ver} ({prev_tag}..{tag}, 代码提交 {code_commits}): " + "; ".join(errors))

    if failures:
        print(f"[FAIL] CHANGELOG 措辞 vs git log 不符（核验 {checked} 段）:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"[OK] CHANGELOG 措辞与 git log 史实一致（核验 {checked} 段，含待发版）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
