"""Job board registry — config-driven, no bespoke code per board.

Every job source is defined in ``config/job_boards.yaml``. Adding a new
board is a config change, not a code change. This module provides:

- Pydantic models matching the YAML schema
- ``JobBoardConnector``: a generic class that reads the registry and
  fetches + normalises postings from any registered board
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from datetime import datetime, timezone
from typing import Any, Literal

import httpx
import re
import yaml
from pydantic import BaseModel, Field

from ..models.schemas import JobPosting

logger = logging.getLogger(__name__)

# SSRF defense: hostname allowlist for multi-company boards
_ALLOWED_HOSTS: dict[str, set[str]] = {
    "greenhouse": {"boards-api.greenhouse.io"},
    "lever": {"api.lever.co"},
    "ashby": {"api.ashbyhq.com"},
}


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
    type: Literal["rest_api", "html_scrape", "rss_feed"] = "rest_api"
    base_url: str
    auth: Literal["none", "api_key"] = "none"
    api_key_env: str | None = None
    rate_limit_per_min: int = 60
    field_mapping: FieldMapping = Field(default_factory=FieldMapping)
    css_selectors: CSSSelectors = Field(default_factory=CSSSelectors)
    pagination: PaginationConfig = Field(default_factory=PaginationConfig)
    extra_params: dict[str, str] = Field(default_factory=dict)
    extra_headers: dict[str, str] = Field(default_factory=dict)
    default_remote_type: str = ""  # Fixed remote_type for boards where all jobs are remote
    # Multi-company expansion: env var with comma-separated company slugs
    company_slugs_env: str | None = None
    # URL with {slug} placeholder (e.g. boards-api.greenhouse.io/v1/boards/{slug}/jobs)
    url_template: str | None = None
    # Derive company name from the slug instead of from the API response
    company_from_slug: bool = False
    # Override fetch timeout for slow providers (e.g. Ashby ~10s+ latency)
    fetch_timeout_override: int | None = None


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
        # Check per-request override from Settings UI headers first
        try:
            from ..main import get_overrides
            ov = get_overrides()
            if board.name == "bluedoor" and ov.bluedoor_api_key:
                return ov.bluedoor_api_key
        except ImportError:
            pass
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
        self._last_request: dict[str, float] = {}  # per-board rate limit tracking

    async def aclose(self) -> None:
        await self._client.aclose()

    def _validate_url(self, url: str, board_name: str) -> None:
        """SSRF defense: reject URLs whose hostname is not on the allowlist.

        Only enforced for boards with an entry in ``_ALLOWED_HOSTS``.
        Raises ``ValueError`` if the hostname is not allowed.
        """
        allowed = _ALLOWED_HOSTS.get(board_name)
        if not allowed:
            return  # no allowlist = no restriction (existing boards)
        try:
            parsed = httpx.URL(url)
            hostname = parsed.host or ""
        except Exception:
            raise ValueError(f"{board_name}: cannot parse URL for SSRF check: {url}")
        if hostname not in allowed:
            raise ValueError(
                f"{board_name}: blocked hostname '{hostname}' — "
                f"must be one of: {', '.join(sorted(allowed))}"
            )

    async def _fetch_with_retry(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 30,
        max_retries: int = 3,
        board_name: str = "",
    ) -> httpx.Response:
        """HTTP GET with exponential backoff + jitter on 429/5xx.

        Retries up to ``max_retries`` times on 429 or 5xx status codes.
        Non-retryable errors (4xx except 429) are raised immediately.
        """
        delay = 0.5  # starting backoff in seconds
        last_exc: Exception | None = None

        # SSRF validation (only for boards with allowlists)
        self._validate_url(url, board_name)

        for attempt in range(max_retries + 1):
            try:
                resp = await self._client.get(
                    url, params=params, headers=headers or {},
                    timeout=timeout,
                )
                if resp.status_code == 429 or resp.status_code >= 500:
                    if attempt < max_retries:
                        retry_after = resp.headers.get("retry-after")
                        wait = float(retry_after) if retry_after else delay + random.uniform(0, 0.3)
                        logger.warning(
                            "%s: HTTP %d on attempt %d/%d — retrying in %.1fs",
                            board_name, resp.status_code, attempt + 1, max_retries + 1, wait,
                        )
                        await asyncio.sleep(wait)
                        delay = min(delay * 2, 4.0)
                        continue
                    resp.raise_for_status()
                return resp
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                last_exc = exc
                if attempt < max_retries:
                    wait = delay + random.uniform(0, 0.3)
                    logger.warning(
                        "%s: %s on attempt %d/%d — retrying in %.1fs",
                        board_name, type(exc).__name__, attempt + 1, max_retries + 1, wait,
                    )
                    await asyncio.sleep(wait)
                    delay = min(delay * 2, 4.0)
                    continue
                raise
        # Should not reach here, but satisfy type checker
        raise last_exc or RuntimeError("_fetch_with_retry: unexpected fallthrough")

    def _enforce_rate_limit(self, board: JobBoardEntry) -> None:
        """Sleep if needed to respect the board's rate limit."""
        if board.rate_limit_per_min <= 0:
            return
        min_interval = 60.0 / board.rate_limit_per_min
        last = self._last_request.get(board.name, 0.0)
        elapsed = time.monotonic() - last
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request[board.name] = time.monotonic()

    def _resolve_slugs(self, board: JobBoardEntry) -> list[str]:
        """Expand company_slugs_env into a list of slugs, or return [''] if not configured."""
        if not board.company_slugs_env:
            return [""]
        raw = os.environ.get(board.company_slugs_env, "")
        if not raw:
            return [""]
        return [s.strip() for s in raw.split(",") if s.strip()]

    async def fetch_all(
        self,
        board: JobBoardEntry,
        *,
        keywords: str = "",
        location: str = "",
        pages: int | None = None,
    ) -> list[JobPosting]:
        """Fetch postings from a board, handling pagination and normalisation.

        When ``url_template`` + ``company_slugs_env`` are configured, expands
        the env var into multiple fetches (one per company slug) in parallel.
        Returns a list of normalised ``JobPosting`` objects.
        """
        slugs = self._resolve_slugs(board)

        # Multi-company expansion: fetch each slug in parallel
        if board.url_template and len(slugs) > 1 and slugs[0]:
            sem = asyncio.Semaphore(5)

            async def _fetch_one(slug: str) -> list[JobPosting]:
                async with sem:
                    entry = board.model_copy(update={
                        "base_url": board.url_template.format(slug=slug),
                    })
                    return await self._fetch_single(entry, keywords=keywords, location=location, pages=pages)

            results = await asyncio.gather(*[_fetch_one(s) for s in slugs])
            all_postings = [p for batch in results for p in batch]
            # Override company name from slug if configured
            if board.company_from_slug:
                for p in all_postings:
                    # Extract slug from the URL if not already set
                    slug_match = re.search(r"/boards/([^/]+)/", p.url) or re.search(r"/postings/([^/]+)/", p.url)
                    if slug_match:
                        p.company = slug_match.group(1).replace("-", " ").title()
            return all_postings

        # Single-company: URL template without env var expansion
        if board.url_template:
            board = board.model_copy(update={"base_url": board.url_template})

        return await self._fetch_single(board, keywords=keywords, location=location, pages=pages)

    async def _fetch_single(
        self,
        board: JobBoardEntry,
        *,
        keywords: str,
        location: str,
        pages: int | None,
    ) -> list[JobPosting]:
        """Fetch from a single board entry (no slug expansion)."""
        if board.type == "html_scrape":
            return await self._fetch_html_scrape(board, keywords=keywords, location=location, pages=pages)
        if board.type == "rss_feed":
            return await self._fetch_rss(board)
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
        headers: dict[str, str] = dict(board.extra_headers)
        api_key = _get_api_key(board)
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        pag = board.pagination
        max_pages = pages or pag.max_pages
        value = pag.start_value
        # Boards with no pagination only need one fetch
        effective_pages = 1 if pag.type == "none" else max_pages
        timeout = board.fetch_timeout_override or 30

        for page_num in range(effective_pages):
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

            # Rate limiting
            self._enforce_rate_limit(board)

            try:
                resp = await self._fetch_with_retry(
                    board.base_url, params=params, headers=headers,
                    timeout=timeout, board_name=board.name,
                )

                # Handle HTML responses (LinkedIn guest API returns HTML, not JSON)
                content_type = resp.headers.get("content-type", "")
                if "text/html" in content_type:
                    items = self._parse_html_postings(resp.text, board)
                    logger.info("Parsed %d postings from HTML for %s", len(items), board.name)
                else:
                    data = resp.json()
                    if isinstance(data, list):
                        items = data
                    else:
                        # Try common keys for job arrays
                        items = None
                        for key in ("results", "data", "jobs", "postings"):
                            if key in data and isinstance(data[key], list):
                                items = data[key]
                                break
                        if items is None:
                            items = []

            except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.DecodingError) as exc:
                logger.warning("Failed to fetch from %s: %s", board.name, exc)
                break

            if not items:
                logger.info("No items from %s (page %d), stopping", board.name, page_num)
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

    async def _fetch_html_scrape(
        self,
        board: JobBoardEntry,
        *,
        keywords: str,
        location: str,
        pages: int | None,
    ) -> list[JobPosting]:
        """Fetch postings from an HTML scrape board using CSS selectors."""
        selectors = board.css_selectors
        pag = board.pagination
        max_pages = pages or pag.max_pages
        value = pag.start_value
        postings: list[JobPosting] = []

        try:
            from bs4 import BeautifulSoup
        except ImportError:
            logger.warning("BeautifulSoup not installed — cannot scrape %s", board.name)
            return []

        for page_num in range(max_pages):
            url = board.base_url
            if pag.type != "none" and pag.param:
                sep = "&" if "?" in url else "?"
                url = f"{url}{sep}{pag.param}={value}"

            # Rate limiting
            self._enforce_rate_limit(board)

            try:
                resp = await self._fetch_with_retry(url, board_name=board.name)
                soup = BeautifulSoup(resp.text, "html.parser")

                # Find all listing containers
                listing_els = soup.select(selectors.listing)
                for el in listing_els:
                    title_el = el.select_one(selectors.title)
                    company_el = el.select_one(selectors.company)
                    location_el = el.select_one(selectors.location)
                    url_el = el.select_one(selectors.url)
                    desc_el = el.select_one(selectors.description)

                    title = title_el.get_text(strip=True) if title_el else ""
                    company = company_el.get_text(strip=True) if company_el else ""
                    loc = location_el.get_text(strip=True) if location_el else ""
                    href = url_el.get("href", "") if url_el else ""
                    if href and not href.startswith("http"):
                        href = f"{board.base_url.rstrip('/')}{href}"
                    desc = desc_el.get_text(strip=True) if desc_el else ""

                    if title or href:
                        postings.append({
                            "title": title,
                            "company": company or board.name,
                            "city": loc,
                            "apply_url": href,
                            "description": desc,
                            "provider": board.name,
                        })

            except Exception as exc:
                logger.warning("HTML scrape failed for %s (page %d): %s", board.name, page_num, exc)
                break

            if pag.type in ("start_offset", "query_param"):
                value += pag.step
            else:
                value += pag.step

        logger.info("Scraped %d postings from %s", len(postings), board.name)
        return [self._normalise(board, p) for p in postings if self._normalise(board, p)]

    async def _fetch_rss(self, board: JobBoardEntry) -> list[JobPosting]:
        """Fetch postings from an RSS/Atom feed.

        Supports RSS 2.0 (<item>) and Atom (<entry>) formats.
        Uses defusedxml to prevent XXE/billion-laughs attacks.
        """
        import defusedxml.ElementTree as ET

        self._enforce_rate_limit(board)
        try:
            resp = await self._fetch_with_retry(board.base_url, board_name=board.name)
            resp.raise_for_status()
        except Exception as exc:
            logger.warning("RSS fetch failed for %s: %s", board.name, exc)
            return []

        try:
            root = ET.fromstring(resp.text)
        except ET.ParseError as exc:
            logger.warning("RSS parse error for %s: %s", board.name, exc)
            return []

        postings: list[JobPosting] = []
        fm = board.field_mapping

        # Detect feed type: RSS 2.0 has <item>, Atom has <entry>
        items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")

        for item in items:
            title = (item.findtext("title") or
                     item.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
            link = (item.findtext("link") or
                    item.findtext("{http://www.w3.org/2005/Atom}link", attrib={"href": ""}) or
                    (item.find("{http://www.w3.org/2005/Atom}link") or {}).get("href", "")).strip()
            description = (item.findtext("description") or
                          item.findtext("{http://www.w3.org/2005/Atom}summary") or
                          item.findtext("{http://www.w3.org/2005/Atom}content") or "").strip()
            pub_date = (item.findtext("pubDate") or
                       item.findtext("{http://www.w3.org/2005/Atom}updated") or "").strip()

            # Strip HTML tags from description
            import re as _re
            description = _re.sub(r"<[^>]+>", " ", description)
            description = " ".join(description.split()).strip()[:4000]

            if title or link:
                posting = {
                    "title": title,
                    "link": link,
                    "description": description,
                    "pubDate": pub_date,
                    "provider": board.name,
                }
                normalised = self._normalise(board, posting)
                if normalised:
                    postings.append(normalised)

        logger.info("Parsed %d postings from RSS feed %s", len(postings), board.name)
        return postings

    def _parse_html_postings(self, html: str, board: JobBoardEntry) -> list[dict[str, Any]]:
        """Parse LinkedIn-style HTML job cards into a list of dicts."""
        postings = []

        # Extract job titles from <span class="sr-only"> tags
        titles = re.findall(r'<span class="sr-only">\s*(.*?)\s*</span>', html, re.DOTALL)
        titles = [t.strip() for t in titles if t.strip()]

        # Extract URLs from href attributes and decode HTML entities (&amp; → &)
        import html as html_mod
        urls = [
            html_mod.unescape(u)
            for u in re.findall(
                r'href="(https://[a-z.]*linkedin\.com/jobs/view/[^"]+)"', html
            )
        ]

        # Extract company names (strip HTML tags)
        company_blocks = re.findall(
            r'<h4 class="base-search-card__subtitle">(.*?)</h4>', html, re.DOTALL
        )
        companies = []
        for block in company_blocks:
            # Extract text content from <a> tag, stripping all HTML
            text = re.sub(r"<[^>]+>", "", block)
            text = " ".join(text.split()).strip()
            if text:
                companies.append(text)

        # Extract locations
        locations = re.findall(
            r'<span class="job-search-card__location">(.*?)</span>', html, re.DOTALL
        )
        locations = [l.strip() for l in locations if l.strip()]

        # Build posting dicts
        for i in range(min(len(titles), len(urls))):
            postings.append({
                "job_id": titles[i] if i < len(titles) else "",
                "title": titles[i] if i < len(titles) else "",
                "apply_url": urls[i] if i < len(urls) else "",
                "org_name": companies[i] if i < len(companies) else "Unknown",
                "city": locations[i] if i < len(locations) else "",
                "remote_policy": "",
                "description": "",
                "provider": "linkedin_guest",
            })

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
            remote_type=board.default_remote_type or str(_resolve_path(raw, fm.remote_type) or ""),
            description=str(_resolve_path(raw, fm.description) or ""),
            fetched_at=datetime.now(timezone.utc),
        )
