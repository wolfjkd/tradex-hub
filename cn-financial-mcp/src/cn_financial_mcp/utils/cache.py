"""
TTL-based two-level cache for AKShare data.

Caching strategy:
- Realtime quotes: 30 seconds (memory only)
- Daily price data: 5 minutes (memory only)
- Financial statements: 24 hours (memory + file)
- Company info: 24 hours (memory + file)
- Macro data: 7 days (memory + file)

Two-level cache:
- Level 1: In-memory LRU with TTL (fast, volatile)
- Level 2: File-based JSON cache (persistent across restarts)

Thread-safe with threading.Lock and configurable max_size LRU eviction.
"""

import hashlib
import json
import logging
import os
import time
import threading
from pathlib import Path
from typing import Any
from collections import OrderedDict

logger = logging.getLogger(__name__)

# Default TTL values in seconds
TTL_REALTIME = 30         # Real-time quotes
TTL_DAILY = 300           # 5 minutes for daily price
TTL_FINANCIAL = 86400     # 24 hours for financial data
TTL_COMPANY = 86400       # 24 hours for company info
TTL_MACRO = 604800        # 7 days for macro data

# TTL 阈值：超过此值的数据同时写入文件缓存
FILE_CACHE_TTL_THRESHOLD = 3600  # 1 hour


class TTLCache:
    """Thread-safe TTL cache backed by OrderedDict with LRU eviction.

    Args:
        max_size: Maximum number of entries. Oldest entries evicted when exceeded.
                  0 means unlimited (default: 5000).
    """

    def __init__(self, max_size: int = 5000):
        self._store: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._max_size = max_size
        self._lock = threading.Lock()
        self._hit_count: int = 0
        self._miss_count: int = 0

    def get(self, key: str) -> Any | None:
        """Get a cached value if it exists and hasn't expired."""
        with self._lock:
            if key in self._store:
                value, expires_at = self._store[key]
                if time.time() < expires_at:
                    # Move to end (most recently used)
                    self._store.move_to_end(key)
                    self._hit_count += 1
                    return value
                # Expired, remove it
                del self._store[key]
            self._miss_count += 1
        return None

    def set(self, key: str, value: Any, ttl: int = TTL_DAILY) -> None:
        """Store a value with a TTL in seconds."""
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            self._store[key] = (value, time.time() + ttl)
            # LRU eviction
            while self._max_size > 0 and len(self._store) > self._max_size:
                self._store.popitem(last=False)

    def invalidate(self, key: str) -> None:
        """Remove a specific cached entry."""
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        """Clear all cached entries."""
        with self._lock:
            self._store.clear()
            self._hit_count = 0
            self._miss_count = 0

    def cleanup(self) -> int:
        """Remove all expired entries. Returns number of entries removed."""
        now = time.time()
        with self._lock:
            expired = [k for k, (_, exp) in self._store.items() if now >= exp]
            for k in expired:
                del self._store[k]
        return len(expired)

    @property
    def size(self) -> int:
        """Number of entries in cache (including possibly expired)."""
        with self._lock:
            return len(self._store)

    @property
    def hit_rate(self) -> float:
        """Cache hit rate (0.0 ~ 1.0)."""
        total = self._hit_count + self._miss_count
        return self._hit_count / total if total > 0 else 0.0

    @property
    def stats(self) -> dict:
        """Cache statistics."""
        with self._lock:
            total = self._hit_count + self._miss_count
            return {
                "size": len(self._store),
                "max_size": self._max_size,
                "hits": self._hit_count,
                "misses": self._miss_count,
                "hit_rate": self._hit_count / total if total > 0 else 0.0,
            }


