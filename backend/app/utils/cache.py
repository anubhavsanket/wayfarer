"""Redis-backed content-hash memoization cache with TTL.

Used by all three stages:
- Stage 1: cache search results by query hash, fetched page content by URL hash
- Stage 2: cache LLM responses (keyword extraction, bullet rewrites) and embeddings
- Stage 3: cache LLM responses (classification), embeddings (JD ↔ resume similarity)

Stores JSON-serialisable values as Redis string keys with per-namespace TTLs.
All operations are async and fail gracefully — a Redis outage or connection
failure returns cache misses (``None`` / ``False``) so the rest of the
pipeline stays functional.

Usage::

    from .utils.cache import llm_cache, embed_cache, page_cache, query_cache

    # Check before an expensive call
    cached = await llm_cache.get(key)
    if cached is not None:
        return cached

    result = await expensive_call()
    await llm_cache.set(key, result)
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import Any

import redis.asyncio as aioredis

from ..config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level Redis connection (lazy, initialised on first use)
# ---------------------------------------------------------------------------

_redis: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis | None:
    """Return the Redis client, creating it lazily on first call."""
    global _redis
    if _redis is not None:
        return _redis
    try:
        _redis = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=5,
        )
        return _redis
    except Exception as exc:
        logger.warning("Redis connection failed: %s", exc)
        return None


async def init_cache() -> None:
    """Proactively initialise the Redis connection (called from lifespan).

    Logs a warning if Redis is unreachable but does NOT raise — the app
    continues without caching.
    """
    client = _get_redis()
    if client is not None:
        try:
            await client.ping()
            logger.info("Redis cache connected: %s", settings.REDIS_URL)
        except Exception as exc:
            logger.warning("Redis ping failed (%s); caching disabled", exc)
            # Reset so _get_redis() re-attempts on next call
            global _redis
            _redis = None


async def close_cache() -> None:
    """Gracefully close the Redis connection."""
    global _redis
    if _redis is not None:
        try:
            await _redis.aclose()
        except Exception:
            pass
        _redis = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_hash_key(*parts: str | bytes) -> str:
    """Deterministic SHA-256 hash key from string/bytes parts."""
    h = hashlib.sha256()
    for p in parts:
        h.update(p if isinstance(p, bytes) else p.encode("utf-8"))
    return h.hexdigest()


def _serialise(value: Any) -> str:
    """JSON-serialise a cache value (handles Pydantic models, datetime, etc.)."""
    if hasattr(value, "model_dump"):
        return json.dumps(value.model_dump())
    return json.dumps(value, default=str)


def _deserialise(raw: str) -> Any:
    """JSON-deserialise a cached value."""
    return json.loads(raw)


# ---------------------------------------------------------------------------
# RedisCache
# ---------------------------------------------------------------------------

class RedisCache:
    """Async Redis-backed key-value cache with per-namespace TTL.

    All methods are fire-and-forget safe: any Redis error is logged and
    treated as a cache miss so callers can fall through to the real source.
    """

    def __init__(self, namespace: str, ttl_seconds: int) -> None:
        self.namespace = namespace
        self.ttl = ttl_seconds

    def _key(self, key: str) -> str:
        """Full Redis key including namespace prefix."""
        return f"wayfarer:{self.namespace}:{key}"

    # -- async API -----------------------------------------------------------

    async def get(self, key: str) -> Any | None:
        """Return the cached value or ``None`` on miss / error."""
        client = _get_redis()
        if client is None:
            return None
        try:
            raw = await client.get(self._key(key))
            if raw is None:
                return None
            return _deserialise(raw)
        except Exception as exc:
            logger.debug("Redis GET %s failed: %s", self._key(key), exc)
            return None

    async def set(self, key: str, value: Any) -> bool:
        """Store a value. Returns True on success, False on error."""
        client = _get_redis()
        if client is None:
            return False
        try:
            await client.set(self._key(key), _serialise(value), ex=self.ttl)
            return True
        except Exception as exc:
            logger.debug("Redis SET %s failed: %s", self._key(key), exc)
            return False

    async def delete(self, key: str) -> bool:
        """Remove a key. Returns True if the key existed."""
        client = _get_redis()
        if client is None:
            return False
        try:
            return bool(await client.delete(self._key(key)))
        except Exception as exc:
            logger.debug("Redis DEL %s failed: %s", self._key(key), exc)
            return False

    async def exists(self, key: str) -> bool:
        client = _get_redis()
        if client is None:
            return False
        try:
            return bool(await client.exists(self._key(key)))
        except Exception:
            return False

    async def clear(self) -> int:
        """Delete all keys in this namespace. Returns count deleted."""
        client = _get_redis()
        if client is None:
            return 0
        try:
            pattern = f"wayfarer:{self.namespace}:*"
            count = 0
            async for k in client.scan_iter(match=pattern, count=200):
                await client.delete(k)
                count += 1
            return count
        except Exception as exc:
            logger.debug("Redis CLEAR %s failed: %s", self.namespace, exc)
            return 0


# ---------------------------------------------------------------------------
# Pre-configured cache instances
# ---------------------------------------------------------------------------
# TTLs are configured in Settings (config.py) and converted to seconds here.

llm_cache = RedisCache("llm", ttl_seconds=settings.CACHE_TTL_LLM_SECONDS)
embed_cache = RedisCache("embed", ttl_seconds=settings.CACHE_TTL_EMBEDDING_SECONDS)
page_cache = RedisCache("pages", ttl_seconds=settings.CACHE_TTL_PAGE_SECONDS)
query_cache = RedisCache("queries", ttl_seconds=settings.CACHE_TTL_QUERY_SECONDS)
