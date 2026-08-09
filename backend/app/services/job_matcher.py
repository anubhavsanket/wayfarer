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


def _dedupe_postings(postings: list[JobPosting]) -> list[JobPosting]:
    """Deduplicate by (title.lower(), company.lower(), url) — FR3.9."""
    seen: set[str] = set()
    out: list[JobPosting] = []
    for p in postings:
        key = (p.title.lower(), p.company.lower(), p.url or "")
        if key not in seen:
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


def _title_overlap_score(posting: JobPosting, bullets: list[Any]) -> float:
    """Zero-token relevance score for postings without a description.

    Boards that only expose title/company cards (LinkedIn guest API, some
    ATS boards) ship no JD body, so they can't be embedded. This scores them
    by the fraction of title/company tokens that also appear in the resume —
    a cheap lexical proxy so they can be ranked by the top-K survivor cutoff
    instead of getting a flat 0.0 and being dropped (§9.6).
    """
    # Require ≥2 chars to avoid single-letter false positives ('t' in 'fastapi',
    # 'c' in 'python') that produce spurious substring matches against resume text.
    tokens = set(re.findall(r"[a-z0-9+#.]{2,}", f"{posting.title} {posting.company}".lower()))
    if not tokens:
        return 0.0
    resume_text = " ".join(b.text.lower() for b in bullets if b.text)
    hits = sum(1 for t in tokens if t in resume_text)
    return hits / len(tokens)


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

        return {
            "experience_level": level,
            "min_experience_years": result.get("min_experience_years") if result else None,
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
    """Whole-word city match: every word of the city must appear in the location.

    Substring matching is too loose — a short city like 'ny' or 'us' matches
    the middle of unrelated words ('any', 'house'). Token matching requires
    the full city phrase: 'San Francisco' matches 'San Francisco, CA' but
    not 'Santa Clara'.
    """
    city_tokens = _LOC_TOKEN_RE.findall(city.lower())
    if not city_tokens:
        return False
    return all(t in loc_tokens for t in city_tokens)


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
    cities = [c.lower().strip() for c in pref.cities if c]
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
    postings = _dedupe_postings(await _discover_postings())
    if not postings:
        return JobMatchResponse(matches=[], aggregate_gaps=[])
    postings = _normalise_postings(postings)
    postings = _drop_stale(postings, ttl_days=max_age_days)

    # Filter by source if specified
    if sources:
        source_set = set(s.lower() for s in sources)
        postings = [p for p in postings if p.source.lower() in source_set]
        logger.info("Source filter: %d postings from %s", len(postings), sources)

    logger.info("After pipeline cleanup: %d postings (max_age=%d days)", len(postings), max_age_days)

    # 2. Embedding similarity (rank all, keep top-K)
    # Limit embedding to first 50 postings with descriptions to bound latency
    # (each embedding takes ~8s on CPU, so 200 × 8 = 26min is unacceptable)
    MAX_EMBED_POSTINGS = 50
    resume_vec = await _embed_resume(parsed)
    if resume_vec is not None:
        # Prioritise postings that have descriptions (they can actually be embedded)
        with_desc = [p for p in postings if p.description]
        without_desc = [p for p in postings if not p.description]
        to_embed = with_desc[:MAX_EMBED_POSTINGS]
        logger.info("Embedding %d of %d postings with descriptions (%d skipped, %d without desc)",
                     len(to_embed), len(with_desc), max(0, len(with_desc) - MAX_EMBED_POSTINGS), len(without_desc))
        scored = await _compute_semantic_scores(resume_vec, to_embed)
        # Remaining with-description postings are never embedded — score 0.
        scored.extend((p, 0.0) for p in with_desc[MAX_EMBED_POSTINGS:])
        scored.sort(key=lambda t: t[1], reverse=True)

        # Title-only postings (LinkedIn guest cards, some ATS boards) have no
        # description to embed, so a flat 0.0 lets description-rich boards
        # starve them out of the top-K entirely (§9.6). Rank them with a
        # zero-token title-overlap score and reserve a few survivor slots.
        title_scored = sorted(
            ((p, _title_overlap_score(p, parsed.bullets)) for p in without_desc),
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
