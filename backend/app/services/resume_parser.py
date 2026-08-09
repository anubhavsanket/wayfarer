"""Resume parser: any document format → structured sections + ATS-visible text.

Parsing pipeline (cheapest first):
1. AnyDoc (Rust) — handles PDF, DOCX, PPTX, XLSX, RTF, EPUB, CSV, ODT
   → clean markdown output,5ms median conversion
2. pdfplumber (fallback) — text-based PDFs only
3. python-docx (fallback) — DOCX only
4. PyMuPDF + Tesseract OCR (last resort) — image-based PDFs

FR2.1 (PRD §8.1): Parse an uploaded resume into structured sections
(contact, skills, experience bullets, education).

FR2.2 (PRD §8.2): Run an ATS parsing simulation — extract text the way a
naive ATS parser would (layout-blind, table-ignorant), and diff against
the properly structured extraction to flag structural loss.
"""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..models.schemas import StructuralIssue

logger = logging.getLogger(__name__)


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
# AnyDoc parser (primary — handles 14 formats)
# ---------------------------------------------------------------------------

def _parse_with_anydoc(file_path: str) -> str | None:
    """Try parsing with AnyDoc (Rust). Returns markdown text or None on failure."""
    try:
        import anydoc
        md = anydoc.to_markdown(file_path)
        if md and md.strip():
            logger.info("AnyDoc parsed %s successfully (%d chars)", file_path, len(md))
            return md
        return None
    except ImportError:
        logger.debug("AnyDoc not installed — falling back to legacy parsers")
        return None
    except Exception as exc:
        logger.info("AnyDoc failed on %s: %s — trying fallback parsers", file_path, exc)
        return None


# ---------------------------------------------------------------------------
# Legacy PDF parser (fallback)
# ---------------------------------------------------------------------------

