"""Multi-collection Qdrant wrapper shared by all Wayfarer stages.

One persistent store, separate collections per stage (no cross-contamination)
while sharing a single embedding model (nomic-embed-text via Ollama) so the
embedding space is consistent for Stage 2 ↔ Stage 3 reuse.

Collections:
- ``resume_sections`` — parsed resume sections for ATS checking
- ``job_postings``  — job descriptions for the matching pipeline

IDs are content-hash based (sha256), so re-adding the same document is a
no-op rather than a duplicate.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Iterable

import httpx
from qdrant_client import QdrantClient, models
from qdrant_client.http.exceptions import UnexpectedResponse, ResponseHandlingException

from .config import settings

logger = logging.getLogger(__name__)


class OllamaEmbeddingFunction:
    """Embedding function backed by Ollama's nomic-embed-text."""

    def __init__(self, model: str | None = None) -> None:
        self.model = model or settings.EMBEDDING_MODEL
        self._url = f"{settings.OLLAMA_ENDPOINT}/api/embeddings"

    def __call__(self, input: list[str]) -> list[list[float]]:
        from .context import get_request_overrides

        overrides = get_request_overrides()
        ollama_endpoint = (overrides.ollama_endpoint if overrides and overrides.ollama_endpoint else settings.OLLAMA_ENDPOINT)
        url = f"{ollama_endpoint.rstrip('/')}/api/embeddings"

        texts = [input] if isinstance(input, str) else list(input)
        vectors: list[list[float]] = []
        with httpx.Client(timeout=httpx.Timeout(120.0)) as client:
            for text in texts:
                try:
                    resp = client.post(
                        url,
                        json={"model": self.model, "prompt": text},
                    )
                    resp.raise_for_status()
                    vectors.append(resp.json()["embedding"])
                except httpx.ConnectError:
                    raise RuntimeError(
                        f"Ollama is not reachable at {url}. "
                        "Start Ollama locally (`ollama serve`) or use Docker Compose, "
                        f"and pull the embedding model: ollama pull {self.model}"
                    ) from None
        return vectors


