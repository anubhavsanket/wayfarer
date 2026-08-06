"""Persistent resume storage: uploaded file + parsed result, keyed by resume_id.

Layout under ``data/uploads/``::

    data/uploads/
      index.json              # primary resume pointer + metadata
      {resume_id}/
        original.pdf|docx     # the uploaded file
        parsed.json           # ParsedResume as JSON
        saved_*.pdf|docx      # outputs of save_resume (new_file mode)

This is what lets ``/resume/save`` look up a parsed resume by ``resume_id``
after ``/resume/check`` produced it.  ``index.json`` tracks which resume
is the user's primary (§8.6 FR2.9).
"""
from __future__ import annotations

import json
import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..models.schemas import StructuralIssue
from .resume_parser import ParsedResume, ResumeBullet

logger = logging.getLogger(__name__)

UPLOADS_ROOT = Path("data/uploads")
_INDEX_PATH = UPLOADS_ROOT / "index.json"


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
    record_upload(resume_id, safe_name)
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


# ---------------------------------------------------------------------------
# Resume graph storage (§12.1)
# ---------------------------------------------------------------------------

def save_graph(resume_id: str, graph_dict: dict[str, Any]) -> None:
    """Persist the resume entity graph alongside parsed.json."""
    rdir = _resume_dir(resume_id)
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / "graph.json").write_text(
        json.dumps(graph_dict, indent=2),
        encoding="utf-8",
    )


def load_graph(resume_id: str) -> dict[str, Any] | None:
    """Load a previously-saved resume graph, or None."""
    path = _resume_dir(resume_id) / "graph.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load resume graph %s: %s", resume_id, exc)
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


# ---------------------------------------------------------------------------
# Primary resume index (§8.6 FR2.9)
# ---------------------------------------------------------------------------
# The index lives at data/uploads/index.json and tracks:
#   - primary_resume_id: which resume is the user's primary
#   - resumes: metadata for every uploaded resume (filename, uploaded_at)

def _load_index() -> dict[str, Any]:
    """Load the resume index from disk, or return an empty index."""
    if not _INDEX_PATH.exists():
        return {"primary_resume_id": None, "resumes": {}}
    try:
        data = json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
        # Ensure required keys exist
        data.setdefault("primary_resume_id", None)
        data.setdefault("resumes", {})
        return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load resume index: %s", exc)
        return {"primary_resume_id": None, "resumes": {}}


def _save_index(data: dict[str, Any]) -> None:
    """Persist the resume index to disk."""
    _INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    _INDEX_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def record_upload(resume_id: str, filename: str) -> None:
    """Record a resume upload in the index (called by store_upload)."""
    index = _load_index()
    index["resumes"][resume_id] = {
        "filename": filename,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_index(index)


def set_primary(resume_id: str) -> None:
    """Set a resume as the user's primary resume (§8.6 FR2.9).

    Validates that resume_id exists in the index before setting.
    """
    index = _load_index()
    if resume_id not in index["resumes"]:
        raise ValueError(f"Unknown resume_id: {resume_id}. Cannot set as primary.")
    index["primary_resume_id"] = resume_id
    _save_index(index)
    logger.info("Primary resume set to %s", resume_id)


def get_primary_id() -> str | None:
    """Return the current primary resume_id, or None if no primary is set."""
    index = _load_index()
    return index.get("primary_resume_id")


def get_primary_info() -> dict[str, str] | None:
    """Return primary resume metadata: {resume_id, filename, uploaded_at}.

    Returns None if no primary resume is set or the primary's metadata
    is missing from the index.
    """
    index = _load_index()
    rid = index.get("primary_resume_id")
    if rid and rid in index["resumes"]:
        info = index["resumes"][rid]
        return {"resume_id": rid, "filename": info["filename"], "uploaded_at": info["uploaded_at"]}
    return None


def get_resume_info(resume_id: str) -> dict[str, str] | None:
    """Return metadata for a specific resume, or None."""
    index = _load_index()
    if resume_id in index["resumes"]:
        info = index["resumes"][resume_id]
        return {"resume_id": resume_id, "filename": info["filename"], "uploaded_at": info["uploaded_at"]}
    return None
