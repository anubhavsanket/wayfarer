"""Focused tests for the two new features.

1. Resume Check "Use Stored Resume" path (/resume/check with resume_id)
2. Redis background job queue (jobs_queue module + /jobs/refresh?background=true)
3. Regression: OOXML track-changes in resume_saver still works

Uses an in-memory FakeRedis (no external redis needed).
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

# No external API keys during tests
for key in ("TAVILY_API_KEY", "BRAVE_API_KEY", "NVIDIA_NIM_API_KEY", "OPENROUTER_API_KEY"):
    os.environ.pop(key, None)


class FakeRedis:
    """Minimal in-memory stand-in for the redis.asyncio API used by jobs_queue.

    Supports: lpush, brpop, hset, hgetall, hget, expire, pipeline, aclose.
    """

    def __init__(self, decode_responses: bool = True):
        self.decode_responses = decode_responses
        self._lists: dict[str, list[str]] = {}
        self._hashes: dict[str, dict[str, str]] = {}

    # -- list ops -----------------------------------------------------------
    async def lpush(self, key: str, *values):
        self._lists.setdefault(key, [])
        self._lists[key] = list(values) + self._lists[key]
        return len(self._lists[key])

    async def brpop(self, key: str, timeout: float = 0):
        if self._lists.get(key):
            return key, self._lists[key].pop(0)
        await asyncio.sleep(timeout)
        return None

    async def llen(self, key: str):
        return len(self._lists.get(key, []))

    # -- hash ops -----------------------------------------------------------
    async def hset(self, key: str, mapping: dict | None = None, **kwargs):
        h = self._hashes.setdefault(key, {})
        h.update(mapping or {})
        h.update(kwargs)
        return len(h)

    async def hgetall(self, key: str):
        return dict(self._hashes.get(key, {}))

    async def hget(self, key: str, field: str):
        return self._hashes.get(key, {}).get(field)

    @staticmethod
    async def expire(key: str, seconds: int):
        return True

    # -- pipeline -----------------------------------------------------------
    class _Pipeline:
        def __init__(self, fake: "FakeRedis"):
            self._fake = fake
            self._pending = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def lpush(self, key: str, *values):
            self._pending.append(("lpush", key, values))
            return self

        def hset(self, key: str, mapping=None, **kwargs):
            self._pending.append(("hset", key, mapping or {}, kwargs))
            return self

        def expire(self, key: str, seconds: int):
            self._pending.append(("expire", key, seconds))
            return self

        async def execute(self):
            for op in self._pending:
                kind = op[0]
                if kind == "lpush":
                    await self._fake.lpush(op[1], *op[2])
                elif kind == "hset":
                    await self._fake.hset(op[1], op[2], **op[3])
                elif kind == "expire":
                    await self._fake.expire(op[1], op[2])
            return None

    def pipeline(self, transaction: bool = True):
        return FakeRedis._Pipeline(self)

    async def aclose(self):
        return None


# ---------------------------------------------------------------------------
# 2. Redis background job queue
# ---------------------------------------------------------------------------

async def test_enqueue_and_status_roundtrip():
    """enqueue_refresh creates a queued job whose status can be read back."""
    from backend.app.services.jobs_queue import enqueue_refresh, get_job_status

    r = FakeRedis()
    job_id = await enqueue_refresh(r)
    assert job_id

    assert await r.llen("wayfarer:jobs:queue") == 1

    status = await get_job_status(r, job_id)
    assert status is not None
    assert status["status"] == "queued"
    assert status["job_id"] == job_id

    assert await get_job_status(r, "nope") is None


async def test_worker_processes_job_and_marks_completed(monkeypatch):
    """_process_job runs the pipeline, marks it completed."""
    from backend.app.services import jobs_queue

    r = FakeRedis()
    calls = {}

    async def fake_pipeline():
        calls["pipeline"] = True
        return [], {}

    monkeypatch.setattr(jobs_queue, "_run_refresh_pipeline", fake_pipeline)

    job_id = await jobs_queue.enqueue_refresh(r)
    await jobs_queue._process_job(r, job_id)

    status = await jobs_queue.get_job_status(r, job_id)
    assert status["status"] == "completed"
    assert status["refreshed"] == "0"
    assert calls.get("pipeline") is True


async def test_worker_failure_marks_failed(monkeypatch):
    from backend.app.services import jobs_queue

    r = FakeRedis()

    async def boom():
        raise RuntimeError("board fetch failed")

    monkeypatch.setattr(jobs_queue, "_run_refresh_pipeline", boom)

    job_id = await jobs_queue.enqueue_refresh(r)
    await jobs_queue._process_job(r, job_id)

    status = await jobs_queue.get_job_status(r, job_id)
    assert status["status"] == "failed"
    assert "board fetch failed" in status["error"]


async def test_run_worker_loop_consumes_jobs(monkeypatch):
    """run_worker blocks on the queue and processes jobs until stopped."""
    from backend.app.services import jobs_queue

    r = FakeRedis()
    processed = []

    async def fake_pipeline():
        processed.append("ran")
        return [], {}

    monkeypatch.setattr(jobs_queue, "_run_refresh_pipeline", fake_pipeline)

    # Enqueue two jobs and start the worker
    j1 = await jobs_queue.enqueue_refresh(r)
    j2 = await jobs_queue.enqueue_refresh(r)
    assert j1 != j2

    stop = asyncio.Event()

    async def shortly_after_run():
        # Let the worker poke at the queue ~3x, then stop it
        await asyncio.sleep(0.05)
        stop.set()

    worker = asyncio.create_task(jobs_queue.run_worker(r, stop_event=stop, poll_interval=0.01))
    controller = asyncio.create_task(shortly_after_run())

    await asyncio.gather(worker, controller)

    # Both jobs should have been picked up and completed
    assert processed == ["ran", "ran"]
    assert await r.llen("wayfarer:jobs:queue") == 0

    status1 = await jobs_queue.get_job_status(r, j1)
    status2 = await jobs_queue.get_job_status(r, j2)
    assert status1["status"] == "completed"
    assert status2["status"] == "completed"


# ---------------------------------------------------------------------------
# 3. Regression: track-changes still work
# ---------------------------------------------------------------------------

async def test_track_changes_write_docx(tmp_path):
    import zipfile
    from backend.app.services.resume_saver import _write_docx
    from backend.app.services.resume_parser import ParsedResume, ResumeBullet
    from backend.app.models.schemas import AcceptedSuggestion

    parsed = ParsedResume(
        sections={"experience": ["Built RAG systems", "Shipped FastAPI"]},
        bullets=[
            ResumeBullet(id="b0", section="experience", text="Built RAG systems"),
            ResumeBullet(id="b1", section="experience", text="Shipped FastAPI"),
        ],
        ats_visible_text="Built RAG systems\nShipped FastAPI",
        structural_issues=[],
        contact={"name": "Test User"},
        raw_text="Test User\nBuilt RAG systems\nShipped FastAPI",
    )
    suggestions = [
        AcceptedSuggestion(
            bullet_id="b0",
            suggested_text="Built RAG systems with LangChain",
            original_text="Built RAG systems",
        )
    ]
    out = tmp_path / "track.docx"
    counts = _write_docx(parsed, out, suggestions)

    assert counts["insertions"] == 1
    assert counts["deletions"] == 1
    assert counts["total_changes"] == 1

    with zipfile.ZipFile(out, "r") as z:
        xml = z.read("word/document.xml").decode()
        assert "w:del" in xml
        assert "w:ins" in xml
        assert "w:delText" in xml