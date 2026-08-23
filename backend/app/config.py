from typing import Literal, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # ── LLM Router ──────────────────────────────────────────────────────
    # Supported: nvidia | openrouter | ollama | lmstudio | custom
    #   nvidia     → NVIDIA NIM free tier (requires NVIDIA_NIM_API_KEY)
    #   openrouter → OpenRouter free tier (requires OPENROUTER_API_KEY)
    #   ollama     → Local Ollama (no key required, but model must be pulled)
    #   lmstudio   → Local LM Studio / any OpenAI-compatible server
    #                  (set LMSTUDIO_ENDPOINT + LMSTUDIO_MODEL)
    #   custom     → Any OpenAI-compatible endpoint
    #                  (set CUSTOM_LLM_ENDPOINT + CUSTOM_LLM_API_KEY + CUSTOM_LLM_MODEL)
    LLM_PROVIDER: Literal["nvidia", "openrouter", "ollama", "lmstudio", "custom"] = "nvidia"

    # NVIDIA NIM
    NVIDIA_NIM_ENDPOINT: str = "https://integrate.api.nvidia.com/v1"
    NVIDIA_NIM_API_KEY: Optional[str] = None

    # OpenRouter
    OPENROUTER_ENDPOINT: str = "https://openrouter.ai/api/v1"
    OPENROUTER_API_KEY: Optional[str] = None

    # Ollama (local)
    OLLAMA_ENDPOINT: str = "http://ollama:11434"

    # LM Studio / any local OpenAI-compatible server (default: localhost:1234)
    LMSTUDIO_ENDPOINT: str = "http://host.docker.internal:1234/v1"
    LMSTUDIO_MODEL: str = ""
    LMSTUDIO_API_KEY: str = "lm-studio"  # LM Studio accepts any string

    # Fully custom OpenAI-compatible endpoint
    CUSTOM_LLM_ENDPOINT: str = ""
    CUSTOM_LLM_API_KEY: str = ""
    CUSTOM_LLM_MODEL: str = ""

    # ── Rate limiting ───────────────────────────────────────────────────
    PROVIDER_RATE_LIMITS: dict = {
        "nvidia": {"requests": 10, "window": 60},
        "openrouter": {"requests": 30, "window": 60},
        "ollama": {"requests": 60, "window": 60},
        "lmstudio": {"requests": 60, "window": 60},
        "custom": {"requests": 60, "window": 60},
    }

    # ── Model selection ─────────────────────────────────────────────────
    # Both tiers use the same model per provider to keep things simple.
    # For LM Studio / custom: the LMSTUDIO_MODEL / CUSTOM_LLM_MODEL is used.
    LLM_MODELS: dict = {
        "simple": {
            "nvidia": "meta/llama-3.1-8b-instruct",
            "openrouter": "meta-llama/llama-3.1-8b-instruct",
            "ollama": "llama3.2:3b",
        },
        "complex": {
            "nvidia": "meta/llama-3.1-8b-instruct",
            "openrouter": "meta-llama/llama-3.1-8b-instruct",
            "ollama": "llama3.2:3b",
        },
    }

    # ── Embedding ───────────────────────────────────────────────────────
    EMBEDDING_MODEL: str = "nomic-embed-text"

    # ── Qdrant ──────────────────────────────────────────────────────────
    QDRANT_HOST: str = "qdrant"
    QDRANT_PORT: int = 6333
    QDRANT_GRPC_PORT: int = 6334

    # ── Redis ───────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://redis:6379"

    # ── Collections ─────────────────────────────────────────────────────
    SEARCH_CACHE_COLLECTION: str = "search_cache"
    RESUME_SECTIONS_COLLECTION: str = "resume_sections"
    JOB_POSTINGS_COLLECTION: str = "job_postings"

    # ── Cache (Redis-backed) ───────────────────────────────────────────
    MAX_CACHE_ENTRIES: int = 10000
    CACHE_TTL_HOURS: int = 48
    CACHE_TTL_LLM_SECONDS: int = 86400       # 24 h — LLM responses
    CACHE_TTL_EMBEDDING_SECONDS: int = 604800  # 7 d  — deterministic embeddings
    CACHE_TTL_PAGE_SECONDS: int = 172800      # 48 h — fetched page content
    CACHE_TTL_QUERY_SECONDS: int = 172800     # 48 h — synthesized query answers

    # ── Job search ──────────────────────────────────────────────────────
    DEFAULT_MAX_SOURCES: int = 5
    DEFAULT_TOP_K: int = 5
    JOBS_SEMANTIC_WEIGHT: float = 0.7
    JOBS_KEYWORD_WEIGHT: float = 0.3
    JOBS_TOP_K_EMBEDDING_SURVIVORS: int = 15

    # ── Timeouts ────────────────────────────────────────────────────────
    REQUEST_TIMEOUT: int = 30
    RATE_LIMIT_BACKOFF: float = 1.5

    # ── Performance ─────────────────────────────────────────────────────
    MAX_VRAM_GB: int = 4

    # ── Job Board API Keys ──────────────────────────────────────────────
    BLUEDOOR_API_KEY: Optional[str] = None

    # ── Helpers ─────────────────────────────────────────────────────────

    def get_model_for_tier(self, tier: str) -> str:
        """Get the appropriate model for a given complexity tier"""
        models = self.LLM_MODELS.get(tier, self.LLM_MODELS["simple"])
        # For lmstudio / custom, use the explicit model name
        if self.LLM_PROVIDER == "lmstudio":
            return self.LMSTUDIO_MODEL or models.get("lmstudio", "default")
        if self.LLM_PROVIDER == "custom":
            return self.CUSTOM_LLM_MODEL or "default"
        return models.get(self.LLM_PROVIDER, "default")

    def get_provider_for_tier(self, tier: str) -> str:
        return self.LLM_PROVIDER

    def get_rate_limit(self, provider: str) -> dict:
        return self.PROVIDER_RATE_LIMITS.get(provider, {"requests": 60, "window": 60})

    def get_collection_url(self, collection: str) -> str:
        return f"http://{self.QDRANT_HOST}:{self.QDRANT_PORT}"

    def get_embedding_url(self) -> str:
        return f"{self.OLLAMA_ENDPOINT}/api/embeddings"

# Global settings instance
settings = Settings()