"""Stage 1 — Web Search Agent orchestration.

Pipeline (PRD §7):
1. Decompose the natural-language query into 1–3 sub-queries (LLM, simple tier)
2. Search each sub-query via Tavily → Brave fallback
3. Fetch + clean top-N pages via Crawl4AI (concurrency-capped), with graceful
   fallback to the search snippet when a fetch fails
4. Cache fetched pages in ChromaDB ``search_cache`` keyed by URL hash + TTL
5. Synthesize an answer via the LLM router with inline citations

Repeated identical queries within the TTL window return cached results
without re-fetching (FR1.5 / acceptance criterion #3).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from ..llm_router import router, extract_json
from ..config import settings
from ..models.schemas import Citation, SearchResponse
from .search_api import SearchResultItem, run_search, SearchAPIError
from .web_fetch import page_fetcher, FetchResult

logger = logging.getLogger(__name__)

# Cache key prefix for search results, TTL from config (48h)
SEARCH_CACHE_COLLECTION = settings.SEARCH_CACHE_COLLECTION


def _query_cache_key(query: str) -> str:
    from ..vector_store import store
    return store._content_hash(query.strip().lower())


async def _decompose_query(query: str) -> list[str]:
    """Decompose a multi-part/vague query into 1–3 searchable sub-queries."""
    prompt = (
        "You decompose a user's search request into 1-3 focused search "
        "sub-queries. If the request is already simple and specific, return "
        "just one query (the original, lightly cleaned).\n\n"
        "Return ONLY a JSON list of strings, no commentary.\n\n"
        f"User request: {query}"
    )
    try:
        resp = await router.chat(
            messages=[{"role": "user", "content": prompt}],
            tier="simple",
            max_tokens=256,
            json_mode=True,
        )
        queries = extract_json(resp["content"])
        if isinstance(queries, dict):
            queries = queries.get("sub_queries", queries.get("queries", []))
        if isinstance(queries, str):
            queries = [queries]
        queries = [q for q in queries if isinstance(q, str) and q.strip()][:3]
        return queries or [query]
    except Exception as exc:
        logger.warning("Query decomposition failed (%s); using raw query", exc)
        return [query]


async def _dedupe_results(items: list[SearchResultItem]) -> list[SearchResultItem]:
    """Deduplicate search results by URL, preserving first-seen order."""
    seen: set[str] = set()
    out: list[SearchResultItem] = []
    for item in items:
        if item.url and item.url not in seen:
            seen.add(item.url)
            out.append(item)
    return out


async def _fetch_and_cache(items: list[SearchResultItem]) -> dict[str, FetchResult]:
    """Fetch top-N pages, storing fetched markdown in ChromaDB ``search_cache``.

    Returns a map url → FetchResult. Pages already in the cache (within TTL)
    are reused without re-fetching.
    """
    from ..vector_store import store

    results: dict[str, FetchResult] = {}
    urls = [i.url for i in items if i.url]
    if not urls:
        return results

    # Check cache first
    cache_ids = [store._content_hash(u) for u in urls]
    cached = store.get(SEARCH_CACHE_COLLECTION, cache_ids)
    cached_docs = cached.get("documents") or []
    cached_urls = {i: u for i, u in enumerate(urls)}
    cached_hits: dict[str, str] = {}  # url -> markdown
    for i, doc in enumerate(cached_docs):
        if doc:
            cached_hits[cached_urls.get(i, "")] = doc

    to_fetch = [u for u in urls if u not in cached_hits]
    logger.info("Crawl4AI fetching %d/%d URLs (cache hit for %d)",
                len(to_fetch), len(urls), len(urls) - len(to_fetch))

    # Fetch uncached pages
    if to_fetch:
        fetched = await page_fetcher.fetch_many(to_fetch)
        # Store successful fetches in cache.
        # nomic-embed-text has a 2048-token input limit (~4000 chars);
        # the search cache doesn't need semantic search, only key-value
        # lookup, so we truncate aggressively before embedding.
        MAX_CACHE_CHARS = 3500
        fresh_docs, fresh_ids, fresh_metas = [], [], []
        for fr in fetched:
            if fr.success and fr.markdown.strip():
                fresh_docs.append(fr.markdown[:MAX_CACHE_CHARS])
                fresh_ids.append(store._content_hash(fr.url))
                fresh_metas.append({
                    "url": fr.url,
                    "title": fr.title[:200],
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                })
        if fresh_docs:
            store.upsert(
                SEARCH_CACHE_COLLECTION,
                fresh_docs,
                ids=fresh_ids,
                metadatas=fresh_metas,
            )
        for fr in fetched:
            results[fr.url] = fr

    # Cache hits
    for url, md in cached_hits.items():
        results[url] = FetchResult(url=url, title=url, markdown=md, success=True)

    return results


async def _synthesize(
    query: str,
    results: list[SearchResultItem],
    fetched: dict[str, FetchResult],
) -> tuple[str, list[Citation]]:
    """Synthesize an answer with inline citations via the LLM router.

    Builds a compact context per source. Failed fetches fall back to the
    search snippet (NFR1.3), so every source still contributes.
    """
    # Build sources list with id, url, title, and content. Per-source cap
    # keeps the synthesis prompt compact so the LLM call completes well
    # under the 90s timeout. Tavily snippets (~500 chars) are pre-summarized
    # by the search provider and are preferred when substantial.
    sources: list[dict[str, Any]] = []
    for i, item in enumerate(results, start=1):
        fr = fetched.get(item.url)
        # Prefer Tavily snippet when it's substantial (>= 200 chars) — it's
        # already a high-quality summary, so the LLM doesn't need the full
        # markdown for synthesis. Fall back to markdown when the snippet is
        # too short to be useful, then truncate aggressively.
        if item.snippet and len(item.snippet) >= 200:
            content = item.snippet
        elif fr and fr.success and fr.markdown.strip():
            content = fr.markdown
        else:
            content = item.snippet or ""
        if not content:
            continue
        if len(content) > 1200:
            content = content[:1200] + "\n...[truncated]"
        sources.append({
            "id": i,
            "url": item.url,
            "title": item.title,
            "content": content,
        })

    if not sources:
        return "No sources could be retrieved for this query.", []

    source_block = "\n\n".join(
        f"[{s['id']}] {s['title']}\nURL: {s['url']}\n{s['content']}"
        for s in sources
    )
    prompt = (
        "You are a research assistant synthesizing an answer from web sources.\n\n"
        "Requirements:\n"
        "- Answer the user's query directly and concisely.\n"
        "- Cite sources inline using bracketed numbers like [1], [2].\n"
        "- Every factual claim must map to at least one citation.\n"
        "- If sources conflict, say so briefly.\n"
        "- Do NOT invent citations beyond the provided sources.\n\n"
        f"USER QUERY: {query}\n\n"
        f"SOURCES:\n{source_block}"
    )
    resp = await router.chat(
        messages=[{"role": "user", "content": prompt}],
        tier="complex",
        max_tokens=1024,
    )
    citations = [
        Citation(id=s["id"], url=s["url"], title=s["title"], snippet=s["content"][:200])
        for s in sources
    ]
    return resp["content"], citations


async def search(query: str, max_sources: int = 5) -> SearchResponse:
    """Run the full Stage 1 search pipeline and return a ``SearchResponse``."""
    from ..vector_store import store

    # 1. Cache check — repeated identical query within TTL returns cached answer
    cache_key = _query_cache_key(query)
    cached = store.get(SEARCH_CACHE_COLLECTION, [cache_key])
    if cached.get("documents") and cached["documents"][0]:
        cached_answer = cached["documents"][0]
        meta = (cached.get("metadatas") or [{}])[0] or {}
        logger.info("Search cache hit for query: %s", query)
        # Metadata stores sub_queries as a comma-joined string (ChromaDB
        # only accepts scalar metadata); split it back into a list here.
        raw_sq = meta.get("sub_queries", "")
        sub_queries_cached: list[str] = (
            raw_sq.split(",") if isinstance(raw_sq, str) and raw_sq else []
        )
        return SearchResponse(
            answer=cached_answer,
            citations=[],
            sub_queries_used=sub_queries_cached,
            cached=True,
        )

    # 2. Decompose query into sub-queries
    sub_queries = await _decompose_query(query)

    # 3. Search each sub-query, merge + dedupe results
    all_items: list[SearchResultItem] = []
    for sq in sub_queries:
        try:
            items, _provider = await run_search(sq, max_results=max_sources)
            all_items.extend(items)
        except SearchAPIError as exc:
            logger.warning("Search failed for sub-query '%s': %s", sq, exc)
    all_items = await _dedupe_results(all_items)
    if not all_items:
        return SearchResponse(
            answer="Search failed — no results could be retrieved. Check that "
                   "TAVILY_API_KEY (or BRAVE_API_KEY) is set.",
            citations=[],
            sub_queries_used=sub_queries,
        )

    # 4. Fetch + clean pages, with cache reuse
    fetched = await _fetch_and_cache(all_items[:max_sources])

    # 5. Synthesize answer with citations.
    # Gracefully degrade: if the LLM is unavailable (all providers exhausted),
    # return the raw search results rather than crashing with a 500.
    synthesized = True
    try:
        answer, citations = await _synthesize(query, all_items[:max_sources], fetched)
    except RuntimeError as exc:
        logger.warning("Synthesis failed, returning raw results: %s", exc)
        synthesized = False
        citations = [
            Citation(
                id=i, url=item.url, title=item.title,
                snippet=(fetched.get(item.url, FetchResult(url=item.url, title="", markdown=item.snippet, success=False)).markdown or item.snippet)[:200],
            )
            for i, item in enumerate(all_items[:max_sources], start=1)
            if item.snippet
        ]
        answer = (
            "LLM synthesis unavailable (all providers exhausted or rate-limited). "
            "Here are the raw sources — you can read them directly:\n\n"
            + "\n".join(f"[{c.id}] {c.title} — {c.url}" for c in citations)
        )

    # 6. Cache the final answer (query hash → answer + sub-queries used)
    # Skip caching fallback answers — they're not useful as cached results.
    if synthesized:
        store.upsert(
            SEARCH_CACHE_COLLECTION,
            [answer],
            ids=[cache_key],
            metadatas=[{
                "sub_queries": ",".join(sub_queries),
                "answer_at": datetime.now(timezone.utc).isoformat(),
            }],
        )

    return SearchResponse(
        answer=answer,
        citations=citations,
        sub_queries_used=sub_queries,
    )
