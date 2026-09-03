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
import time
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar

import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import db
from .config import settings
from .context import RequestOverrides, request_overrides_var
from .exceptions import WayfarerError
from .routers import auth, health, stage1, stage2, stage3, tracker
from .services import jobs_queue
from .utils.cache import set_redis as cache_set_redis

# Per-request correlation id, surfaced in log lines.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIdFilter(logging.Filter):
    """Add the current request id to every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - [%(request_id)s] - %(message)s",
)
for _handler in logging.root.handlers:
    if not any(isinstance(f, RequestIdFilter) for f in _handler.filters):
        _handler.addFilter(RequestIdFilter())
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

    # Share the single Redis connection with the cache layer.
    cache_set_redis(redis_client)

    # Start the Redis-backed refresh worker (only if Redis is available).
    refresh_stop_event = asyncio.Event()
    jobs_queue.redis_client = redis_client
    if redis_client is not None:
        refresh_worker_task = asyncio.create_task(
            jobs_queue.run_worker(redis_client, stop_event=refresh_stop_event)
        )
    else:
        logger.warning("Redis unavailable; background refresh worker not started")

    # Initialise the SQLite tracker DB.
    try:
        db.init_db()
    except Exception as exc:
        logger.error("Tracker DB initialisation failed (%s)", exc)

    yield

    # Shutdown
    db.close_db()
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
        # The cache layer's lazy connection is only used when the shared
        # client was unavailable; nothing extra to close here.


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
app.include_router(auth.router)
app.include_router(stage1.router)
app.include_router(stage2.router)
app.include_router(stage3.router)
app.include_router(tracker.router)


# ---------------------------------------------------------------------------
# Request-ID + timing middleware (outermost request logging)
# ---------------------------------------------------------------------------


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """Assign a request id and log method/path/status/duration for correlation."""
    rid = uuid.uuid4().hex[:12]
    request_id_var.set(rid)
    start = time.perf_counter()
    try:
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "%s %s -> %s (%.0f ms)",
            request.method, request.url.path, response.status_code, duration_ms,
        )
        return response
    except Exception:
        duration_ms = (time.perf_counter() - start) * 1000
        logger.exception("%s %s failed after %.0f ms", request.method, request.url.path, duration_ms)
        raise


# ---------------------------------------------------------------------------
# Request-scoped header overrides middleware
# ---------------------------------------------------------------------------


@app.middleware("http")
async def extract_header_overrides_middleware(request: Request, call_next):
    """Extract X-* request headers and per-user decrypted settings to populate request_overrides_var."""
    headers = request.headers
    user_settings: dict[str, Any] = {}

    auth_header = headers.get("authorization") or ""
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        from .core.auth import decode_access_token
        from .db import get_user_settings
        payload = decode_access_token(token)
        if payload and "sub" in payload:
            user_settings = get_user_settings(payload["sub"])

    overrides = RequestOverrides(
        llm_provider=headers.get("x-llm-provider") or user_settings.get("llm_provider") or None,
        nvidia_api_key=headers.get("x-nvidia-api-key") or user_settings.get("nvidia_api_key") or None,
        nvidia_endpoint=headers.get("x-nvidia-endpoint") or user_settings.get("nvidia_endpoint") or None,
        openrouter_api_key=headers.get("x-openrouter-api-key") or user_settings.get("openrouter_api_key") or None,
        openrouter_endpoint=headers.get("x-openrouter-endpoint") or user_settings.get("openrouter_endpoint") or None,
        ollama_endpoint=headers.get("x-ollama-endpoint") or user_settings.get("ollama_endpoint") or None,
        lmstudio_endpoint=headers.get("x-lmstudio-endpoint") or user_settings.get("lmstudio_endpoint") or None,
        lmstudio_model=headers.get("x-lmstudio-model") or user_settings.get("lmstudio_model") or None,
        custom_endpoint=headers.get("x-custom-endpoint") or user_settings.get("custom_endpoint") or None,
        custom_api_key=headers.get("x-custom-api-key") or user_settings.get("custom_api_key") or None,
        custom_model=headers.get("x-custom-model") or user_settings.get("custom_model") or None,
        tavily_api_key=headers.get("x-tavily-api-key") or user_settings.get("tavily_api_key") or None,
        brave_api_key=headers.get("x-brave-api-key") or user_settings.get("brave_api_key") or None,
        bluedoor_api_key=headers.get("x-bluedoor-api-key") or user_settings.get("bluedoor_api_key") or None,
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
