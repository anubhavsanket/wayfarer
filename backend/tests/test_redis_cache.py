"""Tests for the Redis-backed cache layer.

Covers:
- Hash key determinism
- RedisCache graceful degradation when Redis is unavailable
- Cache namespace configuration
- LLM response caching in the router (cache hit path)
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

# No external API keys during tests
for key in ("TAVILY_API_KEY", "BRAVE_API_KEY", "NVIDIA_NIM_API_KEY", "OPENROUTER_API_KEY"):
    os.environ.pop(key, None)


# ---------------------------------------------------------------------------
# Hash key determinism
# ---------------------------------------------------------------------------

class TestHashKey:
    def test_make_hash_key_deterministic(self):
        from backend.app.utils.cache import make_hash_key
        a = make_hash_key("hello world")
        b = make_hash_key("hello world")
        assert a == b
        assert len(a) == 64  # SHA-256 hex

    def test_make_hash_key_differs_for_different_inputs(self):
        from backend.app.utils.cache import make_hash_key
        a = make_hash_key("foo")
        b = make_hash_key("bar")
        assert a != b

    def test_make_hash_key_multiple_parts(self):
        from backend.app.utils.cache import make_hash_key
        key = make_hash_key("part1", "part2", "part3")
        assert len(key) == 64

    def test_make_hash_key_bytes_input(self):
        from backend.app.utils.cache import make_hash_key
        key = make_hash_key(b"binary", "text")
        assert len(key) == 64


# ---------------------------------------------------------------------------
# RedisCache graceful degradation (no Redis running)
# ---------------------------------------------------------------------------

class TestRedisCacheGracefulDegradation:
    """When Redis is unavailable, all operations should return safe defaults."""

    def test_get_returns_none(self):
        from backend.app.utils.cache import RedisCache
        cache = RedisCache("test", ttl_seconds=60)
        # Use a FakeRedis by overriding _get_redis
        import backend.app.utils.cache as cache_mod
        original = cache_mod._redis
        cache_mod._redis = None  # simulate no Redis
        try:
            result = asyncio.get_event_loop().run_until_complete(
                cache.get("nonexistent")
            )
            assert result is None
        finally:
            cache_mod._redis = original

    def test_set_returns_false(self):
        from backend.app.utils.cache import RedisCache
        cache = RedisCache("test", ttl_seconds=60)
        import backend.app.utils.cache as cache_mod
        original = cache_mod._redis
        cache_mod._redis = None
        try:
            result = asyncio.get_event_loop().run_until_complete(
                cache.set("key", "value")
            )
            assert result is False
        finally:
            cache_mod._redis = original

    def test_clear_returns_zero(self):
        from backend.app.utils.cache import RedisCache
        cache = RedisCache("test", ttl_seconds=60)
        import backend.app.utils.cache as cache_mod
        original = cache_mod._redis
        cache_mod._redis = None
        try:
            result = asyncio.get_event_loop().run_until_complete(cache.clear())
            assert result == 0
        finally:
            cache_mod._redis = original


# ---------------------------------------------------------------------------
# Cache namespace configuration
# ---------------------------------------------------------------------------

class TestCacheInstances:
    def test_llm_cache_has_correct_namespace(self):
        from backend.app.utils.cache import llm_cache
        assert llm_cache.namespace == "llm"
        assert llm_cache.ttl > 0

    def test_embed_cache_has_correct_namespace(self):
        from backend.app.utils.cache import embed_cache
        assert embed_cache.namespace == "embed"
        assert embed_cache.ttl > 0

    def test_page_cache_has_correct_namespace(self):
        from backend.app.utils.cache import page_cache
        assert page_cache.namespace == "pages"
        assert page_cache.ttl > 0

    def test_query_cache_has_correct_namespace(self):
        from backend.app.utils.cache import query_cache
        assert query_cache.namespace == "queries"
        assert query_cache.ttl > 0

    def test_ttl_values_from_config(self):
        from backend.app.utils.cache import llm_cache, embed_cache, page_cache, query_cache
        from backend.app.config import settings
        assert llm_cache.ttl == settings.CACHE_TTL_LLM_SECONDS
        assert embed_cache.ttl == settings.CACHE_TTL_EMBEDDING_SECONDS
        assert page_cache.ttl == settings.CACHE_TTL_PAGE_SECONDS
        assert query_cache.ttl == settings.CACHE_TTL_QUERY_SECONDS


# ---------------------------------------------------------------------------
# LLM cache key generation
# ---------------------------------------------------------------------------

class TestLLMCacheKey:
    def test_cache_key_is_deterministic(self):
        from backend.app.llm_router import LLMRouter
        messages = [{"role": "user", "content": "hello"}]
        import json
        key1 = LLMRouter._cache_key(
            json.dumps(messages, sort_keys=True),
            "llama3.2:3b", "0.2", "ollama"
        )
        key2 = LLMRouter._cache_key(
            json.dumps(messages, sort_keys=True),
            "llama3.2:3b", "0.2", "ollama"
        )
        assert key1 == key2

    def test_cache_key_differs_for_different_inputs(self):
        from backend.app.llm_router import LLMRouter
        import json
        key1 = LLMRouter._cache_key(
            json.dumps([{"role": "user", "content": "hello"}], sort_keys=True),
            "llama3.2:3b", "0.2", "ollama"
        )
        key2 = LLMRouter._cache_key(
            json.dumps([{"role": "user", "content": "world"}], sort_keys=True),
            "llama3.2:3b", "0.2", "ollama"
        )
        assert key1 != key2

    def test_cache_key_differs_for_different_providers(self):
        from backend.app.llm_router import LLMRouter
        import json
        messages = json.dumps([{"role": "user", "content": "hello"}], sort_keys=True)
        key1 = LLMRouter._cache_key(messages, "model-a", "0.2", "ollama")
        key2 = LLMRouter._cache_key(messages, "model-a", "0.2", "nvidia")
        assert key1 != key2

class TestClassificationCache:
    def test_classification_cache_exists(self):
        from backend.app.utils.cache import classification_cache
        assert classification_cache.namespace == "classify"
        assert classification_cache.ttl > 0
