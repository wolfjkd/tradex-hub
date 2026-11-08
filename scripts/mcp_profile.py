#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tradex-hub MCP 工具一键启停（中文 CLI，2026-11-08 老板需求）。

用法（在 tradex-hub 目录下，用任意本机 Python 跑均可）：
    python scripts/mcp_profile.py list            # 按中文分组查看 190 个工具现状
    python scripts/mcp_profile.py apply lean      # 一键精简（禁 73，剩 117）+ 重启网关
    python scripts/mcp_profile.py apply lean80    # 二段精简（再禁 34，剩 83）
    python scripts/mcp_profile.py apply full      # 恢复全部 190
    python scripts/mcp_profile.py show            # 看当前 profile

原理：写 config/mcp_tool_profile.json（隐藏名单）→ 杀 8000 网关进程 →
supervisor 约 5 秒自动拉起新进程加载新名单 → 脚本等待并验证 /health 工具数。
WorkBuddy/ZCode 界面在 MCP 重连后显示的数字即与实际一致。

铁律：只动 hub 自己的配置与网关进程，不碰 WorkBuddy 状态文件。
国内接口直连（/health 走 127.0.0.1，禁代理）。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILE = ROOT / "config" / "mcp_tool_profile.json"
GATEWAY = "http://127.0.0.1:8000/health"

# --------------------------------------------------------------- 中文分组全清单
# 结构：(中文名, 一句话说明, [工具名...])。顺序即 list 输出顺序。

# 数据单一真源：tradex.tools.visibility_catalog（TradeX 看板同源消费）
sys.path.insert(0, str(ROOT / "tradex" / "src"))
from tradex.tools.visibility_catalog import (  # noqa: E402
    GROUPS,
    lean80_hidden as _lean80_hidden,
    lean_hidden as _lean_hidden,
)

ALL_TOOLS: list[str] = [t for _t, _d, _ts in GROUPS for t in _ts]
ALL_TOOLS: list[str] = [t for _, _, ts in GROUPS for t in ts]


def _read_profile() -> dict:
    if PROFILE.exists():
        try:
            return json.loads(PROFILE.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"⚠️ profile 文件损坏（{e}），按 full 处理")
    return {"profile": "full", "hidden_tools": []}


