"""写操作 service —— SQLite 存储 CRUD（阶段二工单 17-18）。

设计演进：
- 阶段一（工单 10）：本地 JSON 文件，原子写（tempfile + os.replace）
- 阶段二（工单 17-18）：SQLite + WAL 模式，启动自动迁移 JSON；对外 API 契约不变

存储：
- 数据库路径：tradex-hub/data/written.db（和阶段一 data/written/ 同目录）
- 两表：strategies / watchlist
- WAL 模式 + PRAGMA synchronous=NORMAL（并发友好）

迁移（启动时执行一次）：
- 检测 data/written/strategies/*.json → 读 → 写 SQLite → 重命名为 .migrated
- 检测 data/written/watchlist.json → 同理
- 迁移日志写 data/written/migration.log
- 幂等：.migrated 文件不再触发迁移

并发安全：
- 写入用 BEGIN IMMEDIATE 事务（防 SQLite concurrent write lock）
- 见工单 18 并发测试

对外契约：
- 7 个函数签名与阶段一一致，路由层零改动
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 写操作根目录（tradex-hub/data/）
# 从本文件位置回溯：src/tradex/service/write_service.py → 向上 4 层到 tradex-hub/
_HUB_ROOT = Path(__file__).resolve().parents[4]
_DATA_DIR = _HUB_ROOT / "data"
_WRITTEN_DIR = _DATA_DIR / "written"  # 阶段一 JSON 兜底目录
_STRATEGY_DIR = _WRITTEN_DIR / "strategies"
_WATCHLIST_FILE = _WRITTEN_DIR / "watchlist.json"
_MIGRATION_LOG = _WRITTEN_DIR / "migration.log"

# SQLite 数据库路径（默认值；测试可通过 monkeypatch 覆盖）
_DB_PATH: Path = _DATA_DIR / "written.db"


# ───────────────────────── 数据库初始化 ──────────────────────────

def _get_db_path() -> Path:
    """返回数据库路径（供测试 monkeypatch _DB_PATH 后动态读取）。"""
    return _DB_PATH


def _connect() -> sqlite3.Connection:
    """打开 SQLite 连接，启用 row factory + 外键。

    WAL 与 synchronous 在 init_schema 时设置一次（PRAGMA 是数据库持久属性），
    不在每个连接重复执行——并发场景下重复 PRAGMA 会触发锁冲突。
    """
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_get_db_path()), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def _cursor():
    """上下文管理器：保证连接在使用后被显式关闭。

    Python 的 sqlite3.Connection.__exit__ 只 commit 不关闭连接，导致 Windows
    上临时目录清理时文件被锁。所有 CRUD 用 _cursor() 替代 with _connect()。
    """
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_schema() -> None:
    """建表 + 索引 + WAL 设置（IF NOT EXISTS，幂等）。

    WAL 与 synchronous=NORMAL 是数据库持久属性，只需在首次初始化时设置一次；
    之后所有连接自动继承。这里每次 init_schema 也重设一遍是安全的（SQLite 会
    短锁数据库改属性，但通常无并发，并发场景由 _bootstrap 单次调用保护）。
    """
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    # 用独立连接设置 WAL（避免和业务连接争锁）
    setup_conn = sqlite3.connect(str(_get_db_path()), timeout=10.0)
    try:
        setup_conn.execute("PRAGMA journal_mode=WAL")
        setup_conn.execute("PRAGMA synchronous=NORMAL")
        setup_conn.commit()
    finally:
        setup_conn.close()
    # 建表用另一个连接
    conn = _connect()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS strategies (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                content TEXT NOT NULL,
                tags TEXT,
                created_at REAL NOT NULL,
                updated_at REAL
            );

            CREATE TABLE IF NOT EXISTS watchlist (
                symbol TEXT PRIMARY KEY,
                note TEXT,
                added_at REAL NOT NULL,
                updated_at REAL
            );

            CREATE INDEX IF NOT EXISTS idx_strategies_created
                ON strategies(created_at DESC);
        """)
        conn.commit()
    finally:
        conn.close()


# ───────────────────────── 迁移逻辑 ──────────────────────────

