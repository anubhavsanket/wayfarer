"""Stage-aware follow-up / outreach email draft generator.

Reuses the resume graph + LLM router from the cover-letter service to produce
stage-appropriate follow-up emails (post-application nudge, post-interview
thank-you, offer-acceptance, rejection reply). Grounded in the stored resume so
emails stay specific and never invent facts.
"""
from __future__ import annotations

import logging
import re

from ..llm_router import router
from ..core.resume_graph import extract_resume_graph
from . import resume_store

logger = logging.getLogger(__name__)

# Stage → target audience + intent of the follow-up.
_STAGE_PROMPTS = {
    "post_application": (
        "Write a short, polite follow-up email to a recruiter or hiring manager "
        "about an application that was submitted some time ago, to gently check "
        "on its status and reiterate interest. Keep it to a few concise sentences."
    ),
    "post_interview": (
        "Write a warm, professional thank-you email after a job interview. "
        "Reiterate enthusiasm for the role, briefly reinforce one relevant "
        "strength from the resume, and end with an open invitation to follow up."
    ),
    "offer": (
        "Write a gracious offer-acceptance email. Confirm acceptance, express "
        "appreciation, ask any clarifying questions about next steps, and state "
        "the intended start timeline (leave specific dates as placeholders if "
        "unknown)."
    ),
    "rejection": (
        "Write a professional, graceful reply to a rejection. Thank the recruiter "
        "for their time, express continued interest in the company, and politely "
        "ask to be considered for future openings."
    ),
}

# Maps an application status to the most likely follow-up stage.
STATUS_TO_STAGE = {
    "applied": "post_application",
    "interview": "post_interview",
    "offer": "offer",
    "rejected": "rejection",
}


async def generate_follow_up(
    resume_id: str,
    job: dict,
    stage: str,
    days_since: int | None = None,
) -> str:
    """Draft a stage-aware follow-up email for ``job``.

    Returns the drafted text. Raises ValueError if the resume can't be found,
    the stage is unknown, or no LLM provider is reachable.
    """
    if stage not in _STAGE_PROMPTS:
        raise ValueError(
            f"Unknown stage '{stage}'. Must be one of: {', '.join(_STAGE_PROMPTS)}"
        )

    parsed = resume_store.load_parsed(resume_id)
    if parsed is None:
        raise ValueError(
            f"No resume found for resume_id '{resume_id}'. Upload a resume first."
        )

    # Build resume context (graph-based, same as cover letter).
    skills_raw = ", ".join(parsed.sections.get("skills", []))
    bullets = [{"section": b.section, "text": b.text} for b in parsed.bullets]
    graph = extract_resume_graph(bullets, skills_raw)

    jd_text = job.get("description") or job.get("jd_text") or ""
    stopwords = {"about", "your", "role", "company", "team", "must", "have", "with", "this", "that", "from"}
    jd_keywords = list(set(re.findall(r"\b[a-zA-Z]{5,}\b", jd_text.lower())) - stopwords)
    subgraph = graph.subgraph_for_keywords(jd_keywords[:20])
    resume_context = subgraph.to_prompt_context()
    if len(subgraph.nodes) < 5:
        resume_context = (
            f"=== Resume Text ===\n{(parsed.raw_text or parsed.ats_visible_text or '')[:4000]}"
        )

    contact = parsed.contact or {}
    name = contact.get("name") or "the candidate"
    title = job.get("title", "the role")
    company = job.get("company", "your company")

    timing = ""
    if days_since is not None:
        timing = f"The application was submitted about {days_since} day(s) ago. "

    system = (
        "You are an experienced career communicator drafting a genuine, human "
        "follow-up email. Ground every claim only in the provided resume context. "
        "Never invent titles, projects, achievements, or contact details not present "
        "in the resume. Be warm, concise, and professional. Do not include a subject "
        "line unless asked. Output only the email body."
    )

    user_prompt = (
        f"{_STAGE_PROMPTS[stage]}\n\n"
        f"ROLE: {title} at {company}\n"
        f"RECIPIENT/CANDIDATE NAME: {name}\n"
        f"{timing}"
        f"JOB DESCRIPTION:\n{jd_text[:1500]}\n\n"
        f"RELEVANT RESUME CONTEXT:\n{resume_context}"
    )

    resp = await router.chat(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
        tier="simple",
        max_tokens=500,
        temperature=0.6,
    )

    text = (resp.get("content") or "").strip()
    if not text:
        raise ValueError("The LLM returned an empty follow-up email. Try again.")
    return text