def _parse_pdf_legacy(file_path: str) -> tuple[list[str], dict[int, str], list[dict[str, Any]]]:
    """Fallback PDF parser using pdfplumber. Returns (all_lines, page_texts, tables)."""
    import pdfplumber

    all_lines: list[str] = []
    page_texts: dict[int, str] = {}
    tables: list[dict[str, Any]] = []

    with pdfplumber.open(file_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            page_text = page.extract_text(x_tolerance=2, y_tolerance=2) or ""
            page_texts[page_num] = page_text
            all_lines.extend(page_text.splitlines())

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


# ---------------------------------------------------------------------------
# Legacy DOCX parser (fallback)
# ---------------------------------------------------------------------------

def _parse_docx_legacy(file_path: str) -> tuple[list[str], dict[int, str], list[dict[str, Any]]]:
    """Fallback DOCX parser using python-docx."""
    import docx

    doc = docx.Document(file_path)
    paragraph_lines: list[str] = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            paragraph_lines.append(text)

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

    return paragraph_lines, {1: "\n".join(paragraph_lines)}, tables


# ---------------------------------------------------------------------------
# OCR fallback (image-based PDFs)
# ---------------------------------------------------------------------------

def _ocr_pdf(file_path: str) -> tuple[list[str], dict[int, str]]:
    """OCR an image-based PDF using PyMuPDF (render) + Tesseract (recognise)."""
    try:
        import fitz  # PyMuPDF
        import pytesseract
        from PIL import Image
        import io
    except ImportError as exc:
        logger.warning("OCR dependencies not available (%s) — cannot OCR PDF", exc)
        return [], {}

    all_lines: list[str] = []
    page_texts: dict[int, str] = {}

    try:
        doc = fitz.open(file_path)
    except Exception as exc:
        logger.warning("PyMuPDF failed to open PDF: %s", exc)
        return [], {}

    for page_num in range(len(doc)):
        page = doc[page_num]
        mat = fitz.Matrix(2, 2)
        pix = page.get_pixmap(matrix=mat)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        text = pytesseract.image_to_string(img, lang="eng")
        page_texts[page_num + 1] = text
        all_lines.extend(text.splitlines())

    doc.close()
    logger.info("OCR extracted %d chars across %d pages", sum(len(t) for t in page_texts.values()), len(page_texts))
    return all_lines, page_texts


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

BULLET_SECTIONS = {"experience", "projects", "awards", "publications", "skills"}


def _parse_sections(lines: list[str]) -> tuple[dict[str, list[str]], list[ResumeBullet]]:
    """Extract named sections and bullets from lines."""
    sections: dict[str, list[str]] = {}
    bullets: list[ResumeBullet] = []
    current_section = "preamble"
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


def _markdown_to_lines(md: str) -> list[str]:
    """Convert AnyDoc's markdown output to plain text lines for section parsing.

    Strips markdown headings (# ## ###), bullet glyphs, bold/italic markers,
    and other formatting to produce clean text lines.
    """
    lines = []
    for raw_line in md.splitlines():
        # Strip markdown heading markers
        line = re.sub(r"^#{1,6}\s+", "", raw_line)
        # Strip bold/italic markers
        line = re.sub(r"\*{1,3}(.+?)\*{1,3}", r"\1", line)
        line = re.sub(r"_{1,3}(.+?)_{1,3}", r"\1", line)
        # Strip inline code
        line = re.sub(r"`(.+?)`", r"\1", line)
        # Strip links, keep text
        line = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", line)
        # Strip images
        line = re.sub(r"!\[.*?\]\(.+?\)", "", line)
        # Strip horizontal rules
        if re.match(r"^[\-\*_]{3,}\s*$", line.strip()):
            continue
        lines.append(line.rstrip())
    return lines


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_resume(file_path: str | Path) -> ParsedResume:
    """Parse a resume file into a ``ParsedResume``.

    Pipeline (cheapest first):
    1. AnyDoc → markdown → sections/bullets
    2. pdfplumber (PDF) / python-docx (DOCX) → raw lines → sections/bullets
    3. OCR (image-based PDF) → raw lines → sections/bullets
    """
    path = str(file_path)
    ext = Path(path).suffix.lower()

    # --- Markdown files: read directly (no conversion needed) ---
    if ext == ".md":
        md_text = Path(path).read_text(encoding="utf-8", errors="replace")
        if md_text.strip():
            lines = _markdown_to_lines(md_text)
            raw_text = "\n".join(lines)
            sections, bullets = _parse_sections(lines)
            contact = _extract_contact(lines)
            return ParsedResume(
                sections=sections,
                bullets=bullets,
                ats_visible_text=md_text,
                structural_issues=[],
                contact=contact,
                raw_text=raw_text,
            )

    # --- Try AnyDoc first (handles PDF, DOCX, PPTX, XLSX, RTF, etc.) ---
    md_text = _parse_with_anydoc(path)
    if md_text:
        lines = _markdown_to_lines(md_text)
        raw_text = "\n".join(lines)
        ats_text = md_text  # AnyDoc markdown IS the clean text
        sections, bullets = _parse_sections(lines)
        contact = _extract_contact(lines)
        return ParsedResume(
            sections=sections,
            bullets=bullets,
            ats_visible_text=ats_text,
            structural_issues=[],  # AnyDoc handles tables natively
            contact=contact,
            raw_text=raw_text,
        )

    # --- Fallback: legacy parsers ---
    if ext == ".pdf":
        raw_lines, page_texts, tables = _parse_pdf_legacy(path)
        ats_text = "\n".join(page_texts.values())

        # OCR fallback for image-based PDFs
        total_chars = sum(len(t) for t in page_texts.values())
        if total_chars == 0:
            logger.info("pdfplumber extracted no text — attempting OCR fallback")
            raw_lines, page_texts = _ocr_pdf(path)
            ats_text = "\n".join(page_texts.values())
            tables = []  # OCR doesn't extract tables

    elif ext in (".docx", ".doc"):
        raw_lines, page_texts, tables = _parse_docx_legacy(path)
        ats_text = "\n".join(page_texts.values())

    else:
        raise ValueError(
            f"Unsupported resume format: {ext}. "
            "Supported: PDF, DOCX, MD, PPTX, XLSX, RTF, EPUB, CSV, ODT."
        )

    # Detect structural issues (table loss in ATS extraction)
    structural_issues = _detect_structural_issues(tables, ats_text)

    # Parse named sections from the raw lines
    raw_text = "\n".join(raw_lines)
    sections, bullets = _parse_sections(raw_lines)

    # Guard: if no text was extracted at all
    if not raw_text.strip():
        raise ValueError(
            f"Could not extract text from {ext} file. "
            "The file may be image-based (scanned) or corrupted. "
            "Try re-exporting as DOCX from the original editor."
        )

    contact = _extract_contact(raw_lines)

    return ParsedResume(
        sections=sections,
        bullets=bullets,
        ats_visible_text=ats_text,
        structural_issues=structural_issues,
        contact=contact,
        raw_text=raw_text,
    )
