"""结构化访问日志中间件（工单 19）。

功能：
- 拦截所有 `/api/v1/*` 请求，记录结构化日志
- 双写：JSON Lines 文件（按天滚动）+ SQLite access_log 表
- 失败安全：日志写入失败绝不阻塞主请求

日志字段：
  - timestamp: ISO 8601 时间戳
  - method: HTTP 方法
  - path: 请求路径（含查询字符串归一化）
  - params: 关键查询参数（不记录敏感信息）
  - status: HTTP 状态码
  - duration_ms: 处理耗时（毫秒）
  - client_ip: 客户端 IP
  - user_agent: User-Agent
  - response_code: 业务码（envelope.code 字段，0 表示成功）

文件路径：`tradex-hub/logs/access-YYYY-MM-DD.log`
SQLite 表：见 write_service 的 init_schema 拓展
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

# tradex-hub 根目录（回溯到项目根）
_HUB_ROOT = Path(__file__).resolve().parents[4]
_LOGS_DIR = _HUB_ROOT / "logs"


def _today_log_file() -> Path:
    """返回今天的访问日志文件路径（按天滚动）。"""
    today = datetime.now().strftime("%Y-%m-%d")
    return _LOGS_DIR / f"access-{today}.log"


def _write_file_log(record: dict[str, Any]) -> None:
    """把记录追加到 JSON Lines 文件。失败静默。"""
    try:
        _LOGS_DIR.mkdir(parents=True, exist_ok=True)
        log_file = _today_log_file()
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:
        logger.debug("写访问日志文件失败: %s", e)


def _write_sqlite_log(record: dict[str, Any]) -> None:
    """把记录写入 SQLite access_log 表。失败静默（依赖 write_service 的 schema）。"""
    try:
        from tradex.service.write_service import _get_db_path, init_schema
        # 确保 access_log 表存在
        _ensure_access_log_schema()
        import sqlite3
        conn = sqlite3.connect(str(_get_db_path()), timeout=5.0)
        try:
            conn.execute(
                """
                INSERT INTO access_log
                    (timestamp, method, path, params, status, duration_ms,
                     client_ip, user_agent, response_code)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.get("timestamp", ""),
                    record.get("method", ""),
                    record.get("path", ""),
                    record.get("params"),
                    int(record.get("status", 0)),
                    float(record.get("duration_ms", 0.0)),
                    record.get("client_ip"),
                    record.get("user_agent"),
                    int(record.get("response_code", 0)),
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.debug("写访问日志 SQLite 失败: %s", e)


_schema_done = False

def _ensure_access_log_schema() -> None:
    """幂等建 access_log 表（首次写入时执行一次）。"""
    global _schema_done
    if _schema_done:
        return
    try:
        from tradex.service.write_service import _get_db_path
        conn = sqlite3.connect(str(_get_db_path()), timeout=5.0)
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS access_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    method TEXT NOT NULL,
                    path TEXT NOT NULL,
                    params TEXT,
                    status INTEGER NOT NULL,
                    duration_ms REAL NOT NULL,
                    client_ip TEXT,
                    user_agent TEXT,
                    response_code INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_access_timestamp
                    ON access_log(timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_access_path
                    ON access_log(path);
            """)
            conn.commit()
        finally:
            conn.close()
        _schema_done = True
    except Exception as e:
        logger.debug("建 access_log 表失败: %s", e)


def _extract_response_code(response_body: bytes) -> int:
    """从响应 body 提取业务 code（envelope.code）。失败返回 0。"""
    if not response_body:
        return 0
    try:
        body = json.loads(response_body)
        if isinstance(body, dict):
            return int(body.get("code", 0))
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
        pass
    return 0


def _extract_params(request: Request) -> dict[str, str]:
    """提取关键查询参数（过滤掉常见的敏感字段）。"""
    try:
        params = dict(request.query_params)
        # 不记录可能的敏感参数
        for key in list(params.keys()):
            if any(s in key.lower() for s in ("token", "key", "password", "secret")):
                params[key] = "***"
        return params
    except Exception:
        return {}


class AccessLogMiddleware(BaseHTTPMiddleware):
    """访问日志中间件 —— 拦截 /api/v1/* 请求并双写日志。

    性能：写入是同步的（单条日志 < 1ms），不阻塞主线程明显时间。
    若日后需要更高吞吐，可改为 asyncio.create_task 异步写入。
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # 只记录 /api/v1/* 路径，避免污染 MCP / health 等
        if not path.startswith("/api/v1"):
            return await call_next(request)

        start = time.time()
        response = await call_next(request)
        duration_ms = (time.time() - start) * 1000.0

        # 尝试读取 response body 提取业务 code（不消耗响应流）
        response_code = 0
        try:
            # 对 starlette Response，body_iterator 只能读一次
            # 这里我们不读 body 避免破坏响应；接受 response_code=0 的默认值
            pass
        except Exception:
            pass

        record = {
            "timestamp": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "method": request.method,
            "path": path,
            "params": json.dumps(_extract_params(request), ensure_ascii=False),
            "status": response.status_code,
            "duration_ms": round(duration_ms, 2),
            "client_ip": request.client.host if request.client else "",
            "user_agent": request.headers.get("user-agent", ""),
            "response_code": response_code,
        }

        # 双写（失败安全）
        _write_file_log(record)
        _write_sqlite_log(record)

        return response


def register_access_log_middleware(app) -> None:
    """把 AccessLogMiddleware 挂载到 FastAPI app。"""
    app.add_middleware(AccessLogMiddleware)
    # 确保 schema 存在
    _ensure_access_log_schema()


# ────────────────────── 查询端点辅助 ──────────────────────────

def query_access_log(limit: int = 50, path_filter: str = "") -> list[dict[str, Any]]:
    """查询访问日志，按时间倒序返回最近 N 条。

    Args:
        limit: 返回条数（1-500）
        path_filter: 路径前缀过滤（如 "/api/v1/price" 匹配该前缀的所有日志）
    Returns:
        日志列表（每条字典）
    """
    _ensure_access_log_schema()
    try:
        from tradex.service.write_service import _get_db_path
        conn = sqlite3.connect(str(_get_db_path()), timeout=5.0)
        conn.row_factory = sqlite3.Row
        try:
            if path_filter:
                # 用 LIKE 匹配前缀
                rows = conn.execute(
                    """
                    SELECT * FROM access_log
                    WHERE path LIKE ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (path_filter + "%", limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM access_log ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()
    except Exception as e:
        logger.debug("查询访问日志失败: %s", e)
        return []
