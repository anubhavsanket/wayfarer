from typing import Literal, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # LLM Router
    LLM_PROVIDER: Literal["nvidia", "openrouter", "ollama"] = "nvidia"
    NVIDIA_NIM_ENDPOINT: str = "https://integrate.api.nvidia.com/v1"
    NVIDIA_NIM_API_KEY: Optional[str] = None
    OPENROUTER_ENDPOINT: str = "https://openrouter.ai/api/v1"
    OPENROUTER_API_KEY: Optional[str] = None
    OLLAMA_ENDPOINT: str = "http://ollama:11434"

    # Rate limiting (token bucket config)
    PROVIDER_RATE_LIMITS: dict = {
        "nvidia": {"requests": 10, "window": 60},
        "openrouter": {"requests": 30, "window": 60},
        "ollama": {"requests": 60, "window": 60}
    }

    # Model selection per complexity tier
    # For Ollama: both tiers use the same model (local GPU has 4GB VRAM).
    # For NVIDIA NIM: both tiers use the 8B model because the free tier rate-limits
    # the 70B model (ResourceExhausted: Worker local total request limit reached).
    LLM_MODELS: dict = {
        "simple": {"nvidia": "meta/llama-3.1-8b-instruct", "openrouter": "meta-llama/llama-3.1-8b-instruct", "ollama": "llama3.2:3b"},
        "complex": {"nvidia": "meta/llama-3.1-8b-instruct", "openrouter": "meta-llama/llama-3.1-8b-instruct", "ollama": "llama3.2:3b"}
    }

    # Embedding
    EMBEDDING_MODEL: str = "nomic-embed-text"

    # ChromaDB
    CHROMA_HOST: str = "chromadb"
    CHROMA_PORT: int = 8001
    CHROMA_PERSIST_DIR: str = "./chroma_db"

    # Redis
    REDIS_URL: str = "redis://redis:6379"

    # Collections
    SEARCH_CACHE_COLLECTION: str = "search_cache"
    RESUME_SECTIONS_COLLECTION: str = "resume_sections"
    JOB_POSTINGS_COLLECTION: str = "job_postings"

    # Cache
    CONTENT_HASH_CACHE_DIR: str = "./cache/content_hashes"
    MAX_CACHE_ENTRIES: int = 10000
    CACHE_TTL_HOURS: int = 48

    # Job search
    DEFAULT_MAX_SOURCES: int = 5
    DEFAULT_TOP_K: int = 5
    JOBS_SEMANTIC_WEIGHT: float = 0.7
    JOBS_KEYWORD_WEIGHT: float = 0.3
    JOBS_TOP_K_EMBEDDING_SURVIVORS: int = 15

    # API timeouts
    REQUEST_TIMEOUT: int = 30
    RATE_LIMIT_BACKOFF: float = 1.5

    # Performance
    MAX_VRAM_GB: int = 4

    def get_model_for_tier(self, tier: str) -> str:
        """Get the appropriate model for a given complexity tier"""
        return self.LLM_MODELS.get(tier, self.LLM_MODELS["simple"])

    def get_provider_for_tier(self, tier: str) -> str:
        """Select the primary provider for a tier"""
        return self.LLM_PROVIDER

    def get_rate_limit(self, provider: str) -> dict:
        """Get rate limit config for a provider"""
        return self.PROVIDER_RATE_LIMITS.get(provider, self.PROVIDER_RATE_LIMITS["openrouter"])

    def get_collection_url(self, collection: str) -> str:
        """Build ChromaDB URL for a collection"""
        return f"http://{self.CHROMA_HOST}:{self.CHROMA_PORT}"

    def get_embedding_url(self) -> str:
        """Get Ollama embedding endpoint"""
        return f"{self.OLLAMA_ENDPOINT}/api/embeddings"

# Global settings instance
settings = Settings()