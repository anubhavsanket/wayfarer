"""SQLite-backed multi-tenant storage (users, encrypted settings, tracker).

Lightweight relational store for user identity, encrypted API keys, and pipeline state.
Persisted at ``settings.TRACKER_DB_PATH`` and volume-mounted so state survives container recreation.

Guarded by a threading lock. All DB calls go through ``asyncio.to_thread`` from routers.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

from .config import settings
from .utils.crypto import encrypt_text, decrypt_text

logger = logging.getLogger(__name__)

# Application lifecycle states
APP_STATUSES = ("applied", "interview", "offer", "rejected")

_conn: sqlite3.Connection | None = None
_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db() -> None:
    """Open the SQLite connection and create tables/columns if needed. Call once at startup."""
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

        # ── Tables ──────────────────────────────────────────────────────
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                name TEXT,
                picture TEXT,
                created_at TEXT NOT NULL,
                last_login TEXT NOT NULL
            )
            """
        )
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id TEXT PRIMARY KEY,
                encrypted_settings TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
            """
        )
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS saved_jobs (
                job_id TEXT NOT NULL,
                user_id TEXT NOT NULL DEFAULT 'local',
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                apply_url TEXT,
                source TEXT,
                location TEXT,
                match_score REAL DEFAULT 0,
                saved_at TEXT NOT NULL,
                PRIMARY KEY (job_id, user_id)
            )
            """
        )
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                user_id TEXT NOT NULL DEFAULT 'local',
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                apply_url TEXT,
                source TEXT,
                location TEXT,
                match_score REAL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'applied',
                date_applied TEXT NOT NULL,
                notes TEXT DEFAULT '',
                resume_id TEXT,
                UNIQUE (job_id, user_id)
            )
            """
        )

        # ── Migrations (add user_id column if upgrading existing DB) ───
        try:
            cur = _conn.execute("PRAGMA table_info(saved_jobs)")
            cols = [r["name"] for r in cur.fetchall()]
            if "user_id" not in cols:
                _conn.execute("ALTER TABLE saved_jobs ADD COLUMN user_id TEXT NOT NULL DEFAULT 'local'")
        except Exception as exc:
            logger.debug("Migration for saved_jobs failed or unneeded: %s", exc)

        try:
            cur = _conn.execute("PRAGMA table_info(applications)")
            cols = [r["name"] for r in cur.fetchall()]
            if "user_id" not in cols:
                _conn.execute("ALTER TABLE applications ADD COLUMN user_id TEXT NOT NULL DEFAULT 'local'")
            if "updated_at" not in cols:
                _conn.execute("ALTER TABLE applications ADD COLUMN updated_at TEXT")
        except Exception as exc:
            logger.debug("Migration for applications failed or unneeded: %s", exc)

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
# User identity & settings management
# ---------------------------------------------------------------------------

def upsert_user(
    user_id: str,
    email: str,
    name: str | None = None,
    picture: str | None = None,
) -> dict:
    now = _now_iso()
    with _lock:
        conn = _get_conn()
        existing = conn.execute("SELECT created_at FROM users WHERE user_id = ?", (user_id,)).fetchone()
        created_at = existing["created_at"] if existing else now
        conn.execute(
            """
            INSERT OR REPLACE INTO users (user_id, email, name, picture, created_at, last_login)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, email, name or "", picture or "", created_at, now),
        )
        conn.commit()
    return get_user(user_id) or {}


def get_user(user_id: str) -> dict | None:
    with _lock:
        row = _get_conn().execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def save_user_settings(user_id: str, settings_dict: dict[str, Any]) -> None:
    """Encrypt and persist user-specific settings/keys."""
    now = _now_iso()
    raw_json = json.dumps(settings_dict)
    encrypted = encrypt_text(raw_json)
    with _lock:
        conn = _get_conn()
        conn.execute(
            """
            INSERT OR REPLACE INTO user_settings (user_id, encrypted_settings, updated_at)
            VALUES (?, ?, ?)
            """,
            (user_id, encrypted, now),
        )
        conn.commit()


def get_user_settings(user_id: str) -> dict[str, Any]:
    """Retrieve and decrypt user-specific settings/keys."""
    with _lock:
        row = _get_conn().execute(
            "SELECT encrypted_settings FROM user_settings WHERE user_id = ?", (user_id,)
        ).fetchone()
    if not row or not row["encrypted_settings"]:
        return {}
    decrypted = decrypt_text(row["encrypted_settings"])
    if not decrypted:
        return {}
    try:
        return json.loads(decrypted)
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Saved jobs (multi-tenant)
# ---------------------------------------------------------------------------

