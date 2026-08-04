"""Rate-limit-aware LLM router with automatic provider fallback.

Every stage calls inference through this module, never directly against a
provider. The router owns:

- Provider selection (NVIDIA NIM → OpenRouter → Ollama local)
- Sliding-window rate limiting per provider (429 protection)
- Automatic failover on 429/5xx/timeout
- Prompt-caching awareness (passes through cache-control headers where
  supported; this is abstracted so callers don't need to know which)
- Model selection per task complexity tier (simple vs complex)

NVIDIA NIM and OpenRouter both expose OpenAI-compatible chat endpoints, so
they share a single request path. Ollama is handled separately.

Usage:
    router = LLMRouter()
    resp = await router.chat(
        messages=[{"role": "user", "content": "..."}],
        tier="simple",          # "simple" | "complex"
        max_tokens=512,
    )
    print(resp["content"])
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

@dataclass
class _RateLimitBucket:
    """Sliding-window request counter for a single provider."""
    max_requests: int
    window_seconds: float
    _timestamps: deque = field(default_factory=deque)

    def allow(self) -> bool:
        now = time.monotonic()
        # Drop timestamps outside the window
        while self._timestamps and now - self._timestamps[0] > self.window_seconds:
            self._timestamps.popleft()
        if len(self._timestamps) >= self.max_requests:
            return False
        return True

    def record(self) -> None:
        self._timestamps.append(time.monotonic())

    def retry_after(self) -> float:
        """Seconds until the next slot frees, or 0 if a slot is free now."""
        if not self._timestamps:
            return 0.0
        now = time.monotonic()
        oldest = self._timestamps[0]
        return max(0.0, (oldest + self.window_seconds) - now)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

class LLMRouter:
    """Multi-provider chat router with fallback and rate limiting.

    Supports: nvidia, openrouter, ollama, lmstudio, custom.
    LM Studio and custom use the same OpenAI-compatible chat endpoint.
    """

    PROVIDER_ORDER = ("nvidia", "openrouter", "ollama", "lmstudio", "custom")

    def __init__(self, providers: tuple[str, ...] | None = None) -> None:
        if providers:
            self.providers = tuple(providers)
        else:
            # Start with the configured provider, then fall back to the others
            primary = settings.LLM_PROVIDER
            fallbacks = [p for p in self.PROVIDER_ORDER if p != primary]
            self.providers = (primary, *fallbacks)
        # Validate that requested providers are recognized
        unknown = set(self.providers) - set(self.PROVIDER_ORDER)
        if unknown:
            raise ValueError(f"Unknown providers: {unknown}")

        self._buckets: dict[str, _RateLimitBucket] = {}
        for provider in self.PROVIDER_ORDER:
            limits = settings.get_rate_limit(provider)
            self._buckets[provider] = _RateLimitBucket(
                max_requests=int(limits["requests"]),
                window_seconds=float(limits["window"]),
            )
        self._client = httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT)
        self._llm_timeout = httpx.Timeout(90.0)
        self._lock = asyncio.Lock()

    # -- public API ---------------------------------------------------------

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        tier: str = "simple",
        max_tokens: int = 512,
        temperature: float = 0.2,
        cache_control: bool = False,
        json_mode: bool = False,
        provider: str | None = None,
    ) -> dict[str, Any]:
        """Send a chat request, failing over across providers.

        Returns {"content": str, "provider": str, "model": str, "cached": bool}.
        Raises RuntimeError if every provider is exhausted.
        """
        # If a specific provider is requested, only try it
        candidates = (provider,) if provider else self.providers
        last_error: Exception | None = None

        for prov in candidates:
            model = self._model_for(prov, tier)
            if not self._provider_available(prov, model):
                logger.debug("Provider %s skipped (no API key / model)", prov)
                continue

            # Wait for a rate-limit slot before hitting the provider
            if not await self._acquire_slot(prov):
                logger.warning("Provider %s rate-limited locally, skipping", prov)
                continue

            try:
                return await self._call_provider(
                    prov, model, messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    cache_control=cache_control,
                    json_mode=json_mode,
                )
            except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                status = getattr(exc, "response", None)
                status_code = getattr(status, "status_code", None)
                logger.warning(
                    "Provider %s failed (status=%s): %s — falling back",
                    prov, status_code, exc,
                )
                # On 429/5xx, back off before the next provider attempt
                if status_code in (429, 500, 502, 503, 504):
                    await asyncio.sleep(settings.RATE_LIMIT_BACKOFF)
                continue
            except Exception as exc:  # unexpected — don't burn more providers silently
                logger.error("Provider %s unexpected error: %s", prov, exc)
                last_error = exc
                continue

        raise RuntimeError(
            f"All LLM providers exhausted: {self.providers}"
            + (f" (last error: {last_error})" if last_error else "")
        )

    async def embed(self, text: str) -> list[float]:
        """Embed text locally via Ollama (nomic-embed-text)."""
        url = f"{settings.OLLAMA_ENDPOINT}/api/embeddings"
        try:
            # Embedding calls use a longer timeout — Ollama can take 30s+
            # to load a model on cold start, then it's fast.
            resp = await self._client.post(
                url,
                json={"model": settings.EMBEDDING_MODEL, "prompt": text},
                timeout=httpx.Timeout(120.0),
            )
            resp.raise_for_status()
            return resp.json()["embedding"]
        except Exception as exc:
            raise RuntimeError(f"Embedding failed via {url}: {exc}") from exc

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- internals ----------------------------------------------------------

    def _model_for(self, provider: str, tier: str) -> str | None:
        """Resolve the model for a provider+tier, or None if unavailable."""
        # For lmstudio / custom, use the explicit model name from settings
        if provider == "lmstudio":
            return settings.LMSTUDIO_MODEL or None
        if provider == "custom":
            return settings.CUSTOM_LLM_MODEL or None

        tier_models = settings.LLM_MODELS.get(tier, settings.LLM_MODELS["simple"])
        model = tier_models.get(provider)
        if not model:
            return None
        # Check the provider has credentials configured
        if provider == "nvidia" and not settings.NVIDIA_NIM_API_KEY:
            return None
        if provider == "openrouter" and not settings.OPENROUTER_API_KEY:
            return None
        return model

    def _provider_available(self, provider: str, model: str | None) -> bool:
        if model is None:
            return False
        if provider == "ollama":
            # Ollama is local; availability is probed at call time.
            return True
        return True

    async def _acquire_slot(self, provider: str) -> bool:
        """Wait up to the window for a rate-limit slot. Returns True if granted."""
        bucket = self._buckets[provider]
        deadline = time.monotonic() + bucket.window_seconds
        while time.monotonic() < deadline:
            if bucket.allow():
                bucket.record()
                return True
            await asyncio.sleep(min(0.5, bucket.retry_after() or 0.5))
        return False

    async def _call_provider(
        self,
        provider: str,
        model: str,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        temperature: float,
        cache_control: bool,
        json_mode: bool,
    ) -> dict[str, Any]:
        if provider == "ollama":
            return await self._call_ollama(
                model, messages, max_tokens=max_tokens, temperature=temperature,
            )
        return await self._call_openai_compatible(
            provider, model, messages,
            max_tokens=max_tokens,
            temperature=temperature,
            cache_control=cache_control,
            json_mode=json_mode,
        )

    async def _call_openai_compatible(
        self,
        provider: str,
        model: str,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        temperature: float,
        cache_control: bool,
        json_mode: bool,
    ) -> dict[str, Any]:
        # Resolve endpoint and API key per provider
        if provider == "nvidia":
            endpoint = settings.NVIDIA_NIM_ENDPOINT
            api_key = settings.NVIDIA_NIM_API_KEY
        elif provider == "openrouter":
            endpoint = settings.OPENROUTER_ENDPOINT
            api_key = settings.OPENROUTER_API_KEY
        elif provider == "lmstudio":
            endpoint = settings.LMSTUDIO_ENDPOINT
            api_key = settings.LMSTUDIO_API_KEY
        elif provider == "custom":
            endpoint = settings.CUSTOM_LLM_ENDPOINT
            api_key = settings.CUSTOM_LLM_API_KEY
        else:
            endpoint = settings.NVIDIA_NIM_ENDPOINT
            api_key = settings.NVIDIA_NIM_API_KEY
        url = f"{endpoint.rstrip('/')}/chat/completions"

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if cache_control:
            # OpenAI-compatible prompt-caching hint (NVIDIA NIM supports it;
            # ignored gracefully by providers that don't).
            payload["cache_control"] = {"type": "ephemeral"}

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        resp = await self._client.post(url, json=payload, headers=headers, timeout=self._llm_timeout)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        cached = bool(data.get("usage", {}).get("prompt_cache_hit_tokens", 0))
        return {"content": content, "provider": provider, "model": model, "cached": cached}

    async def _call_ollama(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        temperature: float,
    ) -> dict[str, Any]:
        url = f"{settings.OLLAMA_ENDPOINT}/api/chat"
        resp = await self._client.post(
            url,
            json={
                "model": model,
                "messages": messages,
                "stream": False,
                "options": {
                    "num_predict": max_tokens,
                    "temperature": temperature,
                },
            },
            timeout=self._llm_timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "content": data["message"]["content"],
            "provider": "ollama",
            "model": model,
            "cached": False,
        }


# Convenience singleton used across the app
router = LLMRouter()


# ---------------------------------------------------------------------------
# Small helpers for structured output
# ---------------------------------------------------------------------------

def extract_json(content: str) -> Any:
    """Best-effort parse of JSON from an LLM response (handles ``` fences)."""
    text = content.strip()
    if text.startswith("```"):
        # Strip code fences and optional language tag
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Fall back to first {...} or [...] block in the response
        import re
        for pattern in (r"\{.*\}", r"\[.*\]"):
            match = re.search(pattern, text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
        raise
