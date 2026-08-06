"""Stage 2 — RAG-Based ATS Resume Checker orchestration.

Pipeline (PRD §8):
1. Parse the uploaded resume (PDF/DOCX) into structured sections + ATS-visible text
2. Extract JD keywords (skills, tools, certifications) via an LLM pass
3. For each JD keyword missing from the ATS-visible text, search the user's
   existing bullets for genuinely related evidence via embedding similarity
   (do NOT literal-swap words)
4. Classify every suggestion into Verified / Reworded / Gap
5. Compute an overall ATS score = structural parseability + keyword coverage
   on ATS-visible text only

The core matching function ``match_keyword_to_bullet`` lives in
``core/confidence.py`` and is shared with Stage 3.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from ..llm_router import router, extract_json
from ..models.schemas import (
    ConfidenceTier,
    KeywordGap,
    ResumeCheckResponse,
)
from .resume_parser import ParsedResume, parse_resume

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# JD keyword extraction
# ---------------------------------------------------------------------------

async def _extract_jd_keywords(jd_text: str) -> list[str]:
    """Extract skills/tools/certifications keywords from a JD via the LLM router.

    §12.6: Strips boilerplate (EEO, benefits, about-us) before extraction.
    """
    from .legitimacy import _strip_boilerplate
    jd_text = _strip_boilerplate(jd_text)

    prompt = (
        "Extract the key technical and professional keywords (skills, tools, "
        "languages, frameworks, certifications) a candidate must demonstrate "
        "for this job description.\n"
        "Rules:\n"
        "- Return ONLY a JSON list of strings, no commentary.\n"
        "- Include concrete skills/tools (e.g. 'Python', 'PyTorch', 'AWS').\n"
        "- Include soft-skill phrases only if stated explicitly.\n"
        "- Max 25 keywords.\n\n"
        f"JOB DESCRIPTION:\n{jd_text[:6000]}"
    )
    try:
        resp = await router.chat(
            messages=[{"role": "user", "content": prompt}],
            tier="simple",
            max_tokens=512,
            json_mode=True,
        )
        data = extract_json(resp["content"])
        if isinstance(data, dict):
            data = data.get("keywords", data.get("skills", []))
        if isinstance(data, str):
            data = [data]
        keywords = [k for k in data if isinstance(k, str) and k.strip()]
        return list(dict.fromkeys(keywords))[:25]
    except Exception as exc:
        logger.warning("JD keyword extraction failed (%s); using fallback regex", exc)
        return _fallback_keywords(jd_text)


def _fallback_keywords(jd_text: str) -> list[str]:
    """Cheap regex fallback when the LLM is unavailable (keeps pipeline usable)."""
    known = [
        "python", "java", "javascript", "typescript", "react", "node", "sql",
        "kubernetes", "docker", "aws", "azure", "gcp", "tensorflow", "pytorch",
        "nlp", "llm", "rag", "machine learning", "data engineering", "golang",
        "rust", "c++", "fastapi", "flask", "django", "chromadb", "redis",
    ]
    text = jd_text.lower()
    found = [k for k in known if re.search(rf"\b{re.escape(k)}\b", text)]
    return list(dict.fromkeys(found))[:15]


# ---------------------------------------------------------------------------
# Bullet rewrite generation (Reworded tier only)
# ---------------------------------------------------------------------------

async def _generate_rewrite(keyword: str, original_bullet: str) -> str:
    """Rewrite a bullet to use JD terminology without changing facts/metrics."""
    prompt = (
        "Rewrite the following resume bullet to incorporate the JD keyword "
        "naturally, WITHOUT changing any facts, metrics, or exaggerating.\n\n"
        f"JD KEYWORD: {keyword}\n"
        f"ORIGINAL BULLET: {original_bullet}\n\n"
        "Return ONLY the rewritten bullet text, nothing else."
    )
    try:
        resp = await router.chat(
            messages=[{"role": "user", "content": prompt}],
            tier="complex",
            max_tokens=256,
        )
        rewritten = resp["content"].strip().strip('"')
        if rewritten and rewritten.lower() != original_bullet.lower():
            return rewritten
    except Exception as exc:
        logger.warning("Bullet rewrite failed (%s); keeping original", exc)
    return original_bullet


# ---------------------------------------------------------------------------
# ATS score
# ---------------------------------------------------------------------------

def _compute_ats_score(
    parsed: ParsedResume,
    keyword_gaps: list[KeywordGap],
) -> float:
    """ATS score = weighted combination of structural parseability + keyword coverage.

    Structural parseability: starts at 1.0, penalised per structural issue.
    Keyword coverage: fraction of JD keywords present in ATS-visible text.
    Weights per PRD: structural 40%, keyword coverage 60%.
    """
    # Structural component — each unresolved structural issue costs 0.15
    structural_score = max(0.0, 1.0 - 0.15 * len(parsed.structural_issues))

    # Keyword coverage on ATS-visible text only
    if keyword_gaps:
        covered = sum(
            1 for g in keyword_gaps
            if g.tier in (ConfidenceTier.VERIFIED, ConfidenceTier.REWORDED)
        )
        keyword_score = covered / len(keyword_gaps)
    else:
        keyword_score = 1.0

    return round(0.4 * structural_score + 0.6 * keyword_score, 3)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def check_resume(
    resume_path: str,
    jd_text: str,
    resume_id: str = "",
) -> ResumeCheckResponse:
    """Run the full Stage 2 ATS check for a resume file against a JD.

    §12.4: Results are cached by hash(resume_content + jd_text) so
    re-running the same check is instant.

    If ``resume_id`` is provided, the parsed resume is persisted via
    :mod:`resume_store` so ``/resume/save`` can apply accepted suggestions.
    """
    # §12.4: Check cache first
    from ..utils.cache import resume_cache
    resume_bytes = Path(resume_path).read_bytes()
    cache_key = resume_cache.make_key(resume_bytes, jd_text.encode())
    cached = resume_cache.get(cache_key)
    if cached is not None:
        logger.info("Cache hit for resume check (key=%s...)", cache_key[:12])
        from ..models.schemas import KeywordGap, ConfidenceTier
        gaps = [KeywordGap(**g) for g in cached["keyword_gaps"]]
        return ResumeCheckResponse(
            resume_id=cached.get("resume_id", resume_id),
            ats_score=cached["ats_score"],
            structural_issues=[],
            keyword_gaps=gaps,
        )

    # 1. Parse resume (structured + ATS-visible text + structural issues)
    parsed = parse_resume(resume_path)

    # Persist the parsed resume for later save (if we have an id)
    if resume_id:
        from .resume_store import save_parsed, save_graph
        save_parsed(resume_id, parsed)

        # §12.1: Extract resume entity graph for token-efficient matching
        from ..core.resume_graph import extract_resume_graph
        skills_text = "\n".join(parsed.sections.get("skills", []))
        graph = extract_resume_graph(
            [{"section": b.section, "text": b.text} for b in parsed.bullets],
            skills_raw=skills_text,
        )
        save_graph(resume_id, graph.to_dict())

    # 2. Extract JD keywords
    keywords = await _extract_jd_keywords(jd_text)
    if not keywords:
        keywords = _fallback_keywords(jd_text)
    logger.info("Extracted %d JD keywords", len(keywords))

    # 3. For each keyword missing from ATS-visible text, match to a bullet
    ats_lower = parsed.ats_visible_text.lower()
    keyword_gaps: list[KeywordGap] = []
    for keyword in keywords:
        kw_lower = keyword.lower()

        # If keyword is already visible in ATS text → Verified (near-verbatim)
        if kw_lower in ats_lower:
            keyword_gaps.append(KeywordGap(
                keyword=keyword,
                tier=ConfidenceTier.VERIFIED,
                confidence=1.0,
                rationale="Keyword present near-verbatim in ATS-visible resume text.",
            ))
            continue

        # Otherwise, search bullets for related evidence via match_keyword_to_bullet
        match = await _match_keyword_to_bullet(keyword, parsed)
        if match is None:
            keyword_gaps.append(KeywordGap(
                keyword=keyword,
                tier=ConfidenceTier.GAP,
                confidence=None,
                rationale="No supporting evidence found in resume — flagged as a gap.",
            ))
            continue

        tier, bullet, score = match
        if tier == ConfidenceTier.VERIFIED:
            keyword_gaps.append(KeywordGap(
                keyword=keyword,
                tier=ConfidenceTier.VERIFIED,
                bullet_id=bullet.id,
                original_text=bullet.text,
                confidence=score,
                rationale="Closely related evidence found; keyword can be surfaced.",
            ))
        elif tier == ConfidenceTier.REWORDED:
            # Generate a rewrite for reworded suggestions
            rewritten = await _generate_rewrite(keyword, bullet.text)
            keyword_gaps.append(KeywordGap(
                keyword=keyword,
                tier=ConfidenceTier.REWORDED,
                bullet_id=bullet.id,
                original_text=bullet.text,
                suggested_text=rewritten,
                confidence=score,
                rationale="Real underlying experience exists; bullet rewritten to use JD terminology.",
            ))
        else:  # GAP
            keyword_gaps.append(KeywordGap(
                keyword=keyword,
                tier=ConfidenceTier.GAP,
                confidence=None,
                rationale="No supporting evidence found in resume — flagged as a gap.",
            ))

    # 4. Compute ATS score
    ats_score = _compute_ats_score(parsed, keyword_gaps)

    # §12.4: Cache the result
    cache_key = resume_cache.make_key(resume_bytes, jd_text.encode())
    resume_cache.set(cache_key, {
        "resume_id": resume_id,
        "ats_score": ats_score,
        "keyword_gaps": [g.model_dump() for g in keyword_gaps],
    })

    return ResumeCheckResponse(
        resume_id=resume_id,
        ats_score=ats_score,
        structural_issues=parsed.structural_issues,
        keyword_gaps=keyword_gaps,
    )


# ---------------------------------------------------------------------------
# Keyword → bullet matching (embeddings-aware)
# ---------------------------------------------------------------------------

async def _match_keyword_to_bullet(
    keyword: str,
    parsed: ParsedResume,
) -> tuple[ConfidenceTier, Any, float] | None:
    """Match a JD keyword against resume bullets using embedding similarity.

    Returns (tier, best_bullet, score) or None if no bullet supports it.
    """
    from ..core.confidence import REWORDED_THRESHOLD, VERIFIED_THRESHOLD
    from ..vector_store import store

    bullets = parsed.bullets
    if not bullets:
        return None

    # Try exact text match first (cheapest, no LLM/embedding call)
    kw_lower = keyword.lower()
    for b in bullets:
        if kw_lower in b.text.lower():
            return ConfidenceTier.VERIFIED, b, 1.0

    # Otherwise attempt embedding similarity via ChromaDB (resume_sections)
    try:
        # Embed the keyword, query the resume sections collection
        query = await router.embed(keyword)
        # Since bullets may not be in the store yet, compute cosine against
        # bullet text embeddings on the fly via the store's embedding fn.
        from ..core.confidence import cosine_similarity

        embed_fn = store._embedding_fn
        bullet_vectors = embed_fn([b.text for b in bullets])

        best_score = 0.0
        best_idx = 0
        for i, vec in enumerate(bullet_vectors):
            score = cosine_similarity(query, vec)
            if score > best_score:
                best_score = score
                best_idx = i

        best_bullet = bullets[best_idx]

        if best_score >= VERIFIED_THRESHOLD:
            return ConfidenceTier.VERIFIED, best_bullet, best_score
        if best_score >= REWORDED_THRESHOLD:
            return ConfidenceTier.REWORDED, best_bullet, best_score
        return None  # below threshold → gap

    except Exception as exc:
        logger.warning("Embedding match failed (%s); lexical fallback", exc)
        # Lexical fallback: shared token overlap as a weak proxy
        import re
        kw_tokens = set(re.findall(r"[a-z0-9+#.]+", keyword.lower()))
        best_score = 0.0
        best_bullet = None
        for b in bullets:
            b_tokens = set(re.findall(r"[a-z0-9+#.]+", b.text.lower()))
            overlap = len(kw_tokens & b_tokens) / max(1, len(kw_tokens))
            if overlap > best_score:
                best_score = overlap
                best_bullet = b
        if best_bullet and best_score >= REWORDED_THRESHOLD:
            return ConfidenceTier.REWORDED, best_bullet, best_score
        return None
