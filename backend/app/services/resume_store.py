"""Persistent resume storage: uploaded file + parsed result, keyed by resume_id.

Layout under ``data/uploads/``::

    data/uploads/
      {resume_id}/
        original.pdf|docx     # the uploaded file
        parsed.json           # ParsedResume as JSON
        saved_*.pdf|docx      # outputs of save_resume (new_file mode)

This is what lets ``/resume/save`` look up a parsed resume by ``resume_id``
after ``/resume/check`` produced it.
"""
from __future__ import annotations

import json
import logging
import shutil
import uuid
from pathlib import Path
from typing import Any

from ..models.schemas import StructuralIssue
from .resume_parser import ParsedResume, ResumeBullet

logger = logging.getLogger(__name__)

UPLOADS_ROOT = Path("data/uploads")


def _resume_dir(resume_id: str) -> Path:
    return UPLOADS_ROOT / resume_id


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _parsed_to_dict(parsed: ParsedResume) -> dict[str, Any]:
    return {
        "sections": parsed.sections,
        "bullets": [{"id": b.id, "section": b.section, "text": b.text} for b in parsed.bullets],
        "ats_visible_text": parsed.ats_visible_text,
        "structural_issues": [
            {"location": s.location, "issue": s.issue} for s in parsed.structural_issues
        ],
        "contact": parsed.contact,
        "raw_text": parsed.raw_text,
    }


def _dict_to_parsed(data: dict[str, Any]) -> ParsedResume:
    return ParsedResume(
        sections=data.get("sections", {}),
        bullets=[
            ResumeBullet(id=b["id"], section=b.get("section", ""), text=b["text"])
            for b in data.get("bullets", [])
        ],
        ats_visible_text=data.get("ats_visible_text", ""),
        structural_issues=[
            StructuralIssue(location=s["location"], issue=s["issue"])
            for s in data.get("structural_issues", [])
        ],
        contact=data.get("contact", {}),
        raw_text=data.get("raw_text", ""),
    )


# ---------------------------------------------------------------------------
# Store / load
# ---------------------------------------------------------------------------

def store_upload(file_content: bytes, filename: str, resume_id: str | None = None) -> tuple[str, Path]:
    """Persist an uploaded resume file. Returns (resume_id, saved_path)."""
    resume_id = resume_id or uuid.uuid4().hex[:12]
    rdir = _resume_dir(resume_id)
    rdir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename).name or "resume"
    dest = rdir / safe_name
    dest.write_bytes(file_content)
    return resume_id, dest


def save_parsed(resume_id: str, parsed: ParsedResume) -> None:
    """Persist the parsed resume alongside the original file."""
    rdir = _resume_dir(resume_id)
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / "parsed.json").write_text(
        json.dumps(_parsed_to_dict(parsed), indent=2),
        encoding="utf-8",
    )


def load_parsed(resume_id: str) -> ParsedResume | None:
    """Load a previously-saved parsed resume, or None."""
    path = _resume_dir(resume_id) / "parsed.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return _dict_to_parsed(data)
    except (json.JSONDecodeError, OSError, KeyError) as exc:
        logger.warning("Failed to load parsed resume %s: %s", resume_id, exc)
        return None


def original_file_path(resume_id: str) -> Path | None:
    """Path to the original uploaded resume file, or None."""
    rdir = _resume_dir(resume_id)
    if not rdir.exists():
        return None
    for candidate in rdir.glob("*"):
        if candidate.suffix.lower() in (".pdf", ".docx", ".doc") and candidate.name != "parsed.json":
            return candidate
    return None


def overwrite_original(resume_id: str, new_content: Path) -> bool:
    """Replace the original uploaded file with new content (overwrite mode)."""
    orig = original_file_path(resume_id)
    if orig is None:
        return False
    shutil.copyfile(new_content, orig)
    return True
