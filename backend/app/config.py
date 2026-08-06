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

    # ── Model selection (§12.5 — benchmarked per-tier) ────────────────
    # Evaluated on two benchmarks:
    #
    # Generation (21 rewrite cases, 2048 max_tokens, /no_think for qwen3):
    #   qwen3:1.7b      97% avg, 0 empty, 16.0s, 542 tok*, 1.3GB
    #   llama3.2:3b      90% avg, 0 empty, 18.1s,  41 tok,  1.9GB
    #   qwen2.5:1.5b     89% avg, 0 empty,  7.5s,  30 tok,  940MB
    #   lfm2.5-thinking  87% avg, 2 empty, 13.2s, 1236 tok, 700MB
    #
    # Classification (20 experience-level cases):
    #   qwen2.5:1.5b     70% acc, 9.5s avg, 940MB
    #   qwen3:0.6b       40% acc, 3.2s avg, ~500MB
    #   qwen3:1.7b       25% acc, 12.7s avg, 1.3GB (breaks with /no_think)
    #   lfm2.5-thinking  10% acc, 3.1s avg, 700MB
    #
    # * qwen3:1.7b uses ~500 thinking tokens internally even with
    #   /no_think — suppressed from output but counted in eval_count.
    #   This is why it's slower despite smaller model size.
    #
    # Key insight: thinking models (qwen3, lfm2.5) fail classification
    # because /no_think suppresses the reasoning chain needed to
    # determine experience level. Non-thinking models (qwen2.5) work.
    #
    # Decision: different models per tier.
    # - Simple tier (keyword extraction, classification): qwen2.5:1.5b
    #   Non-thinking model, 70% classification accuracy, fast.
    # - Complex tier (bullet rewriting, synthesis): qwen3:1.7b
    #   Thinking model, 97% rewrite accuracy, needs /no_think.
    # VRAM: 940MB + 1.3GB + 260MB embed = 2.76GB (1.2GB headroom on 4GB).
    # Both models coexist without cold-start swap risk.
    # Eval scripts: backend/eval_rewrite.py, backend/eval_classify.py
    OLLAMA_MODEL: str = "qwen2.5:1.5b"
    LLM_MODELS: dict = {
        "simple": {
            "nvidia": "meta/llama-3.1-8b-instruct",
            "openrouter": "meta-llama/llama-3.1-8b-instruct",
            "ollama": "qwen2.5:1.5b",
        },
        "complex": {
            "nvidia": "meta/llama-3.1-8b-instruct",
            "openrouter": "meta-llama/llama-3.1-8b-instruct",
            "ollama": "qwen3:1.7b",
        },
    }

    # ── Embedding ───────────────────────────────────────────────────────
    EMBEDDING_MODEL: str = "nomic-embed-text"

    # ── ChromaDB ────────────────────────────────────────────────────────
    CHROMA_HOST: str = "chromadb"
    CHROMA_PORT: int = 8001
    CHROMA_PERSIST_DIR: str = "./chroma_db"

    # ── Redis ───────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://redis:6379"

    # ── Collections ─────────────────────────────────────────────────────
    SEARCH_CACHE_COLLECTION: str = "search_cache"
    RESUME_SECTIONS_COLLECTION: str = "resume_sections"
    JOB_POSTINGS_COLLECTION: str = "job_postings"

    # ── Cache ───────────────────────────────────────────────────────────
    CONTENT_HASH_CACHE_DIR: str = "./cache/content_hashes"
    MAX_CACHE_ENTRIES: int = 10000
    CACHE_TTL_HOURS: int = 48

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
        return f"http://{self.CHROMA_HOST}:{self.CHROMA_PORT}"

    def get_embedding_url(self) -> str:
        return f"{self.OLLAMA_ENDPOINT}/api/embeddings"

# Global settings instance
settings = Settings()