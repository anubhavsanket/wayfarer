"""Resume save service — apply accepted suggestions, write a new file.

FR2.8 (PRD §8.1): After the user reviews and accepts/rejects individual
redline suggestions, let them choose to **save as a new file** (default,
non-destructive) or **overwrite the original** upload. Overwrite requires
an explicit ``confirm_overwrite`` — never silently replace the source.

FR2.11 (PRD §8.6): ``set_as_primary`` mode applies suggestions, saves a
new file, re-persists the parsed data, and promotes the resume to primary.

The v1 output is a reconstructed .docx (the original upload is left
untouched in ``data/uploads/{resume_id}/`` until overwrite is confirmed).
Native OOXML track-changes is a v2 stretch.
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

from docx import Document

from ..models.schemas import AcceptedSuggestion, ResumeSaveResponse, SaveMode
from .resume_parser import ParsedResume
from . import resume_store

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DOCX writer
# ---------------------------------------------------------------------------

def _write_docx(parsed: ParsedResume, out_path: Path) -> None:
    """Reconstruct a .docx from parsed sections, applying any edits already
    reflected in ``parsed.sections`` / ``parsed.bullets``."""
    doc = Document()

    # Title / name
    name = parsed.contact.get("name") or "Resume"
    doc.add_heading(name, level=0)

    # Contact line
    contact_parts = [
        parsed.contact.get("email", ""),
        parsed.contact.get("phone", ""),
        parsed.contact.get("linkedin", ""),
        parsed.contact.get("github", ""),
    ]
    contact_line = " | ".join(p for p in contact_parts if p)
    if contact_line:
        doc.add_paragraph(contact_line)

    # Sections
    section_titles = {
        "summary": "Summary",
        "skills": "Skills",
        "experience": "Experience",
        "projects": "Projects",
        "education": "Education",
        "certifications": "Certifications",
        "awards": "Awards",
        "publications": "Publications",
    }

    # Map bullet id → accepted new text so we apply edits during reconstruction
    bullet_edits: dict[str, str] = {
        b.id: b.text for b in parsed.bullets
    }

    for section_name, lines in parsed.sections.items():
        if section_name in ("contact", "preamble"):
            continue
        title = section_titles.get(section_name, section_name.replace("_", " ").title())
        doc.add_heading(title, level=1)
        for line in lines:
            # If a line corresponds to a bullet that was edited, use the edit
            bullet_match = next(
                (b for b in parsed.bullets if b.text == line and b.id in bullet_edits),
                None,
            )
            text = bullet_edits.get(bullet_match.id, line) if bullet_match else line
            doc.add_paragraph(text, style="List Bullet" if line.strip().startswith(("•", "-", "*")) else None)

    doc.save(str(out_path))


# ---------------------------------------------------------------------------
# Apply suggestions
# ---------------------------------------------------------------------------

def _apply_suggestions(
    parsed: ParsedResume,
    accepted: list[AcceptedSuggestion],
) -> ParsedResume:
    """Return a copy of ``parsed`` with accepted bullet edits applied."""
    edits = {s.bullet_id: s.suggested_text for s in accepted}

    # Update bullets
    new_bullets = []
    for b in parsed.bullets:
        if b.id in edits and edits[b.id]:
            b.text = edits[b.id]
        new_bullets.append(b)
    parsed.bullets = new_bullets

    # Update the section lines that came from edited bullets
    new_sections: dict[str, list[str]] = {}
    for section, lines in parsed.sections.items():
        new_lines = []
        for line in lines:
            match = next((b for b in parsed.bullets if b.text == line or
                          (b.id in edits and edits[b.id] == line)), None)
            if match and match.id in edits:
                new_lines.append(edits[match.id])
            else:
                new_lines.append(line)
        new_sections[section] = new_lines
    parsed.sections = new_sections

    return parsed


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------

async def save_resume(
    resume_id: str,
    accepted_suggestions: list[AcceptedSuggestion],
    mode: SaveMode,
    confirm_overwrite: bool = False,
) -> ResumeSaveResponse:
    """Apply accepted suggestions and save as a new file or overwrite."""
    parsed = resume_store.load_parsed(resume_id)
    if parsed is None:
        raise ValueError(f"Unknown resume_id: {resume_id}. Run /resume/check first.")

    if mode == SaveMode.OVERWRITE and not confirm_overwrite:
        raise ValueError(
            "confirm_overwrite must be true to overwrite the original resume."
        )

    # Apply accepted suggestions to the parsed resume
    edited = _apply_suggestions(parsed, accepted_suggestions)

    # Determine output filename
    original = resume_store.original_file_path(resume_id)
    if mode == SaveMode.OVERWRITE and original is not None:
        out_path = original  # overwrite in place
    else:
        rdir = resume_store._resume_dir(resume_id)
        rdir.mkdir(parents=True, exist_ok=True)
        out_path = rdir / f"saved_{uuid.uuid4().hex[:8]}.docx"

    # Write the DOCX
    _write_docx(edited, out_path)

    # For overwrite and set_as_primary: re-persist the edited parsed data
    # so future loads/queries reflect the change
    if mode in (SaveMode.OVERWRITE, SaveMode.SET_AS_PRIMARY):
        resume_store.save_parsed(resume_id, edited)

    # FR2.11: set_as_primary applies suggestions, saves, and promotes
    if mode == SaveMode.SET_AS_PRIMARY:
        resume_store.set_primary(resume_id)

    return ResumeSaveResponse(
        file_id=uuid.uuid4().hex[:12],
        file_ref=str(out_path),
        mode_applied=mode,
    )
