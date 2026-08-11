"""Content-hash memoization utility with TTL.

Used by all three stages:
- Stage 1: cache search results by query hash
- Stage 2: cache resume+JD checks by ``hash(resume_version + jd_text)``
- Stage 3: cache match scores by the same composite key

Stores a flat JSON file per cache namespace (directory per stage) with
structure::

    {
      "<hash>": {"value": ..., "ts": <unix_epoch>}
    }

Eviction is lazy (on read) to keep it simple — the cache file is
rewritten when stale entries are pruned.
"""
from __future__ import annotations

import hashlib

# Bump this to invalidate all cached entries when scoring logic changes
_CACHE_VERSION = "v2"
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, TypeVar

from ..config import settings

T = TypeVar("T")


@dataclass
class CacheEntry(Generic[T]):
    value: T
    ts: float


class ContentHashCache:
    """Simple file-backed memoization cache keyed by content hash."""

    def __init__(self, namespace: str, ttl_seconds: int | None = None) -> None:
        self.namespace = namespace
        self.ttl = ttl_seconds or (settings.CACHE_TTL_HOURS * 3600)
        self._dir = Path(settings.CONTENT_HASH_CACHE_DIR) / namespace
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / "cache.json"
        self._data: dict[str, CacheEntry[Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text())
            for k, v in raw.items():
                if isinstance(v, dict) and "value" in v and "ts" in v:
                    self._data[k] = CacheEntry(value=v["value"], ts=v["ts"])
        except (json.JSONDecodeError, OSError):
            # Corrupt cache file — start fresh
            self._data = {}

    def _save(self) -> None:
        serialisable = {k: {"value": v.value, "ts": v.ts} for k, v in self._data.items()}
        try:
            self._path.write_text(json.dumps(serialisable))
        except OSError as exc:
            # Non-fatal — log and continue
            import logging
            logging.getLogger(__name__).warning("Failed to write cache: %s", exc)

    @staticmethod
    def _hash(*parts: str | bytes) -> str:
        h = hashlib.sha256()
        for p in parts:
            h.update(p if isinstance(p, bytes) else p.encode("utf-8"))
        return h.hexdigest()

    def make_key(self, *parts: str | bytes) -> str:
        return self._hash(*parts)

    def get(self, key: str) -> Any | None:
        """Retrieve a value if present and not expired."""
        entry = self._data.get(key)
        if entry is None:
            return None
        if time.time() - entry.ts > self.ttl:
            # Expired — remove and report miss
            self._data.pop(key, None)
            self._save()
            return None
        return entry.value

    def set(self, key: str, value: Any) -> None:
        """Store a value with the current timestamp."""
        self._data[key] = CacheEntry(value=value, ts=time.time())
        # Enforce max entries (FIFO eviction)
        if len(self._data) > settings.MAX_CACHE_ENTRIES:
            oldest = min(self._data.items(), key=lambda kv: kv[1].ts)[0]
            self._data.pop(oldest, None)
        self._save()

    def delete(self, key: str) -> bool:
        if key in self._data:
            self._data.pop(key)
            self._save()
            return True
        return False

    def clear(self) -> int:
        count = len(self._data)
        self._data.clear()
        self._save()
        return count

    def prune_expired(self) -> int:
        """Remove all expired entries. Returns number removed."""
        now = time.time()
        before = len(self._data)
        self._data = {
            k: v for k, v in self._data.items()
            if now - v.ts <= self.ttl
        }
        removed = before - len(self._data)
        if removed:
            self._save()
        return removed


# Pre-configured cache instances for each stage
search_cache = ContentHashCache("search", ttl_seconds=48 * 3600)   # 48h
resume_cache = ContentHashCache("resume", ttl_seconds=72 * 3600)   # 72h
jobs_cache = ContentHashCache("jobs", ttl_seconds=24 * 3600)       # 24h
# Dedup cache: 14-day TTL matches the search recency window
dedup_cache = ContentHashCache("dedup", ttl_seconds=14 * 24 * 3600)  # 14 days