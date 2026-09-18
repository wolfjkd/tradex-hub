"""写操作 service —— 本地文件存储 CRUD（阶段一工单 10）。

设计原则（阶段一）：
  - 不引入数据库，降低复杂度；看板接入真实数据库时再迁移
  - 文件原子写：tempfile + os.replace，避免并发写损坏
  - 路径：tradex-hub/data/written/
    - strategies/  每个策略一个 JSON 文件 {id}.json
    - watchlist.json  自选股单一 JSON 数组
  - 不入版本控制（已在 .gitignore 的 data/ 下）

MCP 同步暴露（可选）：后续工单可加 @mcp.tool 包装供 AI 直接调用。
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 写操作根目录（tradex-hub/data/written/）
# 从本文件位置回溯：src/tradex/service/write_service.py → 向上 4 层到 tradex-hub/
_HUB_ROOT = Path(__file__).resolve().parents[4]
_DATA_DIR = _HUB_ROOT / "data" / "written"
_STRATEGY_DIR = _DATA_DIR / "strategies"
_WATCHLIST_FILE = _DATA_DIR / "watchlist.json"


def _ensure_dirs() -> None:
    """惰性创建目录（首次写入时建）。"""
    _STRATEGY_DIR.mkdir(parents=True, exist_ok=True)


def _atomic_write_json(path: Path, data: Any) -> None:
    """原子写 JSON：先写临时文件，再 os.replace 替换（Windows/Linux 均原子）。"""
    _ensure_dirs()
    path.parent.mkdir(parents=True, exist_ok=True)
    # 临时文件放同目录（os.replace 跨目录不原子）
    fd, tmp_path = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, str(path))
    except Exception:
        # 清理孤儿临时文件
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ───────────────────────── 策略 CRUD ──────────────────────────

def create_strategy(name: str, content: str, tags: list[str] | None = None) -> dict:
    """创建量化策略 —— 保存到 data/written/strategies/{id}.json。

    Returns:
        {"id": str, "name": str, "created_at": float, "path": str}
    """
    _ensure_dirs()
    sid = f"{int(time.time() * 1000)}"  # 毫秒时间戳作 id
    record = {
        "id": sid,
        "name": name,
        "content": content,
        "tags": tags or [],
        "created_at": time.time(),
    }
    target = _STRATEGY_DIR / f"{sid}.json"
    _atomic_write_json(target, record)
    logger.info("策略已保存: %s (%s)", name, sid)
    return {"id": sid, "name": name, "created_at": record["created_at"], "path": str(target)}


def list_strategies() -> dict:
    """列出所有已保存策略（仅元信息，不含 content）。"""
    _ensure_dirs()
    items = []
    for f in sorted(_STRATEGY_DIR.glob("*.json")):
        try:
            with open(f, "r", encoding="utf-8") as fp:
                rec = json.load(fp)
            items.append({
                "id": rec.get("id"),
                "name": rec.get("name"),
                "tags": rec.get("tags", []),
                "created_at": rec.get("created_at"),
            })
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("跳过损坏的策略文件 %s: %s", f, e)
    return {"count": len(items), "strategies": items}


def get_strategy(sid: str) -> dict | None:
    """按 id 取单个策略完整内容。不存在返回 None。"""
    target = _STRATEGY_DIR / f"{sid}.json"
    if not target.exists():
        return None
    try:
        with open(target, "r", encoding="utf-8") as fp:
            return json.load(fp)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("读取策略失败 %s: %s", sid, e)
        return None


def delete_strategy(sid: str) -> bool:
    """按 id 删除策略。成功 True，文件不存在 False。"""
    target = _STRATEGY_DIR / f"{sid}.json"
    if not target.exists():
        return False
    try:
        target.unlink()
        return True
    except OSError as e:
        logger.warning("删除策略失败 %s: %s", sid, e)
        return False


# ───────────────────────── 自选股 CRUD ──────────────────────────

def _read_watchlist() -> list[dict]:
    """读自选股列表。文件不存在返回空列表。"""
    if not _WATCHLIST_FILE.exists():
        return []
    try:
        with open(_WATCHLIST_FILE, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("读取自选股失败，重置为空: %s", e)
        return []


def add_to_watchlist(symbol: str, note: str = "") -> dict:
    """添加自选股。若 symbol 已存在则更新 note（不重复添加）。"""
    _ensure_dirs()
    items = _read_watchlist()
    # 已存在则更新 note
    for it in items:
        if it.get("symbol") == symbol:
            it["note"] = note
            it["updated_at"] = time.time()
            _atomic_write_json(_WATCHLIST_FILE, items)
            return {"symbol": symbol, "action": "updated", "total": len(items)}
    # 新增
    items.append({
        "symbol": symbol,
        "note": note,
        "added_at": time.time(),
    })
    _atomic_write_json(_WATCHLIST_FILE, items)
    return {"symbol": symbol, "action": "added", "total": len(items)}


def list_watchlist() -> dict:
    """列出所有自选股。"""
    items = _read_watchlist()
    return {"count": len(items), "watchlist": items}


def remove_from_watchlist(symbol: str) -> dict:
    """从自选股移除。返回剩余数量。"""
    items = _read_watchlist()
    new_items = [it for it in items if it.get("symbol") != symbol]
    if len(new_items) == len(items):
        return {"symbol": symbol, "action": "not_found", "total": len(items)}
    _atomic_write_json(_WATCHLIST_FILE, new_items)
    return {"symbol": symbol, "action": "removed", "total": len(new_items)}
