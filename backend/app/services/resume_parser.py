"""Resume parser: PDF/DOCX → structured sections + ATS-visible text.

FR2.1 (PRD §8.1): Parse an uploaded resume into structured sections
(contact, skills, experience bullets, education).

FR2.2 (PRD §8.2): Run an ATS parsing simulation — extract text the way a
naive ATS parser would (layout-blind, table-ignorant), and diff against
the properly structured extraction to flag structural loss (tables,
multi-column sections that vanish).

Acceptance criterion: "A resume with a table-based skills section shows a
structural-loss flag on that section."
"""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pdfplumber
import docx

from ..models.schemas import StructuralIssue

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OCR support (optional — for embedded images in DOCX)
# ---------------------------------------------------------------------------

_TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

def _ocr_image(image_bytes: bytes) -> str:
    """Run Tesseract OCR on raw image bytes. Returns extracted text or ''."""
    try:
        import pytesseract
        from PIL import Image
        import io

        img = Image.open(io.BytesIO(image_bytes))
        # Skip tiny images (logos, bullets, icons) — OCR on them is noise
        if img.width < 80 or img.height < 30:
            return ""
        text = pytesseract.image_to_string(img, config="--psm 6")
        return text.strip()
    except Exception as exc:
        logger.debug("OCR failed on embedded image: %s", exc)
        return ""


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ResumeBullet:
    id: str
    section: str
    text: str

@dataclass
class ParsedResume:
    sections: dict[str, list[str]]
    bullets: list[ResumeBullet]
    ats_visible_text: str
    structural_issues: list[StructuralIssue]
    contact: dict[str, str] = field(default_factory=dict)
    raw_text: str = ""


# ---------------------------------------------------------------------------
# Section header detection
# ---------------------------------------------------------------------------

SECTION_PATTERNS = [
    (re.compile(r"^(contact|personal|address|info)\s*$", re.I), "contact"),
    (re.compile(r"^(skills?|technical|technologies|competenc)\w*\s*$", re.I), "skills"),
    (re.compile(r"^(experience|work\s+experience|employment|professional)\s*$", re.I), "experience"),
    (re.compile(r"^(education|academics?|qualifications?)\s*$", re.I), "education"),
    (re.compile(r"^(projects?|portfolio|work)\s*$", re.I), "projects"),
    (re.compile(r"^(certifications?|certificates?|licenses?)\s*$", re.I), "certifications"),
    (re.compile(r"^(summary|profile|objective|about)\s*$", re.I), "summary"),
    (re.compile(r"^(publications?|research|papers?)\s*$", re.I), "publications"),
    (re.compile(r"^(awards?|honors?|achievements?)\s*$", re.I), "awards"),
]

BULLET_PATTERN = re.compile(r"^[•‣◦⁃•\-\*]\s*")


def _detect_section(line: str) -> str | None:
    stripped = line.strip()
    if not stripped:
        return None
    for pattern, name in SECTION_PATTERNS:
        if pattern.match(stripped):
            return name
    return None


# ---------------------------------------------------------------------------
# Contact extraction
# ---------------------------------------------------------------------------

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(r"[\+]?[\d\-\(\)\s]{7,15}")
LINKEDIN_RE = re.compile(r"linkedin\.com/in/[a-zA-Z0-9\-_]+", re.I)
GITHUB_RE = re.compile(r"github\.com/[a-zA-Z0-9\-_]+", re.I)


def _extract_contact(lines: list[str]) -> dict[str, str]:
    contact: dict[str, str] = {}
    blob = " ".join(lines[:5])
    email = EMAIL_RE.search(blob)
    if email:
        contact["email"] = email.group()
    phone = PHONE_RE.search(blob)
    if phone:
        contact["phone"] = phone.group().strip()
    linkedin = LINKEDIN_RE.search(blob)
    if linkedin:
        contact["linkedin"] = linkedin.group()
    github = GITHUB_RE.search(blob)
    if github:
        contact["github"] = github.group()
    if lines:
        contact["name"] = lines[0].strip()
    return contact


# ---------------------------------------------------------------------------
# PDF parsing
# ---------------------------------------------------------------------------

