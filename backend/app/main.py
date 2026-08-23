"""Wayfarer FastAPI application entry point.

Exposes:
- GET /health  — dependency health check (Qdrant, Ollama, Redis)
- Stage 1: /api/v1/search
- Stage 2: /api/v1/resume
- Stage 3: /api/v1/jobs
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .context import RequestOverrides, request_overrides_var
from .exceptions import WayfarerError
from .routers import health, stage1, stage2, stage3
from .services import jobs_queue

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Global clients
redis_client: aioredis.Redis | None = None
refresh_worker_task: asyncio.Task | None = None
refresh_stop_event: asyncio.Event | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client, refresh_worker_task, refresh_stop_event
    # Startup
    try:
        redis_client = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=5,
        )
        await redis_client.ping()
        logger.info("Connected to Redis at %s", settings.REDIS_URL)
    except Exception as exc:
        logger.warning("Redis connection failed (%s); running without queue/cache", exc)
        redis_client = None

    # Start the Redis-backed refresh worker
    refresh_stop_event = asyncio.Event()
    jobs_queue.redis_client = redis_client
    refresh_worker_task = asyncio.create_task(
        jobs_queue.run_worker(redis_client, stop_event=refresh_stop_event)
    )

    yield

    # Shutdown
    if refresh_worker_task:
        if refresh_stop_event:
            refresh_stop_event.set()
        refresh_worker_task.cancel()
        try:
            await refresh_worker_task
        except asyncio.CancelledError:
            pass

    if redis_client:
        await redis_client.aclose()
        redis_client = None


app = FastAPI(
    title="Wayfarer",
    description="AI-Powered Job Search Automation Platform",
    version="0.1.0",
    lifespan=lifespan,
)


@app.exception_handler(WayfarerError)
async def wayfarer_exception_handler(request: Request, exc: WayfarerError):
    """Centralized error handling for domain-specific exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message},
    )


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    """Convert generic ValueErrors from services into 400 responses."""
    return JSONResponse(
        status_code=400,
        content={"detail": str(exc)},
    )


# Include routers
app.include_router(health.router)
app.include_router(stage1.router)
app.include_router(stage2.router)
app.include_router(stage3.router)


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
