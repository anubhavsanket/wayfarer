"""Tracker router — saved jobs, applications, and cover-letter drafting.

All state lives in the SQLite tracker DB (see ``..db``). Cover-letter generation
uses the stored resume content via :mod:`..services.cover_letter`.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException

from .. import db
from ..core.auth import User, get_current_user
from ..models.schemas import (
    Application,
    ApplicationCreate,
    ApplicationUpdate,
    CoverLetterRequest,
    CoverLetterResponse,
    FollowUpRequest,
    FollowUpResponse,
    NotificationsResponse,
    SavedJob,
    SavedJobCreate,
    TrackerStats,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/tracker", tags=["tracker"])


def _run(fn, *args, **kwargs):
    return asyncio.to_thread(fn, *args, **kwargs)


# ---------------------------------------------------------------------------
# Saved jobs
# ---------------------------------------------------------------------------


@router.get("/saved", response_model=list[SavedJob])
async def list_saved(user: User = Depends(get_current_user)):
    return await _run(db.list_saved, user_id=user.user_id)


@router.post("/saved", response_model=SavedJob)
async def save_job(body: SavedJobCreate, user: User = Depends(get_current_user)):
    created = await _run(db.save_job, body.model_dump(), user_id=user.user_id)
    if created.get("job_id") is None:
        created["job_id"] = body.job_id
    return created


@router.get("/saved/{job_id}")
async def get_saved(job_id: str, user: User = Depends(get_current_user)):
    item = await _run(db.get_saved, job_id, user_id=user.user_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' is not saved")
    return item


@router.delete("/saved/{job_id}")
async def unsave_job(job_id: str, user: User = Depends(get_current_user)):
    removed = await _run(db.unsave_job, job_id, user_id=user.user_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' is not saved")
    return {"removed": True}


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------


@router.get("/applications", response_model=list[Application])
async def list_applications(user: User = Depends(get_current_user)):
    return await _run(db.list_applications, user_id=user.user_id)


@router.post("/applications", response_model=Application)
async def create_application(body: ApplicationCreate, user: User = Depends(get_current_user)):
    created = await _run(db.create_application, body.model_dump(), user_id=user.user_id)
    if not created:
        # Already tracked — return the existing record.
        created = await _run(db.get_application, body.job_id, user_id=user.user_id)
    if created is None:
        raise HTTPException(status_code=500, detail="Failed to create application")
    return created


@router.patch("/applications/{job_id}", response_model=Application)
async def update_application(job_id: str, body: ApplicationUpdate, user: User = Depends(get_current_user)):
    if body.status is None and body.notes is None:
        raise HTTPException(status_code=400, detail="Nothing to update")
    try:
        updated = await _run(db.update_application, job_id, body.status, body.notes, user_id=user.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail=f"No application for '{job_id}'")
    return updated


@router.delete("/applications/{job_id}")
async def delete_application(job_id: str, user: User = Depends(get_current_user)):
    removed = await _run(db.delete_application, job_id, user_id=user.user_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"No application for '{job_id}'")
    return {"removed": True}


# ---------------------------------------------------------------------------
# Tracker stats
# ---------------------------------------------------------------------------

@router.get("/stats", response_model=TrackerStats)
async def get_tracker_stats(user: User = Depends(get_current_user)):
    return await _run(db.get_tracker_stats, user_id=user.user_id)


@router.get("/notifications", response_model=NotificationsResponse)
async def get_notifications(since: str = "", user: User = Depends(get_current_user)):
    return await _run(db.get_notifications, user_id=user.user_id, since_iso=since or None)

# ---------------------------------------------------------------------------
# Cover letter
# ---------------------------------------------------------------------------


@router.post("/cover-letter", response_model=CoverLetterResponse)
async def cover_letter(body: CoverLetterRequest):
    from ..services.cover_letter import generate_cover_letter

    try:
        text = await generate_cover_letter(body.resume_id, body.job, tone=body.tone)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return CoverLetterResponse(cover_letter=text)


# ---------------------------------------------------------------------------
# Follow-up email
# ---------------------------------------------------------------------------


@router.post("/follow-up", response_model=FollowUpResponse)
async def follow_up(body: FollowUpRequest):
    from ..services.follow_up import generate_follow_up

    try:
        text = await generate_follow_up(body.resume_id, body.job, body.stage, body.days_since)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FollowUpResponse(email=text)
