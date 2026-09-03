"""Cover-letter / outreach draft generator.

Uses the resume content that lives on disk (via :func:`resume_store.load_parsed`)
so the draft stays grounded in what's actually on the candidate's resume — real
skills, real experience, real projects. The active LLM provider (from request
overrides / config) does the prose assembly.
"""
from __future__ import annotations

import logging

from ..config import settings
from ..llm_router import router
from . import resume_store

logger = logging.getLogger(__name__)


async def generate_cover_letter(resume_id: str, job: dict) -> str:
    """Build a cover letter for ``job`` grounded in the stored resume.

    Returns the drafted text. Raises ValueError if the resume can't be found or
    no LLM provider is reachable.
    """
    parsed = resume_store.load_parsed(resume_id)
    if parsed is None:
        raise ValueError(
            f"No resume found for resume_id '{resume_id}'. Upload a resume first."
        )

    resume_text = parsed.raw_text or parsed.ats_visible_text or ""
    if not resume_text:
        raise ValueError("Stored resume contains no parseable text.")
    # Keep the prompt lean but faithful.
    resume_excerpt = resume_text[:6000]

    contact = parsed.contact or {}
    name = contact.get("name") or "the candidate"
    title = job.get("title", "the role")
    company = job.get("company", "your company")
    jd_text = job.get("description") or job.get("jd_text") or ""

    system = (
        "You are an experienced career coach writing a genuine, specific cover "
        "letter. Ground every claim in the provided resume. Never invent skills, "
        "titles, projects, or achievements that are not present in the resume. "
        "Use the candidate's real name and contact details only when they appear "
        "in the resume. Match the tone of the job description and the field. "
        "Keep it to about 3 concise paragraphs. Do not wrap in quotes or add a "
        "subject line."
    )

    user_prompt = (
        f"Write a cover letter for {name} applying to the role of '{title}' at "
        f"'{company}'.\n\n"
        f"JOB DESCRIPTION:\n{jd_text[:3000]}\n\n"
        f"CANDIDATE RESUME (use only what is real and present here):\n"
        f"{resume_excerpt}"
    )

    resp = await router.chat(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
        tier="simple",
        max_tokens=600,
        temperature=0.6,
    )

    text = (resp.get("content") or "").strip()
    if not text:
        raise ValueError("The LLM returned an empty cover letter. Try again.")
    return text
