"""Stage 3 — Live Job Posting Matcher orchestration.

Pipeline (PRD §9.1, §12.2 — embedding-first, cost-aware):
1. **Zero-token discovery + dedup** — fetch postings from enabled boards via
   :class:`JobBoardConnector`, dedupe by URL/content hash, drop stale (TTL).
2. **Embedding similarity** — cheap vector comparison ranks the postings
   (resume embedded once, each JD embedded against it).
3. **Keyword overlap** — for the top-K survivors only, run Stage 2's
   ``match_keyword_to_bullet`` (LLM keyword extraction + honest bullet match)
   to compute keyword coverage.
4. **Hybrid score** = semantic_weight * semantic_sim + keyword_weight * overlap.
5. Rank, filter by location preference, and aggregate missing skills across
   postings (FR3.5 "learn X next").

Key architectural reuse: ``match_keyword_to_bullet`` (core/confidence.py)
is the same function Stage 2 uses — one owned matching engine.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from ..config import settings
from ..llm_router import extract_json, router
from ..models.job_boards import JobBoardConnector, load_registry
from ..models.schemas import (
    AggregateGap,
    EmploymentType,
    ExperienceLevel,
    JobMatch,
    JobMatchResponse,
    JobPosting,
    LocationMatch,
    LocationMode,
    LocationPreference,
)
from ..core.confidence import ConfidenceTier, cosine_similarity, match_keyword_to_bullet
from . import resume_store

logger = logging.getLogger(__name__)

SEMANTIC_WEIGHT = settings.JOBS_SEMANTIC_WEIGHT
KEYWORD_WEIGHT = settings.JOBS_KEYWORD_WEIGHT
TOP_K_EMBEDDING_SURVIVORS = settings.JOBS_TOP_K_EMBEDDING_SURVIVORS

# ---------------------------------------------------------------------------
# City alias map — bidirectional matching for common city name variants
# ---------------------------------------------------------------------------

_CITY_ALIASES: dict[str, list[str]] = {
    # India
    "bengaluru": ["bangalore", "blore", "bengaluru"],
    "bangalore": ["bengaluru", "blore", "bangalore"],
    "mumbai": ["bombay", "mumbai"],
    "bombay": ["mumbai", "bombay"],
    "chennai": ["madras", "chennai"],
    "madras": ["chennai", "madras"],
    "delhi": ["new delhi", "delhi", "ncr"],
    "new delhi": ["delhi", "ncr"],
    "hyderabad": ["secunderabad", "hyderabad"],
    "pune": ["poona", "pune"],
    "kolkata": ["calcutta", "kolkata"],
    # US
    "new york": ["nyc", "new york city", "new york"],
    "nyc": ["new york", "new york city"],
    "san francisco": ["sf", "sfo", "san francisco"],
    "sf": ["san francisco", "sfo"],
    "los angeles": ["la", "los angeles"],
    "la": ["los angeles"],
    "washington": ["dc", "washington dc", "washington d.c."],
    "dc": ["washington", "washington dc"],
    "bay area": ["san francisco", "san jose", "oakland", "bay area"],
    # Europe
    "london": ["london"],
    "berlin": ["berlin"],
    "paris": ["paris"],
    # Common abbreviations
    "uk": ["united kingdom", "england", "great britain"],
    "us": ["united states", "usa", "america"],
    "eu": ["europe", "european union"],
}


def _normalize_city(city: str) -> str:
    """Normalize a city name to its canonical form via the alias map."""
    lower = city.lower().strip()
    for canonical, variants in _CITY_ALIASES.items():
        if lower == canonical or lower in variants:
            return canonical
    return lower


def _expand_cities(cities: list[str]) -> set[str]:
    """Expand user-provided city names to include all known aliases.

    Returns a flat set of all variants so token matching catches any spelling.
    """
    expanded: set[str] = set()
    for city in cities:
        canonical = _normalize_city(city)
        variants = _CITY_ALIASES.get(canonical, [canonical])
        expanded.update(v.lower() for v in variants)
        expanded.add(canonical.lower())
    return expanded


# ---------------------------------------------------------------------------
# Title-only posting enrichment
# ---------------------------------------------------------------------------

_MAX_ENRICH = 30  # cap enrichment requests per call to bound latency
_ENRICH_TIMEOUT = 10  # seconds per detail fetch
_ENRICH_CONCURRENCY = 10


async def _enrich_title_only_postings(postings: list[JobPosting]) -> list[JobPosting]:
    """Fetch descriptions for title-only postings (LinkedIn, bluedoor).

    Boards like LinkedIn guest API and bluedoor return titles but no JD body,
    giving these postings a flat 0.0 semantic score. This function fetches
    the detail page for each title-only posting and extracts the description,
    allowing them to be embedded and scored properly.

    Capped at ``_MAX_ENRICH`` postings per call to bound latency.
    """
    import asyncio
    import re as _re

    title_only = [p for p in postings if not p.description and p.url]
    if not title_only:
        return postings

    # Prioritise by title overlap score (most relevant first)
    # We don't have bullets here, so just take the first N
    to_enrich = title_only[:_MAX_ENRICH]
    sem = asyncio.Semaphore(_ENRICH_CONCURRENCY)

    async def _fetch_detail(client: httpx.AsyncClient, posting: JobPosting) -> str:
        """Fetch and extract description text from a posting's detail page."""
        async with sem:
            try:
                # LinkedIn guest detail endpoint
                if "linkedin.com/jobs/view/" in posting.url:
                    job_id_match = re.search(r"/(\d+)(?:\?|$)", posting.url)
                    if job_id_match:
                        detail_url = (
                            f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/"
                            f"{job_id_match.group(1)}"
                        )
                    else:
                        detail_url = posting.url
                else:
                    detail_url = posting.url

                resp = await client.get(
                    detail_url,
                    timeout=_ENRICH_TIMEOUT,
                    follow_redirects=True,
                )
                if not resp.is_success:
                    return ""

                html = resp.text

                # LinkedIn: extract from show-more-less-html__markup div
                if "linkedin.com" in detail_url:
                    match = _re.search(
                        r'class="show-more-less-html__markup[^"]*"[^>]*>(.*?)</div>',
                        html, _re.DOTALL,
                    )
                    if match:
                        text = _re.sub(r"<[^>]+>", " ", match.group(1))
                        return " ".join(text.split()).strip()[:4000]

                # Generic: extract all visible text, take first 4000 chars
                try:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(html, "html.parser")
                    # Remove script/style tags
                    for tag in soup(["script", "style", "nav", "header", "footer"]):
                        tag.decompose()
                    text = soup.get_text(separator=" ", strip=True)
                    return text[:4000]
                except ImportError:
                    # Fallback: regex strip
                    text = _re.sub(r"<[^>]+>", " ", html)
                    return " ".join(text.split()).strip()[:4000]

            except Exception as exc:
                logger.debug("Enrichment failed for %s: %s", posting.id, exc)
                return ""

    async with httpx.AsyncClient(
        timeout=_ENRICH_TIMEOUT,
        headers={"User-Agent": "Mozilla/5.0 (compatible; wayfarer/1.1)"},
    ) as client:
        tasks = [_fetch_detail(client, p) for p in to_enrich]
        descriptions = await asyncio.gather(*tasks)

    enriched_count = 0
    for posting, desc in zip(to_enrich, descriptions):
        if desc:
            posting.description = desc
            enriched_count += 1

    if enriched_count:
        logger.info(
            "Enriched %d/%d title-only postings with descriptions",
            enriched_count, len(to_enrich),
        )

    return postings