def _parse_pdf(file_path: str) -> tuple[list[str], dict[int, str], list[dict[str, Any]]]:
    """Parse PDF: returns (all_lines, page_texts, tables).

    page_texts: page number → layout-blind text (simulating a naive ATS parser)
    tables: list of {page, headers, rows} for every table found
    """
    all_lines: list[str] = []
    page_texts: dict[int, str] = {}
    tables: list[dict[str, Any]] = []

    with pdfplumber.open(file_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            # Layout-blind extraction (what a naive ATS sees)
            page_text = page.extract_text(x_tolerance=2, y_tolerance=2) or ""
            page_texts[page_num] = page_text
            all_lines.extend(page_text.splitlines())

            # Structured table extraction (what a good PDF reader sees)
            for table in page.extract_tables():
                if not table:
                    continue
                headers = [str(c or "").strip() for c in table[0]]
                rows = []
                for row in table[1:]:
                    rows.append([str(c or "").strip() for c in row])
                tables.append({
                    "page": page_num,
                    "headers": headers,
                    "rows": rows,
                    "cell_text": " ".join(
                        " ".join(row) for row in [headers] + rows
                    ),
                })

    return all_lines, page_texts, tables


def _parse_docx(file_path: str) -> tuple[list[str], dict[int, str], list[dict[str, Any]]]:
    """Parse DOCX: returns (paragraph_lines, page_placeholder, tables).

    DOCX has no "pages"; page_placeholder is {1: full text} for uniform API.
    Tables: list of {page, headers, rows, cell_text}.
    Embedded images are OCR'd via Tesseract and appended as text lines.
    """
    doc = docx.Document(file_path)
    paragraph_lines: list[str] = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            paragraph_lines.append(text)

    # Table extraction
    tables: list[dict[str, Any]] = []
    for table in doc.tables:
        if not table.rows:
            continue
        headers = [cell.text.strip() for cell in table.rows[0].cells]
        rows = []
        for row in table.rows[1:]:
            rows.append([cell.text.strip() for cell in row.cells])
        cell_text = " ".join(" ".join(row) for row in [headers] + rows)
        tables.append({
            "page": 1,
            "headers": headers,
            "rows": rows,
            "cell_text": cell_text,
        })

    # ── OCR embedded images (profile photos, diagrams, etc.) ──────────
    ocr_lines: list[str] = []
    try:
        from docx.opc.constants import RELATIONSHIP_TYPE as RT
        for rel in doc.part.rels.values():
            if "image" in rel.reltype:
                try:
                    image_part = rel.target_part
                    image_bytes = image_part.blob
                    ocr_text = _ocr_image(image_bytes)
                    if ocr_text:
                        # Split into lines and filter noise
                        for line in ocr_text.splitlines():
                            cleaned = line.strip()
                            if len(cleaned) > 3:  # skip single-char OCR noise
                                ocr_lines.append(cleaned)
                except Exception as exc:
                    logger.debug("Failed to OCR embedded image: %s", exc)
    except Exception as exc:
        logger.debug("Image extraction skipped: %s", exc)

    if ocr_lines:
        logger.info("OCR extracted %d lines from embedded images", len(ocr_lines))

    return paragraph_lines, {1: "\n".join(paragraph_lines)}, tables, ocr_lines


# ---------------------------------------------------------------------------
# ATS simulation diff
# ---------------------------------------------------------------------------

def _detect_structural_issues(
    tables: list[dict[str, Any]],
    ats_text: str,
) -> list[StructuralIssue]:
    """Flag table content that doesn't appear in the layout-blind ATS text."""
    issues: list[StructuralIssue] = []
    ats_lower = ats_text.lower()
    for tbl in tables:
        for header in tbl["headers"]:
            header_stripped = header.strip().lower()
            if header_stripped and header_stripped not in ats_lower:
                issues.append(StructuralIssue(
                    location=f"table on page {tbl['page']}",
                    issue=(
                        f"Table header '{header}' not visible in ATS text — "
                        f"table structure may be lost by ATS parsers"
                    ),
                ))
    return issues


# ---------------------------------------------------------------------------
# Section extraction
# ---------------------------------------------------------------------------

# Sections whose lines are treated as candidate bullets (evidence for matching)
BULLET_SECTIONS = {"experience", "projects", "awards", "publications", "skills"}


def _parse_sections(lines: list[str]) -> tuple[dict[str, list[str]], list[ResumeBullet]]:
    """Extract named sections and bullets from lines. Returns (sections, bullets)."""
    sections: dict[str, list[str]] = {}
    bullets: list[ResumeBullet] = []
    current_section = "preamble"  # content before any known header
    bullet_id = 0

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        detected = _detect_section(stripped)
        if detected:
            current_section = detected
            sections.setdefault(current_section, [])
            continue

        sections.setdefault(current_section, []).append(stripped)

        # Record as a bullet when it looks like one: a bullet glyph, or a
        # substantive line inside a BULLET_SECTION (resumes rarely use glyphs).
        clean = BULLET_PATTERN.sub("", stripped).strip()
        is_bullet = bool(BULLET_PATTERN.match(stripped)) or (
            current_section in BULLET_SECTIONS and clean
        )
        if is_bullet and clean:
            bullets.append(ResumeBullet(
                id=f"b{bullet_id}",
                section=current_section,
                text=clean,
            ))
            bullet_id += 1

    return sections, bullets


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_resume(file_path: str | Path) -> ParsedResume:
    """Parse a resume file (PDF or DOCX) into a ``ParsedResume``.

    Returns structured sections, bullets, ATS-visible text, and any
    structural issues detected (tables lost by naive ATS extraction).
    """
    path = str(file_path)
    ext = Path(path).suffix.lower()

    if ext == ".pdf":
        raw_lines, page_texts, tables = _parse_pdf(path)
        ats_text = "\n".join(page_texts.values())
        ocr_lines: list[str] = []
    elif ext in (".docx", ".doc"):
        raw_lines, page_texts, tables, ocr_lines = _parse_docx(path)
        ats_text = "\n".join(page_texts.values())
    else:
        raise ValueError(f"Unsupported resume format: {ext} (use .pdf or .docx)")

    # Detect structural issues (table loss in ATS extraction)
    structural_issues = _detect_structural_issues(tables, ats_text)

    # Parse named sections from the raw lines (include OCR text)
    all_lines = raw_lines + ocr_lines
    raw_text = "\n".join(all_lines)
    sections, bullets = _parse_sections(all_lines)

    # Extract contact info
    contact = _extract_contact(raw_lines)

    return ParsedResume(
        sections=sections,
        bullets=bullets,
        ats_visible_text=ats_text,
        structural_issues=structural_issues,
        contact=contact,
        raw_text=raw_text,
    )
