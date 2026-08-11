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
        # Ollama runs locally — no real rate limit. Set high enough to never
        # block synthesis (60/60s was too low: 8 test queries × 6 ollama calls
        # = 48 calls, and synthesis timed out at request #10).
        "ollama": {"requests": 600, "window": 60},
        "lmstudio": {"requests": 600, "window": 60},
        "custom": {"requests": 600, "window": 60},
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
    # Classification (20 cases, stability-tested at temperature=0.1):
    #   qwen2.5:1.5b     40-50% acc, 1.4s avg, 30 tok, 940MB
    #     (non-deterministic: 2/20 cases flip between runs at temp=0.1)
    #     (outputs non-standard labels: "1-3 years", "advanced",
    #      "intermediate", "professional" — not in standard set)
    #   qwen3:0.6b       32% acc, 3.2s avg, ~500 tok, 500MB
    #   qwen3:1.7b       26% acc, 4.2s avg, ~300 tok, 1.3GB
    #   qwen3.5:2b       ~70%+ acc, 120s+, 2618 tok, 2.6GB (thinking ON)
    #
    # * qwen3:1.7b uses ~500 thinking tokens internally even with
    #   /no_think — suppressed from output but counted in eval_count.
    #
    # Raw-output analysis of /no_think classification failures:
    #   Two failure modes found in thinking models with /no_think:
    #   (1) Non-standard labels: "entry-level", "mid-level", "Senior"
    #       vs standard set — requires synonym mapping
    #   (2) Genuine errors: "Staff Engineer" → "Mid" (should be senior)
    #
    # Non-determinism confirmed: even at temperature=0.1, 2/20 cases
    # flip between runs. Earlier accuracy numbers (74%, 68%) were
    # inflated by comparing different runs — not reproducible.
    # Real accuracy for qwen2.5:1.5b is 40-50%.
    #
    # Decision: different models per tier (best available, not perfect).
    # - Simple tier (keyword extraction, classification): qwen2.5:1.5b
    #   Non-thinking model, 40-50% classification accuracy, 1.4s.
    #   Outputs non-standard labels but fastest and least token-hungry.
    # - Complex tier (bullet rewriting, synthesis): qwen3:1.7b
    #   Thinking model, 97% rewrite accuracy, 16s avg.
    #   /no_think suppresses output but ~500 tokens still consumed
    #   internally (visible in eval_count, not in content).
    # VRAM: 940MB + 1.3GB + 260MB embed = 2.76GB (1.2GB headroom on 4GB).
    # Both models coexist without cold-start swap risk.
    # Eval scripts: backend/eval_rewrite.py, backend/eval_classify.py,
    #               backend/eval_stability.py (determinism check)
    OLLAMA_MODEL: str = "qwen2.5:1.5b"
    LLM_MODELS: dict = {
        "simple": {
            "nvidia": "meta/llama-3.1-8b-instruct",
            "openrouter": "meta-llama/llama-3.1-8b-instruct",
            "ollama": "llama3.2:3b",  # fastest (16s), non-thinking, fits in 4GB VRAM
        },
        "complex": {
            "nvidia": "meta/llama-3.1-8b-instruct",
            "openrouter": "meta-llama/llama-3.1-8b-instruct",
            "ollama": "llama3.2:3b",  # thinking models return empty after tag stripping
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
    JOBS_TOP_K_EMBEDDING_SURVIVORS: int = 25  # increased from 15 — more survivors = better coverage
    JOBS_MAX_EMBED_POSTINGS: int = 50  # max postings to embed (two-pass: lexical pre-filter → embed top N)
    JOBS_LEXICAL_PREFILTER_TOP_N: int = 100  # lexical pre-filter keeps this many before embedding

    # ── Timeouts ────────────────────────────────────────────────────────
    REQUEST_TIMEOUT: int = 30
    RATE_LIMIT_BACKOFF: float = 1.5
    SYNTHESIS_TIMEOUT: float = 90.0  # CPU inference queues when concurrent; 90s handles up to ~12 parallel requests

    # ── Performance ─────────────────────────────────────────────────────
    MAX_VRAM_GB: int = 4

    # ── Job Board API Keys ──────────────────────────────────────────────
    BLUEDOOR_API_KEY: Optional[str] = None

    # ── User Preferences ────────────────────────────────────────────
    NEEDS_VISA_SPONSORSHIP: bool = False  # FR3.8: set True to flag no-sponsorship postings
    ENABLE_PROMPT_CACHING: bool = True   # §12.3: enable prompt caching for repeated calls

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