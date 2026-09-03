# Wayfarer Architecture Plan: Markdown Resume Parser & OAuth Security

## Overview
This document outlines the architectural plan for:
1. Replacing/upgrading the resume parser with a high-speed Markdown-based document converter (e.g. AnyDoc / MarkItDown / PyMuPDF4LLM) to accelerate parsing speed (from ~5s to <300ms) and improve LLM semantic understanding while maintaining full backward compatibility with the `ParsedResume` data contract.
2. Setting up an OAuth 2.0 multi-tenant authentication framework and encrypted storage for user application data, bookmarks, and custom API keys.

---

## Part 1: Markdown Resume Parser Strategy

### Goals
- **Performance**: Reduce parse time from 2–8 seconds to <300 milliseconds.
- **LLM Readability**: Native Markdown header (`#`, `##`) and bullet structure (`-`, `*`) for superior vector chunking and LLM reasoning.
- **Backward Compatibility**: Preserve `ParsedResume` model schema:
  - `sections`: Dictionary of section header -> text lines.
  - `bullets`: List of `ResumeBullet(id, section, text)`.
  - `ats_visible_text`: Plain text string for legacy ATS simulation.
  - `raw_text`: Complete raw document text.
  - `structural_issues`: List of layout warnings (e.g. tables, multi-column loss).
  - `contact`: Extracted email, phone, name.

### Implementation Pipeline
1. **Document Conversion**: Convert PDF/DOCX to Markdown string using fast document parsing (PyMuPDF4LLM / MarkItDown / AnyDoc fallback).
2. **Markdown Structural Extraction**:
   - Parse section headers (`#`, `##`, or ALL CAPS lines) into section buckets (`experience`, `skills`, `education`, etc.).
   - Extract bullet points (`- `, `* `, `• `) into `ResumeBullet` instances with unique bullet IDs (`b0`, `b1`, ...).
3. **ATS Simulation & Fallback**:
   - Generate layout-blind plain text extraction (`ats_visible_text`).
   - Detect tables/complex structures in Markdown or via fallback inspection to populate `structural_issues`.

---

## Part 2: OAuth Setup & Per-User Data Isolation

### Architecture
- **Auth Provider**: OAuth 2.0 / OpenID Connect (Google OAuth, GitHub OAuth, or OIDC IdP).
- **Backend Auth Dependency**: FastAPI JWT validation middleware (`get_current_user`).
- **Database Scope**: Add `user_id` column to `saved_jobs` and `applications` tables in `db.py`. Scope all SQL queries by `user_id`.
- **API Key Security**: Encrypt user API keys at rest using AES-128/256 (Fernet encryption) with a server-side secret key (`ENCRYPTION_SECRET_KEY`). Inject user keys dynamically into `llm_router` requests.
