"""Multi-collection ChromaDB wrapper shared by all Wayfarer stages.

One persistent store, separate collections per stage (no cross-contamination)
while sharing a single embedding model (nomic-embed-text via Ollama) so the
embedding space is consistent for Stage 2 ↔ Stage 3 reuse.

Collections:
- ``search_cache``  — Crawl4AI fetched pages, keyed by URL hash, TTL'd
- ``resume_sections`` — parsed resume sections for ATS checking
- ``job_postings``  — job descriptions for the matching pipeline

IDs are content-hash based (sha256), so re-adding the same document is a
no-op rather than a duplicate.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Iterable

import chromadb
import httpx

from .config import settings

logger = logging.getLogger(__name__)


class OllamaEmbeddingFunction:
    """ChromaDB embedding function backed by Ollama's nomic-embed-text."""

    def __init__(self, model: str | None = None) -> None:
        self.model = model or settings.EMBEDDING_MODEL
        self._url = f"{settings.OLLAMA_ENDPOINT}/api/embeddings"

    def __call__(self, input: list[str]) -> list[list[float]]:
        import numpy as np

        texts = [input] if isinstance(input, str) else list(input)
        vectors: list[list[float]] = []
        # Embedding calls need a longer timeout — Ollama can take 30s+ to load a model
        # on first request (cold start), then it's fast.
        with httpx.Client(timeout=httpx.Timeout(120.0)) as client:
            for text in texts:
                try:
                    resp = client.post(
                        self._url,
                        json={"model": self.model, "prompt": text},
                    )
                    resp.raise_for_status()
                    vectors.append(resp.json()["embedding"])
                except httpx.ConnectError:
                    raise RuntimeError(
                        f"Ollama is not reachable at {self._url}. "
                        "Start Ollama locally (`ollama serve`) or use Docker Compose, "
                        f"and pull the embedding model: ollama pull {self.model}"
                    ) from None
        # ChromaDB expects numpy-style arrays with .tolist() — convert here so
        # the rest of the codebase stays free of numpy imports.
        return [np.array(v, dtype=np.float32) for v in vectors]


class VectorStore:
    """Thin multi-collection wrapper around ChromaDB."""

    COLLECTIONS = (
        settings.SEARCH_CACHE_COLLECTION,
        settings.RESUME_SECTIONS_COLLECTION,
        settings.JOB_POSTINGS_COLLECTION,
    )

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        persist_dir: str | None = None,
    ) -> None:
        self._embedding_fn = OllamaEmbeddingFunction()
        self._client = self._create_client(host, port, persist_dir)
        self._collections: dict[str, chromadb.Collection] = {}

    def _create_client(
        self,
        host: str | None,
        port: int | None,
        persist_dir: str | None,
    ) -> chromadb.ClientAPI:
        host = host or settings.CHROMA_HOST
        port = port or settings.CHROMA_PORT
        persist_dir = persist_dir or settings.CHROMA_PERSIST_DIR
        try:
            client = chromadb.HttpClient(host=host, port=port)
            # Probe connectivity
            client.heartbeat()
            logger.info("Connected to ChromaDB at %s:%s", host, port)
            return client
        except Exception as exc:
            logger.warning(
                "ChromaDB HTTP at %s:%s unreachable (%s); falling back to "
                "persistent local store at %s",
                host, port, exc, persist_dir,
            )
            return chromadb.PersistentClient(path=persist_dir)

    def _ensure_collection(self, name: str) -> chromadb.Collection:
        if name not in self._collections:
            self._collections[name] = self._client.get_or_create_collection(
                name=name,
                embedding_function=self._embedding_fn,
                metadata={"hnsw:space": "cosine"},
            )
        return self._collections[name]

    # -- shared helpers -----------------------------------------------------

    @staticmethod
    def _content_hash(text: str, extra: str = "") -> str:
        return hashlib.sha256(f"{text}\0{extra}".encode("utf-8")).hexdigest()

    # -- add / get / query --------------------------------------------------

    def upsert(
        self,
        collection: str,
        documents: Iterable[str],
        ids: Iterable[str] | None = None,
        metadatas: Iterable[dict[str, Any]] | None = None,
    ) -> list[str]:
        """Add or update documents in a collection. Returns the ids used."""
        docs = list(documents)
        col = self._ensure_collection(collection)
        doc_ids = (
            list(ids)
            if ids is not None
            else [self._content_hash(d) for d in docs]
        )
        meta_list = list(metadatas) if metadatas is not None else None
        # Split into ids that already exist vs. new (upsert does this anyway,
        # but doing it explicitly lets us log dedup hits).
        existing = set(col.get(ids=doc_ids, include=[])["ids"])
        fresh = [i for i in doc_ids if i not in existing]
        if existing:
            logger.debug(
                "Collection %s: %d/%d documents were duplicates (skipped)",
                collection, len(existing), len(doc_ids),
            )
        if fresh:
            fresh_idx = [doc_ids.index(i) for i in fresh]
            col.upsert(
                ids=fresh,
                documents=[docs[i] for i in fresh_idx],
                metadatas=(
                    [meta_list[i] for i in fresh_idx]
                    if meta_list is not None
                    else None
                ),
            )
        return doc_ids

    def get(self, collection: str, ids: Iterable[str]) -> dict[str, Any]:
        """Fetch documents by id."""
        return self._ensure_collection(collection).get(ids=list(ids))

    def query(
        self,
        collection: str,
        query_texts: list[str],
        n_results: int = settings.DEFAULT_TOP_K,
        where: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Semantic search. Returns ChromaDB's {ids, documents, metadatas, distances}."""
        return self._ensure_collection(collection).query(
            query_texts=query_texts,
            n_results=n_results,
            where=where,
            include=["documents", "metadatas", "distances"],
        )

    def delete_older_than(self, collection: str, field: str, cutoff_iso: str) -> int:
        """Delete docs whose metadata field (ISO datetime) is older than cutoff."""
        col = self._ensure_collection(collection)
        result = col.get(where={field: {"$lt": cutoff_iso}}, include=[])
        ids = result["ids"]
        if ids:
            col.delete(ids=ids)
        return len(ids)

    def count(self, collection: str) -> int:
        return self._ensure_collection(collection).count()

    def list_collections(self) -> list[str]:
        return [c.name for c in self._client.list_collections()]


# Singleton used across stages
store = VectorStore()
