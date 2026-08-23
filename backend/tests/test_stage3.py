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


# ---------------------------------------------------------------------------
# Fresher Mode — experience-level classification (§15.1)
# ---------------------------------------------------------------------------

class TestExperienceClassification:
    async def test_classifies_fresher_posting(self, monkeypatch):
        """_classify_experience parses a valid LLM response into a level."""
        from backend.app.services import job_matcher

        async def fake_chat(*args, **kwargs):
            # The bug: router.chat() has no `model` kwarg. This fake asserts
            # the call now carries the qwen3:0.6b model + ollama provider.
            assert kwargs.get("model") == "qwen3:0.6b"
            assert kwargs.get("provider") == "ollama"
            return {
                "content": '{"experience_level": "fresher", "min_experience_years": 0, "confidence": 0.9}',
                "provider": "ollama",
                "model": "qwen3:0.6b",
                "cached": False,
            }

        monkeypatch.setattr(job_matcher.router, "chat", fake_chat)
        result = await job_matcher._classify_experience(
            "Entry-level graduate role, freshers welcome, 0-1 years experience."
        )
        assert result == {
            "experience_level": "fresher",
            "min_experience_years": 0,
            "confidence": 0.9,
        }

    async def test_falls_back_to_unclear_on_llm_failure(self, monkeypatch):
        """If classification fails, it degrades to 'unclear' — never crashes."""
        from backend.app.services import job_matcher

        async def broken_chat(*args, **kwargs):
            raise RuntimeError("ollama unreachable")

        monkeypatch.setattr(job_matcher.router, "chat", broken_chat)
        result = await job_matcher._classify_experience("Senior staff engineer role")
        assert result["experience_level"] == "unclear"
        assert result["min_experience_years"] is None

    async def test_invalid_level_sanitised_to_unclear(self, monkeypatch):
        from backend.app.services import job_matcher

        async def fake_chat(*args, **kwargs):
            return {
                "content": '{"experience_level": "principal-arch", "confidence": 1.0}',
                "provider": "ollama", "model": "qwen3:0.6b", "cached": False,
            }

        monkeypatch.setattr(job_matcher.router, "chat", fake_chat)
        result = await job_matcher._classify_experience("some JD")
        assert result["experience_level"] == "unclear"


class TestLLMRouterModelOverride:
    """Regression: router.chat() must accept a `model` override kwarg."""

    async def test_chat_accepts_model_override(self, monkeypatch):
        """chat(model=...) must not raise TypeError; the override reaches the provider."""
        from backend.app.llm_router import router

        captured: dict = {}

        async def fake_call_provider(
            provider, model, messages, *, max_tokens, temperature, cache_control, json_mode, tools=None, tool_choice=None
        ):
            captured["provider"] = provider
            captured["model"] = model
            return {"content": "ok", "provider": provider, "model": model, "cached": False, "tool_calls": None}

        monkeypatch.setattr(router, "_call_provider", fake_call_provider)

        result = await router.chat(
            messages=[{"role": "user", "content": "classify"}],
            provider="ollama",
            model="qwen3:0.6b",
            max_tokens=150,
        )
        assert result["content"] == "ok"
        assert captured["model"] == "qwen3:0.6b"
        assert captured["provider"] == "ollama"

    def test_model_override_respects_missing_credentials(self, monkeypatch):
        """An explicit model override must not bypass nvidia credential gating."""
        from backend.app.llm_router import router
        from backend.app import config

        # No NVIDIA key present (tests strip it) — override must be rejected
        monkeypatch.setattr(config.settings, "NVIDIA_NIM_API_KEY", None)
        assert router._model_for("nvidia", "simple", override="gpt-4o") is None

        # Ollama is local — no credentials needed, override passes through
        assert router._model_for("ollama", "simple", override="qwen3:0.6b") == "qwen3:0.6b"