def migrate_from_json() -> dict[str, Any]:
    """启动时执行一次：把阶段一 JSON 文件迁到 SQLite，原文件改名 .migrated。

    Returns:
        {"strategies_migrated": int, "watchlist_migrated": int, "errors": list[str]}
    """
    # 迁移前必须先建表（保证幂等性：单独调用 migrate 也安全）
    init_schema()
    result = {"strategies_migrated": 0, "watchlist_migrated": 0, "errors": []}
    _WRITTEN_DIR.mkdir(parents=True, exist_ok=True)
    _STRATEGY_DIR.mkdir(parents=True, exist_ok=True)

    # 1) 迁移 strategies/*.json
    try:
        for json_file in sorted(_STRATEGY_DIR.glob("*.json")):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    record = json.load(f)
                # 检查是否已存在于 SQLite（幂等）
                with _cursor() as conn:
                    existing = conn.execute(
                        "SELECT 1 FROM strategies WHERE id = ?", (record.get("id"),)
                    ).fetchone()
                    if existing:
                        # 已存在则只重命名 JSON，不重复写
                        pass
                    else:
                        conn.execute(
                            "INSERT INTO strategies (id, name, content, tags, created_at, updated_at) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            (
                                str(record.get("id")),
                                str(record.get("name", "")),
                                str(record.get("content", "")),
                                json.dumps(record.get("tags", []), ensure_ascii=False),
                                float(record.get("created_at", time.time())),
                                record.get("updated_at"),
                            ),
                        )
                # 重命名原文件为 .migrated（不删，兜底）
                migrated_path = json_file.with_suffix(".json.migrated")
                try:
                    json_file.rename(migrated_path)
                except OSError as e:
                    result["errors"].append(f"rename {json_file.name}: {e}")
                result["strategies_migrated"] += 1
            except (json.JSONDecodeError, OSError, KeyError) as e:
                result["errors"].append(f"{json_file.name}: {e}")
                logger.warning("迁移策略失败 %s: %s", json_file, e)
    except Exception as e:
        result["errors"].append(f"strategies dir: {e}")

    # 2) 迁移 watchlist.json
    try:
        if _WATCHLIST_FILE.exists():
            with open(_WATCHLIST_FILE, "r", encoding="utf-8") as f:
                items = json.load(f)
            if isinstance(items, list):
                with _cursor() as conn:
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        symbol = item.get("symbol")
                        if not symbol:
                            continue
                        existing = conn.execute(
                            "SELECT 1 FROM watchlist WHERE symbol = ?", (symbol,)
                        ).fetchone()
                        if not existing:
                            conn.execute(
                                "INSERT INTO watchlist (symbol, note, added_at, updated_at) "
                                "VALUES (?, ?, ?, ?)",
                                (
                                    str(symbol),
                                    item.get("note", ""),
                                    float(item.get("added_at", time.time())),
                                    item.get("updated_at"),
                                ),
                            )
                        result["watchlist_migrated"] += 1
            # 重命名原文件
            migrated_path = _WATCHLIST_FILE.with_suffix(".json.migrated")
            try:
                _WATCHLIST_FILE.rename(migrated_path)
            except OSError as e:
                result["errors"].append(f"rename watchlist.json: {e}")
    except Exception as e:
        result["errors"].append(f"watchlist: {e}")
        logger.warning("迁移自选股失败: %s", e)

    # 3) 写迁移日志
    try:
        with open(_MIGRATION_LOG, "a", encoding="utf-8") as f:
            f.write(
                f"{time.strftime('%Y-%m-%d %H:%M:%S')} "
                f"strategies={result['strategies_migrated']} "
                f"watchlist={result['watchlist_migrated']} "
                f"errors={len(result['errors'])}\n"
            )
    except OSError as e:
        logger.warning("写迁移日志失败: %s", e)

    if result["strategies_migrated"] or result["watchlist_migrated"]:
        logger.info(
            "迁移完成: %d 策略, %d 自选股, %d 错误",
            result["strategies_migrated"],
            result["watchlist_migrated"],
            len(result["errors"]),
        )
    return result


# ───────────────────────── 策略 CRUD ──────────────────────────

def create_strategy(name: str, content: str, tags: list[str] | None = None) -> dict:
    """创建量化策略 —— 保存到 SQLite strategies 表。

    Returns:
        {"id": str, "name": str, "created_at": float, "path": str}
    """
    _ensure_bootstrap()
    # 毫秒时间戳作 id；并发场景下同一毫秒冲突时追加线程 id + 随机
    import random
    sid = f"{int(time.time() * 1000)}-{threading.get_ident()}-{random.randint(0, 9999)}"
    created_at = time.time()
    with _cursor() as conn:
        conn.execute(
            "INSERT INTO strategies (id, name, content, tags, created_at) VALUES (?, ?, ?, ?, ?)",
            (sid, name, content, json.dumps(tags or [], ensure_ascii=False), created_at),
        )
        conn.commit()
    logger.info("策略已保存: %s (%s)", name, sid)
    return {"id": sid, "name": name, "created_at": created_at, "path": str(_DB_PATH)}


