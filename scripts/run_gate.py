#!/usr/bin/env python3
"""全量回归门包装脚本（QI-RETRO-04）。

qc-20261122 实跑踩两回坑：管道 tail 吞输出导致日志为空；pytest 进程挂住不退
出（总结行已出，CPU 0 flaky）。Agent 需要一条干净的门命令——本脚本封装：

  1. 跑全量门：./tradex/.venv/Scripts/python.exe -m pytest tests tradex/tests
     -m "not network" -q（AGENTS.md 原始命令保留为底层形态）；
  2. 输出**实时**落 .scratch/gate-<YYYYMMDD-HHMMSS>.txt（stdout+stderr 合流）；
  3. 超时守护（默认 300s，--timeout 覆盖）：超时杀整个进程树（taskkill /T，
     防 pytest 子进程残留）；若日志已有总结行 → 按日志判定（挂住 flaky 的
     正解，AGENTS.md 口径「总结行以日志为准」）；没有 → 明确报
     「总结行未出，疑似 pytest 挂住」；
  4. 判定：取日志**最后一条含计数的 ==== ... ==== 总结行**，failed==0 且
     error==0 才 exit 0（pytest 全绿总结行不含 failed 字样，缺省按 0 计）；
     找不到总结行一律 exit 1（防管道吞输出/日志半截假绿）；
  5. 计数总结行是 pytest 最后一条输出：**已出即提前判定退出**（短宽限后杀
     树），不干等挂住的退出路径；输出 EOF 但进程不退（AGENTS.md 挂住 flaky
     原始形态）同样杀树按日志判定——两种挂住形态都不误报卡死。

用法：python scripts/run_gate.py [--timeout 300]   → 退出码 0 门绿 / 1 门红或挂住
"""

from __future__ import annotations

import argparse
import queue
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV_PYTHON = ROOT / "tradex" / ".venv" / "Scripts" / "python.exe"
SCRATCH = ROOT / ".scratch"

DEFAULT_TIMEOUT = 300  # 全量门实测 ~100s；AGENTS.md「超 3 分钟无输出先查日志」× 宽限
EOF_EXIT_GRACE = 30  # 输出 EOF 后给 pytest 的退出宽限；超限即挂住 flaky 形态
SUMMARY_EXIT_GRACE = 5  # 总结行已出后的退出宽限；超限即挂住 flaky 形态（提前判，不干等到超时）

# 总结行形态（-q 短总结）：==== 1285 passed, 5 skipped, 36 deselected, 3 warnings in 87.11s ====
_SUMMARY_RE = re.compile(r"^=+ .* =+$")
_COUNT_RE = re.compile(r"(\d+) (failed|passed|error)")


def _reader_thread(proc: subprocess.Popen, out_q: queue.Queue) -> None:
    """子进程输出泵：逐行推队列，EOF 后推 None 哨兵。"""
    try:
        for line in iter(proc.stdout.readline, ""):
            out_q.put(line)
    finally:
        out_q.put(None)


def _kill_tree(pid: int) -> None:
    """Windows 杀整个进程树（pytest 可能带子进程）；守护路径自身不允许抛。"""
    for args in (["taskkill", "/F", "/T", "/PID", str(pid)], ["taskkill", "/F", "/PID", str(pid)]):
        try:
            subprocess.run(args, capture_output=True, timeout=15, check=False)
            return
        except Exception:  # noqa: BLE001 — 守护路径，能杀则杀，杀不掉不炸脚本
            continue


def _judge_log(log_path: Path) -> tuple[int, str]:
    """按落盘日志判定：返回 (退出码, 人类可读结论)。

    取最后一条含计数的 ==== 总结行；failed==0 且 error==0 → 0；否则 1。
    找不到总结行 → 1（日志半截/被吞，绝不假绿）。
    """
    text = log_path.read_text(encoding="utf-8", errors="replace")
    count_lines = [
        ln
        for ln in text.splitlines()
        if _SUMMARY_RE.match(ln.strip()) and _COUNT_RE.search(ln)
    ]
    if not count_lines:
        return 1, "日志中未找到 pytest 计数总结行——疑似输出被吞或日志半截，判红"
    summary = count_lines[-1].strip()
    counts = {name: int(n) for n, name in _COUNT_RE.findall(summary)}
    failed = counts.get("failed", 0)
    errors = counts.get("error", 0)
    if failed == 0 and errors == 0 and counts.get("passed", 0) > 0:
        return 0, f"门绿｜{summary}"
    return 1, f"门红｜{summary}"