def _write_profile(profile: str, hidden: list[str]) -> None:
    PROFILE.parent.mkdir(parents=True, exist_ok=True)
    PROFILE.write_text(
        json.dumps(
            {
                "profile": profile,
                "hidden_tools": hidden,
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _hidden_set(data: dict) -> set[str]:
    return set(data.get("hidden_tools") or [])


def cmd_list() -> int:
    hidden = _hidden_set(_read_profile())
    known = set(ALL_TOOLS)
    print(f"\n当前 profile：{_read_profile().get('profile', 'full')} ｜ "
          f"启用 {len(known - hidden)} / 全量 {len(known)}（另有名单外工具以网关为准）\n")
    print(f"{'状态':<4} {'工具':<34} 说明")
    print("-" * 88)
    for title, desc, tools in GROUPS:
        print(f"\n▎{title} —— {desc}")
        for t in tools:
            mark = "🚫" if t in hidden else "✅"
            print(f"  {mark} {t:<34}")
    extra = hidden - known
    if extra:
        print(f"\n▎名单内但未分组（仍处于隐藏状态）：{sorted(extra)}")
    print("\n提示：🚫=已隐藏（AI 不可见） ✅=启用。"
          "TradeX 看板/短线落库/数据源降级链不受本启停影响（进程内调用）。\n")
    return 0


def _resolve_preset(name: str) -> tuple[str, list[str]]:
    if name == "full":
        return "full", []
    if name == "lean":
        return "lean", _lean_hidden()
    if name == "lean80":
        return "lean80", _lean80_hidden()
    raise SystemExit(f"未知预设：{name}（可选 lean / lean80 / full）")


def _gateway_tools() -> int | None:
    """读网关 /health 的 tools 数；国内回环直连（禁代理）。"""
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(GATEWAY, timeout=5) as r:
            return int(json.loads(r.read().decode("utf-8")).get("tools", -1))
    except Exception:  # noqa: BLE001
        return None


def _kill_gateway() -> int:
    """杀 8000 端口网关进程（supervisor 约 5 秒自动拉起新进程）。返回杀掉的 PID 数。

    查 PID 双通道：① PowerShell Get-NetTCPConnection（主，Bash/沙箱内 netstat
    可能被拦截误报空——AGENTS.md 已知坑）；② netstat 兜底。中文 Windows 下
    netstat 输出 GBK，按 bytes 取回再容错解码。
    """
    pids: set[str] = set()
    # 主通道：按命令行精确匹配网关进程（本机实测 Get-NetTCPConnection/netstat
    # 对 :8000 监听都可能查不到——多进程绑定下端口表不可靠，cmdline 匹配最稳）
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe' OR Name='python.exe'\" | "
             "Where-Object {$_.CommandLine -like '*-m tradex --http*'} | "
             "Select-Object -ExpandProperty ProcessId"],
            capture_output=True, timeout=25,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout.decode("utf-8", errors="replace")
        pids |= {l.strip() for l in out.splitlines() if l.strip().isdigit()}
    except Exception as e:  # noqa: BLE001
        print(f"  PowerShell 查网关进程失败（{e}），转 netstat 兜底")
    if not pids:
        try:
            out = subprocess.run(
                ["netstat", "-ano"], capture_output=True, timeout=15
            ).stdout.decode("utf-8", errors="replace")
            for line in out.splitlines():
                if ":8000" in line and "LISTENING" in line:
                    parts = line.split()
                    if len(parts) >= 5 and parts[1].endswith(":8000"):
                        pids.add(parts[-1])
        except Exception as e:  # noqa: BLE001
            print(f"⚠️ netstat 也失败：{e}")
    for pid in pids:
        subprocess.run(
            ["taskkill", "/PID", pid, "/F"],
            capture_output=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        print(f"  已停网关进程 pid={pid}（supervisor 将自动拉起）")
    return len(pids)


def cmd_apply(name: str) -> int:
    profile, hidden = _resolve_preset(name)
    _write_profile(profile, hidden)
    print(f"\n✅ 已写入 {PROFILE.name}：profile={profile}，隐藏 {len(hidden)} 个"
          f"（暴露 {len(ALL_TOOLS) - len(hidden)}）")
    print("⏳ 重启网关使其生效……")
    killed = _kill_gateway()
    if not killed:
        print("  ⚠️ 未发现 8000 监听进程（网关可能没在跑），profile 已写入，下次启动生效")
    deadline = time.time() + 45
    while time.time() < deadline:
        time.sleep(3)
        n = _gateway_tools()
        if n is not None and n > 0:
            expect = len(ALL_TOOLS) - len(hidden)
            mark = "✅" if n == expect else "⚠️"
            print(f"{mark} 网关已就绪：/health 报告 tools={n}"
                  + (f"（预期 {expect}）" if n != expect else ""))
            break
        print("  等待网关拉起……")
    else:
        print("⚠️ 45 秒内未等到网关健康报告，请稍后手动确认：curl http://127.0.0.1:8000/health")
    print("\n📱 WorkBuddy/ZCode 在 MCP 重连后显示新数字（WorkBuddy 可关开一次 tradex 开关触发重连）")
    print("↩️  恢复全量：python scripts/mcp_profile.py apply full\n")
    return 0


def cmd_show() -> int:
    data = _read_profile()
    hidden = _hidden_set(data)
    print(f"\nprofile = {data.get('profile', 'full')} ｜ 隐藏 {len(hidden)} ｜ "
          f"启用 {len(ALL_TOOLS) - len(hidden)}（名单内口径）")
    gw = _gateway_tools()
    if gw is not None:
        print(f"网关 /health tools = {gw}")
    print(f"profile 文件：{PROFILE}\n")
    return 0


def main() -> int:
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd = argv[0]
    if cmd == "list":
        return cmd_list()
    if cmd == "show":
        return cmd_show()
    if cmd == "apply" and len(argv) > 1 and not argv[1].startswith("-"):
        return cmd_apply(argv[1].strip().lower())
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
