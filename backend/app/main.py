"""Wayfarer FastAPI application entry point.

Exposes:
- GET /health  — dependency health check (ChromaDB, Ollama, Redis)
- Stage 1: /api/v1/search (stub)
- Stage 2: /api/v1/resume (stub)
- Stage 3: /api/v1/jobs (stub)
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

import httpx
import redis.asyncio as redis
from fastapi import FastAPI, File, Form, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .llm_router import router as llm_router
from .vector_store import store as vector_store
from .models.schemas import (
    DependencyStatus,
    HealthResponse,
    JobMatchResponse,
    LocationMode,
    ResumeCheckResponse,
    ResumeSaveRequest,
    ResumeSaveResponse,
    SearchRequest,
    SearchResponse,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Global clients
redis_client: redis.Redis | None = None
http_client: httpx.AsyncClient | None = None


async def _check_chromadb() -> DependencyStatus:
    try:
        await asyncio.to_thread(vector_store._client.heartbeat)
        return DependencyStatus(name="chromadb", status="up", detail="connected")
    except Exception as exc:
        return DependencyStatus(name="chromadb", status="down", detail=str(exc))


async def _http_get(url: str, headers: dict | None = None) -> httpx.Response:
    """GET using the shared client (safe: does NOT close it).

    If the shared client isn't available (pre-lifespan), creates a throwaway
    one and closes it afterward so the health check still works.
    """
    own_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT)
    resp = await client.get(url, headers=headers or {})
    resp.raise_for_status()
    if own_client:
        await client.aclose()
    return resp


async def _check_ollama() -> DependencyStatus:
    try:
        await _http_get(f"{settings.OLLAMA_ENDPOINT}/api/tags")
        return DependencyStatus(name="ollama", status="up", detail="model list OK")
    except Exception as exc:
        return DependencyStatus(name="ollama", status="down", detail=str(exc))


async def _check_redis() -> DependencyStatus:
    if redis_client is None:
        return DependencyStatus(name="redis", status="down", detail="not initialised")
    try:
        await redis_client.ping()
        return DependencyStatus(name="redis", status="up", detail="ping OK")
    except Exception as exc:
        return DependencyStatus(name="redis", status="down", detail=str(exc))


async def _check_nvidia_nim() -> DependencyStatus:
    if not settings.NVIDIA_NIM_API_KEY:
        return DependencyStatus(name="nvidia_nim", status="down", detail="no API key")
    try:
        await _http_get(
            f"{settings.NVIDIA_NIM_ENDPOINT.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {settings.NVIDIA_NIM_API_KEY}"},
        )
        return DependencyStatus(name="nvidia_nim", status="up", detail="API reachable")
    except Exception as exc:
        return DependencyStatus(name="nvidia_nim", status="down", detail=str(exc))


async def _check_openrouter() -> DependencyStatus:
    if not settings.OPENROUTER_API_KEY:
        return DependencyStatus(name="openrouter", status="down", detail="no API key")
    try:
        await _http_get(
            f"{settings.OPENROUTER_ENDPOINT.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {settings.OPENROUTER_API_KEY}"},
        )
        return DependencyStatus(name="openrouter", status="up", detail="API reachable")
    except Exception as exc:
        return DependencyStatus(name="openrouter", status="down", detail=str(exc))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup & shutdown."""
    global redis_client, http_client

    # Startup
    logger.info("Starting Wayfarer API...")
    http_client = httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT)
    redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)

    # Ensure ChromaDB collections exist
    for name in vector_store.COLLECTIONS:
        try:
            col = vector_store._ensure_collection(name)
            logger.info("Collection '%s' ready (count=%d)", name, col.count())
        except Exception as exc:
            logger.warning("Collection '%s' init failed: %s", name, exc)

    # Warm up Ollama so the model is loaded into GPU before first request.
    # Without this, the first search call takes 20-30s on cold start and
    # hits the httpx timeout. Retry up to 3 times with backoff.
    if settings.LLM_PROVIDER == "ollama":
        for attempt in range(1, 4):
            try:
                await llm_router.embed("warm-up")
                logger.info("Ollama embedding model warmed up (attempt %d)", attempt)
                break
            except Exception as exc:
                logger.warning("Ollama warm-up attempt %d failed: %s", attempt, exc)
                if attempt < 3:
                    await asyncio.sleep(5 * attempt)

    yield

    # Shutdown
    logger.info("Shutting down...")
    await llm_router.aclose()
    if http_client:
        await http_client.aclose()
    if redis_client:
        await redis_client.aclose()