# ---------------------------------------------------------------------------
# Posting discovery + dedup
# ---------------------------------------------------------------------------

async def _discover_postings() -> list[JobPosting]:
    """Fetch postings from every enabled board in the registry."""
    registry = load_registry("config/job_boards.yaml")
    enabled = [b for b in registry.job_boards if b.enabled]
    connector = JobBoardConnector()
    try:
        postings: list[JobPosting] = []
        for board in enabled:
            try:
                board_postings = await connector.fetch_all(board)
                postings.extend(board_postings)
                logger.info("Fetched %d postings from %s", len(board_postings), board.name)
            except Exception as exc:
                logger.warning("Board %s fetch failed: %s", board.name, exc)
        return postings
    finally:
        await connector.aclose()


def _dedupe_postings(
    postings: list[JobPosting],
    cache: Any | None = None,
) -> list[JobPosting]:
    """Deduplicate by (title.lower(), company.lower(), url) — FR3.9.

    When a ``cache`` (ContentHashCache) is provided, also checks persistent
    cross-request dedup. New postings are marked as seen so subsequent calls
    within the TTL window return them as duplicates.
    """
    seen: set[str] = set()
    out: list[JobPosting] = []
    for p in postings:
        key = (p.title.lower(), p.company.lower(), p.url or "")
        dedup_key = f"{key[0]}::{key[1]}::{key[2]}"

        # In-memory dedup (within this request)
        if key in seen:
            continue

        # Persistent dedup (across requests)
        if cache is not None:
            cache_key = cache.make_key(dedup_key)
            if cache.get(cache_key) is not None:
                continue
            # Mark as seen for future requests
            cache.set(cache_key, True)

        seen.add(key)
        out.append(p)
    return out


def _normalise_postings(postings: list[JobPosting]) -> list[JobPosting]:
    """Normalise status/location fields across sources — FR3.9."""
    for p in postings:
        # Normalise remote_type across sources
        p.remote_type = _normalise_remote_type(p.remote_type)
        # Normalise location strings (trim, title-case)
        if p.location:
            p.location = p.location.strip().title()
    return postings


async def _check_url_liveness(matches: list[JobMatch], max_checks: int = 20) -> list[JobMatch]:
    """Lightweight HEAD check on apply URLs — flag dead links (§9.6 acceptance).

    Runs concurrently with a single client to bound latency.
    Only checks the top max_checks results.
    """
    import httpx as _httpx
    import asyncio

    async def _check_one(client: _httpx.AsyncClient, m: JobMatch) -> bool:
        """Check if a URL is alive. Returns True if dead."""
        if not m.apply_url:
            return False
        try:
            resp = await client.head(m.apply_url, follow_redirects=True)
            return resp.status_code >= 400
        except Exception:
            return True

    to_check = [m for m in matches[:max_checks] if m.apply_url]
    if not to_check:
        return matches

    async with _httpx.AsyncClient(timeout=5) as client:
        results = await asyncio.gather(
            *[_check_one(client, m) for m in to_check],
            return_exceptions=True,
        )

    for m, result in zip(to_check, results):
        if result is True:  # True = dead
            m.flags.append("dead_link")

    dead = sum(1 for m in to_check if "dead_link" in m.flags)
    if dead:
        logger.info("URL liveness check: %d/%d dead links found", dead, len(to_check))
    return matches


