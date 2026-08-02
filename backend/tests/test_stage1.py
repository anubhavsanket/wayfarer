"""Stage 1 unit tests — exercise reachable code paths without external APIs.

The full pipeline (search → fetch → synthesize) requires live Tavily/Brave
keys + LLM provider. These tests cover the parts that can be exercised
without external dependencies:

- Search API provider selection (no keys → SearchAPIError)
- Result deduplication
- Query decomposition graceful fallback (LLM offline → raw query)
- /search endpoint behavior with no API keys (returns graceful error)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

# Ensure no API keys are present for the duration of these tests
for key in ("TAVILY_API_KEY", "BRAVE_API_KEY", "NVIDIA_NIM_API_KEY", "OPENROUTER_API_KEY"):
    os.environ.pop(key, None)


@pytest.fixture
def client():
    """TestClient inside the app's lifespan context."""
    from backend.app.main import app
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Search API provider selection
# ---------------------------------------------------------------------------

def test_search_providers_report_no_keys():
    from backend.app.services.search_api import TavilyClient, BraveClient
    assert not TavilyClient().available()
    assert not BraveClient().available()


@pytest.mark.asyncio
async def test_run_search_no_keys_raises():
    from backend.app.services.search_api import run_search, SearchAPIError
    with pytest.raises(SearchAPIError):
        await run_search("python async testing", max_results=3)


# ---------------------------------------------------------------------------
# Search result deduplication
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dedupe_results_preserves_first_seen():
    from backend.app.services.search_service import _dedupe_results
    from backend.app.services.search_api import SearchResultItem

    items = [
        SearchResultItem(url="https://a.com", title="A", snippet="s", rank=0),
        SearchResultItem(url="https://b.com", title="B", snippet="s", rank=1),
        SearchResultItem(url="https://a.com", title="A dup", snippet="s", rank=2),
        SearchResultItem(url="", title="empty", snippet="s", rank=3),
    ]
    out = await _dedupe_results(items)
    assert [i.url for i in out] == ["https://a.com", "https://b.com"]
    assert out[0].title == "A"  # first-seen preserved


# ---------------------------------------------------------------------------
# Query decomposition (LLM fallback path)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_decompose_query_falls_back_when_no_llm():
    """With no LLM providers configured, decompose returns the raw query."""
    from backend.app.services.search_service import _decompose_query
    out = await _decompose_query("what is RAG?")
    assert out == ["what is RAG?"]


# ---------------------------------------------------------------------------
# /search endpoint with no API keys
# ---------------------------------------------------------------------------

def test_search_endpoint_returns_graceful_error_when_no_keys(client):
    """With no Tavily/Brave keys, /search should return a clear message
    rather than a 500."""
    resp = client.post("/api/v1/search", json={"query": "test query", "max_sources": 3})
    assert resp.status_code == 200
    data = resp.json()
    # Either we got a graceful 'no results' answer, or the pipeline
    # short-circuited with the no-API-key message
    assert "answer" in data
    assert "citations" in data
    assert "sub_queries_used" in data


def test_search_endpoint_validates_query(client):
    """Empty query should be rejected by Pydantic validation."""
    resp = client.post("/api/v1/search", json={"query": "", "max_sources": 3})
    assert resp.status_code == 422


def test_search_endpoint_validates_max_sources(client):
    """max_sources > 10 should be rejected."""
    resp = client.post(
        "/api/v1/search",
        json={"query": "test", "max_sources": 11},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Vector store content hashing (pure function, no deps)
# ---------------------------------------------------------------------------

def test_content_hash_is_deterministic():
    from backend.app.vector_store import VectorStore
    a = VectorStore._content_hash("hello world")
    b = VectorStore._content_hash("hello world")
    assert a == b
    assert len(a) == 64  # SHA-256 hex


def test_content_hash_differs_for_different_inputs():
    from backend.app.vector_store import VectorStore
    a = VectorStore._content_hash("foo")
    b = VectorStore._content_hash("bar")
    assert a != b
