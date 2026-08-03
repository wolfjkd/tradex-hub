"""数据源版本监控 — 检查 eltdx / akshare 是否有新版本。

设计原则：
  - 仅提醒不升级（升级由老板手动执行）
  - 使用 stdlib urllib.request，不引入 requests 依赖
  - 超时 5 秒，失败静默返回 error 字段
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any

_TIMEOUT = 5  # 秒


def _get_local_version(name: str) -> str:
    """获取本地已安装版本号，失败返回 "unknown"。"""
    try:
        if name == "eltdx":
            import eltdx

            return getattr(eltdx, "__version__", "unknown")
        if name == "akshare":
            import akshare

            return getattr(akshare, "__version__", "unknown")
    except Exception:
        return "unknown"
    return "unknown"


def _fetch_json(url: str) -> Any:
    """用 urllib 请求 JSON，超时 5 秒。"""
    req = urllib.request.Request(
        url, headers={"User-Agent": "tradex-dashboard/1.0", "Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _has_update(current: str, latest: str) -> bool:
    """简单比较版本号，unknown 不提醒。"""
    if not current or current == "unknown" or not latest or latest == "unknown":
        return False
    return current != latest


def check_eltdx_version() -> dict:
    """检查 eltdx PyPI 最新版本。

    查询 https://pypi.org/pypi/eltdx/json（与 akshare 一致，避免 GitHub API 速率限制）。
    对比本地版本（import eltdx; eltdx.__version__）。

    Returns:
        成功: {"name", "current", "latest", "has_update", "url"}
        失败: {"name": "eltdx", "error": "...", "has_update": False}
    """
    try:
        data = _fetch_json("https://pypi.org/pypi/eltdx/json")
        latest = (data.get("info") or {}).get("version") or "unknown"
        current = _get_local_version("eltdx")
        return {
            "name": "eltdx",
            "current": current,
            "latest": latest,
            "has_update": _has_update(current, latest),
            "url": "https://pypi.org/project/eltdx/",
        }
    except Exception as e:
        return {"name": "eltdx", "error": str(e), "has_update": False}


def check_akshare_version() -> dict:
    """检查 akshare PyPI 最新版本。

    查询 https://pypi.org/pypi/akshare/json
    对比本地版本（import akshare; akshare.__version__）。

    Returns:
        成功: {"name", "current", "latest", "has_update", "url"}
        失败: {"name": "akshare", "error": "...", "has_update": False}
    """
    try:
        data = _fetch_json("https://pypi.org/pypi/akshare/json")
        latest = (data.get("info") or {}).get("version") or "unknown"
        current = _get_local_version("akshare")
        return {
            "name": "akshare",
            "current": current,
            "latest": latest,
            "has_update": _has_update(current, latest),
            "url": "https://pypi.org/project/akshare/",
        }
    except Exception as e:
        return {"name": "akshare", "error": str(e), "has_update": False}


def check_all_versions() -> list[dict]:
    """聚合返回所有数据源版本状态。"""
    return [check_eltdx_version(), check_akshare_version()]