def _drop_stale(postings: list[JobPosting], ttl_days: int = 30) -> list[JobPosting]:
    """Drop postings whose ``fetched_at`` is older than ``ttl_days`` — FR3.9."""
    from datetime import datetime, timezone, timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=ttl_days)
    before = len(postings)
    out = [p for p in postings if p.fetched_at >= cutoff]
    dropped = before - len(out)
    if dropped:
        logger.info("Dropped %d stale postings (older than %d days)", dropped, ttl_days)
    return out


# ---------------------------------------------------------------------------
# Mass-posting detection and consolidation
# ---------------------------------------------------------------------------

def _consolidate_mass_postings(postings: list[JobPosting]) -> list[JobPosting]:
    """Detect and consolidate identical roles posted across multiple cities.

    When 3+ postings share the same title and company but differ only in
    location, keeps the best one (most complete description) and records the
    other cities in ``also_available_in``. This prevents identical roles from
    inflating the result set (ai-job-search Step 2.5 pattern).
    """
    from collections import defaultdict

    # Group by (title.lower, company.lower)
    groups: dict[tuple[str, str], list[JobPosting]] = defaultdict(list)
    for p in postings:
        key = (p.title.lower().strip(), p.company.lower().strip())
        groups[key].append(p)

    consolidated: list[JobPosting] = []
    mass_count = 0

    for (title, company), group in groups.items():
        if len(group) < 3:
            # Not enough to be a mass posting — keep all
            consolidated.extend(group)
            continue

        # Check if they differ only in location (same description or all empty)
        descriptions = {(p.description or "").strip() for p in group}
        if len(descriptions) > 2:
            # Too many different descriptions — probably different roles, keep all
            consolidated.extend(group)
            continue

        # Mass posting detected — keep the best one (longest description)
        best = max(group, key=lambda p: len(p.description or ""))
        other_locations = [
            p.location for p in group
            if p.location and p.location != best.location
        ]
        if other_locations:
            best.also_available_in = list(dict.fromkeys(other_locations))  # dedup, preserve order
            best.flags.append("mass_posting")
        consolidated.append(best)
        mass_count += 1

    if mass_count:
        logger.info("Consolidated %d mass-posting groups (%d postings → %d)",
                     mass_count, len(postings), len(consolidated))
    return consolidated


def _consolidate_mass_matches(matches: list[JobMatch]) -> list[JobMatch]:
    """Consolidate mass-postings at the JobMatch level (after scoring).

    Same logic as ``_consolidate_mass_postings`` but works on scored matches.
    Keeps the highest-scoring match per group and records other cities.
    """
    from collections import defaultdict

    groups: dict[tuple[str, str], list[JobMatch]] = defaultdict(list)
    for m in matches:
        key = (m.title.lower().strip(), m.company.lower().strip())
        groups[key].append(m)

    consolidated: list[JobMatch] = []
    mass_count = 0

    for (title, company), group in groups.items():
        if len(group) < 3:
            consolidated.extend(group)
            continue

        # Check location diversity — if all same location, not a mass posting
        locations = {m.location for m in group if m.location}
        if len(locations) < 2:
            consolidated.extend(group)
            continue

        # Keep the best-scoring match, collect other cities
        best = max(group, key=lambda m: m.match_score)
        other_locations = [
            m.location for m in group
            if m.location and m.location != best.location
        ]
        if other_locations:
            best.also_available_in = list(dict.fromkeys(other_locations))
            if "mass_posting" not in best.flags:
                best.flags.append("mass_posting")
        consolidated.append(best)
        mass_count += 1

    if mass_count:
        logger.info("Consolidated %d mass-posting match groups (%d → %d)",
                     mass_count, len(matches), len(consolidated))
    return consolidated


def _normalise_remote_type(raw: str | None) -> str:
    """Normalise a remote_type string into '', 'remote', 'hybrid', or 'onsite'."""
    if not raw:
        return ""
    s = raw.strip().lower()
    if "remote" in s:
        return "remote" if "hybrid" not in s else "hybrid"
    if "hybrid" in s:
        return "hybrid"
    if "onsite" in s or "on-site" in s or "on site" in s:
        return "onsite"
    return s


# ---------------------------------------------------------------------------
# Embedding / scoring
# ---------------------------------------------------------------------------

async def _embed_resume(parsed: Any) -> list[float] | None:
    """Embed the resume (concatenated bullet texts) once.

    Returns None if embedding is unavailable (no model pulled, no API key)
    so the caller can fall back to keyword-only scoring.
    """
    text = "\n".join(b.text for b in parsed.bullets) or parsed.ats_visible_text
    try:
        return await router.embed(text)
    except Exception as exc:
        logger.warning("Resume embedding failed: %s — falling back to keyword-only scoring", exc)
        return None


