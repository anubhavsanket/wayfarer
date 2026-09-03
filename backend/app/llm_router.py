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
import hashlib
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import settings
from .context import get_request_overrides
from .utils.cache import llm_cache, embed_cache

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
        while self._timestamps and self._timestamps[0] < now - self.window_seconds:
            self._timestamps.popleft()
        if len(self._timestamps) < self.max_requests:
            self._timestamps.append(now)
            return True
        return False

    def reset(self) -> None:
        self._timestamps.clear()


# ---------------------------------------------------------------------------
# LLM Router
# ---------------------------------------------------------------------------

class LLMRouter:
    """Multi-provider LLM router with caching and rate limiting."""

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT)
        # Build rate-limit buckets from config
        self._buckets: dict[str, _RateLimitBucket] = {}
        for prov, cfg in settings.PROVIDER_RATE_LIMITS.items():
            self._buckets[prov] = _RateLimitBucket(
                max_requests=cfg["requests"],
                window_seconds=float(cfg["window"]),
            )

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
        tools: list[dict] | None = None,
        tool_choice: str | dict | None = None,
        provider: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Route a chat completion through the best available provider."""
        overrides = get_request_overrides()
        
        # Use explicit args if provided, else fall back to request overrides
        resolved_provider = provider or (overrides.llm_provider if overrides else None)
        resolved_model = model or (overrides.custom_model if overrides and resolved_provider == "custom" else None)
        
        if not resolved_provider:
            candidates = list(settings.PROVIDER_RATE_LIMITS.keys())
        else:
            # Preferred provider first, then the rest of the chain so a dead
            # primary (EOL model, revoked key, exhausted quota) still falls
            # through to local Ollama instead of failing the whole request.
            candidates = [resolved_provider] + [
                p for p in settings.PROVIDER_RATE_LIMITS if p != resolved_provider
            ]
            
        last_error: Exception | None = None


        for prov in candidates:
            # Check provider credentials
            if not self._provider_available(prov, overrides):
                logger.debug("Provider %s skipped (no API key / model)", prov)
                continue

            # Wait for a rate-limit slot before hitting the provider
            if not await self._acquire_slot(prov):
                logger.warning("Provider %s rate-limited locally, skipping", prov)
                continue

            # Check Redis cache before making the provider call
            cache_key = self._cache_key(
                json.dumps(messages, sort_keys=True, default=str),
                resolved_model or "",
                str(temperature),
                prov,
                json.dumps(tools, sort_keys=True) if tools else "",
            )
            logger.debug("Checking LLM Cache (Key: %s)", cache_key[:16])

            try:
                cached = await llm_cache.get(cache_key)
                if cached is not None:
                    logger.info("LLM cache HIT (Key: %s)", cache_key[:16])
                    cached["cached"] = True
                    return cached
                logger.info("LLM cache MISS (Key: %s)", cache_key[:16])
            except Exception:
                pass  # cache failure is non-fatal

            try:
                result = await self._call_provider(
                    prov, resolved_model, messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    cache_control=cache_control,
                    json_mode=json_mode,
                    tools=tools,
                    tool_choice=tool_choice,
                )
                # Store successful result in cache
                try:
                    await llm_cache.set(cache_key, result)
                except Exception:
                    pass
                return result
            except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                status = getattr(exc, "response", None)
                status_code = getattr(status, "status_code", None)
                logger.warning(
                    "Provider %s failed (status=%s): %s — falling back",
                    prov, status_code, exc,
                )
                # If rate-limited (429), back off briefly
                if status_code == 429:
                    retry_after = self._parse_retry_after(exc)
                    if retry_after:
                        logger.info("Rate-limited by %s, waiting %ss", prov, retry_after)
                        await asyncio.sleep(retry_after)
                continue

        # All providers exhausted
        raise RuntimeError(
            f"All LLM providers exhausted. Last error: {last_error}"
        )

    async def embed(self, text: str) -> list[float]:
        """Embed text locally via Ollama (nomic-embed-text)."""
        overrides = get_request_overrides()
        ollama_endpoint = (overrides.ollama_endpoint if overrides and overrides.ollama_endpoint else settings.OLLAMA_ENDPOINT)

        # Check embedding cache before calling Ollama
        cache_key = self._cache_key(text, settings.EMBEDDING_MODEL)
        try:
            cached = await embed_cache.get(cache_key)
            if cached is not None:
                logger.info("Embedding cache HIT (Key: %s)", cache_key[:16])
                return cached
            logger.info("Embedding cache MISS (Key: %s)", cache_key[:16])
        except Exception:
            pass

        url = f"{ollama_endpoint.rstrip('/')}/api/embeddings"
        try:
            # Embedding calls use a longer timeout — Ollama can take 30s+
            # to load a model on cold start, then it's fast.
            resp = await self._client.post(
                url,
                json={"model": settings.EMBEDDING_MODEL, "prompt": text},
                timeout=httpx.Timeout(120.0),
            )
            resp.raise_for_status()
            embedding = resp.json()["embedding"]
            # Cache the embedding for future calls
            try:
                await embed_cache.set(cache_key, embedding)
            except Exception:
                pass
            return embedding
        except Exception as exc:
            raise RuntimeError(f"Embedding failed via {url}: {exc}") from exc

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- cache helpers ------------------------------------------------------

    @staticmethod
    def _cache_key(*parts: str) -> str:
        """Deterministic SHA-256 hash key for caching."""
        h = hashlib.sha256()
        for p in parts:
            h.update(p.encode("utf-8"))
        return h.hexdigest()

    # -- internals ----------------------------------------------------------

    def _model_for(self, provider: str, tier: str, override: str | None = None) -> str | None:
        """Resolve the model for a given provider+tier."""
        overrides = get_request_overrides()
        resolved_provider = provider or (overrides.llm_provider if overrides else settings.LLM_PROVIDER)
        
        # If model override is given, use it
        if override:
            return override
            
        # Check for model from request overrides
        if overrides:
            if resolved_provider == "custom" and overrides.custom_model:
                return overrides.custom_model
            if resolved_provider == "lmstudio" and overrides.lmstudio_model:
                return overrides.lmstudio_model

        # Default to settings-based resolution
        tier_models = settings.LLM_MODELS.get(tier, settings.LLM_MODELS["simple"])
        model = tier_models.get(resolved_provider)
        return model

    def _resolve_candidates(self, overrides) -> list[str]:
        """Return an ordered list of providers to try."""
        if overrides.llm_provider:
            return [overrides.llm_provider] + [
                p for p in settings.PROVIDER_RATE_LIMITS if p != overrides.llm_provider
            ]
        return list(settings.PROVIDER_RATE_LIMITS.keys())

    def _provider_available(self, provider: str, overrides) -> bool:
        if provider == "nvidia":
            return bool(overrides.nvidia_api_key or settings.NVIDIA_NIM_API_KEY)
        if provider == "openrouter":
            return bool(overrides.openrouter_api_key or settings.OPENROUTER_API_KEY)
        if provider == "ollama":
            return True
        if provider == "lmstudio":
            return True
        if provider == "custom":
            return bool(settings.CUSTOM_LLM_ENDPOINT)
        return False

    async def _acquire_slot(self, provider: str) -> bool:
        bucket = self._buckets.get(provider)
        if bucket is None:
            return True
        if bucket.allow():
            return True
        # Wait until the oldest timestamp in the window expires
        now = time.monotonic()
        if bucket._timestamps:
            wait = bucket._timestamps[0] + bucket.window_seconds - now
            if wait > 0:
                await asyncio.sleep(wait)
            return bucket.allow()
        return True

    @staticmethod
    def _parse_retry_after(exc: httpx.HTTPStatusError) -> float | None:
        resp = exc.response
        if resp is None:
            return None
        header = resp.headers.get("retry-after")
        if header:
            try:
                return float(header)
            except ValueError:
                pass
        return None

    async def _call_provider(
        self,
        provider: str,
        model: str | None,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        temperature: float,
        cache_control: bool,
        json_mode: bool,
        tools: list[dict] | None = None,
        tool_choice: str | dict | None = None,
    ) -> dict[str, Any]:
        if provider in ("nvidia", "openrouter", "lmstudio", "custom"):
            return await self._call_openai_compat(
                provider, model, messages,
                max_tokens=max_tokens,
                temperature=temperature,
                cache_control=cache_control,
                json_mode=json_mode,
                tools=tools,
                tool_choice=tool_choice,
            )
        elif provider == "ollama":
            return await self._call_ollama(
                model, messages,
                max_tokens=max_tokens,
                temperature=temperature,
                json_mode=json_mode,
                tools=tools,
                tool_choice=tool_choice,
            )
        else:
            raise ValueError(f"Unknown provider: {provider}")

    async def _call_openai_compat(
        self,
        provider: str,
        model: str | None,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        temperature: float,
        cache_control: bool,
        json_mode: bool,
        tools: list[dict] | None = None,
        tool_choice: str | dict | None = None,
    ) -> dict[str, Any]:
        overrides = get_request_overrides()
        endpoint, api_key = self._get_endpoint_and_key(provider, overrides)
        resolved_model = model or self._default_model(provider)

        payload: dict[str, Any] = {
            "model": resolved_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if tools:
            payload["tools"] = tools
            if tool_choice is not None:
                payload["tool_choice"] = tool_choice

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        if cache_control:
            payload["cache_control"] = {"type": "ephemeral"}

        resp = await self._client.post(
            f"{endpoint.rstrip('/')}/chat/completions",
            json=payload,
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()

        content = data["choices"][0]["message"]["content"] or ""
        tool_calls = data["choices"][0]["message"].get("tool_calls")
        provider_name = provider
        model_used = data.get("model", resolved_model)
        cached = bool(data.get("usage", {}).get("prompt_cache_hit_tokens", 0))
        return {
            "content": content,
            "provider": provider_name,
            "model": model_used,
            "cached": cached,
            "tool_calls": tool_calls,
        }

    async def _call_ollama(
        self,
        model: str | None,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        temperature: float,
        json_mode: bool,
        tools: list[dict] | None = None,
        tool_choice: str | dict | None = None,
    ) -> dict[str, Any]:
        overrides = get_request_overrides()
        ollama_endpoint = overrides.ollama_endpoint if overrides and overrides.ollama_endpoint else settings.OLLAMA_ENDPOINT
        resolved_model = model or settings.get_model_for_tier("simple")

        payload: dict[str, Any] = {
            "model": resolved_model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if json_mode:
            payload["format"] = "json"
        if tools:
            payload["tools"] = tools
            if tool_choice is not None:
                # Ollama supports tool_choice as "auto", "none", or a tool name
                payload["tool_choice"] = tool_choice

        url = f"{ollama_endpoint.rstrip('/')}/api/chat"

        try:
            resp = await self._client.post(url, json=payload, timeout=httpx.Timeout(90.0))
            resp.raise_for_status()
            data = resp.json()

            message = data.get("message", {})
            content = message.get("content", "")
            tool_calls = message.get("tool_calls")

            return {
                "content": content,
                "provider": "ollama",
                "model": resolved_model,
                "cached": False,
                "tool_calls": tool_calls,
            }
        except httpx.ConnectError:
            raise RuntimeError(
                f"Ollama is not reachable at {url}. "
                "Start Ollama locally (`ollama serve`) or use Docker Compose, "
                f"and pull the model: ollama pull {resolved_model}"
            ) from None

    def _get_endpoint_and_key(self, provider: str, overrides) -> tuple[str, str]:
        if provider == "nvidia":
            return (
                overrides.nvidia_endpoint or settings.NVIDIA_NIM_ENDPOINT,
                overrides.nvidia_api_key or settings.NVIDIA_NIM_API_KEY or "",
            )
        if provider == "openrouter":
            return (
                overrides.openrouter_endpoint or settings.OPENROUTER_ENDPOINT,
                overrides.openrouter_api_key or settings.OPENROUTER_API_KEY or "",
            )
        if provider == "lmstudio":
            return (settings.LMSTUDIO_ENDPOINT, settings.LMSTUDIO_API_KEY)
        if provider == "custom":
            return (settings.CUSTOM_LLM_ENDPOINT, settings.CUSTOM_LLM_API_KEY)
        raise ValueError(f"No endpoint for provider: {provider}")

    def _default_model(self, provider: str) -> str:
        tier_models = settings.LLM_MODELS.get("simple", {})
        return tier_models.get(provider, "unknown")


# ---------------------------------------------------------------------------
# JSON extraction helper (used across stages)
# ---------------------------------------------------------------------------

def extract_json(text: str) -> Any:
    """Best-effort JSON extraction from LLM output."""
    if not text:
        return None
    # Strip markdown code fences if present
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        # Remove first and last fence lines
        if lines[-1].strip() == "```":
            lines = lines[1:-1]
        elif lines[0].strip().startswith("```"):
            lines = lines[1:]
        cleaned = "\n".join(lines).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to find JSON array or object in the text
        for start_char, end_char in [("[", "]"), ("{", "}")]:
            start = cleaned.find(start_char)
            end = cleaned.rfind(end_char)
            if start != -1 and end > start:
                try:
                    return json.loads(cleaned[start:end + 1])
                except json.JSONDecodeError:
                    continue
        return None


# ---------------------------------------------------------------------------
# Tool definitions for structured extraction
# ---------------------------------------------------------------------------

EXTRACT_KEYWORDS_TOOL = {
    "type": "function",
    "function": {
        "name": "extract_keywords",
        "description": "Extract technical and professional keywords from a job description.",
        "parameters": {
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of technical skills, tools, languages, frameworks, certifications"
                }
            },
            "required": ["keywords"]
        }
    }
}

EXTRACT_JSON_TOOL = {
    "type": "function",
    "function": {
        "name": "extract_json",
        "description": "Extract structured data as JSON matching the expected schema.",
        "parameters": {
            "type": "object",
            "properties": {
                "data": {
                    "type": "object",
                    "description": "The extracted structured data"
                }
            },
            "required": ["data"]
        }
    }
}

CLASSIFY_SIMILARITY_TOOL = {
    "type": "function",
    "function": {
        "name": "classify_similarity",
        "description": "Classify the similarity between a keyword and a resume bullet.",
        "parameters": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string"},
                "bullet_text": {"type": "string"},
                "tier": {"type": "string", "enum": ["verified", "reworded", "gap"]},
                "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "rewritten_text": {"type": "string"}
            },
            "required": ["keyword", "bullet_text", "tier", "confidence"]
        }
    }
}


def extract_tool_response(result: dict) -> Any:
    """Extract the tool call arguments from a router chat result.
    
    If the model responded with a tool call, extract the arguments.
    Otherwise, fall back to parsing the content as JSON.
    """
    tool_calls = result.get("tool_calls")
    if tool_calls and len(tool_calls) > 0:
        # Get the first tool call's arguments
        tool_call = tool_calls[0]
        if isinstance(tool_call, dict):
            function = tool_call.get("function", {})
            arguments = function.get("arguments", {})
            if isinstance(arguments, str):
                return json.loads(arguments)
            return arguments
    # Fallback to content parsing
    return extract_json(result.get("content", ""))


# ---------------------------------------------------------------------------
# Singleton router instance
# ---------------------------------------------------------------------------

router = LLMRouter()
