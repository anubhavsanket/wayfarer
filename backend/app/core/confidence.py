"""Confidence-tier classification shared by Stage 2 and Stage 3.

Ported from the real-estate RAG project's VerificationLayer (EXACT /
PARTIAL / NO_MATCH) into a standalone, pure-function utility so the tier
logic is testable without any LLM dependency.

Tier semantics (from the PRD):
- ``verified``  — keyword present near-verbatim; just needs surfacing/reordering
- ``reworded``  — real underlying experience exists; bullet rewritten to use JD
  terminology, facts/metrics unchanged
- ``gap``       — no supporting evidence found; flagged, never auto-inserted

The one hard rule: **never** insert a keyword with no supporting bullet above
the similarity threshold, regardless of tier.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..models.schemas import ConfidenceTier


# Default thresholds (tunable via config in a later pass)
VERIFIED_THRESHOLD = 0.90   # near-verbatim match
REWORDED_THRESHOLD = 0.75   # genuine semantic overlap, different wording
GAP_FLOOR = 0.0             # anything below REWORDED_THRESHOLD is a gap


@dataclass
class ResumeBullet:
    """A single resume bullet, as stored in the ``resume_sections`` collection."""
    id: str
    section: str
    text: str
    embedding: list[float] | None = None


@dataclass
class MatchResult:
    """Outcome of matching a single JD keyword against resume bullets."""
    keyword: str
    tier: ConfidenceTier
    bullet_id: str | None = None
    confidence: float | None = None
    rewritten_text: str | None = None


def classify_similarity(score: float) -> ConfidenceTier:
    """Map a similarity score to a confidence tier.

    >>> classify_similarity(0.95)
    <ConfidenceTier.VERIFIED: 'verified'>
    >>> classify_similarity(0.80)
    <ConfidenceTier.REWORDED: 'reworded'>
    >>> classify_similarity(0.40)
    <ConfidenceTier.GAP: 'gap'>
    """
    if score >= VERIFIED_THRESHOLD:
        return ConfidenceTier.VERIFIED
    if score >= REWORDED_THRESHOLD:
        return ConfidenceTier.REWORDED
    return ConfidenceTier.GAP


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two embedding vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def match_keyword_to_bullet(
    jd_keyword: str,
    resume_bullets: list[ResumeBullet],
    similarity_threshold: float = REWORDED_THRESHOLD,
    jd_keyword_embedding: list[float] | None = None,
) -> MatchResult:
    """Core matching function from PRD §8.2.

    Returns one of:
    - ``MatchResult(tier=verified, bullet_id, confidence)``
    - ``MatchResult(tier=reworded, bullet_id, rewritten_text, confidence)``
    - ``MatchResult(tier=gap, confidence=None)``

    Never inserts a keyword with no supporting bullet, regardless of tier.
    """
    if not resume_bullets:
        return MatchResult(keyword=jd_keyword, tier=ConfidenceTier.GAP)

    # Exact / near-verbatim presence wins immediately (cheap text check)
    lowered = jd_keyword.lower()
    exact = [
        b for b in resume_bullets
        if lowered in b.text.lower()
    ]
    if exact:
        best = exact[0]
        return MatchResult(
            keyword=jd_keyword,
            tier=ConfidenceTier.VERIFIED,
            bullet_id=best.id,
            confidence=1.0,
        )

    # Otherwise compare against bullet embeddings when available. Embeddings
    # are compared against the JD keyword's own embedding (not self-similarity).
    scored: list[tuple[float, ResumeBullet]] = []
    if jd_keyword_embedding is not None:
        for bullet in resume_bullets:
            if bullet.embedding is not None:
                score = cosine_similarity(jd_keyword_embedding, bullet.embedding)
                scored.append((score, bullet))

    # Fallback path when embeddings aren't available yet — lexical overlap as a
    # weak proxy so the pipeline can run before embeddings are populated.
    if not scored:
        import re
        kw_tokens = set(re.findall(r"[a-z0-9+#.]+", lowered))
        if not kw_tokens:
            return MatchResult(keyword=jd_keyword, tier=ConfidenceTier.GAP)
        for bullet in resume_bullets:
            btokens = set(re.findall(r"[a-z0-9+#.]+", bullet.text.lower()))
            overlap = len(kw_tokens & btokens) / len(kw_tokens)
            scored.append((overlap, bullet))

    scored.sort(key=lambda t: t[0], reverse=True)
    top_score, top_bullet = scored[0]

    tier = classify_similarity(top_score)
    if tier in (ConfidenceTier.VERIFIED, ConfidenceTier.REWORDED):
        return MatchResult(
            keyword=jd_keyword,
            tier=tier,
            bullet_id=top_bullet.id,
            confidence=top_score,
        )
    return MatchResult(keyword=jd_keyword, tier=ConfidenceTier.GAP)


def rerank_matches(results: list[MatchResult]) -> list[MatchResult]:
    """Sort match results by descending confidence, gaps last.

    Used by Stage 3 to present the strongest keyword matches first.
    """
    def sort_key(r: MatchResult) -> tuple[int, float]:
        tier_rank = {
            ConfidenceTier.VERIFIED: 0,
            ConfidenceTier.REWORDED: 1,
            ConfidenceTier.GAP: 2,
        }[r.tier]
        return (tier_rank, -(r.confidence or 0.0))

    return sorted(results, key=sort_key)