async def _compute_semantic_scores(
    resume_vec: list[float],
    postings: list[JobPosting],
) -> list[tuple[JobPosting, float]]:
    """Cosine similarity of each posting's JD against the resume embedding.

    Embeds in concurrent batches of 5 to avoid sequential N×8s latency.
    """
    import asyncio
    from .legitimacy import _strip_boilerplate

    BATCH_SIZE = 5

    async def _embed_one(p: JobPosting) -> float:
        if not p.description:
            return 0.0
        try:
            desc = _strip_boilerplate(p.description)[:4000]
            jd_vec = await router.embed(desc)
            return cosine_similarity(resume_vec, jd_vec)
        except Exception as exc:
            logger.warning("JD embed failed for %s: %s", p.id, exc)
            return 0.0

    scored: list[tuple[JobPosting, float]] = []
    for i in range(0, len(postings), BATCH_SIZE):
        batch = postings[i : i + BATCH_SIZE]
        scores = await asyncio.gather(*[_embed_one(p) for p in batch])
        scored.extend(zip(batch, scores))
    return scored


# ---------------------------------------------------------------------------
# Search query decomposition — expand resume keywords for broader matching
# ---------------------------------------------------------------------------

_EXPANSION_PROMPT = """\
Given these job-related keywords from a resume, return a JSON list of 2-3 related \
synonyms, abbreviations, or common alternative terms for each. \
Return ONLY the expanded list as a flat JSON array of strings, no commentary.

Keywords: {keywords}
"""

_expansion_cache: dict[str, list[str]] = {}


async def _decompose_job_query(keywords: list[str]) -> list[str]:
    """Expand resume keywords into related terms via LLM.

    E.g., ['machine learning', 'pytorch', 'transformer'] →
    ['machine learning', 'ML', 'deep learning', 'pytorch', 'transformer',
     'neural network', 'AI', 'LLM'].

    Results are cached in-memory so the expansion happens once per session.
    """
    cache_key = "::".join(sorted(k.lower() for k in keywords))
    if cache_key in _expansion_cache:
        return _expansion_cache[cache_key]

    if not keywords:
        return []

    try:
        resp = await router.chat(
            messages=[{"role": "user", "content": _EXPANSION_PROMPT.format(
                keywords=", ".join(keywords[:10])
            )}],
            tier="simple",
            max_tokens=200,
        )
        raw = resp["content"]
        result = extract_json(raw)
        if isinstance(result, list):
            expanded = [str(k).strip().lower() for k in result if k]
        else:
            expanded = []
    except Exception as exc:
        logger.debug("Query expansion failed: %s", exc)
        expanded = []

    # Always include the original keywords
    all_terms = list(set([k.lower() for k in keywords] + expanded))
    _expansion_cache[cache_key] = all_terms
    return all_terms


def _title_overlap_score(
    posting: JobPosting,
    bullets: list[Any],
    expanded_terms: set[str] | None = None,
) -> float:
    """Zero-token relevance score for postings without a description.

    Boards that only expose title/company cards (LinkedIn guest API, some
    ATS boards) ship no JD body, so they can't be embedded. This scores them
    by the fraction of title/company tokens that also appear in the resume —
    a cheap lexical proxy so they can be ranked by the top-K survivor cutoff
    instead of getting a flat 0.0 and being dropped (§9.6).

    When ``expanded_terms`` is provided (from ``_decompose_job_query``),
    also checks whether posting tokens match expanded resume keywords.
    """
    # Require ≥2 chars to avoid single-letter false positives ('t' in 'fastapi',
    # 'c' in 'python') that produce spurious substring matches against resume text.
    tokens = set(re.findall(r"[a-z0-9+#.]{2,}", f"{posting.title} {posting.company}".lower()))
    if not tokens:
        return 0.0
    resume_text = " ".join(b.text.lower() for b in bullets if b.text)
    hits = sum(1 for t in tokens if t in resume_text)
    # Also check against expanded terms (broader matching)
    if expanded_terms:
        hits += sum(1 for t in tokens if t in expanded_terms and t not in resume_text)
    return min(hits / len(tokens), 1.0)  # cap at 1.0 since expanded terms can inflate hits


def _lexical_pre_filter(
    postings: list[JobPosting],
    bullets: list[Any],
    top_n: int,
) -> list[JobPosting]:
    """Cheap lexical pre-filter: rank all postings by title+description token overlap.

    Zero-cost (no LLM/embedding calls). Returns the top ``top_n`` postings
    by lexical relevance score, so the embedding budget is spent on the most
    promising candidates rather than the first N alphabetically.
    """
    resume_text = " ".join(b.text.lower() for b in bullets if b.text)
    if not resume_text:
        return postings[:top_n]

    scored: list[tuple[JobPosting, float]] = []
    for p in postings:
        # Score = fraction of posting tokens found in resume
        text = f"{p.title} {p.company} {p.description or ''}".lower()
        tokens = set(re.findall(r"[a-z0-9+#.]{2,}", text))
        if not tokens:
            scored.append((p, 0.0))
            continue
        hits = sum(1 for t in tokens if t in resume_text)
        scored.append((p, hits / len(tokens)))

    scored.sort(key=lambda t: t[1], reverse=True)
    return [p for p, _ in scored[:top_n]]


