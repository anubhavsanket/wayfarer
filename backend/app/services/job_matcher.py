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
from typing import Any

from ..config import settings
from ..llm_router import extract_json, router
from ..utils.cache import classification_cache, make_hash_key
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

import re

_ROLE_PATTERNS = [
    r"\b(machine learning engineer|ml engineer|ai engineer|ai/ml engineer)\b",
    r"\b(software engineer|software developer|full[- ]stack developer|backend developer|frontend developer)\b",
    r"\b(data scientist|data engineer|devops engineer|cloud engineer|systems engineer)\b",
]


def _extract_resume_search_keywords(parsed: Any) -> str:
    """Extract candidate target role or top technical keywords from parsed resume."""
    text = getattr(parsed, "raw_text", "") or ""
    text_lower = text[:1000].lower()

    for pattern in _ROLE_PATTERNS:
        match = re.search(pattern, text_lower)
        if match:
            found = match.group(1).title()
            if "Ai/Ml" in found:
                return "AI Machine Learning Engineer"
            if "Ml" in found:
                return "Machine Learning Engineer"
            if "Ai" in found:
                return "AI Engineer"
            return found

    # Fallback to skills section if present
    sections = getattr(parsed, "sections", {}) or {}
    skills_lines = sections.get("skills", [])
    skills_text = " ".join(skills_lines)
    if skills_text:
        tech_kw = []
        for kw in ["Python", "Java", "React", "TypeScript", "C++", "PyTorch", "Node", "SQL"]:
            if re.search(rf"\b{kw}\b", skills_text, re.IGNORECASE):
                tech_kw.append(kw)
        if tech_kw:
            return f"{tech_kw[0]} Developer"

    return "Software Engineer"


def _interleave_postings(board_results: list[list[JobPosting]]) -> list[JobPosting]:
    """Interleave postings from multiple boards so no single board dominates."""
    out: list[JobPosting] = []
    max_len = max((len(r) for r in board_results), default=0)
    for i in range(max_len):
        for result_list in board_results:
            if i < len(result_list):
                out.append(result_list[i])
    return out


async def _discover_postings(keywords: str = "", location: str = "") -> list[JobPosting]:
    """Fetch postings from every enabled board in the registry."""
    registry = load_registry("config/job_boards.yaml")
    enabled = [b for b in registry.job_boards if b.enabled]
    connector = JobBoardConnector()
    try:
        board_results: list[list[JobPosting]] = []
        for board in enabled:
            try:
                board_postings = await connector.fetch_all(board, keywords=keywords, location=location)
                board_results.append(board_postings)
                logger.info("Fetched %d postings from %s", len(board_postings), board.name)
            except Exception as exc:
                logger.warning("Board %s fetch failed: %s", board.name, exc)
        postings = _interleave_postings(board_results)
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

async def _embed_resume(parsed: Any) -> list[float]:
    """Embed the resume (concatenated bullet texts) once."""
    text = "\n".join(b.text for b in parsed.bullets) or parsed.ats_visible_text
    return await router.embed(text)


async def _compute_semantic_scores(
    resume_vec: list[float],
    postings: list[JobPosting],
) -> list[tuple[JobPosting, float]]:
    """Cosine similarity of each posting's JD (or title+company fallback) against resume embedding."""
    scored: list[tuple[JobPosting, float]] = []
    for posting in postings:
        desc = (posting.description or "").strip()
        text_to_embed = desc if len(desc) > 20 else f"{posting.title} at {posting.company}"
        if not text_to_embed.strip():
            scored.append((posting, 0.0))
            continue
        try:
            jd_vec = await router.embed(text_to_embed)
            score = cosine_similarity(resume_vec, jd_vec)
        except Exception as exc:
            logger.warning("JD embed failed for %s: %s", posting.id, exc)
            score = 0.0
        scored.append((posting, score))
    return scored


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
    """Classify experience level using a small local LLM (qwen3:0.6b)."""
    key = make_hash_key(jd_text)
    cached = await classification_cache.get(key)
    if cached:
        return cached

    VALID_LEVELS = {"fresher", "junior", "mid", "senior", "unclear"}
    try:
        resp = await router.chat(
            messages=[{"role": "user", "content": _CLASSIFICATION_PROMPT.format(text=jd_text[:1500])}],
            model="qwen3:0.6b",
            provider="ollama",
            max_tokens=150,
        )
        result = extract_json(resp["content"])
        level = result.get("experience_level", "unclear")
        if level not in VALID_LEVELS:
            level = "unclear"
        final_result = {
            "experience_level": level,
            "min_experience_years": result.get("min_experience_years"),
            "confidence": result.get("confidence", 0.0),
        }
        await classification_cache.set(key, final_result)
        return final_result
    except Exception as exc:
        logger.debug("Experience classification failed: %s", exc)
        return {"experience_level": "unclear", "min_experience_years": None, "confidence": 0.0}


async def _match_one(
    posting: JobPosting,
    parsed: Any,
    resume_vec: list[float],
    semantic_score: float,
) -> JobMatch:
    """Compute the full hybrid match for a single posting (top-K only)."""
    bullets = parsed.bullets
    keywords = await _extract_jd_keywords(posting.description or "")
    overlap, missing = await _compute_keyword_overlap(posting, bullets, keywords)

    hybrid = round(SEMANTIC_WEIGHT * semantic_score + KEYWORD_WEIGHT * overlap, 3)
    top_gaps = missing[:3]

    # Legitimacy flags (FR3.8) — ghost/scam and sponsorship check
    from .legitimacy import check_posting
    flag_dicts = check_posting(posting, needs_sponsorship=False)
    flags = [f["kind"] for f in flag_dicts]

    # Fresher Mode: classify experience level (§15.1)
    exp_class = await _classify_experience(posting.description or posting.title)

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
        flags=flags,
        experience_level=ExperienceLevel(exp_class["experience_level"]),
        min_experience_years=exp_class["min_experience_years"],
    )


