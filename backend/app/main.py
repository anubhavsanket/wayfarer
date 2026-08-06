"""Wayfarer FastAPI application entry point.

Exposes:
- GET /health  — dependency health check (ChromaDB, Ollama, Redis)
- Stage 1: /api/v1/search
- Stage 2: /api/v1/resume (check, save, primary resume management)
- Stage 3: /api/v1/jobs
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from contextvars import ContextVar

import httpx
import redis.asyncio as redis
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .config import settings
from .llm_router import router as llm_router
from .vector_store import store as vector_store
from .models.schemas import (
    DependencyStatus,
    HealthResponse,
    JobMatchResponse,
    LocationMode,
    ResumeCheckResponse,
    ResumePrimaryInfo,
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

# Context variable for per-request model override (set by middleware from headers)
request_model_override: ContextVar[str | None] = ContextVar("model_override", default=None)

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


@app.middleware("http")
async def read_model_override(request, call_next):
    """Read X-Ollama-Model header and set it in context for the LLM router."""
    model = request.headers.get("X-Ollama-Model")
    token = request_model_override.set(model or None)
    try:
        response = await call_next(request)
        return response
    finally:
        request_model_override.reset(token)


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
    resume_file: UploadFile | None = File(None),
    jd_text: str = Form(...),
) -> ResumeCheckResponse:
    """Stage 2: check a resume against a job description.

    FR2.10 (§8.6): If ``resume_file`` is omitted, checks the user's
    primary resume from Settings.  If a file is provided, it's treated
    as a one-off variant check — scored and redlined, but never silently
    replaces the primary.
    """
    from .services import resume_store
    from .services.ats_checker import check_resume

    if resume_file is not None:
        # Variant check — upload and check against the provided file
        content = await resume_file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Uploaded resume is empty")
        resume_id, saved_path = resume_store.store_upload(
            content, resume_file.filename or "resume",
        )
    else:
        # Primary resume check — resolve from the primary index
        resume_id = resume_store.get_primary_id()
        if not resume_id:
            raise HTTPException(
                status_code=400,
                detail="No resume file uploaded and no primary resume set. "
                       "Upload a resume in Settings first.",
            )
        saved_path = resume_store.original_file_path(resume_id)
        if saved_path is None:
            raise HTTPException(
                status_code=404,
                detail=f"Primary resume file not found on disk for {resume_id}.",
            )

    try:
        return await check_resume(str(saved_path), jd_text, resume_id=resume_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/resume/save", response_model=ResumeSaveResponse, tags=["stage2"])
async def resume_save(request: ResumeSaveRequest) -> ResumeSaveResponse:
    """Stage 2: save accepted redline suggestions as a new file, overwrite, or set as primary."""
    from .services.resume_saver import save_resume
    try:
        return await save_resume(
            resume_id=request.resume_id,
            accepted_suggestions=request.accepted_suggestions,
            mode=request.mode,
            confirm_overwrite=request.confirm_overwrite,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Primary resume management (§8.6 FR2.9)
# ---------------------------------------------------------------------------

@app.get("/api/v1/resume/primary", response_model=ResumePrimaryInfo, tags=["stage2"])
async def get_primary_resume() -> ResumePrimaryInfo:
    """Return the current primary resume's metadata, or 404 if none is set."""
    from .services import resume_store
    info = resume_store.get_primary_info()
    if info is None:
        raise HTTPException(status_code=404, detail="No primary resume is set. Upload one in Settings.")
    return ResumePrimaryInfo(**info)


@app.post("/api/v1/resume/primary", response_model=ResumePrimaryInfo, tags=["stage2"])
async def set_primary_resume(
    resume_file: UploadFile = File(...),
) -> ResumePrimaryInfo:
    """Upload a resume and set it as the primary resume.

    FR2.9 (§8.6): Settings page upload slot.  Stores the file, parses it,
    and marks it as primary so /resume/check and /jobs/match can resolve it.
    """
    from .services import resume_store
    from .services.resume_parser import parse_resume

    content = await resume_file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded resume is empty")

    # Store the file and get a resume_id
    resume_id, saved_path = resume_store.store_upload(
        content, resume_file.filename or "resume",
    )

    # Parse and persist for downstream matching (/jobs/match needs bullets)
    try:
        parsed = parse_resume(str(saved_path))
        resume_store.save_parsed(resume_id, parsed)

        # §12.1: Extract resume entity graph for token-efficient matching
        from .core.resume_graph import extract_resume_graph
        skills_text = "\n".join(parsed.sections.get("skills", []))
        graph = extract_resume_graph(
            [{"section": b.section, "text": b.text} for b in parsed.bullets],
            skills_raw=skills_text,
        )
        resume_store.save_graph(resume_id, graph.to_dict())
    except ValueError as exc:
        # Parser explicitly rejected the file (e.g. image-based PDF) —
        # surface the error so the user can try DOCX instead.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("Primary resume parse failed: %s (storing raw only)", exc)

    # Set as primary
    resume_store.set_primary(resume_id)

    info = resume_store.get_primary_info()
    return ResumePrimaryInfo(**info)