def list_saved(user_id: str = "local") -> list[dict]:
    with _lock:
        rows = _get_conn().execute(
            "SELECT * FROM saved_jobs WHERE user_id = ? ORDER BY saved_at DESC", (user_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_saved(job_id: str, user_id: str = "local") -> dict | None:
    with _lock:
        row = _get_conn().execute(
            "SELECT * FROM saved_jobs WHERE job_id = ? AND user_id = ?", (job_id, user_id)
        ).fetchone()
    return dict(row) if row else None


def save_job(job: dict, user_id: str = "local") -> dict:
    now = _now_iso()
    with _lock:
        conn = _get_conn()
        conn.execute(
            """
            INSERT OR REPLACE INTO saved_jobs
                (job_id, user_id, title, company, apply_url, source, location, match_score, saved_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job["job_id"], user_id, job["title"], job["company"], job.get("apply_url"),
                job.get("source"), job.get("location"), job.get("match_score", 0.0), now,
            ),
        )
        conn.commit()
    res = dict(job)
    res["user_id"] = user_id
    res["saved_at"] = now
    return res


def is_saved(job_id: str, user_id: str = "local") -> bool:
    return get_saved(job_id, user_id=user_id) is not None


def unsave_job(job_id: str, user_id: str = "local") -> bool:
    with _lock:
        cur = _get_conn().execute(
            "DELETE FROM saved_jobs WHERE job_id = ? AND user_id = ?", (job_id, user_id)
        )
        _get_conn().commit()
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Applications (multi-tenant)
# ---------------------------------------------------------------------------

def list_applications(user_id: str = "local") -> list[dict]:
    with _lock:
        rows = _get_conn().execute(
            "SELECT * FROM applications WHERE user_id = ? ORDER BY date_applied DESC", (user_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_application(job_id: str, user_id: str = "local") -> dict | None:
    with _lock:
        row = _get_conn().execute(
            "SELECT * FROM applications WHERE job_id = ? AND user_id = ?", (job_id, user_id)
        ).fetchone()
    return dict(row) if row else None


def create_application(job: dict, user_id: str = "local") -> dict:
    now = _now_iso()
    with _lock:
        conn = _get_conn()
        conn.execute(
            """
            INSERT OR IGNORE INTO applications
                (job_id, user_id, title, company, apply_url, source, location, match_score,
                 status, date_applied, notes, resume_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'applied', ?, '', ?)
            """,
            (
                job["job_id"], user_id, job["title"], job["company"], job.get("apply_url"),
                job.get("source"), job.get("location"), job.get("match_score", 0.0),
                now, job.get("resume_id"),
            ),
        )
        conn.commit()
    return get_application(job["job_id"], user_id=user_id) or {}


def update_application(
    job_id: str,
    status: str | None = None,
    notes: str | None = None,
    user_id: str = "local",
) -> dict | None:
    existing = get_application(job_id, user_id=user_id)
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
            "UPDATE applications SET status = ?, notes = ?, updated_at = ? WHERE job_id = ? AND user_id = ?",
            (existing["status"], existing["notes"], _now_iso(), job_id, user_id),
        )
        conn.commit()
    return existing


def delete_application(job_id: str, user_id: str = "local") -> bool:
    with _lock:
        cur = _get_conn().execute(
            "DELETE FROM applications WHERE job_id = ? AND user_id = ?", (job_id, user_id)
        )
        _get_conn().commit()
        return cur.rowcount > 0


def get_tracker_stats(user_id: str = "local") -> dict:
    with _lock:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT * FROM applications WHERE user_id = ?", (user_id,)
        ).fetchall()
    
    if not rows:
        return {
            "total": 0, "by_status": {}, "avg_match_score": 0.0, "interview_rate": 0.0,
            "source_breakdown": {}, "oldest_pending_days": None, "days_in_stage": {}
        }

    total = len(rows)
    by_status = {}
    source_breakdown = {}
    total_score = 0.0
    interview_count = 0
    oldest_pending_days = None
    days_in_stage = {}

    now = datetime.now(timezone.utc)

    for row in rows:
        r = dict(row)
        status = r["status"]
        by_status[status] = by_status.get(status, 0) + 1
        source_breakdown[r.get("source") or "unknown"] = source_breakdown.get(r.get("source") or "unknown", 0) + 1
        total_score += r.get("match_score", 0.0)
        
        if status == "interview":
            interview_count += 1
            
        # Calculate days in current stage
        updated_at = r.get("updated_at") or r.get("date_applied")
        if updated_at:
            try:
                last_update = datetime.fromisoformat(updated_at)
                if last_update.tzinfo is None:
                    last_update = last_update.replace(tzinfo=timezone.utc)
                days = (now - last_update).days
                days_in_stage[r["job_id"]] = days
                
                if status == "applied":
                    if oldest_pending_days is None or days > oldest_pending_days:
                        oldest_pending_days = days
            except ValueError:
                pass

    return {
        "total": total,
        "by_status": by_status,
        "avg_match_score": round(total_score / total, 2),
        "interview_rate": round(interview_count / total, 2),
        "source_breakdown": source_breakdown,
        "oldest_pending_days": oldest_pending_days,
        "days_in_stage": days_in_stage
    }
