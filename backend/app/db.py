"""SQLite-backed application tracker (saved jobs + applications).

Lightweight relational store for the job-search pipeline state that doesn't
belong in a vector DB: which postings you saved, which you applied to, and the
status of each application. Persisted at ``settings.TRACKER_DB_PATH`` and
volume-mounted so state survives container recreation.

Single-user design: one shared connection guarded by a threading lock. All DB
calls go through ``asyncio.to_thread`` from routers so they never block the
event loop.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime, timezone

from .config import settings

logger = logging.getLogger(__name__)

# Application lifecycle states
APP_STATUSES = ("applied", "interview", "offer", "rejected")

_conn: sqlite3.Connection | None = None
_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db() -> None:
    """Open the SQLite connection and create tables if needed. Call once at startup."""
    global _conn
    import os
    os.makedirs(os.path.dirname(settings.TRACKER_DB_PATH) or ".", exist_ok=True)
    with _lock:
        if _conn is not None:
            return
        _conn = sqlite3.connect(
            settings.TRACKER_DB_PATH,
            check_same_thread=False,
        )
        _conn.row_factory = sqlite3.Row
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS saved_jobs (
                job_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                apply_url TEXT,
                source TEXT,
                location TEXT,
                match_score REAL DEFAULT 0,
                saved_at TEXT NOT NULL
            )
            """
        )
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT UNIQUE,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                apply_url TEXT,
                source TEXT,
                location TEXT,
                match_score REAL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'applied',
                date_applied TEXT NOT NULL,
                notes TEXT DEFAULT '',
                resume_id TEXT
            )
            """
        )
        _conn.commit()
        logger.info("Tracker DB initialised at %s", settings.TRACKER_DB_PATH)


def close_db() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None


def _get_conn() -> sqlite3.Connection:
    if _conn is None:
        init_db()
    assert _conn is not None
    return _conn


# ---------------------------------------------------------------------------
# Saved jobs
# ---------------------------------------------------------------------------

def list_saved() -> list[dict]:
    with _lock:
        rows = _get_conn().execute(
            "SELECT * FROM saved_jobs ORDER BY saved_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_saved(job_id: str) -> dict | None:
    with _lock:
        row = _get_conn().execute(
            "SELECT * FROM saved_jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
    return dict(row) if row else None


def save_job(job: dict) -> dict:
    now = _now_iso()
    with _lock:
        conn = _get_conn()
        conn.execute(
            """
            INSERT OR REPLACE INTO saved_jobs
                (job_id, title, company, apply_url, source, location, match_score, saved_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job["job_id"], job["title"], job["company"], job.get("apply_url"),
                job.get("source"), job.get("location"), job.get("match_score", 0.0), now,
            ),
        )
        conn.commit()
    res = dict(job)
    res["saved_at"] = now
    return res


def is_saved(job_id: str) -> bool:
    return get_saved(job_id) is not None


def unsave_job(job_id: str) -> bool:
    with _lock:
        cur = _get_conn().execute("DELETE FROM saved_jobs WHERE job_id = ?", (job_id,))
        _get_conn().commit()
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

def list_applications() -> list[dict]:
    with _lock:
        rows = _get_conn().execute(
            "SELECT * FROM applications ORDER BY date_applied DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_application(job_id: str) -> dict | None:
    with _lock:
        row = _get_conn().execute(
            "SELECT * FROM applications WHERE job_id = ?", (job_id,)
        ).fetchone()
    return dict(row) if row else None


def create_application(job: dict) -> dict:
    now = _now_iso()
    with _lock:
        conn = _get_conn()
        conn.execute(
            """
            INSERT OR IGNORE INTO applications
                (job_id, title, company, apply_url, source, location, match_score,
                 status, date_applied, notes, resume_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'applied', ?, '', ?)
            """,
            (
                job["job_id"], job["title"], job["company"], job.get("apply_url"),
                job.get("source"), job.get("location"), job.get("match_score", 0.0),
                now, job.get("resume_id"),
            ),
        )
        conn.commit()
    return get_application(job["job_id"]) or {}


def update_application(job_id: str, status: str | None = None, notes: str | None = None) -> dict | None:
    existing = get_application(job_id)
    if existing is None:
        return None
    if status is not None:
        if status not in APP_STATUSES:
            raise ValueError(
                f"Invalid status '{status}'. Must be one of: {', '.join(APP_STATUSES)}"
            )
        existing["status"] = status
    if notes is not None:
        existing["notes"] = notes
    with _lock:
        conn = _get_conn()
        conn.execute(
            "UPDATE applications SET status = ?, notes = ? WHERE job_id = ?",
            (existing["status"], existing["notes"], job_id),
        )
        conn.commit()
    return existing


def delete_application(job_id: str) -> bool:
    with _lock:
        cur = _get_conn().execute("DELETE FROM applications WHERE job_id = ?", (job_id,))
        _get_conn().commit()
        return cur.rowcount > 0