def list_strategies() -> dict:
    """列出所有已保存策略（仅元信息，不含 content）。"""
    _ensure_bootstrap()
    with _cursor() as conn:
        rows = conn.execute(
            "SELECT id, name, tags, created_at FROM strategies ORDER BY created_at DESC"
        ).fetchall()
    items = []
    for row in rows:
        try:
            tags = json.loads(row["tags"]) if row["tags"] else []
        except json.JSONDecodeError:
            tags = []
        items.append({
            "id": row["id"],
            "name": row["name"],
            "tags": tags,
            "created_at": row["created_at"],
        })
    return {"count": len(items), "strategies": items}


def get_strategy(sid: str) -> dict | None:
    """按 id 取单个策略完整内容。不存在返回 None。"""
    _ensure_bootstrap()
    with _cursor() as conn:
        row = conn.execute(
            "SELECT * FROM strategies WHERE id = ?", (sid,)
        ).fetchone()
    if not row:
        return None
    try:
        tags = json.loads(row["tags"]) if row["tags"] else []
    except json.JSONDecodeError:
        tags = []
    return {
        "id": row["id"],
        "name": row["name"],
        "content": row["content"],
        "tags": tags,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def delete_strategy(sid: str) -> bool:
    """按 id 删除策略。成功 True，文件不存在 False。"""
    _ensure_bootstrap()
    with _cursor() as conn:
        cur = conn.execute("DELETE FROM strategies WHERE id = ?", (sid,))
        conn.commit()
        return cur.rowcount > 0


# ───────────────────────── 自选股 CRUD ──────────────────────────

def add_to_watchlist(symbol: str, note: str = "") -> dict:
    """添加自选股。若 symbol 已存在则更新 note（UPSERT）。"""
    _ensure_bootstrap()
    now = time.time()
    with _cursor() as conn:
        # BEGIN IMMEDIATE 保证并发写安全（工单 18）
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT 1 FROM watchlist WHERE symbol = ?", (symbol,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE watchlist SET note = ?, updated_at = ? WHERE symbol = ?",
                (note, now, symbol),
            )
            action = "updated"
        else:
            conn.execute(
                "INSERT INTO watchlist (symbol, note, added_at) VALUES (?, ?, ?)",
                (symbol, note, now),
            )
            action = "added"
        conn.commit()
    # 统计总数
    with _cursor() as conn:
        total = conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
    return {"symbol": symbol, "action": action, "total": total}


def list_watchlist() -> dict:
    """列出所有自选股。"""
    _ensure_bootstrap()
    with _cursor() as conn:
        rows = conn.execute(
            "SELECT symbol, note, added_at, updated_at FROM watchlist ORDER BY added_at ASC"
        ).fetchall()
    items = []
    for row in rows:
        items.append({
            "symbol": row["symbol"],
            "note": row["note"] or "",
            "added_at": row["added_at"],
            "updated_at": row["updated_at"],
        })
    return {"count": len(items), "watchlist": items}


def remove_from_watchlist(symbol: str) -> dict:
    """从自选股移除。返回剩余数量。"""
    _ensure_bootstrap()
    with _cursor() as conn:
        cur = conn.execute("DELETE FROM watchlist WHERE symbol = ?", (symbol,))
        deleted = cur.rowcount
        conn.commit()
        total = conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
    if deleted == 0:
        return {"symbol": symbol, "action": "not_found", "total": total}
    return {"symbol": symbol, "action": "removed", "total": total}


# ───────────────────────── 启动时自动初始化与迁移 ──────────────────────────

_bootstrap_done = False
_bootstrap_lock = threading.Lock()

def _bootstrap() -> None:
    """模块首次使用时执行：建 schema + 迁移 JSON（幂等）。

    改为惰性触发（不在模块加载时执行），确保测试 fixture monkeypatch 路径后
    才执行，避免污染真实数据目录。线程锁保护并发场景下只触发一次。
    """
    global _bootstrap_done
    if _bootstrap_done:
        return
    with _bootstrap_lock:
        if _bootstrap_done:
            return
        try:
            init_schema()
            migrate_from_json()
        except Exception as e:
            logger.error("write_service bootstrap 失败（不阻断后续）：%s", e)
        finally:
            _bootstrap_done = True


def _ensure_bootstrap() -> None:
    """每个对外 API 调用前触发一次 bootstrap（惰性）。"""
    if not _bootstrap_done:
        _bootstrap()


# 改为惰性 —— 不在模块加载时调用
