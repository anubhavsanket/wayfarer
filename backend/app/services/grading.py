"""Posting age grading logic — fresh / stale / re-stamped / ghost classification."""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone, timedelta

from ..db import upsert_post_history, get_post_history, _get_conn, _lock

logger = logging.getLogger(__name__)

GRADE_FRESH = "fresh"       # < 7 days since first seen
GRADE_STALE = "stale"       # > 30 days since last fetched (but < 365 days)
GRADE_RE_STAMPED = "re-stamped"  # same content hash, but fetched_at changed significantly (indicating a repost with a new date)
GRADE_GHOST = "ghost"       # > 365 days since first seen, no updates, or description too sparse

# Thresholds in days
FRESH_DAYS = 7
STALE_DAYS = 30
GHOST_DAYS = 365


def _hash_text(text: str | None) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def grade_posting(
    job_id: str,
    fetched_at_str: str,
    url: str,
    source: str,
    title: str = "",
    description: str | None = None,
) -> str:
    """Compute and persist the age/grade of a job posting.

    Grades:
    - fresh: first_seen < 7d ago
    - stale: first_seen between 30d and 365d ago
    - re-stamped: same content hash, but fetched_at changed significantly (indicating repost with new date)
    - ghost: first_seen > 365d ago, no updates
    """
    # Compute content hash
    content_text = f"{title}\0{description or ''}"
    content_hash = _hash_text(content_text)

    # Persist/update history
    upsert_post_history(job_id, url or "", source, content_hash)

    # Retrieve history for grading
    history = get_post_history(job_id)
    if not history:
        # Should not happen after upsert, but guard
        return GRADE_FRESH

    from datetime import datetime, timezone
    first_seen = datetime.fromisoformat(history["first_seen_at"])
    last_fetched = datetime.fromisoformat(history.get("last_fetched_at", fetched_at_str) or fetched_at_str)
    fetched_dt = datetime.fromisoformat(fetched_at_str)

    # Set timezone info if missing
    for dt_obj in (first_seen, last_fetched, fetched_dt):
        if dt_obj.tzinfo is None:
            dt_obj = dt_obj.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)

    # Determine grade
    age_days = (now - first_seen).days if first_seen.tzinfo else (now.replace(tzinfo=timezone.utc) - first_seen.replace(tzinfo=timezone.utc)).days
    days_since_fetch = (now - last_fetched).days if last_fetched.tzinfo else (now.replace(tzinfo=timezone.utc) - last_fetched.replace(tzinfo=timezone.utc)).days

    if age_days > GHOST_DAYS:
        grade = GRADE_GHOST
    elif age_days > STALE_DAYS:
        # Check if fetched_at has been significantly updated from original (re-stamped detection)
        # A re-stamped posting has a fetched_at that is much newer than first_seen,
        # but the content hasn't changed (same job, reposted with new date)
        fetched_diff_days = (fetched_dt - first_seen).days if fetched_dt.tzinfo and first_seen.tzinfo else 0
        if fetched_diff_days > 7 and content_hash == history.get("content_hash"):
            # If fetched date is much newer than original but content unchanged, mark as re-stamped
            grade = GRADE_RE_STAMPED
        else:
            grade = GRADE_STALE
    else:
        grade = GRADE_FRESH

    # Update grade in DB
    with _lock:
        conn = _get_conn()
        conn.execute(
            "UPDATE post_history SET grade = ?, last_fetched_at = ? WHERE job_id = ?",
            (grade, fetched_at_str, job_id)
        )
        conn.commit()
    return grade