class VectorStore:
    """Thin multi-collection wrapper around Qdrant."""

    COLLECTIONS = (
        settings.RESUME_SECTIONS_COLLECTION,
        settings.JOB_POSTINGS_COLLECTION,
    )

    def __init__(self) -> None:
        self._embedding_fn = OllamaEmbeddingFunction()
        self._client: QdrantClient | None = None
        self._ensure_client()

    def _ensure_client(self) -> None:
        """Initialize Qdrant client, falling back to in-memory on connection errors."""
        if self._client is not None:
            return
        try:
            self._client = QdrantClient(
                host=settings.QDRANT_HOST,
                port=settings.QDRANT_PORT,
                timeout=5,
            )
            self._client.get_collections()
            logger.info("Connected to Qdrant at %s:%s", settings.QDRANT_HOST, settings.QDRANT_PORT)
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            logger.warning(
                "Qdrant at %s:%s unreachable (%s); falling back to in-memory store",
                settings.QDRANT_HOST, settings.QDRANT_PORT, exc,
            )
            self._client = QdrantClient(":memory:")
        except (ResponseHandlingException, UnexpectedResponse) as exc:
            logger.warning(
                "Qdrant at %s:%s returned an error (%s); falling back to in-memory store",
                settings.QDRANT_HOST, settings.QDRANT_PORT, exc,
            )
            self._client = QdrantClient(":memory:")
        except Exception as exc:
            logger.error(
                "Unexpected error connecting to Qdrant at %s:%s: %s",
                settings.QDRANT_HOST, settings.QDRANT_PORT, exc,
                exc_info=True
            )
            self._client = QdrantClient(":memory:")

    def _ensure_collection(self, name: str) -> None:
        self._ensure_client()
        existing = [c.name for c in self._client.get_collections().collections]
        if name not in existing:
            self._client.create_collection(
                collection_name=name,
                vectors_config=models.VectorParams(
                    size=768, distance=models.Distance.COSINE
                ),
            )
            logger.info("Created Qdrant collection: %s", name)

    # -- shared helpers -----------------------------------------------------

    @staticmethod
    def _content_hash(text: str, extra: str = "") -> str:
        return hashlib.sha256(f"{text}\0{extra}".encode("utf-8")).hexdigest()

    @staticmethod
    def _to_uuid(id_str: str) -> str:
        """Convert any string ID to a deterministic UUID5 for Qdrant compatibility."""
        import uuid
        # Use a fixed namespace for Wayfarer point IDs
        NAMESPACE_WAYFARER = uuid.UUID("12345678-1234-5678-1234-567812345678")
        return str(uuid.uuid5(NAMESPACE_WAYFARER, id_str))

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
        self._ensure_collection(collection)
        
        raw_ids = (
            list(ids) if ids is not None
            else [self._content_hash(d) for d in docs]
        )
        # Qdrant requires UUID or integer IDs
        doc_ids = [self._to_uuid(rid) for rid in raw_ids]
        
        meta_list = list(metadatas) if metadatas is not None else [{} for _ in docs]

        # Embed documents
        vectors = self._embedding_fn(docs)

        points = []
        for rid, doc_id, vec, payload in zip(raw_ids, doc_ids, vectors, meta_list):
            points.append(models.PointStruct(
                id=doc_id,
                vector=vec,
                payload={
                    "text": docs[0], 
                    "_original_id": rid,  # Keep the original string ID for reconstruction
                    **(payload or {})
                },
            ))

        if points:
            self._client.upsert(collection_name=collection, points=points)
        return raw_ids

    def get(self, collection: str, ids: Iterable[str]) -> dict[str, Any]:
        """Fetch documents by id. Returns ChromaDB-compatible format."""
        self._ensure_collection(collection)
        original_ids = list(ids)
        qdrant_ids = [self._to_uuid(i) for i in original_ids]
        
        try:
            results = self._client.retrieve(
                collection_name=collection,
                ids=qdrant_ids,
            )
            
            # Reconstruct in the original order requested
            id_map = {r.id: r for r in results}
            ordered_docs = []
            ordered_meta = []
            
            for qid in qdrant_ids:
                if qid in id_map and id_map[qid].payload:
                    ordered_docs.append(id_map[qid].payload.get("text", ""))
                    # Strip internal fields
                    meta = {k: v for k, v in id_map[qid].payload.items() if k not in ("text", "_original_id")}
                    ordered_meta.append(meta)
                else:
                    ordered_docs.append(None)
                    ordered_meta.append(None)
            
            return {"ids": original_ids, "documents": ordered_docs, "metadatas": ordered_meta}
        except Exception:
            return {"ids": original_ids, "documents": [None] * len(original_ids), "metadatas": [None] * len(original_ids)}

    def query(
        self,
        collection: str,
        query_texts: list[str],
        n_results: int = settings.DEFAULT_TOP_K,
        where: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Semantic search. Returns Qdrant results in ChromaDB-compatible format."""
        self._ensure_collection(collection)
        query_vec = self._embedding_fn(query_texts)[0]
        
        results = self._client.query_points(
            collection_name=collection,
            query=query_vec,
            limit=n_results,
            with_payload=True,
        )
        
        return {
            "ids": [[r.payload.get("_original_id", str(r.id)) for r in results.points]],
            "documents": [[r.payload.get("text", "") if r.payload else "" for r in results.points]],
            "metadatas": [[{k: v for k, v in (r.payload or {}).items() if k not in ("text", "_original_id")} for r in results.points]],
            "distances": [[r.score for r in results.points]],
        }

    def delete_older_than(self, collection: str, field: str, cutoff_iso: str) -> int:
        """Delete docs whose metadata field (ISO datetime) is older than cutoff."""
        self._ensure_collection(collection)
        # Use Qdrant's filtering
        results = self._client.query_points(
            collection_name=collection,
            query=[0] * 768,  # Dummy vector
            query_filter=models.Filter(
                must=[models.FieldCondition(
                    key=field,
                    range=models.Range(lt=cutoff_iso)
                )]
            ),
            limit=1000,  # Max batch
        )
        
        ids_to_delete = [r.id for r in results.points]
        if ids_to_delete:
            self._client.delete(
                collection_name=collection,
                points_selector=models.PointIdsList(points=ids_to_delete),
            )
        return len(ids_to_delete)

    def count(self, collection: str) -> int:
        self._ensure_collection(collection)
        return self._client.count(collection_name=collection).count

    def list_collections(self) -> list[str]:
        self._ensure_client()
        return [c.name for c in self._client.get_collections().collections]


# Singleton used across stages
store = VectorStore()
