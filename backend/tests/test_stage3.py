"""Stage 3 tests — location filtering, legitimacy, config-driven boards, aggregation.

Mapped to PRD §9.6 acceptance criteria:
- [ ] Setting location_preference to a city other than Bengaluru returns
      relevant postings without code changes — location logic is fully
      parameterised, not hardcoded
- [ ] A synthetic ghost-job posting (vague description, no company info,
      inflated comp) is flagged rather than surfaced as a clean match
- [ ] A posting with an explicit no-sponsorship clause is marked as a hard
      blocker when the user's profile indicates they need sponsorship
- [ ] config/job_boards.yaml loads correctly and boards can be toggled
"""
from __future__ import annotations

import os
import sys
import datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

for key in ("TAVILY_API_KEY", "BRAVE_API_KEY", "NVIDIA_NIM_API_KEY", "OPENROUTER_API_KEY"):
    os.environ.pop(key, None)

from backend.app.models.schemas import JobPosting  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _posting(
    id: str = "1",
    location: str = "Remote",
    company: str = "Acme",
    url: str = "https://example.com/apply",
    description: str = "Build ML models with Python and TensorFlow",
) -> JobPosting:
    return JobPosting(
        id=id, source="test", title="ML Engineer",
        company=company, url=url, location=location,
        description=description,
        fetched_at=datetime.datetime.now(datetime.timezone.utc),
    )


def _match(loc: str = "Remote", company: str = "X", score: float = 0.8):
    from backend.app.models.schemas import JobMatch, LocationMatch
    return JobMatch(
        job_id="1", title="ML Engineer", company=company, source="test",
        location=loc, match_score=score, location_match=LocationMatch.NONE,
        top_gaps=[], apply_url="https://example.com",
    )


# ---------------------------------------------------------------------------
# Location filtering (PRD §9.6 — city logic must be parameterised)
# ---------------------------------------------------------------------------

class TestLocationFiltering:
    def test_remote_only_keeps_remote(self):
        from backend.app.services.job_matcher import _apply_location_preference
        from backend.app.models.schemas import LocationPreference, LocationMode
        m = _match(loc="Remote")
        kept = _apply_location_preference([m], LocationPreference(mode=LocationMode.REMOTE_ONLY))
        assert len(kept) == 1

    def test_remote_only_filters_onsite(self):
        from backend.app.services.job_matcher import _apply_location_preference
        from backend.app.models.schemas import LocationPreference, LocationMode
        m = _match(loc="Bengaluru, India")
        kept = _apply_location_preference([m], LocationPreference(mode=LocationMode.REMOTE_ONLY))
        assert len(kept) == 0

    def test_specific_city_bengaluru(self):
        """Acceptance: city other than Bengaluru requires no code changes."""
        from backend.app.services.job_matcher import _apply_location_preference
        from backend.app.models.schemas import LocationPreference, LocationMode
        m = _match(loc="Bengaluru, Karnataka")
        kept = _apply_location_preference([m], LocationPreference(
            mode=LocationMode.SPECIFIC_CITY, cities=["bengaluru"],
        ))
        assert len(kept) == 1

    def test_specific_city_includes_remote_when_remote_ok(self):
        from backend.app.services.job_matcher import _apply_location_preference
        from backend.app.models.schemas import LocationPreference, LocationMode
        m = _match(loc="Remote")
        kept = _apply_location_preference([m], LocationPreference(
            mode=LocationMode.SPECIFIC_CITY, cities=["chennai"], remote_ok=True,
        ))
        assert len(kept) == 1

    def test_open_to_relocation_marks_relocation_required(self):
        """Posting in a different city than the preference → relocation_required."""
        from backend.app.services.job_matcher import _apply_location_preference
        from backend.app.models.schemas import LocationPreference, LocationMode, LocationMatch
        m = _match(loc="New York, USA")  # not in pref.cities
        kept = _apply_location_preference([m], LocationPreference(
            mode=LocationMode.OPEN_TO_RELOCATION, cities=["san francisco"],
        ))
        assert len(kept) == 1
        assert kept[0].location_match == LocationMatch.RELOCATION_REQUIRED

    def test_open_to_relocation_exact_city_is_exact(self):
        from backend.app.services.job_matcher import _apply_location_preference
        from backend.app.models.schemas import LocationPreference, LocationMode, LocationMatch
        m = _match(loc="San Francisco, USA")
        kept = _apply_location_preference([m], LocationPreference(
            mode=LocationMode.OPEN_TO_RELOCATION, cities=["san francisco"],
        ))
        assert kept[0].location_match == LocationMatch.EXACT