def _select_survivors(
    scored_desc: list[tuple[JobPosting, float]],
    title_scored: list[tuple[JobPosting, float]],
    top_k: int,
) -> list[tuple[JobPosting, float]]:
    """Top-K survivors with a guaranteed share for title-only postings.

    Description-based postings get ``top_k - reserved`` slots; the rest are
    reserved for title-only postings (LinkedIn guest cards, some ATS boards)
    so they aren't starved out by description-rich boards. If there aren't
    enough description postings, title-only postings fill the budget.
    """
    # Only reserve slots for title-only postings that actually scored > 0.
    # Unconditionally injecting zero-relevance postings displaces genuine matches.
    relevant_titles = [t for t in title_scored if t[1] > 0]
    reserved = min(len(relevant_titles), max(2, top_k // 5))
    return (scored_desc[: top_k - reserved] + title_scored)[:top_k]


async def _extract_jd_keywords(jd_text: str) -> list[str]:
    """Extract keywords from a JD via LLM, with regex fallback."""
    from .ats_checker import _extract_jd_keywords as extract
    return await extract(jd_text)


async def _compute_keyword_overlap(
    posting: JobPosting,
    bullets: list[Any],
    keywords: list[str],
) -> tuple[float, list[str]]:
    """Fraction of JD keywords the resume covers, plus the missing ones.

    Reuses ``match_keyword_to_bullet`` (the same function Stage 2 uses).
    """
    if not keywords:
        return 0.0, []
    covered = 0
    missing: list[str] = []
    for kw in keywords:
        match = match_keyword_to_bullet(kw, bullets)
        if match.tier in (ConfidenceTier.VERIFIED, ConfidenceTier.REWORDED):
            covered += 1
        else:
            missing.append(kw)
    overlap = covered / len(keywords)
    return overlap, missing


# ---------------------------------------------------------------------------
# Fresher Mode: experience level + employment type classification (§15.1/15.2)
# ---------------------------------------------------------------------------

VALID_LEVELS = {"fresher", "junior", "mid", "senior", "unclear"}
VALID_EMPLOYMENT_TYPES = {"full_time", "contract", "freelance", "part_time", "unclear"}

_CLASSIFICATION_PROMPT = """\
Classify this job posting. Return ONLY a JSON object with these fields:
- experience_level: "fresher" | "junior" | "mid" | "senior" | "unclear"
- min_experience_years: float or null
- confidence: float between 0.0 and 1.0

Rules:
- "fresher": 0-1 years, entry-level, graduate, freshers welcome
- "junior": 1-3 years
- "mid": 3-5 years
- "senior": 5+ years, lead, principal, staff
- "unclear": no clear experience requirement stated

Job posting:
{text}
"""


async def _classify_experience(jd_text: str) -> dict[str, Any]:
    """Classify experience level using a small local LLM.

    Falls back to regex-based detection when the LLM fails or returns
    unparsable output.
    """
    VALID_LEVELS = {"fresher", "junior", "mid", "senior", "unclear"}
    try:
        resp = await router.chat(
            messages=[{"role": "user", "content": _CLASSIFICATION_PROMPT.format(text=jd_text[:1500])}],
            tier="simple",
            max_tokens=150,
        )
        raw = resp["content"]
        result = extract_json(raw)
        level = result.get("experience_level", "unclear") if result else "unclear"
        if level not in VALID_LEVELS:
            level = "unclear"

        # If LLM returned "unclear", try regex on both the raw LLM output
        # and the original JD text as a second chance
        if level == "unclear":
            fallback = _classify_experience_regex(raw + "\n" + jd_text)
            if fallback["experience_level"] != "unclear":
                return fallback

        # Validate min_experience_years — LLM can emit non-numeric strings
        min_years = result.get("min_experience_years") if result else None
        if min_years is not None:
            try:
                min_years = float(min_years)
            except (ValueError, TypeError):
                min_years = None

        return {
            "experience_level": level,
            "min_experience_years": min_years,
            "confidence": result.get("confidence", 0.0) if result else 0.0,
        }
    except Exception as exc:
        logger.debug("LLM classification failed (%s), using regex fallback", exc)
        return _classify_experience_regex(jd_text)


def _classify_experience_regex(text: str) -> dict[str, Any]:
    """Regex-based experience level detection (fallback when LLM unavailable)."""
    text_lower = text.lower()

    # Senior indicators
    if re.search(r"\b(senior|lead|principal|staff|head of|director|vp |vice president)\b", text_lower):
        return {"experience_level": "senior", "min_experience_years": 5.0, "confidence": 0.6}

    # Mid indicators
    if re.search(r"\b(mid[-\s]?level|3[-+]?\s*years|5[-+]?\s*years)\b", text_lower):
        return {"experience_level": "mid", "min_experience_years": 3.0, "confidence": 0.5}

    # Junior indicators
    if re.search(r"\b(junior|jr\.?|entry[-\s]?level|1[-+]?\s*years|2[-+]?\s*years)\b", text_lower):
        return {"experience_level": "junior", "min_experience_years": 1.0, "confidence": 0.5}

    # Fresher indicators
    if re.search(r"\b(fresher|graduate|no experience|intern|trainee|0[-+]?\s*years|recent grad)\b", text_lower):
        return {"experience_level": "fresher", "min_experience_years": 0.0, "confidence": 0.6}

    # Experience year patterns
    year_match = re.search(r"(\d+)\s*(?:to|-)\s*(\d+)\s*years?", text_lower)
    if year_match:
        min_years = int(year_match.group(1))
        if min_years <= 1:
            return {"experience_level": "fresher", "min_experience_years": float(min_years), "confidence": 0.5}
        elif min_years <= 3:
            return {"experience_level": "junior", "min_experience_years": float(min_years), "confidence": 0.5}
        elif min_years <= 5:
            return {"experience_level": "mid", "min_experience_years": float(min_years), "confidence": 0.5}
        else:
            return {"experience_level": "senior", "min_experience_years": float(min_years), "confidence": 0.5}

    return {"experience_level": "unclear", "min_experience_years": None, "confidence": 0.0}


async def _match_one(
    posting: JobPosting,
    parsed: Any,
    resume_vec: list[float] | None,
    semantic_score: float,
    resume_graph: Any | None = None,
    fresher_only: bool = False,
) -> JobMatch:
    """Compute the full hybrid match for a single posting (top-K only).

    §12.1: When a resume_graph is available, uses its subgraph to
    filter bullets to only those relevant to the JD's keywords —
    turns O(N × full_resume_tokens) into O(N × relevant_subgraph_tokens).
    """
    # §12.1: Extract JD keywords first, then use graph to filter bullets.
    # Title-only postings (LinkedIn guest cards) have no description to mine
    # — fall back to title + company so they're still matchable.
    jd_text = posting.description or f"{posting.title} {posting.company}"
    keywords = await _extract_jd_keywords(jd_text)

    if resume_graph and keywords:
        # Use graph subgraph to get only relevant bullet IDs
        subgraph = resume_graph.subgraph_for_keywords(keywords)
        relevant_bullets = [
            b for b in parsed.bullets
            if any(n.id == b.id for n in subgraph.nodes.values())
        ]
        # Fall back to all bullets if subgraph is too narrow
        if len(relevant_bullets) < 2:
            relevant_bullets = parsed.bullets
    else:
        relevant_bullets = parsed.bullets

    overlap, missing = await _compute_keyword_overlap(posting, relevant_bullets, keywords)

    hybrid = round(SEMANTIC_WEIGHT * semantic_score + KEYWORD_WEIGHT * overlap, 3)
    top_gaps = missing[:3]

    # Legitimacy flags (FR3.8) — ghost/scam and sponsorship check
    from .legitimacy import check_posting
    from ..config import settings
    flag_dicts = check_posting(posting, needs_sponsorship=getattr(settings, 'NEEDS_VISA_SPONSORSHIP', False))
    flags = [f["kind"] for f in flag_dicts]

    # Legitimacy penalty: ghost/scam postings score lower, no-sponsorship even lower
    if "ghost_posting" in flags:
        hybrid *= 0.5
    if "no_sponsorship" in flags:
        hybrid *= 0.3
    hybrid = round(hybrid, 3)

    # Fresher Mode: classify experience level (§15.1)
    # Skip expensive LLM classification when not in fresher mode
    if fresher_only:
        exp_class = await _classify_experience(posting.description or posting.title)
    else:
        exp_class = {"experience_level": "unclear", "min_experience_years": None}

    return JobMatch(
        job_id=posting.id,
        title=posting.title,
        company=posting.company,
        source=posting.source,
        location=posting.location or "",
        match_score=hybrid,
        location_match=LocationMatch.NONE,
        top_gaps=top_gaps,
        apply_url=posting.url,
        remote_type=posting.remote_type or "",
        flags=flags,
        experience_level=ExperienceLevel(exp_class["experience_level"]),
        min_experience_years=exp_class["min_experience_years"],
    )


# ---------------------------------------------------------------------------
# Location preference (FR3.6, FR3.7)
# ---------------------------------------------------------------------------

_LOC_TOKEN_RE = re.compile(r"[a-z][a-z]+")


def _loc_tokens(loc: str | None) -> set[str]:
    """Word tokens of a location string (lowercased, punctuation dropped)."""
    return set(_LOC_TOKEN_RE.findall((loc or "").lower()))


def _city_matches(loc_tokens: set[str], city: str) -> bool:
    """Whole-word city match with alias expansion.

    Substring matching is too loose — a short city like 'ny' or 'us' matches
    the middle of unrelated words ('any', 'house'). Token matching requires
    the full city phrase: 'San Francisco' matches 'San Francisco, CA' but
    not 'Santa Clara'.

    Expands the city through the alias map so "Bangalore" matches "Bengaluru"
    and vice versa.
    """
    canonical = _normalize_city(city)
    variants = _CITY_ALIASES.get(canonical, [canonical])
    for variant in variants:
        city_tokens = _LOC_TOKEN_RE.findall(variant.lower())
        if city_tokens and all(t in loc_tokens for t in city_tokens):
            return True
    return False


def _apply_location_preference(
    matches: list[JobMatch],
    pref: LocationPreference,
) -> list[JobMatch]:
    """Filter + label postings per the user's location preference.

    - specific_city: require a city match (optionally include remote if remote_ok)
    - remote_only:   only postings whose remote_type is remote
    - hybrid:        only postings whose remote_type is hybrid or remote
    - open_to_relocation: accept city matches in pref.cities, label as
      RELOCATION_REQUIRED if not exact
    """
    mode = pref.mode
    # Expand user cities through alias map for bidirectional matching
    raw_cities = [c.lower().strip() for c in pref.cities if c]
    cities = list(_expand_cities(raw_cities)) if raw_cities else []
    remote_ok = pref.remote_ok

    def _city_in_tokens(loc_tokens: set[str]) -> bool:
        if not cities:
            return True  # no city constraint
        return any(_city_matches(loc_tokens, c) for c in cities)

    kept: list[JobMatch] = []
    for m in matches:
        # Whole-word token matching, so 'remote' isn't confused with
        # 'Remote, OR' and city names don't match inside unrelated words.
        loc_tokens = _loc_tokens(m.location)
        is_remote = (
            "remote" in loc_tokens
            or "remote" in (m.remote_type or "").lower()
        )
        is_hybrid = (
            "hybrid" in loc_tokens
            or "hybrid" in (m.remote_type or "").lower()
        )

        if mode == LocationMode.REMOTE_ONLY:
            if not is_remote:
                continue
            m.location_match = LocationMatch.REMOTE

        elif mode == LocationMode.HYBRID:
            if not (is_remote or is_hybrid):
                continue
            m.location_match = LocationMatch.REMOTE

        elif mode == LocationMode.SPECIFIC_CITY:
            if not cities:
                # No city constraint — accept all postings
                if is_remote and remote_ok:
                    m.location_match = LocationMatch.REMOTE
                elif is_remote:
                    m.location_match = LocationMatch.REMOTE
                else:
                    m.location_match = LocationMatch.RELOCATION_REQUIRED
            elif _city_in_tokens(loc_tokens):
                # A remote posting is remote even when its location string
                # happens to mention the city (e.g. 'Remote — Bengaluru').
                m.location_match = (
                    LocationMatch.REMOTE if is_remote else LocationMatch.EXACT
                )
            elif is_remote and remote_ok:
                m.location_match = LocationMatch.REMOTE
            else:
                continue  # filtered out

        elif mode == LocationMode.OPEN_TO_RELOCATION:
            # Accept every posting; mark REMOTE for remote, EXACT when a
            # preferred city matches, otherwise RELOCATION_REQUIRED.
            if is_remote:
                m.location_match = LocationMatch.REMOTE
            elif not cities:
                # No city constraint — can't claim EXACT, so relocation.
                m.location_match = LocationMatch.RELOCATION_REQUIRED
            else:
                m.location_match = (
                    LocationMatch.EXACT
                    if _city_in_tokens(loc_tokens)
                    else LocationMatch.RELOCATION_REQUIRED
                )

        kept.append(m)

    # Re-rank: exact matches first, then remote, then relocation
    order = {
        LocationMatch.EXACT: 0,
        LocationMatch.REMOTE: 1,
        LocationMatch.RELOCATION_REQUIRED: 2,
        LocationMatch.NONE: 3,
    }
    kept.sort(key=lambda m: (order[m.location_match], -m.match_score))
    return kept


# ---------------------------------------------------------------------------
# Aggregate gaps (FR3.5)
# ---------------------------------------------------------------------------

def _aggregate_gaps(matches: list[JobMatch]) -> list[AggregateGap]:
    """Across matched postings, surface the most frequently missing skills."""
    from collections import Counter
    counts: Counter[str] = Counter()
    total = len(matches)
    for m in matches:
        for gap in m.top_gaps:
            counts[gap] += 1
    if total == 0:
        return []
    return [
        AggregateGap(skill=skill, missing_in_pct=round(count / total, 3))
        for skill, count in counts.most_common(10)
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def match_jobs(
    resume_id: str,
    location_preference: LocationPreference | None = None,
    limit: int = 20,
    fresher_only: bool = False,
    max_age_days: int = 30,
    min_score: float = 0.0,
    sources: list[str] | None = None,
) -> JobMatchResponse:
    """Rank live postings by fit against a resume, with location filtering.

    When ``fresher_only=True`` (§15.1), only postings classified as "fresher"
    or "junior" are surfaced in ``matches``. Postings classified as "unclear"
    go into ``unclear_matches`` so they aren't silently dropped.

    ``max_age_days`` controls how old a posting can be (drops older ones).
    ``min_score`` filters out results below this match score threshold.
    """
    pref = location_preference or LocationPreference()
    limit = min(limit, 100)

    # Load the resume (bullets) by resume_id
    parsed = resume_store.load_parsed(resume_id)
    if parsed is None:
        raise ValueError(f"Unknown resume_id: {resume_id}. Run /resume/check first.")
    if not parsed.bullets:
        raise ValueError("Resume has no parseable bullets — cannot match.")

    # §12.1: Load resume entity graph for token-efficient matching
    resume_graph_dict = resume_store.load_graph(resume_id)
    resume_graph = None
    if resume_graph_dict:
        from ..core.resume_graph import ResumeGraph
        resume_graph = ResumeGraph.from_dict(resume_graph_dict)
        logger.info("Loaded resume graph: %d nodes, %d edges",
                     len(resume_graph.nodes), len(resume_graph.edges))

    # 1. Discovery + dedup + normalise + drop stale (zero-token)
    try:
        from ..utils.cache import dedup_cache
        cache = dedup_cache
    except Exception:
        cache = None
    postings = _dedupe_postings(await _discover_postings(), cache=cache)
    if not postings:
        return JobMatchResponse(matches=[], aggregate_gaps=[])
    postings = _normalise_postings(postings)
    # Enrich title-only postings (LinkedIn, bluedoor) with fetched descriptions
    postings = await _enrich_title_only_postings(postings)
    postings = _drop_stale(postings, ttl_days=max_age_days)

    # Filter by source if specified
    if sources:
        source_set = set(s.lower() for s in sources)
        postings = [p for p in postings if p.source.lower() in source_set]
        logger.info("Source filter: %d postings from %s", len(postings), sources)

    logger.info("After pipeline cleanup: %d postings (max_age=%d days)", len(postings), max_age_days)

    # 2. Two-pass embedding similarity (rank all, keep top-K)
    # Pass 1: cheap lexical pre-filter narrows to top N candidates
    # Pass 2: embed only those N (bounded by JOBS_MAX_EMBED_POSTINGS)
    max_embed = settings.JOBS_MAX_EMBED_POSTINGS
    prefilter_n = settings.JOBS_LEXICAL_PREFILTER_TOP_N

    # Expand resume keywords for broader title matching (query decomposition)
    resume_keywords = list(set(
        b.text.lower() for b in parsed.bullets if b.text
    ))[:10]
    expanded_terms = await _decompose_job_query(resume_keywords)
    expanded_set = set(expanded_terms)
    logger.info("Query expansion: %d original keywords → %d total terms", len(resume_keywords), len(expanded_set))

    resume_vec = await _embed_resume(parsed)
    if resume_vec is not None:
        with_desc = [p for p in postings if p.description]
        without_desc = [p for p in postings if not p.description]
        logger.info("Two-pass: %d with desc, %d without desc", len(with_desc), len(without_desc))

        # Pass 1: lexical pre-filter (zero-cost) — rank by title+desc token overlap
        prefiltered = _lexical_pre_filter(with_desc, parsed.bullets, top_n=prefilter_n)
        # Pass 2: embed only the top candidates
        to_embed = prefiltered[:max_embed]
        logger.info("Embedding %d of %d prefiltered postings (%d skipped by pre-filter, %d without desc)",
                     len(to_embed), len(with_desc),
                     max(0, len(with_desc) - len(prefiltered)), len(without_desc))
        scored = await _compute_semantic_scores(resume_vec, to_embed)
        # Remaining prefiltered postings that weren't embedded get 0
        scored.extend((p, 0.0) for p in prefiltered[max_embed:])
        scored.sort(key=lambda t: t[1], reverse=True)

        # Title-only postings get lexical proxy score + reserved survivor slots
        # Use expanded terms for broader matching
        title_scored = sorted(
            ((p, _title_overlap_score(p, parsed.bullets, expanded_terms=expanded_set)) for p in without_desc),
            key=lambda t: t[1], reverse=True,
        )
        top_k = _select_survivors(scored, title_scored, TOP_K_EMBEDDING_SURVIVORS)
        logger.info("Top-K survivors: %d postings (%d embedded, %d title-only)",
                     len(top_k), len(scored), len(top_k) - min(len(scored), TOP_K_EMBEDDING_SURVIVORS))
    else:
        # No embeddings available — use keyword-only scoring on all postings
        logger.info("Embeddings unavailable; using keyword-only scoring on all %d postings", len(postings))
        top_k = [(p, 0.0) for p in postings]

    # 3. LLM keyword overlap on top-K only (cost control)
    matches: list[JobMatch] = []
    for posting, semantic in top_k:
        m = await _match_one(posting, parsed, resume_vec, semantic,
                             resume_graph=resume_graph, fresher_only=fresher_only)
        matches.append(m)

    # 3b. Consolidate mass-postings (same role across multiple cities)
    # Works on the JobMatch list by grouping on (title, company)
    matches = _consolidate_mass_matches(matches)

    # 4. Location filter + re-rank
    matches = _apply_location_preference(matches, pref)

    # 4b. Minimum score filter — hide irrelevant listings
    if min_score > 0:
        matches = [m for m in matches if m.match_score >= min_score]

    # 4c. URL liveness check (§9.6 acceptance)
    matches = await _check_url_liveness(matches)

    # 5. Fresher Mode: separate confirmed vs unclear (§15.1)
    unclear_matches: list[JobMatch] = []
    if fresher_only:
        confirmed = []
        for m in matches:
            if m.experience_level in (ExperienceLevel.FRESHER, ExperienceLevel.JUNIOR):
                confirmed.append(m)
            elif m.experience_level == ExperienceLevel.UNCLEAR:
                unclear_matches.append(m)
            # mid/senior silently excluded in fresher mode
        matches = confirmed

    # 6. Aggregate gaps across the matched set
    aggregate_gaps = _aggregate_gaps(matches)

    return JobMatchResponse(
        matches=matches[:limit],
        unclear_matches=unclear_matches[:limit],
        aggregate_gaps=aggregate_gaps,
    )
