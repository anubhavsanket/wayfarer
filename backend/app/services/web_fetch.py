"""Crawl4AI page fetcher with concurrency capping.

Fetches multiple URLs in parallel using ``AsyncWebCrawler`` with a shared
semaphore to bound RAM usage. On any per-URL failure, returns a
``FetchResult`` with ``success=False`` so the orchestrator can fall back
to the search snippet (per PRD §7 NFR1.3).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from crawl4ai import AsyncWebCrawler, CrawlerRunConfig
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

logger = logging.getLogger(__name__)


@dataclass
class FetchResult:
    url: str
    title: str
    markdown: str
    success: bool
    error: str | None = None


class PageFetcher:
    """Concurrency-capped page fetcher backed by Crawl4AI."""

    def __init__(self, max_concurrent: int = 3, timeout: int = 20000) -> None:
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.timeout = timeout
        self._markdown_gen = DefaultMarkdownGenerator(
            options={"fit_markdown": True, "strip_links": True},
        )

    async def fetch_one(self, crawler: AsyncWebCrawler, url: str) -> FetchResult:
        """Fetch a single URL with rate-limiting via semaphore."""
        async with self.semaphore:
            try:
                cfg = CrawlerRunConfig(
                    markdown_generator=self._markdown_gen,
                    page_timeout=self.timeout,
                    only_text=False,
                    word_count_threshold=10,
                )
                result = await crawler.arun(url=url, config=cfg)
                if result.success:
                    md = result.markdown
                    # Crawl4AI 0.6.x returns a MarkdownGenerationResult object
                    # with raw_markdown / fit_markdown. Prefer fit (cleaner) but
                    # fall back to raw when fit is None (JS-heavy pages where
                    # fit_mode can't find the article body).
                    if md is None:
                        text = ""
                    elif hasattr(md, "fit_markdown") and md.fit_markdown:
                        text = md.fit_markdown
                    elif hasattr(md, "raw_markdown"):
                        text = md.raw_markdown or ""
                    else:
                        text = str(md)
                    return FetchResult(
                        url=url,
                        title=getattr(result, "title", url),
                        markdown=text,
                        success=True,
                    )
                return FetchResult(
                    url=url,
                    title=url,
                    markdown="",
                    success=False,
                    error=f"Crawl4AI reported failure: {result.error_message}",
                )
            except Exception as exc:
                logger.warning("Fetch failed for %s: %s", url, exc)
                return FetchResult(url=url, title=url, markdown="", success=False, error=str(exc))

    async def fetch_many(self, urls: list[str]) -> list[FetchResult]:
        """Fetch many URLs in parallel, bounded by ``max_concurrent``."""
        if not urls:
            return []
        try:
            async with AsyncWebCrawler() as crawler:
                tasks = [self.fetch_one(crawler, url) for url in urls]
                return await asyncio.gather(*tasks)
        except Exception as exc:
            logger.error("Crawl4AI AsyncWebCrawler failed: %s", exc)
            return [
                FetchResult(url=u, title=u, markdown="", success=False, error=str(exc))
                for u in urls
            ]


# Module-level singleton
page_fetcher = PageFetcher(max_concurrent=3)
