#!/usr/bin/env python
"""tradex-hub 版本自检 —— 不联网、不问 AI，只看本地文件夹。

回答一个问题：**当前这份代码是什么版本、有没有未发布的改动？**

版本信号的可靠性分层（本脚本据此做交叉比对）：

    权威层（应一致，不一致即发布流程出错）
      1. VERSION                          发布版本号单一真源
      2. tradex/pyproject.toml            打包版本号
      3. git tag / git describe           代码快照位置（本地 .git 自带，无需联网）
    展示层（可能滞后，仅作参考，但本脚本会指出漂移）
      4. CHANGELOG.md 顶部条目
      5. README.md 徽章
    运行时层（可能是旧进程，不等于文件夹里的代码）
      6. GET /health 的 version 字段

退出码：0 = 权威层一致；1 = 权威层互相矛盾。

用法
----
    python scripts/version.py            # 完整自检（含本地 8000 端口探活）
    python scripts/version.py --no-health  # 跳过探活（纯读文件）
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = REPO_ROOT / "VERSION"
PYPROJECT = REPO_ROOT / "tradex" / "pyproject.toml"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
README = REPO_ROOT / "README.md"
HEALTH_URL = "http://127.0.0.1:8000/health"

OK = "[OK]"
BAD = "[!!]"
NA = "[--]"


def read_version_file() -> str | None:
    if not VERSION_FILE.exists():
        return None
    return VERSION_FILE.read_text(encoding="utf-8").strip() or None


def read_pyproject_version() -> str | None:
    if not PYPROJECT.exists():
        return None
    try:
        import tomllib

        data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
        return data.get("project", {}).get("version")
    except Exception:  # noqa: BLE001 - 版本自检不应因解析失败而崩溃
        match = re.search(r'^version\s*=\s*"([^"]+)"', PYPROJECT.read_text(encoding="utf-8"), re.M)
        return match.group(1) if match else None


def read_changelog_top() -> tuple[str, str] | None:
    """返回 CHANGELOG 顶部 (版本, 日期)。"""
    if not CHANGELOG.exists():
        return None
    match = re.search(
        r"^## \[(\d+\.\d+\.\d+)\](?: - (\d{4}-\d{2}-\d{2}))?",
        CHANGELOG.read_text(encoding="utf-8"),
        re.M,
    )
    if not match:
        return None
    return match.group(1), match.group(2) or "未标注"


def read_readme_badge() -> str | None:
    if not README.exists():
        return None
    match = re.search(r"badge/Version-([0-9.]+)-", README.read_text(encoding="utf-8"))
    return match.group(1) if match else None


def _git(*args: str) -> str | None:
    """在仓库根目录执行 git 命令；git 缺失或非仓库时返回 None。"""
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip()


def read_git_state() -> dict[str, str] | None:
    describe = _git("describe", "--tags", "--dirty")
    if describe is None:
        return None
    state: dict[str, str] = {"describe": describe}

    state["tag"] = _git("describe", "--tags", "--abbrev=0") or "无"
    state["commit"] = _git("log", "-1", "--format=%h %ad %s", "--date=format:%Y-%m-%d %H:%M") or ""

    dirty = _git("status", "--porcelain")
    state["dirty"] = "干净" if not dirty else f"{len(dirty.splitlines())} 个文件未提交"

    # git describe 形如 v3.6.1-3-gae9ff3e / v3.6.1-dirty
    match = re.fullmatch(r".+-(\d+)-g[0-9a-f]+(?:-dirty)?", describe)
    state["ahead"] = match.group(1) if match else "0"

    counts = _git("rev-list", "--left-right", "--count", "origin/master...HEAD")
    if counts:
        behind, ahead = counts.split()
        state["track"] = f"落后 {behind} / 领先 {ahead}（相对上次 fetch 的 origin/master）"
    else:
        state["track"] = "无上游跟踪分支"

    fetch_head = REPO_ROOT / ".git" / "FETCH_HEAD"
    if fetch_head.exists():
        stamp = datetime.fromtimestamp(fetch_head.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        state["fetched_at"] = stamp
    else:
        state["fetched_at"] = "从未 fetch"
    return state


def read_health(timeout: float = 1.5) -> dict[str, object] | None:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=timeout) as resp:  # noqa: S310 - 固定本地回环地址
            return json.loads(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - 服务未启动属于正常情况
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="tradex-hub 版本自检")
    parser.add_argument("--no-health", action="store_true", help="跳过本地服务探活")
    args = parser.parse_args()

    version = read_version_file()
    pyproject = read_pyproject_version()
    changelog = read_changelog_top()
    badge = read_readme_badge()
    git_state = read_git_state()

    print("tradex-hub 版本自检")
    print("=" * 56)
    print(f"仓库：{REPO_ROOT}")
    print()

    # ---- 权威层 ----
    print("权威层（不一致 = 发布流程出错）")
    print(f"  VERSION 文件        {version or '缺失'}")
    print(f"  pyproject version   {pyproject or '缺失'}")
    if git_state:
        print(f"  最近 tag            {git_state['tag']}")
        print(f"  git describe        {git_state['describe']}")
    else:
        print("  git                不可用（未安装或不是 git 仓库）")
    print()

    # ---- 展示层 ----
    print("展示层（滞后不影响代码，但说明文档需同步）")
    if changelog:
        print(f"  CHANGELOG 最新条目  {changelog[0]}（{changelog[1]}）")
    else:
        print("  CHANGELOG 最新条目  未找到")
    print(f"  README 徽章         {badge or '未找到'}")
    print()

    # ---- Git 状态 ----
    if git_state:
        print("代码状态（本地 .git，无需联网）")
        print(f"  标签后提交数        {git_state['ahead']} 个")
        print(f"  当前提交            {git_state['commit']}")
        print(f"  工作区              {git_state['dirty']}")
        print(f"  相对远端快照        {git_state['track']}")
        print(f"  上次 fetch 时间     {git_state['fetched_at']}")
        print()

    # ---- 运行时 ----
    runtime: dict[str, object] | None = None
    if not args.no_health:
        runtime = read_health()
        print("运行实例（可能是旧进程，不等于文件夹里的代码）")
        if runtime:
            print(
                f"  /health            版本 {runtime.get('version')} / "
                f"工具 {runtime.get('tools')} / 已运行 {runtime.get('uptime_seconds')}s"
            )
        else:
            print(f"  127.0.0.1:8000     未启动或不可达（代码版本不受影响）")
        print()

    # ---- 结论 ----
    print("=" * 56)
    core = {"VERSION": version, "pyproject": pyproject}
    core_ok = len({v for v in core.values() if v}) == 1
    print(f"{OK if core_ok else BAD} 代码版本：{version}")

    if git_state and git_state["ahead"] != "0":
        print(f"    注意：该版本之后还有 {git_state['ahead']} 个未发布提交，发布号仍为 {version}")

    drifts = []
    if badge and badge != version:
        drifts.append(f"README 徽章写 {badge}")
    if changelog and changelog[0] != version:
        drifts.append(f"CHANGELOG 顶部写 {changelog[0]}")
    if drifts:
        print(f"{BAD} 文档漂移：" + "；".join(drifts))
    else:
        print(f"{OK} 文档与版本号一致")

    if runtime is not None and runtime.get("version") != version:
        print(f"{BAD} 运行实例版本 {runtime.get('version')} 与代码 {version} 不同，需重启服务")
    elif runtime is not None:
        print(f"{OK} 运行实例与代码一致")
    elif not args.no_health:
        print(f"{NA} 运行实例未探活")

    if not git_state:
        print(f"{NA} git 不可用，无法判断是否有未发布提交")

    if sys.stdin is not None and sys.stdin.isatty():
        print()
        try:
            input("按回车退出…")
        except (EOFError, KeyboardInterrupt):
            # 双击运行时留窗口；被重定向或管道调用时直接退出，不算失败
            pass
    return 0 if core_ok and not drifts else 1


if __name__ == "__main__":
    sys.exit(main())
