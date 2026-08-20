"""Redis-backed background job queue for ``POST /jobs/refresh``.

Solves the "synchronous refresh blocks the request" problem (FR3.9):

- ``enqueue_refresh()`` is the *producer*: it creates a ``job_id``, pushes it
  onto a Redis list (``wayfarer:jobs:queue``) and writes a status hash.
  The HTTP handler returns immediately with the ``job_id``.
- ``run_worker()`` is the *consumer*: a long-lived asyncio task started in
  the app lifespan. It ``BRPOP``s job ids, runs the discovery→dedup→normalise
  →drop-stale→store pipeline, and writes results back to the status hash.

Status is stored as a Redis hash per job::

    wayfarer:jobs:{job_id} ->
        status:    queued | running | completed | failed
        created_at, started_at, finished_at: ISO timestamps
        refreshed: int            (only on completion)
        by_source: JSON string    (only on completion)
        error:     str            (only on failure)

All job keys get a TTL so the hash can't grow unbounded (default 6h).
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

# Redis key layout
QUEUE_KEY = "wayfarer:jobs:queue"
JOB_KEY_PREFIX = "wayfarer:jobs:"
JOB_TTL_SECONDS = 6 * 3600  # keep completed job status for 6h


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _job_key(job_id: str) -> str:
    return f"{JOB_KEY_PREFIX}{job_id}"


async def enqueue_refresh(redis_client: Redis, force: bool = False) -> str:
    """Producer: create a job, push it onto the queue. Returns the job_id."""
    job_id = uuid.uuid4().hex[:12]
    async with redis_client.pipeline(transaction=True) as pipe:
        pipe.lpush(QUEUE_KEY, job_id)
        pipe.hset(_job_key(job_id), mapping={
            "status": "queued",
            "created_at": _now_iso(),
            "force": "1" if force else "0",
        })
        pipe.expire(_job_key(job_id), JOB_TTL_SECONDS)
        await pipe.execute()
    logger.info("Enqueued refresh job %s (force=%s)", job_id, force)
    return job_id


async def get_job_status(redis_client: Redis, job_id: str) -> dict | None:
    """Read the status hash for a job, or None if the job doesn't exist."""
    data = await redis_client.hgetall(_job_key(job_id))
    if not data:
        return None
    # Decode JSON fields for convenience
    for field in ("by_source",):
        if field in data and data[field]:
            try:
                data[field] = json.loads(data[field])
            except json.JSONDecodeError:
                pass
    data["job_id"] = job_id
    return data


async def _mark(redis_client: Redis, job_id: str, **fields) -> None:
    """Update status fields for a job."""
    async with redis_client.pipeline(transaction=True) as pipe:
        pipe.hset(_job_key(job_id), mapping=fields)
        pipe.expire(_job_key(job_id), JOB_TTL_SECONDS)
        await pipe.execute()


async def _run_refresh_pipeline() -> tuple[list, dict]:
    """Run the actual refresh work (discovery→dedup→normalise→store)."""
    from .job_matcher import (
        _discover_postings,
        _dedupe_postings,
        _normalise_postings,
        _drop_stale,
    )
    from ..config import settings
    from ..vector_store import store

    postings = await _discover_postings()
    postings = _dedupe_postings(postings)
    postings = _normalise_postings(postings)
    postings = _drop_stale(postings)

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
        store.upsert(settings.JOB_POSTINGS_COLLECTION, docs, ids=ids, metadatas=metadatas)

    by_source = {
        s: sum(1 for p in postings if p.source == s)
        for s in set(p.source for p in postings)
    } if postings else {}

    return postings, by_source


async def _process_job(redis_client: Redis, job_id: str) -> None:
    """Consumer side: execute a single queued job, writing status updates."""
    await _mark(redis_client, job_id, status="running", started_at=_now_iso())
    logger.info("Refresh job %s started", job_id)
    try:
        postings, by_source = await _run_refresh_pipeline()
        await _mark(
            redis_client,
            job_id,
            status="completed",
            finished_at=_now_iso(),
            refreshed=str(len(postings)),
            by_source=json.dumps(by_source),
        )
        logger.info("Refresh job %s completed: %d postings", job_id, len(postings))
    except Exception as exc:
        logger.exception("Refresh job %s failed: %s", job_id, exc)
        await _mark(
            redis_client,
            job_id,
            status="failed",
            finished_at=_now_iso(),
            error=str(exc)[:500],
        )


async def run_worker(
    redis_client: Redis,
    stop_event: asyncio.Event | None = None,
    poll_interval: float = 1.0,
) -> None:
    """Consumer: block on the queue and process jobs until stopped.

    Started as a background task in the app lifespan and cancelled on
    shutdown. Uses ``BRPOP`` with a timeout so the loop can observe the
    stop event promptly instead of blocking forever.
    """
    stop_event = stop_event or asyncio.Event()
    logger.info("Refresh worker started (queue=%s)", QUEUE_KEY)
    while not stop_event.is_set():
        try:
            result = await redis_client.brpop(QUEUE_KEY, timeout=poll_interval)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("Worker BRPOP failed: %s", exc)
            await asyncio.sleep(poll_interval)
            continue

        if result is None:
            continue  # timeout — loop and re-check stop_event

        _queue_key, job_id = result
        logger.info("Worker picked up job %s", job_id)
        try:
            await _process_job(redis_client, job_id)
        except asyncio.CancelledError:
            # Re-queue the job so it isn't lost on shutdown, then exit
            await redis_client.lpush(QUEUE_KEY, job_id)
            break
        except Exception as exc:
            logger.error("Worker crashed processing %s: %s", job_id, exc)
    logger.info("Refresh worker stopped")