# ---------------------------------------------------------------------------
# Location preference (FR3.6, FR3.7)
# ---------------------------------------------------------------------------

def _apply_location_preference(
    matches: list[JobMatch],
    pref: LocationPreference,
) -> list[JobMatch]:
    """Filter and label postings based on user location preferences.

    Applies the selected LocationMode (REMOTE_ONLY, HYBRID, SPECIFIC_CITY, OPEN_TO_RELOCATION)
    to sort and label job matches. Matches that don't meet the criteria
    are removed from the final list, and surviving matches receive a LocationMatch label
    (EXACT, REMOTE, RELOCATION_REQUIRED).

    Args:
        matches: A list of matched JobMatch objects to filter.
        pref: The user's LocationPreference configuration.

    Returns:
        A filtered and re-ranked list of JobMatch objects.
    """
    mode = pref.mode
    cities = [c.lower().strip() for c in pref.cities if c]
    remote_ok = pref.remote_ok

    def city_matches(p: JobMatch) -> bool:
        if not cities:
            return True  # no city constraint
        loc = (p.location or "").lower()
        return any(c in loc for c in cities)

    kept: list[JobMatch] = []
    for m in matches:
        is_remote = "remote" in (m.location or "").lower()

        if mode == LocationMode.REMOTE_ONLY:
            if not is_remote:
                continue
            m.location_match = LocationMatch.REMOTE

        elif mode == LocationMode.HYBRID:
            if not (is_remote or "hybrid" in (m.location or "").lower()):
                continue
            m.location_match = LocationMatch.REMOTE

        elif mode == LocationMode.SPECIFIC_CITY:
            if not cities:
                # No city constraint — accept all postings (mark as exact if
                # remote_ok or not remote; otherwise mark as relocation required)
                if is_remote and remote_ok:
                    m.location_match = LocationMatch.REMOTE
                elif is_remote:
                    m.location_match = LocationMatch.REMOTE
                else:
                    m.location_match = LocationMatch.RELOCATION_REQUIRED
            elif city_matches(m):
                m.location_match = LocationMatch.EXACT
            elif is_remote and remote_ok:
                m.location_match = LocationMatch.REMOTE
            else:
                continue  # filtered out

        elif mode == LocationMode.OPEN_TO_RELOCATION:
            # Accept every posting; mark EXACT when a preferred city matches,
            # otherwise RELOCATION_REQUIRED so the user knows it implies moving.
            loc = (m.location or "").lower()
            m.location_match = (
                LocationMatch.EXACT
                if any(c in loc for c in cities)
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
    """Aggregate missing skills across matched job postings.

    Args:
        matches: List of job matches to analyze for missing skills (gaps).

    Returns:
        List of AggregateGap objects representing the top 10 most frequently
        missing skills, with their frequency as a percentage.
    """
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
) -> JobMatchResponse:
    """Orchestrate the Stage 3 job matching pipeline.

    Fetches live job postings, ranks them based on semantic similarity and
    keyword coverage, applies location filtering, and classifies experience levels.

    Args:
        resume_id: The ID of the parsed resume to match against.
        location_preference: User's location mode and preferred cities.
        limit: Max number of matches to return (clamped to 100).
        fresher_only: If True, filters matches to include only 'fresher'/'junior'
                      roles, with 'unclear' roles separated into `unclear_matches`.

    Returns:
        JobMatchResponse containing sorted matches, unclear matches, and aggregated skill gaps.

    Raises:
        ValueError: If `resume_id` is invalid or resume has no bullets.
    """
    pref = location_preference or LocationPreference()
    limit = min(limit, 100)

    # Load the resume (bullets) by resume_id
    parsed = resume_store.load_parsed(resume_id)
    if parsed is None:
        raise ValueError(f"Unknown resume_id: {resume_id}. Run /resume/check first.")
    if not parsed.bullets:
        raise ValueError("Resume has no parseable bullets — cannot match.")

    # Extract candidate keywords from resume
    search_keywords = _extract_resume_search_keywords(parsed)
    location_query = ", ".join(pref.cities) if pref and pref.cities else ""

    # 1. Discovery + dedup + normalise + drop stale (zero-token)
    postings = _dedupe_postings(await _discover_postings(keywords=search_keywords, location=location_query))
    if not postings:
        return JobMatchResponse(matches=[], aggregate_gaps=[])
    postings = _normalise_postings(postings)
    postings = _drop_stale(postings)
    logger.info("After pipeline cleanup: %d postings", len(postings))

    # 2. Embedding similarity (rank all, keep top-K)
    resume_vec = await _embed_resume(parsed)
    scored = await _compute_semantic_scores(resume_vec, postings)
    scored.sort(key=lambda t: t[1], reverse=True)
    top_k = scored[:TOP_K_EMBEDDING_SURVIVORS]
    logger.info("Top-K after semantic score: %d postings (of %d total)", len(top_k), len(scored))

    # 3. LLM keyword overlap on top-K only (cost control)
    matches: list[JobMatch] = []
    for posting, semantic in top_k:
        m = await _match_one(posting, parsed, resume_vec, semantic)
        matches.append(m)

    # 4. Location filter + re-rank
    matches = _apply_location_preference(matches, pref)

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
