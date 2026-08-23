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
from fastapi import FastAPI, File, Form, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .context import RequestOverrides, get_request_overrides, request_overrides_var
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

# Background refresh worker (Redis job queue)
refresh_worker_task: asyncio.Task | None = None
refresh_stop_event: asyncio.Event | None = None


async def _check_qdrant() -> DependencyStatus:
    try:
        await asyncio.to_thread(vector_store._client.get_collections)
        return DependencyStatus(name="qdrant", status="up", detail="connected")
    except Exception as exc:
        return DependencyStatus(name="qdrant", status="down", detail=str(exc))


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
    overrides = get_request_overrides()
    api_key = (overrides.nvidia_api_key if overrides and overrides.nvidia_api_key else settings.NVIDIA_NIM_API_KEY)
    endpoint = (overrides.nvidia_endpoint if overrides and overrides.nvidia_endpoint else settings.NVIDIA_NIM_ENDPOINT)
    if not api_key:
        return DependencyStatus(name="nvidia_nim", status="down", detail="no API key")
    try:
        await _http_get(
            f"{endpoint.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        return DependencyStatus(name="nvidia_nim", status="up", detail="API reachable")
    except Exception as exc:
        return DependencyStatus(name="nvidia_nim", status="down", detail=str(exc))


async def _check_openrouter() -> DependencyStatus:
    overrides = get_request_overrides()
    api_key = (overrides.openrouter_api_key if overrides and overrides.openrouter_api_key else settings.OPENROUTER_API_KEY)
    endpoint = (overrides.openrouter_endpoint if overrides and overrides.openrouter_endpoint else settings.OPENROUTER_ENDPOINT)
    if not api_key:
        return DependencyStatus(name="openrouter", status="down", detail="no API key")
    try:
        await _http_get(
            f"{endpoint.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        return DependencyStatus(name="openrouter", status="up", detail="API reachable")
    except Exception as exc:
        return DependencyStatus(name="openrouter", status="down", detail=str(exc))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup & shutdown."""
    global redis_client, http_client, refresh_worker_task, refresh_stop_event

    # Startup
    logger.info("Starting Wayfarer API...")
    http_client = httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT)

    # Create Redis client with a connection timeout so DNS resolution of
    # the Docker hostname ('redis') doesn't block startup when running locally.
    try:
        redis_client = await asyncio.wait_for(
            asyncio.to_thread(
                redis.from_url, settings.REDIS_URL, decode_responses=True
            ),
            timeout=5.0,
        )
    except (asyncio.TimeoutError, Exception) as exc:
        logger.warning("Redis client creation failed (%s); running without Redis", exc)
        redis_client = None

    # Initialise Redis cache (LLM responses, embeddings, pages, queries)
    from .utils.cache import init_cache
    await init_cache()

    # Initialise LlamaIndex RAG settings
    from .core.rag_engine import init_rag_settings
    init_rag_settings()

    # Ensure Qdrant collections exist
    for name in vector_store.COLLECTIONS:
        try:
            vector_store._ensure_collection(name)
            logger.info("Collection '%s' ready", name)
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

    # Start the Redis-backed refresh worker (consumes /jobs/refresh jobs)
    refresh_stop_event = asyncio.Event()
    from .services.jobs_queue import run_worker
    refresh_worker_task = asyncio.create_task(
        run_worker(redis_client, stop_event=refresh_stop_event)
    )

    yield

    # Shutdown
    logger.info("Shutting down...")
    if refresh_worker_task:
        if refresh_stop_event:
            refresh_stop_event.set()
        refresh_worker_task.cancel()
        try:
            await refresh_worker_task
        except asyncio.CancelledError:
            pass
    from .utils.cache import close_cache
    await close_cache()
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

# ---------------------------------------------------------------------------
# Request-scoped header overrides middleware
# ---------------------------------------------------------------------------


@app.middleware("http")
async def extract_header_overrides_middleware(request: Request, call_next):
    """Extract X-* request headers from frontend and populate request_overrides_var."""
    headers = request.headers
    overrides = RequestOverrides(
        llm_provider=headers.get("x-llm-provider") or None,
        nvidia_api_key=headers.get("x-nvidia-api-key") or None,
        nvidia_endpoint=headers.get("x-nvidia-endpoint") or None,
        openrouter_api_key=headers.get("x-openrouter-api-key") or None,
        openrouter_endpoint=headers.get("x-openrouter-endpoint") or None,
        ollama_endpoint=headers.get("x-ollama-endpoint") or None,
        lmstudio_endpoint=headers.get("x-lmstudio-endpoint") or None,
        lmstudio_model=headers.get("x-lmstudio-model") or None,
        custom_endpoint=headers.get("x-custom-endpoint") or None,
        custom_api_key=headers.get("x-custom-api-key") or None,
        custom_model=headers.get("x-custom-model") or None,
        tavily_api_key=headers.get("x-tavily-api-key") or None,
        brave_api_key=headers.get("x-brave-api-key") or None,
        bluedoor_api_key=headers.get("x-bluedoor-api-key") or None,
    )
    token = request_overrides_var.set(overrides)
    try:
        return await call_next(request)
    finally:
        request_overrides_var.reset(token)


# CORS — must be added AFTER the custom middleware above so it runs outermost.
# FastAPI stacks add_middleware() calls in reverse: last added = outermost.
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
        _check_qdrant(),
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
    resume_id: str | None = Form(None),
    jd_text: str = Form(...),
) -> ResumeCheckResponse:
    """Stage 2: check a resume (PDF/DOCX) against a job description.

    Supports either:
    1. Uploading a new file (resume_file)
    2. Referencing a previously uploaded resume (resume_id)
    """
    from .services import resume_store
    from .services.ats_checker import check_resume
    from fastapi import HTTPException

    if resume_file:
        content = await resume_file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Uploaded resume is empty")

        # Persist the upload and get a resume_id for later save
        resume_id, saved_path = resume_store.store_upload(
            content, resume_file.filename or "resume",
        )
    elif resume_id:
        saved_path = resume_store.original_file_path(resume_id)
        if not saved_path:
            raise HTTPException(status_code=404, detail=f"Resume {resume_id} not found")
    else:
        raise HTTPException(status_code=400, detail="Either resume_file or resume_id must be provided")

    try:
        return await check_resume(str(saved_path), jd_text, resume_id=resume_id)
    except ValueError as exc:
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
    fresher_only: bool = Query(default=False, description="Filter to fresher/junior roles only (v1.1)"),
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
        return await match_jobs(resume_id, location_pref, limit, fresher_only=fresher_only)
    except ValueError as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Background refresh — FR3.9 (pipeline integrity)
# ---------------------------------------------------------------------------

@app.post("/api/v1/jobs/refresh", tags=["stage3"])
async def jobs_refresh(background: bool = Query(default=False, description="Run asynchronously via the Redis job queue")):
    """Re-fetch postings from all boards and store in ChromaDB job_postings.

    Two modes:
    - ``background=false`` (default): runs synchronously, returning the
      refreshed counts in the response body.
    - ``background=true``: enqueues a job on the Redis-backed queue and
      returns immediately with ``job_id`` / ``status="queued"``. Track
      progress via ``GET /api/v1/jobs/refresh/status/{job_id}``.
    """
    from .services.jobs_queue import enqueue_refresh

    if redis_client is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="Redis unavailable")

    if background:
        job_id = await enqueue_refresh(redis_client)
        return {"job_id": job_id, "status": "queued"}

    # Synchronous path — ran by a client that wants the result inline
    from .services.job_matcher import _discover_postings, _dedupe_postings, _normalise_postings, _drop_stale
    from .config import settings

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


@app.get("/api/v1/jobs/refresh/status/{job_id}", tags=["stage3"])
async def jobs_refresh_status(job_id: str) -> dict:
    """Poll the status of a background refresh job (see /jobs/refresh)."""
    from .services.jobs_queue import get_job_status

    if redis_client is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="Redis unavailable")

    status = await get_job_status(redis_client, job_id)
    if status is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Unknown job_id: {job_id}")
    return status


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)