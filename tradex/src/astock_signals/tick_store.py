"""
Tick 数据本地存储模块 — SQLite 持久化。

用途：
- 逐笔成交数据（tick）落盘到 SQLite
- 支持历史查询和回测数据准备
- 自动建表、索引、去重

设计原则：
- 按股票代码分表（避免单表过大）
- 交易日+时间戳联合去重
- WAL模式提高并发读写性能
- 写操作使用 threading.Lock 保证线程安全
"""

from __future__ import annotations

import re
import os
import sqlite3
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

_DEFAULT_DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data")
_DEFAULT_DB_NAME = "tick_store.db"

# 表名合法字符白名单：仅允许字母、数字、下划线
_SAFE_TABLE_RE = re.compile(r"^[a-zA-Z0-9_]+$")


class TickStore:
    """Tick 数据 SQLite 存储引擎。

    Usage:
        store = TickStore()
        store.save_tick("600519", "20260624", tick_data)
        df = store.load_tick("600519", "20260624")
    """

    def __init__(self, db_path: str = ""):
        if not db_path:
            db_dir = _DEFAULT_DB_DIR
            os.makedirs(db_dir, exist_ok=True)
            db_path = os.path.join(db_dir, _DEFAULT_DB_NAME)
        self._db_path = db_path
        self._local = threading.local()
        self._write_lock = threading.Lock()  # 保护写操作
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """获取线程本地连接（WAL模式）。"""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._db_path, timeout=30)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=10000")
            self._local.conn = conn
        return conn

    def _init_db(self):
        """初始化元数据表。"""
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS _tick_meta (
                code TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                table_name TEXT NOT NULL,
                row_count INTEGER DEFAULT 0,
                updated_at TEXT,
                PRIMARY KEY (code, trade_date)
            )
        """)
        conn.commit()

    def _table_name(self, code: str, trade_date: str) -> str:
        """生成分表名：tick_{code}_{date}

        Raises:
            ValueError: 参数包含非法字符
        """
        safe_code = code.replace(".", "_").replace(" ", "")
        safe_date = trade_date.replace(".", "").replace("-", "").replace(" ", "")
        # 白名单校验，防止 SQL 注入
        if not _SAFE_TABLE_RE.match(safe_code):
            raise ValueError(f"Invalid code for table name: {code!r}")
        if not _SAFE_TABLE_RE.match(safe_date):
            raise ValueError(f"Invalid trade_date for table name: {trade_date!r}")
        return f"tick_{safe_code}_{safe_date}"

    def _ensure_table(self, table_name: str):
        """确保 tick 数据表存在。"""
        conn = self._get_conn()
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS "{table_name}" (
                time TEXT NOT NULL,
                price REAL,
                volume INTEGER,
                amount REAL,
                direction TEXT,
                bid1 REAL,
                ask1 REAL,
                UNIQUE(time, price, volume)
            )
        """)
        conn.execute(f"""
            CREATE INDEX IF NOT EXISTS "idx_{table_name}_time"
            ON "{table_name}" (time)
        """)
        conn.commit()

    def save_tick(self, code: str, trade_date: str, data: list[dict]) -> int:
        """保存 tick 数据（去重插入）。

        Args:
            code: 股票代码
            trade_date: 交易日期 YYYYMMDD
            data: tick 数据列表，每条含 time/price/volume/amount/direction/bid1/ask1

        Returns:
            实际插入行数
        """
        if not data:
            return 0

        table = self._table_name(code, trade_date)
        with self._write_lock:
            self._ensure_table(table)

            conn = self._get_conn()
            inserted = 0
            for row in data:
                try:
                    cursor = conn.execute(
                        f'INSERT OR IGNORE INTO "{table}" '
                        f"(time, price, volume, amount, direction, bid1, ask1) "
                        f"VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            row.get("time", ""),
                            row.get("price"),
                            row.get("volume"),
                            row.get("amount"),
                            row.get("direction", ""),
                            row.get("bid1"),
                            row.get("ask1"),
                        ),
                    )
                    if cursor.rowcount > 0:
                        inserted += 1
                except sqlite3.IntegrityError:
                    pass
                except Exception as e:
                    logger.warning("save_tick row failed: %s", e)

            conn.commit()

            # 更新元数据
            total = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            conn.execute(
                "INSERT OR REPLACE INTO _tick_meta (code, trade_date, table_name, row_count, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (code, trade_date, table, total, datetime.now().isoformat()),
            )
            conn.commit()

        logger.info("Saved %d tick rows for %s/%s (total: %d)", inserted, code, trade_date, total)
        return inserted

    def load_tick(
        self,
        code: str,
        trade_date: str,
        start_time: str = "",
        end_time: str = "",
    ) -> pd.DataFrame:
        """加载 tick 数据。

        Args:
            code: 股票代码
            trade_date: 交易日期 YYYYMMDD
            start_time: 开始时间 HH:MM:SS（可选）
            end_time: 结束时间 HH:MM:SS（可选）

        Returns:
            DataFrame with time/price/volume/amount/direction/bid1/ask1
        """
        table = self._table_name(code, trade_date)
        conn = self._get_conn()

        # 检查表是否存在
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        if not exists:
            return pd.DataFrame()

        query = f'SELECT time, price, volume, amount, direction, bid1, ask1 FROM "{table}"'
        conditions = []
        params = []
        if start_time:
            conditions.append("time >= ?")
            params.append(start_time)
        if end_time:
            conditions.append("time <= ?")
            params.append(end_time)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY time"

        df = pd.read_sql_query(query, conn, params=params)
        return df

    def list_dates(self, code: str) -> list[str]:
        """列出某只股票已存储的所有交易日期。"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT trade_date FROM _tick_meta WHERE code=? ORDER BY trade_date DESC",
            (code,),
        ).fetchall()
        return [r[0] for r in rows]

    def list_codes(self) -> list[str]:
        """列出所有已存储的股票代码。"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT DISTINCT code FROM _tick_meta ORDER BY code"
        ).fetchall()
        return [r[0] for r in rows]

    def get_stats(self) -> list[dict]:
        """获取所有存储表的统计信息。"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT code, trade_date, row_count, updated_at FROM _tick_meta ORDER BY trade_date DESC, code"
        ).fetchall()
        return [
            {
                "code": r[0],
                "trade_date": r[1],
                "row_count": r[2],
                "updated_at": r[3],
            }
            for r in rows
        ]


# 全局单例
_global_store: TickStore | None = None
_store_lock = threading.Lock()


def get_tick_store(db_path: str = "") -> TickStore:
    global _global_store
    if _global_store is None:
        with _store_lock:
            if _global_store is None:
                _global_store = TickStore(db_path)
    return _global_store
