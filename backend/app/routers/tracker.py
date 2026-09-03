"""Tracker router — saved jobs, applications, and cover-letter drafting.

All state lives in the SQLite tracker DB (see ``..db``). Cover-letter generation
uses the stored resume content via :mod:`..services.cover_letter`.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException

from .. import db
from ..models.schemas import (
    Application,
    ApplicationCreate,
    ApplicationUpdate,
    CoverLetterRequest,
    CoverLetterResponse,
    SavedJob,
    SavedJobCreate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/tracker", tags=["tracker"])


def _run(fn, *args):
    return asyncio.to_thread(fn, *args)


# ---------------------------------------------------------------------------
# Saved jobs
# ---------------------------------------------------------------------------


@router.get("/saved", response_model=list[SavedJob])
async def list_saved():
    return await _run(db.list_saved)


@router.post("/saved", response_model=SavedJob)
async def save_job(body: SavedJobCreate):
    created = await _run(db.save_job, body.model_dump())
    if created.get("job_id") is None:
        created["job_id"] = body.job_id
    return created


@router.get("/saved/{job_id}")
async def get_saved(job_id: str):
    item = await _run(db.get_saved, job_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' is not saved")
    return item


@router.delete("/saved/{job_id}")
async def unsave_job(job_id: str):
    removed = await _run(db.unsave_job, job_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' is not saved")
    return {"removed": True}


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------


@router.get("/applications", response_model=list[Application])
async def list_applications():
    return await _run(db.list_applications)


@router.post("/applications", response_model=Application)
async def create_application(body: ApplicationCreate):
    created = await _run(db.create_application, body.model_dump())
    if not created:
        # Already tracked — return the existing record.
        created = await _run(db.get_application, body.job_id)
    if created is None:
        raise HTTPException(status_code=500, detail="Failed to create application")
    return created


@router.patch("/applications/{job_id}", response_model=Application)
async def update_application(job_id: str, body: ApplicationUpdate):
    if body.status is None and body.notes is None:
        raise HTTPException(status_code=400, detail="Nothing to update")
    try:
        updated = await _run(db.update_application, job_id, body.status, body.notes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail=f"No application for '{job_id}'")
    return updated


@router.delete("/applications/{job_id}")
async def delete_application(job_id: str):
    removed = await _run(db.delete_application, job_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"No application for '{job_id}'")
    return {"removed": True}


# ---------------------------------------------------------------------------
# Cover letter
# ---------------------------------------------------------------------------


@router.post("/cover-letter", response_model=CoverLetterResponse)
async def cover_letter(body: CoverLetterRequest):
    from ..services.cover_letter import generate_cover_letter

    try:
        text = await generate_cover_letter(body.resume_id, body.job)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return CoverLetterResponse(cover_letter=text)