class FileCache:
    """文件级缓存，进程重启不丢失。

    使用 JSON 文件存储缓存数据，支持 TTL 过期。
    适用于长 TTL 数据（财报、公司信息、宏观数据等）。

    Args:
        cache_dir: 缓存文件目录路径
    """

    def __init__(self, cache_dir: str = ".cache"):
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _key_to_path(self, key: str) -> Path:
        """将缓存键转换为文件路径。"""
        safe_key = hashlib.md5(key.encode()).hexdigest()
        return self._cache_dir / f"{safe_key}.json"

    def get(self, key: str) -> Any | None:
        """从 JSON 文件读取缓存。

        Args:
            key: 缓存键

        Returns:
            缓存值，未命中或已过期返回 None
        """
        path = self._key_to_path(key)
        if not path.exists():
            return None

        try:
            with self._lock:
                data = json.loads(path.read_text(encoding="utf-8"))
                if time.time() < data.get("expires_at", 0):
                    return data.get("value")
                # 已过期，删除文件
                path.unlink(missing_ok=True)
        except Exception as exc:
            logger.debug("文件缓存读取失败 %s: %s", key, exc)
        return None

    def set(self, key: str, value: Any, ttl: int) -> None:
        """写入 JSON 文件缓存。

        Args:
            key: 缓存键
            value: 缓存值（必须 JSON 可序列化）
            ttl: TTL 秒数
        """
        path = self._key_to_path(key)
        data = {
            "key": key,
            "value": value,
            "expires_at": time.time() + ttl,
            "created_at": time.time(),
        }
        try:
            with self._lock:
                path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            logger.debug("文件缓存写入失败 %s: %s", key, exc)

    def invalidate(self, key: str) -> None:
        """删除指定缓存文件。"""
        path = self._key_to_path(key)
        with self._lock:
            path.unlink(missing_ok=True)

    def clear(self) -> int:
        """清空所有文件缓存，返回删除的文件数。"""
        count = 0
        with self._lock:
            for path in self._cache_dir.glob("*.json"):
                try:
                    path.unlink()
                    count += 1
                except Exception:
                    pass
        return count

    def cleanup(self) -> int:
        """清理过期文件，返回删除的数量。"""
        count = 0
        now = time.time()
        with self._lock:
            for path in self._cache_dir.glob("*.json"):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    if now >= data.get("expires_at", 0):
                        path.unlink(missing_ok=True)
                        count += 1
                except Exception:
                    path.unlink(missing_ok=True)
                    count += 1
        return count

    @property
    def size(self) -> int:
        """缓存文件数量。"""
        return len(list(self._cache_dir.glob("*.json")))


class TwoLevelCache:
    """两级缓存：内存(LRU) + 文件(JSON)。

    短 TTL 数据（< 1小时）仅写入内存；
    长 TTL 数据（>= 1小时）同时写入内存和文件，进程重启后从文件恢复。

    Args:
        max_size: 内存缓存最大条目数
        cache_dir: 文件缓存目录
        file_enabled: 是否启用文件缓存
    """

    def __init__(
        self,
        max_size: int = 5000,
        cache_dir: str = ".cache",
        file_enabled: bool = True,
    ):
        self._memory = TTLCache(max_size)
        self._file = FileCache(cache_dir) if file_enabled else None
        self._file_enabled = file_enabled

    def get(self, key: str) -> Any | None:
        """读取缓存：先查内存，未命中再查文件。

        Args:
            key: 缓存键

        Returns:
            缓存值，未命中返回 None
        """
        # Level 1: 内存缓存
        result = self._memory.get(key)
        if result is not None:
            return result

        # Level 2: 文件缓存
        if self._file is not None:
            result = self._file.get(key)
            if result is not None:
                # 文件命中，回填内存缓存（短期 TTL 避免内存膨胀）
                self._memory.set(key, result, ttl=min(TTL_DAILY, 3600))
                return result

        return None

    def set(self, key: str, value: Any, ttl: int = TTL_DAILY) -> None:
        """写入缓存：内存必写，长 TTL 数据同时写文件。

        Args:
            key: 缓存键
            value: 缓存值
            ttl: TTL 秒数
        """
        # Level 1: 始终写入内存
        self._memory.set(key, value, ttl)

        # Level 2: 长 TTL 数据写入文件
        if self._file is not None and ttl >= FILE_CACHE_TTL_THRESHOLD:
            self._file.set(key, value, ttl)

    def invalidate(self, key: str) -> None:
        """同时清除内存和文件缓存。"""
        self._memory.invalidate(key)
        if self._file is not None:
            self._file.invalidate(key)

    def clear(self) -> None:
        """清空所有缓存。"""
        self._memory.clear()
        if self._file is not None:
            self._file.clear()

    def cleanup(self) -> int:
        """清理过期条目，返回清理数量。"""
        count = self._memory.cleanup()
        if self._file is not None:
            count += self._file.cleanup()
        return count

    @property
    def stats(self) -> dict:
        """缓存统计信息。"""
        stats = self._memory.stats
        stats["file_size"] = self._file.size if self._file else 0
        stats["file_enabled"] = self._file_enabled
        return stats


# Global cache instance (two-level cache)
cache = TwoLevelCache()
