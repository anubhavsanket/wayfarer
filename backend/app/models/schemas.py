"""Shared Pydantic schemas used across all Wayfarer stages."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# ---------- Confidence tiers (shared across Stage 2/3) ----------

class ConfidenceTier(str, Enum):
    VERIFIED = "verified"
    REWORDED = "reworded"
    GAP = "gap"


class LocationMode(str, Enum):
    SPECIFIC_CITY = "specific_city"
    REMOTE_ONLY = "remote_only"
    HYBRID = "hybrid"
    OPEN_TO_RELOCATION = "open_to_relocation"


class LocationMatch(str, Enum):
    EXACT = "exact"
    REMOTE = "remote"
    RELOCATION_REQUIRED = "relocation_required"
    NONE = "none"


# ---------- Stage 1: Search ----------

class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Natural-language search query")
    max_sources: int = Field(default=5, ge=1, le=10)


class Citation(BaseModel):
    id: int
    url: str
    title: str
    snippet: str


class SearchResponse(BaseModel):
    answer: str
    citations: list[Citation]
    sub_queries_used: list[str]
    cached: bool = False


# ---------- Stage 2: Resume / ATS ----------

class StructuralIssue(BaseModel):
    location: str
    issue: str


class KeywordGap(BaseModel):
    keyword: str
    tier: ConfidenceTier
    bullet_id: str | None = None
    original_text: str | None = None
    suggested_text: str | None = None
    rationale: str
    confidence: float | None = None


class ResumeCheckResponse(BaseModel):
    resume_id: str = ""
    ats_score: float
    structural_issues: list[StructuralIssue]
    keyword_gaps: list[KeywordGap]


class AcceptedSuggestion(BaseModel):
    bullet_id: str
    suggested_text: str


class SaveMode(str, Enum):
    NEW_FILE = "new_file"
    OVERWRITE = "overwrite"
    SET_AS_PRIMARY = "set_as_primary"


class ResumePrimaryInfo(BaseModel):
    """Response schema for primary resume endpoints (§8.6)."""
    resume_id: str
    filename: str
    uploaded_at: str


class ResumeSaveRequest(BaseModel):
    resume_id: str
    accepted_suggestions: list[AcceptedSuggestion]
    mode: SaveMode
    confirm_overwrite: bool = False


class ResumeSaveResponse(BaseModel):
    file_id: str
    file_ref: str
    mode_applied: SaveMode


# ---------- Stage 3: Job matching ----------

class LocationPreference(BaseModel):
    mode: LocationMode = LocationMode.SPECIFIC_CITY
    cities: list[str] = []
    remote_ok: bool = False


class JobMatchRequest(BaseModel):
    resume_id: str
    limit: int = Field(default=20, ge=1, le=100)
    location_preference: LocationPreference = Field(default_factory=LocationPreference)


class ExperienceLevel(str, Enum):
    FRESHER = "fresher"
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    UNCLEAR = "unclear"


class EmploymentType(str, Enum):
    FULL_TIME = "full_time"
    CONTRACT = "contract"
    FREELANCE = "freelance"
    PART_TIME = "part_time"
    UNCLEAR = "unclear"


class JobMatch(BaseModel):
    job_id: str
    title: str
    company: str
    source: str
    location: str
    match_score: float
    location_match: LocationMatch
    top_gaps: list[str]
    apply_url: str
    remote_type: str = ""
    flags: list[str] = Field(
        default_factory=list,
        description="Legitimacy flags: ghost/vague/unknown_company/sponsorship",
    )
    experience_level: ExperienceLevel = ExperienceLevel.UNCLEAR
    min_experience_years: float | None = None
    employment_type: EmploymentType = EmploymentType.UNCLEAR
    also_available_in: list[str] = Field(
        default_factory=list,
        description="Other cities where this same role is posted (mass-posting consolidation)",
    )


class AggregateGap(BaseModel):
    skill: str
    missing_in_pct: float


class JobMatchResponse(BaseModel):
    matches: list[JobMatch]
    unclear_matches: list[JobMatch] = Field(default_factory=list)
    aggregate_gaps: list[AggregateGap]


# ---------- Job posting model ----------

class JobPosting(BaseModel):
    id: str
    source: str
    title: str
    company: str
    url: str
    location: str | None = None
    remote_type: str | None = None
    description: str | None = None
    fetched_at: datetime
    jd_id: str | None = None


# ---------- Health ----------

class DependencyStatus(BaseModel):
    name: str
    status: Literal["up", "down"]
    detail: str = ""


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    dependencies: list[DependencyStatus]
