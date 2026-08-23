"""LlamaIndex-based RAG engine for unified document indexing and retrieval.

Wraps LlamaIndex to provide:
- Unified embedding (via Ollama)
- Vector storage (via Qdrant)
- Document chunking and indexing
- Semantic and hybrid retrieval
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional

from llama_index.core import (
    Document,
    Settings,
    StorageContext,
    VectorStoreIndex,
)
from llama_index.core.node_parser import SentenceSplitter
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.llms.ollama import Ollama
from llama_index.vector_stores.qdrant import QdrantVectorStore
import qdrant_client

from ..config import settings

logger = logging.getLogger(__name__)

# -- Global LlamaIndex Configuration ----------------------------------------

def init_rag_settings():
    """Initialise global RAG settings (Embeddings, LLM, Chunks)."""
    Settings.embed_model = OllamaEmbedding(
        model_name=settings.EMBEDDING_MODEL,
        base_url=settings.OLLAMA_ENDPOINT,
    )
    
    # We use our own router for most things, but LlamaIndex needs a default LLM
    # for certain high-level query engines.
    Settings.llm = Ollama(
        model=settings.get_model_for_tier("simple"),
        base_url=settings.OLLAMA_ENDPOINT,
    )
    
    Settings.node_parser = SentenceSplitter(chunk_size=512, chunk_overlap=50)

# -- RAG Engine -----------------------------------------------------------

class RAGEngine:
    """Core RAG engine managing indexing and retrieval."""

    def __init__(self, collection_name: str):
        self.collection_name = collection_name
        self.client = qdrant_client.QdrantClient(
            host=settings.QDRANT_HOST,
            port=settings.QDRANT_PORT,
        )
        self.vector_store = QdrantVectorStore(
            client=self.client,
            collection_name=collection_name,
        )
        self.storage_context = StorageContext.from_defaults(vector_store=self.vector_store)
        self.index = self._load_index()

    def _load_index(self) -> VectorStoreIndex:
        """Load or create a VectorStoreIndex."""
        return VectorStoreIndex.from_vector_store(
            vector_store=self.vector_store,
            storage_context=self.storage_context,
        )

    def index_documents(self, texts: List[str], metadatas: Optional[List[dict]] = None):
        """Index a list of text strings as documents."""
        documents = []
        for i, text in enumerate(texts):
            meta = metadatas[i] if metadatas else {}
            documents.append(Document(text=text, extra_info=meta))
        
        for doc in documents:
            self.index.insert(doc)
        
        logger.info("Indexed %d documents into collection '%s'", len(documents), self.collection_name)

    def query(self, query_text: str, similarity_top_k: int = 5) -> List[dict]:
        """Run a semantic query and return results with metadata."""
        retriever = self.index.as_retriever(similarity_top_k=similarity_top_k)
        nodes = retriever.retrieve(query_text)
        
        results = []
        for node in nodes:
            results.append({
                "text": node.node.get_content(),
                "score": node.score,
                "metadata": node.node.metadata,
            })
        return results

    def delete_all(self):
        """Clear the collection."""
        self.client.delete_collection(self.collection_name)
        # Re-create empty
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=qdrant_client.models.VectorParams(size=768, distance="Cosine"),
        )
        self.index = self._load_index()

# -- Factory --------------------------------------------------------------

def get_engine(collection_name: str) -> RAGEngine:
    """Get a RAGEngine instance for a specific collection."""
    return RAGEngine(collection_name)