# ---------------------------------------------------------------------------
# Model configuration (§12.5 user-configurable)
# ---------------------------------------------------------------------------

class ModelConfig(BaseModel):
    ollama_model: str = Field(default="lfm2.5-thinking", description="Ollama model for all tiers")


@app.get("/api/v1/config/model", tags=["config"])
async def get_model_config() -> ModelConfig:
    """Return the current model configuration."""
    return ModelConfig(ollama_model=settings.OLLAMA_MODEL)


@app.post("/api/v1/config/model", tags=["config"])
async def set_model_config(config: ModelConfig) -> dict:
    """Update the model configuration at runtime.

    The change applies immediately but does not persist across restarts.
    To persist, set OLLAMA_MODEL in .env.
    """
    settings.OLLAMA_MODEL = config.ollama_model
    logger.info("Model updated to: %s", config.ollama_model)
    return {"status": "ok", "ollama_model": config.ollama_model}


@app.get("/api/v1/jobs/match", response_model=JobMatchResponse, tags=["stage3"])
async def jobs_match(
    resume_id: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    location_mode: LocationMode = LocationMode.SPECIFIC_CITY,
    cities: str = Query(default="", description="Comma-separated cities"),
    remote_ok: bool = False,
    fresher_only: bool = Query(default=False, description="Filter to fresher/junior roles only (v1.1)"),
    max_age_days: int = Query(default=30, ge=1, le=365, description="Max age of job postings in days"),
    min_score: float = Query(default=0.0, ge=0.0, le=1.0, description="Minimum match score (0-1) to include"),
    sources: str = Query(default="", description="Comma-separated source names to include (empty = all)"),
    test: bool = Query(default=False, description="Return sample data for UI testing"),
) -> JobMatchResponse:
    """Stage 3: rank live postings by fit against a resume.

    FR2.12 (§8.6): ``resume_id`` is optional — when omitted, matches
    against the user's current primary resume.
    """
    from datetime import datetime, timezone
    from .models.schemas import (
        AggregateGap, JobMatch as JM, LocationMatch as LM,
    )

    # Mock data for testing the UI when board APIs are unavailable
    if test:
        from .models.schemas import LocationPreference
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
        # Apply filters to mock data so the UI filters actually work
        filtered = mock_matches
        if min_score > 0:
            filtered = [m for m in filtered if m.match_score >= min_score]
        location_pref = LocationPreference(
            mode=location_mode,
            cities=[c.strip() for c in cities.split(",") if c.strip()],
            remote_ok=remote_ok,
        )
        from .services.job_matcher import _apply_location_preference
        filtered = _apply_location_preference(filtered, location_pref)
        return JobMatchResponse(
            matches=filtered[:limit],
            aggregate_gaps=[
                AggregateGap(skill="kubernetes", missing_in_pct=0.6),
                AggregateGap(skill="pytorch lightning", missing_in_pct=0.4),
                AggregateGap(skill="terraform", missing_in_pct=0.2),
            ],
        )

    # FR2.12: resolve primary resume if resume_id is not provided
    if not resume_id:
        from .services import resume_store
        resume_id = resume_store.get_primary_id()
        if not resume_id:
            raise HTTPException(
                status_code=400,
                detail="No resume_id provided and no primary resume set. "
                       "Upload a resume in Settings or provide a resume_id.",
            )

    from .services.job_matcher import match_jobs
    from .models.schemas import LocationPreference

    location_pref = LocationPreference(
        mode=location_mode,
        cities=[c.strip() for c in cities.split(",") if c.strip()],
        remote_ok=remote_ok,
    )
    source_list = [s.strip() for s in sources.split(",") if s.strip()] if sources else []
    try:
        return await match_jobs(
            resume_id, location_pref, limit,
            fresher_only=fresher_only,
            max_age_days=max_age_days,
            min_score=min_score,
            sources=source_list,
        )
    except ValueError as exc:
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