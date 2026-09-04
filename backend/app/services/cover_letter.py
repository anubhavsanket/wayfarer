"""Cover-letter / outreach draft generator.

Uses the resume content that lives on disk (via :func:`resume_store.load_parsed`)
so the draft stays grounded in what's actually on the candidate's resume — real
skills, real experience, real projects. The active LLM provider (from request
overrides / config) does the prose assembly.
"""
from __future__ import annotations

import logging
import re

from ..config import settings
from ..llm_router import router
from ..core.resume_graph import extract_resume_graph
from . import resume_store

logger = logging.getLogger(__name__)


async def generate_cover_letter(resume_id: str, job: dict, tone: str = "professional") -> str:
    """Build a cover letter for ``job`` grounded in the stored resume graph.

    Returns the drafted text. Raises ValueError if the resume can't be found or
    no LLM provider is reachable.
    """
    parsed = resume_store.load_parsed(resume_id)
    if parsed is None:
        raise ValueError(
            f"No resume found for resume_id '{resume_id}'. Upload a resume first."
        )

    # Extract skills and bullets for graph construction
    skills_raw = ", ".join(parsed.sections.get("skills", []))
    bullets = [{"section": b.section, "text": b.text} for b in parsed.bullets]
    
    graph = extract_resume_graph(bullets, skills_raw)
    
    # Extract keywords from JD for graph filtering
    jd_text = job.get("description") or job.get("jd_text") or ""
    # Simple keyword extraction: take words longer than 4 chars, removing stopwords
    stopwords = {"about", "your", "role", "company", "team", "must", "have", "with", "this", "that", "from"}
    jd_keywords = list(set(re.findall(r'\b[a-zA-Z]{5,}\b', jd_text.lower())) - stopwords)
    
    # Get relevant subgraph
    subgraph = graph.subgraph_for_keywords(jd_keywords[:20]) # Limit to top 20 keywords
    resume_context = subgraph.to_prompt_context()
    
    # Fallback to raw text if graph is empty (e.g. very short resume)
    if len(subgraph.nodes) < 5:
        resume_context = f"=== Resume Text ===\n{(parsed.raw_text or parsed.ats_visible_text or '')[:4000]}"

    contact = parsed.contact or {}
    name = contact.get("name") or "the candidate"
    title = job.get("title", "the role")
    company = job.get("company", "your company")

    tone_instructions = {
        "professional": "Maintain a professional, balanced tone. Focus on alignment between skills and requirements.",
        "enthusiastic": "Show genuine excitement for the role and company. Be energetic and passionate.",
        "concise": "Be extremely direct and brief. Cut all fluff. Focus on high-impact statements only."
    }

    system = (
        "You are an experienced career coach writing a genuine, specific cover "
        "letter. Ground every claim in the provided resume context. Never invent skills, "
        "titles, projects, or achievements that are not present in the resume. "
        "Use the candidate's real name and contact details only when they appear "
        "in the resume. "
        f"Tone: {tone_instructions.get(tone, tone_instructions['professional'])} "
        "Keep it to about 3 concise paragraphs. Do not wrap in quotes or add a "
        "subject line."
    )

    user_prompt = (
        f"Write a cover letter for {name} applying to the role of '{title}' at "
        f"'{company}'.\n\n"
        f"JOB DESCRIPTION:\n{jd_text[:3000]}\n\n"
        f"RELEVANT RESUME CONTEXT:\n{resume_context}"
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
