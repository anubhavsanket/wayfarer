"""Search API clients — Tavily (primary) and Brave (fallback).

Each provider exposes the same interface: ``search(query, max_results) ->
list[SearchResultItem]`` so the orchestrator can swap providers without
knowing which one answered.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import httpx

from ..context import get_request_overrides

logger = logging.getLogger(__name__)


@dataclass
class SearchResultItem:
    url: str
    title: str
    snippet: str
    rank: int


class SearchAPIError(RuntimeError):
    """Raised when a search provider fails (missing key, HTTP error)."""


class TavilyClient:
    BASE_URL = "https://api.tavily.com/search"

    def __init__(self, api_key: str | None = None) -> None:
        overrides = get_request_overrides()
        self.api_key = (
            api_key
            or (overrides.tavily_api_key if overrides and overrides.tavily_api_key else None)
            or os.environ.get("TAVILY_API_KEY")
        )

    def available(self) -> bool:
        return bool(self.api_key)

    async def search(self, query: str, max_results: int = 5) -> list[SearchResultItem]:
        if not self.available():
            raise SearchAPIError("Tavily API key not configured")
        payload = {
            "api_key": self.api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(self.BASE_URL, json=payload)
            resp.raise_for_status()
            data = resp.json()
        items: list[SearchResultItem] = []
        for i, r in enumerate(data.get("results", [])):
            items.append(
                SearchResultItem(
                    url=r.get("url", ""),
                    title=r.get("title", ""),
                    snippet=r.get("content", ""),
                    rank=i,
                )
            )
        return items


class BraveClient:
    BASE_URL = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key: str | None = None) -> None:
        overrides = get_request_overrides()
        self.api_key = (
            api_key
            or (overrides.brave_api_key if overrides and overrides.brave_api_key else None)
            or os.environ.get("BRAVE_API_KEY")
        )

    def available(self) -> bool:
        return bool(self.api_key)

    async def search(self, query: str, max_results: int = 5) -> list[SearchResultItem]:
        if not self.available():
            raise SearchAPIError("Brave API key not configured")
        headers = {"X-Subscription-Token": self.api_key}
        params = {"q": query, "count": max_results, "search_lang": "en"}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(self.BASE_URL, params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        items: list[SearchResultItem] = []
        for i, r in enumerate(data.get("web", {}).get("results", [])):
            items.append(
                SearchResultItem(
                    url=r.get("url", ""),
                    title=r.get("title", ""),
                    snippet=r.get("description", ""),
                    rank=i,
                )
            )
        return items


# Provider registry — tried in order, first available wins
SEARCH_PROVIDERS = (TavilyClient, BraveClient)


async def run_search(
    query: str,
    max_results: int = 5,
    providers: tuple[type, ...] = SEARCH_PROVIDERS,
) -> tuple[list[SearchResultItem], str]:
    """Search using the first available provider.

    Returns ``(items, provider_name)``. Raises ``SearchAPIError`` if every
    configured provider fails (missing key or HTTP error).
    """
    errors: list[str] = []
    for cls in providers:
        client = cls()
        if not client.available():
            errors.append(f"{cls.__name__}: no API key")
            continue
        try:
            items = await client.search(query, max_results)
            if items:
                return items, cls.__name__.replace("Client", "").lower()
        except Exception as exc:
            errors.append(f"{cls.__name__}: {exc}")
            logger.warning("Search provider %s failed: %s", cls.__name__, exc)
    raise SearchAPIError("All search providers failed: " + "; ".join(errors))