# ---------------------------------------------------------------------------
# Legitimacy checker (PRD §9.6 acceptance criteria)
# ---------------------------------------------------------------------------

class TestLegitimacy:
    def test_ghost_posting_flagged(self):
        """A ghost posting (vague desc, no company, no URL) is flagged."""
        from backend.app.services.legitimacy import check_posting
        ghost = _posting(company="", url="", description="Great opportunity!!!")
        flags = check_posting(ghost)
        kinds = {f["kind"] for f in flags}
        assert "vague" in kinds
        assert "unknown_company" in kinds

    def test_clean_posting_no_flags(self):
        from backend.app.services.legitimacy import check_posting
        clean = _posting(
            description=(
                "We are hiring an ML engineer to build, train, and deploy "
                "machine learning models with Python, TensorFlow, and PyTorch. "
                "You will work on large-scale recommendation systems, optimize "
                "inference latency, and collaborate with data engineering teams."
            ),
        )
        flags = check_posting(clean)
        assert len(flags) == 0

    def test_no_sponsorship_flagged_as_hard_blocker(self):
        """A posting with no-sponsorship clause is flagged when user needs it."""
        from backend.app.services.legitimacy import check_posting, has_no_sponsorship
        p = _posting(description="Python dev role. No visa sponsorship available.")
        flags = check_posting(p, needs_sponsorship=True)
        kinds = {f["kind"] for f in flags}
        assert "sponsorship" in kinds
        assert has_no_sponsorship("Cannot sponsor any visa for this role.")

    def test_no_sponsorship_not_flagged_when_not_needed(self):
        from backend.app.services.legitimacy import check_posting
        p = _posting(description="Python dev role. No visa sponsorship available.")
        flags = check_posting(p, needs_sponsorship=False)
        kinds = {f["kind"] for f in flags}
        assert "sponsorship" not in kinds


# ---------------------------------------------------------------------------
# Config-driven job board registry (PRD §9.7)
# ---------------------------------------------------------------------------

class TestJobBoardRegistry:
    def test_loads_from_yaml(self):
        from backend.app.models.job_boards import load_registry
        registry = load_registry("config/job_boards.yaml")
        names = {b.name for b in registry.job_boards}
        assert "bluedoor" in names
        assert "linkedin_guest" in names

    def test_enabled_boards_only(self):
        from backend.app.models.job_boards import load_registry
        registry = load_registry("config/job_boards.yaml")
        enabled = [b for b in registry.job_boards if b.enabled]
        assert all(b.name in ("bluedoor", "linkedin_guest") for b in enabled)

    def test_adding_board_is_config_change_not_code(self):
        """PRD §9.7: adding a new board = adding an entry to job_boards.yaml."""
        from backend.app.models.job_boards import load_registry
        registry = load_registry("config/job_boards.yaml")
        # Any enabled board with type=rest_api should have valid field_mapping
        for b in registry.job_boards:
            if b.enabled and b.type == "rest_api":
                assert b.base_url
                assert b.field_mapping.title


# ---------------------------------------------------------------------------
# Aggregate gaps (FR3.5)
# ---------------------------------------------------------------------------

class TestAggregateGaps:
    def test_finds_most_common_missing_skill(self):
        from backend.app.services.job_matcher import _aggregate_gaps
        from backend.app.models.schemas import JobMatch
        m1 = JobMatch(job_id="1", title="a", company="a", source="s", location="R",
                      match_score=0.5, location_match="none", top_gaps=["k8s", "rust"], apply_url="x")
        m2 = JobMatch(job_id="2", title="b", company="b", source="s", location="R",
                      match_score=0.4, location_match="none", top_gaps=["k8s"], apply_url="y")
        gaps = _aggregate_gaps([m1, m2])
        assert gaps[0].skill == "k8s"
        assert gaps[0].missing_in_pct == 1.0

    def test_empty_matches_returns_empty_gaps(self):
        from backend.app.services.job_matcher import _aggregate_gaps
        assert _aggregate_gaps([]) == []

    def test_jobmatch_schema_accepts_flags_field(self):
        """JobMatch with a flags list (from legitimacy checker) round-trips cleanly."""
        from backend.app.models.schemas import JobMatch, LocationMatch
        m = JobMatch(
            job_id="x", title="ML", company="A", source="bluedoor",
            location="Remote", match_score=0.7, location_match=LocationMatch.REMOTE,
            top_gaps=[], apply_url="https://x.com", flags=["vague", "unknown_company"],
        )
        d = m.model_dump()
        assert d["flags"] == ["vague", "unknown_company"]
        assert m.model_validate(d).flags == ["vague", "unknown_company"]