def main() -> int:
    parser = argparse.ArgumentParser(description="全量回归门包装：落盘 + 超时守护 + 总结行判定")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="子进程总超时秒数（默认 300）")
    args = parser.parse_args()

    if not VENV_PYTHON.exists():
        print(f"[FAIL] venv python 不存在：{VENV_PYTHON}（venv 口径见 AGENTS.md）")
        return 1

    SCRATCH.mkdir(exist_ok=True)
    log_path = SCRATCH / f"gate-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"

    cmd = [str(VENV_PYTHON), "-m", "pytest", "tests", "tradex/tests", "-m", "not network", "-q"]
    start = time.monotonic()
    print(f"[gate] 启动全量门（超时守护 {args.timeout}s）")
    print(f"[gate] 日志：{log_path}")

    proc = subprocess.Popen(  # noqa: S603 — 命令为仓库内常量，无外部输入拼接
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        cwd=ROOT,
    )

    out_q: queue.Queue = queue.Queue()
    reader = threading.Thread(target=_reader_thread, args=(proc, out_q), daemon=True)
    reader.start()

    timed_out = False
    summary_seen = False
    with log_path.open("w", encoding="utf-8") as log:
        deadline = start + args.timeout
        while True:
            try:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    break
                item = out_q.get(timeout=remaining)
            except queue.Empty:
                timed_out = True
                break
            if item is None:
                break
            log.write(item)
            # 计数总结行是 pytest 最后一条输出：已出即可提前按日志判定，
            # 不干等挂住的退出路径（qc-20261122 实测 flaky 挂到 300s）
            if _SUMMARY_RE.match(item.strip()) and _COUNT_RE.search(item):
                summary_seen = True
                break

        # 泵干队列剩余输出再收尾（超时杀树后 reader 可能仍有积压）
        while True:
            try:
                item = out_q.get_nowait()
            except queue.Empty:
                break
            if item is not None:
                log.write(item)

    elapsed = time.monotonic() - start

    def _reap(message: str) -> None:
        """挂住形态收尾：给短宽限自然退出，不退杀树；打印一条说明。"""
        try:
            proc.wait(timeout=SUMMARY_EXIT_GRACE)
        except subprocess.TimeoutExpired:
            _kill_tree(proc.pid)
            try:
                proc.wait(timeout=EOF_EXIT_GRACE)
            except subprocess.TimeoutExpired:
                pass  # taskkill 已尽力，守护路径不再抛——按日志判定收尾
            print(message)

    if timed_out:
        _kill_tree(proc.pid)
        try:
            proc.wait(timeout=EOF_EXIT_GRACE)
        except subprocess.TimeoutExpired:
            pass
        code, verdict = _judge_log(log_path)
        if code == 0:
            print(f"[gate] 超时（{elapsed:.0f}s）但总结行已出——pytest 挂住 flaky，按日志判定干净退出")
            print(f"[gate] {verdict}")
            print(f"[gate] 日志：{log_path}")
            return 0
        print(f"[gate] 超时（{elapsed:.0f}s）杀进程树（pid {proc.pid}）：总结行未出，疑似 pytest 挂住")
        print(f"[gate] 日志：{log_path}（先查日志再判卡死，AGENTS.md 口径）")
        return 1

    if summary_seen:
        _reap(f"[gate] 总结行已出但 pytest {SUMMARY_EXIT_GRACE}s 不退——挂住 flaky，按日志判定干净退出")
    else:
        # 输出 EOF 已到（无总结行形态）：正常应很快退出；宽限内不退也按挂住处理
        _reap(f"[gate] pytest 输出已结束但进程 {EOF_EXIT_GRACE}s 不退——挂住 flaky，杀进程树按日志判定")

    code, verdict = _judge_log(log_path)
    print(f"[gate] pytest 退出码 {proc.returncode}（{elapsed:.0f}s）")
    print(f"[gate] {verdict}")
    print(f"[gate] 日志：{log_path}")
    return code


if __name__ == "__main__":
    sys.exit(main())
