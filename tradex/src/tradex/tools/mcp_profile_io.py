"""MCP 工具可见性 profile 的读写与网关重启（2026-11-08 一键启停共享层）。

消费方：scripts/mcp_profile.py（CLI）、dashboard 数据看板（8765）、
TradeX 看板（进程内自实现同款逻辑）。

设计：
  - profile 文件单一真源 config/mcp_tool_profile.json（黑名单语义）
  - 重启网关按 cmdline 精确匹配 `-m tradex --http`（本机 :8000 监听在
    netstat/Get-NetTCPConnection 下均可能查不到——多进程绑定语义，
    cmdline 匹配实测可靠）
  - 只动 hub 自己的配置与网关进程，不碰 WorkBuddy 状态文件
"""
from __future__ import annotations

import json
import subprocess
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

_GATEWAY_HEALTH = "http://127.0.0.1:8000/health"


def profile_path() -> Path | None:
    """profile 文件路径（复用 registry 的定位逻辑，env 可覆盖）。"""
    from .registry import _tool_profile_path

    return _tool_profile_path()


def read_hidden() -> tuple[str, set[str]]:
    """读当前 profile：返回 (profile 名, hidden 集合)。缺失按 full。"""
    from .registry import _load_hidden_tools

    profile, hidden = _load_hidden_tools()
    return profile, set(hidden)


def write_profile(profile: str, hidden: list[str]) -> Path:
    """写 profile 文件（原子性不作要求：单写者场景，损坏自动回退 full）。"""
    path = profile_path()
    if path is None:
        raise RuntimeError("profile 文件路径不可定位（hub registry 未找到项目根）")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
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
    return path


def gateway_tools(timeout: float = 4.0) -> int | None:
    """读网关 /health 的 tools 数；网关不在跑返回 None（回环直连禁代理）。"""
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(_GATEWAY_HEALTH, timeout=timeout) as r:
            return int(json.loads(r.read().decode("utf-8")).get("tools", -1))
    except Exception:  # noqa: BLE001
        return None


def kill_gateway() -> int:
    """按 cmdline 杀 hub 网关进程，返回杀掉的 PID 数。

    TradeX 自身（uvicorn tradex_app）与数据看板（-m tradex.dashboard）
    的命令行都不含 `-m tradex --http`，不会被误伤。
    """
    ps = (
        "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe' OR Name='python.exe'\" | "
        "Where-Object {$_.CommandLine -like '*-m tradex --http*'} | "
        "Select-Object -ExpandProperty ProcessId"
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, timeout=25,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout.decode("utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"查询网关进程失败：{e}") from e
    pids = [l.strip() for l in out.splitlines() if l.strip().isdigit()]
    killed = 0
    for pid in pids:
        try:
            subprocess.run(
                ["taskkill", "/PID", pid, "/F"],
                capture_output=True, timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            killed += 1
        except Exception:  # noqa: BLE001
            pass
    return killed


def wait_gateway(expected: int | None, deadline_s: float = 45.0) -> int | None:
    """等 supervisor 拉起新网关并返回工具数（expected 命中即提前返回）。"""
    deadline = time.time() + deadline_s
    last: int | None = None
    while time.time() < deadline:
        time.sleep(3)
        last = gateway_tools()
        if last is not None and last > 0 and (expected is None or last == expected):
            return last
    return last


def apply_preset_values(preset: str, lean_hidden: list[str], lean80_hidden: list[str],
                        total: int) -> dict[str, Any]:
    """通用 apply：写 profile + 重启网关 + 等待验证。

    lean/lean80 的隐藏名单由调用方从 visibility_catalog 传入
    （本模块不 import 分组数据，保持 IO 与数据解耦）。
    """
    if preset == "full":
        hidden: list[str] = []
    elif preset == "lean":
        hidden = list(lean_hidden)
    elif preset == "lean80":
        hidden = list(lean80_hidden)
    else:
        raise ValueError(f"非法预设：{preset!r}（可选 lean / lean80 / full）")
    write_profile(preset, hidden)
    killed = kill_gateway()
    expected = total - len(hidden)
    gateway = wait_gateway(expected)
    return {
        "preset": preset,
        "hidden_count": len(hidden),
        "enabled": expected,
        "gateway_tools": gateway,
        "killed": killed,
    }