app = FastAPI(
    title="Wayfarer",
    description="AI-Powered Job Search Automation Platform",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow local frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health() -> HealthResponse:
    """Dependency health check."""
    results = await asyncio.gather(
        _check_chromadb(),
        _check_ollama(),
        _check_redis(),
        _check_nvidia_nim(),
        _check_openrouter(),
    )
    down = [r for r in results if r.status == "down"]
    return HealthResponse(
        status="degraded" if down else "ok",
        dependencies=list(results),
    )


# ---------------------------------------------------------------------------
# Stage router stubs (to be implemented in Phase 1–3)
# ---------------------------------------------------------------------------

@app.post("/api/v1/search", tags=["stage1"])
async def search(request: SearchRequest) -> SearchResponse:
    """Stage 1: web search agent with citation synthesis."""
    from .services.search_service import search as run_search_pipeline
    return await run_search_pipeline(request.query, request.max_sources)


@app.post("/api/v1/resume/check", response_model=ResumeCheckResponse, tags=["stage2"])
async def resume_check(
    resume_file: UploadFile = File(...),
    jd_text: str = Form(...),
) -> ResumeCheckResponse:
    """Stage 2: check a resume (PDF/DOCX) against a job description."""
    from .services import resume_store
    from .services.ats_checker import check_resume

    content = await resume_file.read()
    if not content:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Uploaded resume is empty")

    # Persist the upload and get a resume_id for later save
    resume_id, saved_path = resume_store.store_upload(
        content, resume_file.filename or "resume",
    )
    try:
        return await check_resume(str(saved_path), jd_text, resume_id=resume_id)
    except ValueError as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/resume/save", response_model=ResumeSaveResponse, tags=["stage2"])
async def resume_save(request: ResumeSaveRequest) -> ResumeSaveResponse:
    """Stage 2: save accepted redline suggestions as a new file or overwrite."""
    from .services.resume_saver import save_resume
    try:
        return await save_resume(
            resume_id=request.resume_id,
            accepted_suggestions=request.accepted_suggestions,
            mode=request.mode,
            confirm_overwrite=request.confirm_overwrite,
        )
    except ValueError as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/jobs/match", response_model=JobMatchResponse, tags=["stage3"])
async def jobs_match(
    resume_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    location_mode: LocationMode = LocationMode.SPECIFIC_CITY,
    cities: str = Query(default="", description="Comma-separated cities"),
    remote_ok: bool = False,
    test: bool = Query(default=False, description="Return sample data for UI testing"),
) -> JobMatchResponse:
    """Stage 3: rank live postings by fit against a resume."""
    from datetime import datetime, timezone
    from .models.schemas import (
        AggregateGap, JobMatch as JM, LocationMatch as LM,
    )

    # Mock data for testing the UI when board APIs are unavailable
    if test:
        now = datetime.now(timezone.utc)
        mock_matches = [
            JM(job_id="mock-1", title="Senior ML Engineer", company="Acme AI", source="bluedoor",
               location="Bengaluru", match_score=0.87, location_match=LM.EXACT,
               top_gaps=["kubernetes", "rust"], apply_url="https://example.com/jobs/1"),
            JM(job_id="mock-2", title="GenAI Platform Engineer", company="NeuralOps", source="linkedin",
               location="Remote (India)", match_score=0.82, location_match=LM.REMOTE,
               top_gaps=["terraform"], apply_url="https://example.com/jobs/2",
               flags=["unknown_company"]),
            JM(job_id="mock-3", title="RAG Systems Engineer", company="DeepSearch", source="bluedoor",
               location="Hybrid — Bengaluru", match_score=0.79, location_match=LM.EXACT,
               top_gaps=["graph databases", "spark"], apply_url="https://example.com/jobs/3"),
            JM(job_id="mock-4", title="AI Research Engineer", company="Inference Labs", source="linkedin",
               location="Remote", match_score=0.71, location_match=LM.REMOTE,
               top_gaps=["pytorch lightning", "WandB"], apply_url="https://example.com/jobs/4"),
            JM(job_id="mock-5", title="NLP Engineer", company="Syntax AI", source="bluedoor",
               location="Pune, India", match_score=0.64, location_match=LM.RELOCATION_REQUIRED,
               top_gaps=["transformers", "hugging face"], apply_url="https://example.com/jobs/5"),
        ]
        return JobMatchResponse(
            matches=mock_matches[:limit],
            aggregate_gaps=[
                AggregateGap(skill="kubernetes", missing_in_pct=0.6),
                AggregateGap(skill="pytorch lightning", missing_in_pct=0.4),
                AggregateGap(skill="terraform", missing_in_pct=0.2),
            ],
        )

    from .services.job_matcher import match_jobs
    from .models.schemas import LocationPreference

    location_pref = LocationPreference(
        mode=location_mode,
        cities=[c.strip() for c in cities.split(",") if c.strip()],
        remote_ok=remote_ok,
    )
    try:
        return await match_jobs(resume_id, location_pref, limit)
    except ValueError as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Background refresh — FR3.9 (pipeline integrity)
# ---------------------------------------------------------------------------

@app.post("/api/v1/jobs/refresh", tags=["stage3"])
async def jobs_refresh():
    """Re-fetch postings from all boards and store in ChromaDB job_postings.

    Intended to be called periodically (e.g. via a cron job or background
    task queue). Stores postings in ChromaDB so future /jobs/match calls
    can read from the local store instead of hitting external APIs.
    """
    from .services.job_matcher import _discover_postings, _dedupe_postings, _normalise_postings, _drop_stale
    from .config import settings
    from datetime import datetime, timezone

    postings = await _discover_postings()
    postings = _dedupe_postings(postings)
    postings = _normalise_postings(postings)
    postings = _drop_stale(postings)

    # Store in ChromaDB for fast retrieval on /jobs/match
    if postings:
        docs = [
            f"{p.title} | {p.company} | {p.location} | {p.remote_type}"
            for p in postings
        ]
        ids = [p.id[:64] for p in postings]  # ChromaDB limits ID length
        metadatas = [
            {
                "title": p.title[:200],
                "company": p.company[:200],
                "location": p.location[:200],
                "remote_type": p.remote_type,
                "source": p.source,
                "fetched_at": p.fetched_at.isoformat(),
                "url": p.url[:500] if p.url else "",
            }
            for p in postings
        ]
        from .vector_store import store
        store.upsert(settings.JOB_POSTINGS_COLLECTION, docs, ids=ids, metadatas=metadatas)

    return {
        "refreshed": len(postings),
        "by_source": {
            s: sum(1 for p in postings if p.source == s)
            for s in set(p.source for p in postings)
        } if postings else {},
    }


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)