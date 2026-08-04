"""Job posting legitimacy checker (FR3.8).

Flags likely scam/ghost postings before they surface as matches:

- Vague description (very short, or near-empty after stripping boilerplate)
- No verifiable company info (company == "Unknown" or missing URL)
- Identical text repeated across many listings (caller supplies that signal)
- Explicit "no visa sponsorship" hard blocker when the candidate needs it

Returns a list of flag dicts suitable for surfacing on each posting.
"""
from __future__ import annotations

import re

from ..models.schemas import JobPosting

# Reasonable thresholds for v1 — tunable in config later.
MIN_DESCRIPTION_LENGTH = 100
NO_SPONSORSHIP_PATTERNS = [
    r"no\s+visa\s+sponsorship",
    r"not\s+sponsoring",
    r"cannot\s+sponsor",
    r"unable\s+to\s+sponsor",
    r"sponsorship\s+(?:is\s+)?not\s+(?:available|provided|offered)",
]


def _strip_boilerplate(text: str) -> str:
    """Strip common boilerplate sections that aren't a real job description."""
    boilerplate_markers = [
        r"equal\s+opportunity\s+employer",
        r"we\s+offer",
        r"benefits:?",
        r"about\s+us:?",
        r"company\s+(?:overview|description):?",
    ]
    out = text
    for marker in boilerplate_markers:
        out = re.split(marker, out, maxsplit=1, flags=re.I)[0]
    return out.strip()


def has_no_sponsorship(text: str) -> bool:
    """Detect an explicit no-visa-sponsorship statement."""
    if not text:
        return False
    return any(
        re.search(pattern, text, re.I)
        for pattern in NO_SPONSORSHIP_PATTERNS
    )


def check_posting(
    posting: JobPosting,
    *,
    needs_sponsorship: bool = False,
    description_text: str | None = None,
) -> list[dict[str, str]]:
    """Return a list of flag dicts for a single posting.

    Each flag: ``{"kind": "ghost" | "sponsorship" | "vague" | "unknown_company",
    "detail": str}``. Empty list means the posting looks clean.

    ``description_text`` overrides ``posting.description`` for the heuristics
    (lets the orchestrator feed the full JD text it already extracted).
    """
    description = description_text or posting.description or ""
    cleaned = _strip_boilerplate(description)
    flags: list[dict[str, str]] = []

    # 1. Vague description
    if len(cleaned) < MIN_DESCRIPTION_LENGTH:
        flags.append({
            "kind": "vague",
            "detail": (
                f"Description is too short ({len(cleaned)} chars after stripping "
                "boilerplate) — likely a low-quality listing."
            ),
        })

    # 2. No verifiable company
    if not posting.company or posting.company.strip().lower() == "unknown":
        flags.append({
            "kind": "unknown_company",
            "detail": "No company name in posting — unverifiable.",
        })
    if not posting.url:
        flags.append({
            "kind": "unknown_company",
            "detail": "No apply URL — unverifiable.",
        })

    # 3. No-visa-sponsorship hard blocker
    if needs_sponsorship and has_no_sponsorship(description):
        flags.append({
            "kind": "sponsorship",
            "detail": "Posting explicitly states no visa sponsorship.",
        })

    return flags