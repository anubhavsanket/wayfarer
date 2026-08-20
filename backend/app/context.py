"""Request-scoped overrides context for API keys and endpoint settings.

Allows FastAPI middleware to extract ``X-*`` HTTP headers sent from the frontend
Settings tab and make them available to LLMRouter, SearchAPI, and JobBoardConnector
for the duration of the request without polluting global environment variables.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class RequestOverrides:
    llm_provider: Optional[str] = None
    nvidia_api_key: Optional[str] = None
    nvidia_endpoint: Optional[str] = None
    openrouter_api_key: Optional[str] = None
    openrouter_endpoint: Optional[str] = None
    ollama_endpoint: Optional[str] = None
    lmstudio_endpoint: Optional[str] = None
    lmstudio_model: Optional[str] = None
    custom_endpoint: Optional[str] = None
    custom_api_key: Optional[str] = None
    custom_model: Optional[str] = None
    tavily_api_key: Optional[str] = None
    brave_api_key: Optional[str] = None
    bluedoor_api_key: Optional[str] = None


request_overrides_var: ContextVar[Optional[RequestOverrides]] = ContextVar(
    "request_overrides", default=None
)


def get_request_overrides() -> Optional[RequestOverrides]:
    """Return current request overrides, if set."""
    return request_overrides_var.get()
