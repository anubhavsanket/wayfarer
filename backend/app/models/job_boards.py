"""Job board registry — config-driven, no bespoke code per board.

Every job source is defined in ``config/job_boards.yaml``. Adding a new
board is a config change, not a code change. This module provides:

- Pydantic models matching the YAML schema
- ``JobBoardConnector``: a generic class that reads the registry and
  fetches + normalises postings from any registered board
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Literal

import httpx
import yaml
from pydantic import BaseModel, Field

from ..models.schemas import JobPosting

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config models
# ---------------------------------------------------------------------------

class PaginationConfig(BaseModel):
    type: Literal["offset", "start_offset", "query_param", "none"] = "offset"
    param: str = "page"
    start_value: int = 0
    step: int = 10
    max_pages: int = 5


class FieldMapping(BaseModel):
    title: str = ""
    company: str = ""
    location: str = ""
    url: str = ""
    description: str = ""
    remote_type: str = ""


class CSSSelectors(BaseModel):
    listing: str = "li"
    title: str = "a"
    company: str = ".company"
    location: str = ".location"
    url: str = "a"
    description: str = ".description"


class JobBoardEntry(BaseModel):
    name: str
    enabled: bool = True
    type: Literal["rest_api", "html_scrape"] = "rest_api"
    base_url: str
    auth: Literal["none", "api_key"] = "none"
    api_key_env: str | None = None
    rate_limit_per_min: int = 60
    field_mapping: FieldMapping = Field(default_factory=FieldMapping)
    css_selectors: CSSSelectors = Field(default_factory=CSSSelectors)
    pagination: PaginationConfig = Field(default_factory=PaginationConfig)
    extra_params: dict[str, str] = Field(default_factory=dict)


class JobBoardRegistry(BaseModel):
    job_boards: list[JobBoardEntry] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_path(obj: Any, path: str) -> Any:
    """Resolve a JSONPath-like path (e.g. '$.employer_name') against a dict.

    Supports dotted keys: ``$.foo.bar.baz`` walks ``obj["foo"]["bar"]["baz"]``.
    """
    if not path.startswith("$"):
        return None
    parts = path.lstrip("$.").split(".")
    current = obj
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _get_api_key(board: JobBoardEntry) -> str | None:
    if board.auth == "api_key" and board.api_key_env:
        return os.environ.get(board.api_key_env)
    return None


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def load_registry(path: str = "config/job_boards.yaml") -> JobBoardRegistry:
    """Load job board config from the YAML registry."""
    with open(path) as f:
        data = yaml.safe_load(f)
    return JobBoardRegistry.model_validate(data or {"job_boards": []})


# ---------------------------------------------------------------------------
# Generic connector
# ---------------------------------------------------------------------------

class JobBoardConnector:
    """Fetches and normalises postings from any registered board.

    Usage::

        registry = load_registry()
        connector = JobBoardConnector()
        for board in registry.job_boards:
            postings = await connector.fetch_all(board)
    """

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(timeout=30)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def fetch_all(
        self,
        board: JobBoardEntry,
        *,
        keywords: str = "",
        location: str = "",
        pages: int | None = None,
    ) -> list[JobPosting]:
        """Fetch postings from a board, handling pagination and normalisation.

        Returns a list of normalised ``JobPosting`` objects.
        """
        if board.type == "html_scrape":
            logger.warning(
                "HTML scrape boards not yet implemented — skipping %s", board.name,
            )
            return []
        return await self._fetch_rest_api(board, keywords=keywords, location=location, pages=pages)

    async def _fetch_rest_api(
        self,
        board: JobBoardEntry,
        *,
        keywords: str,
        location: str,
        pages: int | None,
    ) -> list[JobPosting]:
        postings: list[JobPosting] = []
        headers: dict[str, str] = {}
        api_key = _get_api_key(board)
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        pag = board.pagination
        max_pages = pages or pag.max_pages
        value = pag.start_value

        for page_num in range(max_pages):
            params: dict[str, Any] = dict(board.extra_params)
            if keywords:
                params["q"] = keywords
            if location:
                params["location"] = location

            # Add limit parameter for APIs that support it
            if board.name == "bluedoor":
                params["limit"] = 20

            # Inject pagination parameter (skip for "none" pagination)
            if pag.type != "none" and pag.param:
                params[pag.param] = value

            try:
                resp = await self._client.get(
                    board.base_url, params=params, headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
            except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.DecodingError) as exc:
                logger.warning("Failed to fetch from %s: %s", board.name, exc)
                break

            # data may be a list directly or wrapped in a key
            items: list[dict[str, Any]] = (
                data if isinstance(data, list) else data.get("results", data.get("data", []))
            )
            if not items:
                break

            for item in items:
                posting = self._normalise(board, item)
                if posting:
                    postings.append(posting)

            # Advance pagination
            if pag.type in ("start_offset", "query_param"):
                value += pag.step
            else:
                value += pag.step

        return postings

    def _normalise(self, board: JobBoardEntry, raw: dict[str, Any]) -> JobPosting | None:
        """Map a raw API response item to a normalised ``JobPosting``."""
        fm = board.field_mapping
        title = _resolve_path(raw, fm.title) or ""
        url = _resolve_path(raw, fm.url) or ""
        if not title and not url:
            return None

        # Fall back to 'provider' field when org_name is empty (bluedoor quirk)
        company = str(_resolve_path(raw, fm.company) or "")
        if not company or company == "None":
            company = str(_resolve_path(raw, "$.provider") or "Unknown")

        return JobPosting(
            id=f"{board.name}:{url or title}",
            source=board.name,
            title=str(title),
            company=company,
            url=str(url),
            location=str(_resolve_path(raw, fm.location) or ""),
            remote_type=str(_resolve_path(raw, fm.remote_type) or ""),
            description=str(_resolve_path(raw, fm.description) or ""),
            fetched_at=datetime.now(timezone.utc),
        )
