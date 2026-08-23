from fastapi import APIRouter, Query, HTTPException

from ..models.schemas import (
    JobMatchResponse,
    LocationMode,
    LocationPreference,
    RefreshStatusResponse,
    BackgroundRefreshResponse,
)

router = APIRouter(prefix="/api/v1/jobs", tags=["stage3"])

@router.get("/match", response_model=JobMatchResponse)
async def jobs_match(
    resume_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    location_mode: LocationMode = LocationMode.SPECIFIC_CITY,
    cities: str = Query(default="", description="Comma-separated cities"),
    remote_ok: bool = False,
    fresher_only: bool = Query(default=False),
    test: bool = Query(default=False, description="Return sample data for UI testing"),
) -> JobMatchResponse:
    pref = LocationPreference(
        mode=location_mode,
        cities=[c.strip() for c in cities.split(",") if c.strip()] if cities else [],
        remote_ok=remote_ok,
    )
    if not test:
        from ..services.job_matcher import match_jobs
        try:
            return await match_jobs(resume_id, pref, limit, fresher_only=fresher_only)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Mock data for UI testing
    from datetime import datetime, timezone
    from ..models.schemas import AggregateGap, JobMatch as JM, LocationMatch as LM
    now = datetime.now(timezone.utc)
    mock_matches = [
        JM(
            job_id="mock-1", title="Python Developer", company="TechCorp",
            source="mock", location="Remote", match_score=0.85,
            location_match=LM.REMOTE, top_gaps=["Rust", "Go"],
            apply_url="https://example.com/1",
        ),
        JM(
            job_id="mock-2", title="Backend Engineer", company="StartupXYZ",
            source="mock", location="Remote", match_score=0.72,
            location_match=LM.REMOTE, top_gaps=["Kubernetes"],
            apply_url="https://example.com/2",
        ),
        JM(
            job_id="mock-3", title="Full-Stack Developer", company="BigCo",
            source="mock", location="Hybrid", match_score=0.68,
            location_match=LM.NONE, top_gaps=["React", "GraphQL"],
            apply_url="https://example.com/3",
        ),
    ]
    return JobMatchResponse(
        matches=mock_matches,
        aggregate_gaps=[
            AggregateGap(skill="Rust", missing_in_pct=0.33),
            AggregateGap(skill="Go", missing_in_pct=0.33),
            AggregateGap(skill="Kubernetes", missing_in_pct=0.33),
        ],
    )

@router.post("/refresh", response_model=BackgroundRefreshResponse)
async def jobs_refresh(
    force: bool = Query(default=False, description="Force refresh even if recent"),
):
    from ..services import jobs_queue
    job_id = await jobs_queue.enqueue_refresh(jobs_queue.redis_client, force=force)
    return BackgroundRefreshResponse(
        status="accepted",
        message="Background refresh started.",
        job_id=job_id,
    )

@router.get("/refresh/status/{job_id}", response_model=RefreshStatusResponse)
async def jobs_refresh_status(job_id: str):
    from ..services import jobs_queue
    if jobs_queue.redis_client is None:
        raise HTTPException(status_code=503, detail="Redis not available")
    status = await jobs_queue.get_status(jobs_queue.redis_client, job_id)
    if not status:
        raise HTTPException(status_code=404, detail="Job not found")
    return RefreshStatusResponse(**status)
