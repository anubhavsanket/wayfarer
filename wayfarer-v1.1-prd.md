# PRD: Wayfarer — AI-Powered Job Search Automation Platform

**Author:** Anubhav
**Version:** 1.1
**Date:** August 2026
**Status:** Draft — ready for build
**Working name:** Wayfarer (domain `wayfarer.run` — reserve once the project is validated)

---

## 1. Overview & Vision

**Wayfarer** — a locally-hosted, RAG-driven job search platform built in three connected stages: a web search agent, a RAG-based ATS resume checker with redlining, and a live job-posting matcher. The system is designed as an AI engineering portfolio piece — the differentiator isn't the workflow (several tools already do parts of this), it's that the retrieval, scoring, and matching logic is **built and owned**, not delegated to a general-purpose coding agent's context window.

Target outcome: a working, demoable system that Anubhav also uses for his own job search, deployed as callable services (not a CLI tool), running within a 4GB VRAM budget with free-tier API fallback for anything heavier.

## 2. Problem Statement

- Manually searching multiple job boards and reading postings one by one doesn't scale
- ATS systems silently reject resumes for structural/parsing reasons the candidate never sees
- Tailoring a resume per JD is slow, and naive tools solve it by keyword-stuffing, which is dishonest and often backfires in interviews
- The closest existing OSS project (`ai-job-search`, 28.6k★) solves this well at the *product* level but is architecturally a Claude Code prompt-orchestration framework — no embeddings, no vector store, no owned retrieval engine — and is Denmark-market-first. That leaves a real gap for an India-first, RAG-engineered version.

## 3. Competitive Differentiation

| Dimension | `ai-job-search` | `career-ops` (61.9k★) | This project |
|---|---|---|---|
| Core engine | Claude Code slash commands + prompt orchestration | Any AI coding CLI + markdown/YAML state, agent reasoning | Owned RAG pipeline — embeddings, vector store, hybrid scoring |
| Deployment | CLI, requires Claude Code + LaTeX toolchain | CLI, requires an AI coding CLI (Claude Code/Codex/etc.) | FastAPI services, callable/deployable independently |
| Resume handling | Generates a fresh CV per job (LaTeX, from scratch) | Generates a fresh ATS-optimized PDF per job | Redlines the user's *existing* resume with tracked suggestions |
| Market | Denmark-first; LinkedIn/freehire are the only country-agnostic portals | Global, AI/tech-role-first (45+ pre-configured companies) | India-first (Bengaluru context, Naukri/LinkedIn India) |
| Inference reliability | Assumes a paid Claude subscription | CLI-agnostic, supports free/local models | Multi-provider router (NVIDIA NIM / OpenRouter free tiers) with rate-limit fallback |
| Transparency | Keyword-honesty rule (binary: kept or flagged as gap) | 6-block evaluation + explicit human-in-the-loop, never auto-applies | Confidence-tiered suggestions: Verified / Reworded / Gap |
| ATS check | Extracts PDF text layer, checks keyword coverage | Keyword-injected PDF generation | Same idea, plus a visual redline diff showing exactly what to change and where |
| Posting trust | Not addressed | Ghost-job/scam detection + sponsorship blocker (adopted here — see §9) | Same check, adopted from career-ops |

Where it's *not* differentiated (and shouldn't try to be): job-fit scoring, deal-breaker filtering, honest-gap reporting, human-in-the-loop as a principle. Those are solved problems, proven at scale by `career-ops` in particular — replicate them, don't reinvent. The one structural thing every prior-art entry shares, and the one place this project stays genuinely different, is that they all delegate matching intelligence to a general-purpose coding agent's reasoning over text files, while this project builds and owns the retrieval/embedding layer directly.


## 4. Goals / Non-Goals

**Goals**
- G1: Ship all three stages as working, independently demoable services
- G2: Stay within 4GB VRAM for local components; route to free-tier APIs for anything heavier (reuse the LLM router project as the inference abstraction layer)
- G3: Reuse proven patterns from prior projects — ChromaDB + Ollama setup from LocalBrain, confidence scoring from the real estate RAG project
- G4: Dogfood it — actually use it for the real job search, not just as a demo
- G5: **Human-in-the-loop, always.** The system evaluates, ranks, and drafts (redlines, match scores) — it never submits, auto-fills, or clicks anything on a third-party site on the user's behalf. This is both an ethical stance and a direct mitigation for the ToS risk flagged in the Risks section around scraping job boards.

**Non-goals (v1)**
- No multi-user accounts / SaaS layer — single-user local tool
- No fresh resume generation from scratch — editing/redlining an existing resume only
- No massive-scale scraping — a handful of sources done well (bluedoor + 1-2 India-specific sources) beats broad, fragile coverage
- No native Word track-changes XML in v1 — HTML/artifact-style diff view first, `.docx` track-changes is a v2 stretch goal

## 5. Users & Core Use Cases

Primary user: solo AI/GenAI job seeker in India (self). Three core use cases, one per stage:

- **UC1** — "Search the web for X and synthesize an answer with sources" (general-purpose, reusable beyond job search)
- **UC2** — "Check my resume against this JD, tell me exactly what to change and why"
- **UC3** — "Show me live postings ranked by fit, with apply links"

## 6. System Architecture

```
                    ┌─────────────────────────────┐
                    │        LLM Router            │
                    │  (existing project — reused) │
                    │  NVIDIA NIM ⇄ OpenRouter      │
                    │  rate-limit-aware fallback    │
                    └───────────────┬───────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        │                           │                           │
┌───────▼────────┐      ┌───────────▼──────────┐     ┌───────────▼──────────┐
│   Stage 1       │      │       Stage 2         │     │       Stage 3         │
│  Search Agent   │      │  Resume/ATS Checker    │     │   Job Matcher         │
│                 │      │                        │     │                       │
│ Search API      │      │ pdfplumber/python-docx │     │ bluedoor.sh API       │
│ (Tavily/Brave)  │      │ pdftotext ATS sim      │     │ LinkedIn/Naukri (IN)  │
│ + Crawl4AI      │      │ Embedding matcher      │     │ Reuses Stage 2's      │
│ fetch/clean     │      │ Confidence-tiered      │     │ matching engine       │
│                 │      │ redline generator      │     │ in a loop             │
└─────────────────┘      └────────────────────────┘     └───────────────────────┘
        │                           │                           │
        └───────────────────────────┴───────────────────────────┘
                                    │
                        ┌───────────▼───────────┐
                        │       ChromaDB          │
                        │  (separate collections  │
                        │   per stage, shared      │
                        │   embedding model:       │
                        │   nomic-embed-text)      │
                        └─────────────────────────┘
```

**Shared infrastructure (build once, use in all 3 stages):**
- **LLM Router** — your existing free-tier routing project. Every stage calls inference through this, not directly against a provider. This is also the piece that most visibly demonstrates production-thinking to an interviewer, so it's worth surfacing in the README as shared infra, not buried.
- **Embedding layer** — `nomic-embed-text` via Ollama, same config that worked in LocalBrain. Keep it local; embeddings are cheap enough on the 1650 that this shouldn't need router fallback.
- **ChromaDB** — one persistent store, separate collections: `search_cache`, `resume_sections`, `job_postings`. Avoids cross-contamination between stages while sharing the embedding space for Stage 2 ↔ Stage 3 reuse.
- **Confidence-scoring module** — pull this out of the real estate project as a standalone utility rather than reimplementing. Same Verified/Inferred/Gap logic applies almost directly to resume matching.

---

## 7. Stage 1 — Web Search Agent

### 7.1 Functional Requirements
- FR1.1: Accept a natural-language query, decompose into 1–3 search sub-queries if the question is multi-part or vague
- FR1.2: Hit a search API (Tavily primary, Brave as fallback) to get ranked URLs
- FR1.3: Fetch + clean top-N pages via Crawl4AI (fit-markdown mode, noise stripped)
- FR1.4: Synthesize an answer via the LLM router, with inline citations mapped to source URLs
- FR1.5: Cache fetched pages in ChromaDB (`search_cache` collection) keyed by URL hash, with a TTL, to avoid re-fetching on repeated queries

### 7.2 API Design

```
POST /search
Body: { "query": string, "max_sources": int (default 5) }
Response: {
  "answer": string,
  "citations": [ { "id": int, "url": string, "title": string, "snippet": string } ],
  "sub_queries_used": [string]
}
```

### 7.3 Tech Stack
- Search: Tavily API (free tier) → Brave Search API (fallback)
- Fetch/clean: Crawl4AI (`AsyncWebCrawler`, fit-markdown generator, HTTP-only strategy for non-JS pages to save resources; Playwright strategy only when needed)
- Synthesis: LLM router → NVIDIA NIM / OpenRouter free-tier models
- Cache: ChromaDB

### 7.4 Non-Functional Requirements
- NFR1.1: p95 latency under 8s for a single-query answer (search + fetch of 3-5 pages + synthesis)
- NFR1.2: Concurrency-cap Crawl4AI fetches (e.g. max 3 concurrent Playwright instances) to bound RAM use
- NFR1.3: Graceful degradation — if Crawl4AI fetch fails on a URL, fall back to the search API's snippet rather than dropping the source entirely

### 7.5 Acceptance Criteria
- [ ] Given a multi-part query, sub-queries are generated and each is searched independently
- [ ] Every claim in the synthesized answer maps to at least one citation
- [ ] Repeated identical queries within the TTL window return cached results without re-fetching

---

## 8. Stage 2 — RAG-Based ATS Resume Checker

### 8.1 Functional Requirements
- FR2.1: Parse an uploaded resume (PDF/DOCX) into structured sections (contact, skills, experience bullets, education)
- FR2.2: Run an **ATS parsing simulation** — extract text the way a naive ATS parser would (layout-blind extraction via `pdftotext`-equivalent), and diff against the properly structured extraction to flag structural loss (tables, multi-column sections, headers/footers that vanish)
- FR2.3: Extract JD keywords (skills, tools, certifications) via LLM pass
- FR2.4: For each JD keyword missing from the ATS-visible text, search the user's existing bullets for genuinely related evidence via embedding similarity — do **not** literal-swap words
- FR2.5: Classify every suggestion into one of three confidence tiers:
  - **Verified** — keyword present near-verbatim, just needs surfacing/reordering
  - **Reworded** — real underlying experience exists, bullet rewritten to use JD terminology, facts/metrics unchanged
  - **Gap** — no supporting evidence found; flagged, never auto-inserted
- FR2.6: Render a redline view — side-by-side original vs. suggested bullet, color-coded by tier, with a one-line rationale per change
- FR2.7: Overall ATS score = weighted combination of (a) structural parseability and (b) keyword coverage on ATS-visible text only
- FR2.8: After the user reviews and accepts/rejects individual redline suggestions, let them choose to **save as a new file** (default, non-destructive) or **overwrite the original** upload. Overwrite requires an explicit confirmation step — never silently replace the source resume.

### 8.2 Core Matching Function

```python
def match_keyword_to_bullet(
    jd_keyword: str,
    resume_bullets: list[ResumeBullet],
    similarity_threshold: float = 0.75
) -> MatchResult:
    """
    Returns one of:
    - {tier: "verified", bullet_id, confidence}
    - {tier: "reworded", bullet_id, rewritten_text, confidence}
    - {tier: "gap", confidence: None}
    Never inserts a keyword with no supporting bullet, regardless of tier.
    """
```

### 8.3 API Design

```
POST /resume/check
Body: {
  "resume_file": file (pdf/docx),
  "jd_text": string
}
Response: {
  "ats_score": float,
  "structural_issues": [ { "location": string, "issue": string } ],
  "keyword_gaps": [
    {
      "keyword": string,
      "tier": "verified" | "reworded" | "gap",
      "bullet_id": string | null,
      "original_text": string | null,
      "suggested_text": string | null,
      "rationale": string
    }
  ]
}
```

```
POST /resume/save
Body: {
  "resume_id": string,
  "accepted_suggestions": [ { "bullet_id": string, "suggested_text": string } ],
  "mode": "new_file" | "overwrite",
  "confirm_overwrite": bool  // required true if mode == "overwrite", else request is rejected
}
Response: {
  "file_id": string,
  "file_ref": string,       // path/URL to the saved file
  "mode_applied": "new_file" | "overwrite"
}
```

### 8.4 Tech Stack
- Parsing: `pdfplumber` / `python-docx` for structured extraction; `pdftotext`-equivalent (or a layout-blind PyPDF read) for the ATS simulation pass
- Embeddings: `nomic-embed-text` (same as Stage 1/LocalBrain)
- Vector store: ChromaDB `resume_sections` collection
- LLM: router, for keyword extraction and rewrite generation
- Redline rendering: HTML/artifact diff view for MVP; `.docx` OOXML track-changes as a v2 stretch

### 8.5 Acceptance Criteria
- [ ] A resume with a table-based skills section shows a structural-loss flag on that section
- [ ] No keyword is ever inserted into a suggested rewrite without a traceable source bullet
- [ ] Every suggestion carries a visible confidence tier in the output
- [ ] ATS score changes measurably (and correctly) when a structural issue is fixed vs. when only a keyword is added
- [ ] Default save mode never overwrites the original file; overwrite only happens with explicit confirmation, and the original is retained in `documents/` history until overwrite is confirmed

### 8.6 Primary Resume Management (Settings) — v1, cross-stage

Closes a gap in the original design: Stage 3's `/jobs/match` has always taken a `resume_id`, but v1 never defined where that ID comes from — Stage 2 only handled ad-hoc per-check uploads. A Settings-page primary resume is the one-stop source of truth both stages read from, without losing the ability to test one-off variants.

- **FR2.9**: Settings page has a single **Primary Resume** upload slot — upload, replace, or view the currently active file and when it was last updated. Only one resume can be marked primary at a time (`Resume.is_primary: bool`).
- **FR2.10**: `/resume/check` accepts an optional file upload. If omitted, it checks the primary resume from Settings against the supplied JD. If a file is provided, it's treated as a **one-off variant check** — scored and redlined, but never silently replaces the primary.
- **FR2.11**: `/resume/save` (§8.3) gains a third `mode`: `"set_as_primary"`, alongside the existing `"new_file"` and `"overwrite"`. Promoting a checked/redlined variant to primary is always an explicit user action, consistent with G5 (human-in-the-loop) — nothing gets auto-promoted just because it was checked.
- **FR2.12**: `/jobs/match`'s `resume_id` param (§9.2) becomes optional — when omitted, Stage 3 matches against the current primary resume. This removes the ambiguity that existed in the original Stage 3 spec about where matching input comes from.

**Data model:** `Resume` gains `is_primary: bool`, `uploaded_at: timestamp`. No separate settings entity needed — the primary pointer lives on the resume record itself, avoiding a second source of truth to keep in sync.

**Acceptance criteria:**
- [ ] Uploading a resume in Settings makes it the one Stage 3 matches against by default, with no other configuration required
- [ ] Checking a one-off variant via `/resume/check` never changes which resume Stage 3 uses, unless the user explicitly selects `"set_as_primary"`
- [ ] `/jobs/match` called with no `resume_id` uses the current primary resume without error

---

## 9. Stage 3 — Live Job Posting Matcher

### 9.1 Functional Requirements
- FR3.1: Fetch active postings from bluedoor.sh (free tier, US-focused) and at least one India-specific source (LinkedIn public guest job endpoints, or a scraped source — check ToS before implementing)
- FR3.2: Embed each JD into `job_postings` collection
- FR3.3: For the user's resume, compute a hybrid match score per posting = semantic similarity + keyword overlap (**reusing Stage 2's `match_keyword_to_bullet` function** — this is the key architectural reuse point)
- FR3.4: Rank postings by match score, surface top-N with direct apply link
- FR3.5 (stretch): Cross-JD aggregation — across all fetched postings, surface the highest-frequency *missing* skill, reframing the output as "learn X next" rather than "fix this one application"
- FR3.6: Accept a **location preference** as part of the match request — one or more of: a specific city, "remote only," "hybrid," or "open to relocation" (with an optional list of acceptable cities/regions). Use this to filter and re-rank postings rather than hardcoding any single city into the pipeline, so the tool is useful for job seekers outside Bengaluru without code changes
- FR3.7: **Config-driven job board registry** — job sources (bluedoor, LinkedIn guest endpoints, any future board) are defined in a config file, not hardcoded in application logic. Adding a new board is a config change, not a code change. This is the primary lever for making the tool usable outside India/Bengaluru without forking the codebase.
- FR3.8: **Posting legitimacy check** — flag likely scam/ghost postings (vague description, no verifiable company info, suspiciously high comp for the role, identical text repeated across many listings) before surfacing them as matches. Also flag an explicit "no visa sponsorship" statement as a hard blocker for candidates who indicated they'd need one, rather than silently ranking it alongside viable postings.
- FR3.9: **Pipeline integrity** — a lightweight maintenance pass on `job_postings` that merges duplicate listings pulled from multiple sources (same role, different board), normalizes status/location fields across sources, and drops stale entries past a TTL. Runs as part of the background refresh job (backed by the `redis` queue in §13's Docker Compose stack), not on the request path.

*(Fresher Mode was originally scoped here as FR3.10 — deferred to v2, full design preserved in §15.)*

### 9.2 API Design

```
GET /jobs/match?resume_id={id}&limit=20
Body/Query params: {
  "location_preference": {
    "mode": "specific_city" | "remote_only" | "hybrid" | "open_to_relocation",
    "cities": [string],       // used for specific_city or open_to_relocation
    "remote_ok": bool         // true if remote postings should be included alongside city matches
  }
  // fresher_only param deferred to v2 — see §15 for the full design
  // (fresher_only flag, unclear_matches array, experience_level field)
}
Response: {
  "matches": [
    {
      "job_id": string,
      "title": string,
      "company": string,
      "source": string,
      "location": string,
      "match_score": float,
      "location_match": "exact" | "remote" | "relocation_required" | "none",
      "top_gaps": [string],
      "apply_url": string
    }
  ],
  "aggregate_gaps": [ { "skill": string, "missing_in_pct": float } ]
}
```

### 9.3 Tech Stack
- Data sources: bluedoor.sh API (free tier), LinkedIn guest job endpoints (personal-use rate limits — keep volume low)
- Matching: same embedding + keyword engine as Stage 2, called per posting
- Store: ChromaDB `job_postings` collection

### 9.4 Job Board Registry (config-driven)

Every job source is defined as an entry in `config/job_boards.yaml`, not as bespoke code per board:

```yaml
job_boards:
  - name: bluedoor
    enabled: true
    type: rest_api
    base_url: "https://api.bluedoor.sh/v1/postings"
    auth: none
    rate_limit_per_min: 60
    field_mapping:
      title: "$.job_title"
      company: "$.employer_name"
      location: "$.location.city"
      remote_type: "$.location.remote"
      url: "$.apply_url"
      description: "$.description_text"
    pagination:
      type: "offset"
      param: "page"

  - name: linkedin_guest
    enabled: true
    type: rest_api
    base_url: "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    auth: none
    rate_limit_per_min: 20
    field_mapping:
      title: "$.title"
      company: "$.company.name"
      location: "$.formattedLocation"
      url: "$.jobPostingUrl"
    pagination:
      type: "start_offset"
      param: "start"

  # Adding a new board = adding an entry here, not writing new fetch/parse code
  - name: custom_board_example
    enabled: false
    type: rest_api
    base_url: "https://example-jobboard.com/api/jobs"
    auth: api_key
    api_key_env: "CUSTOM_BOARD_API_KEY"
    rate_limit_per_min: 30
    field_mapping:
      title: "$.title"
      company: "$.company"
      location: "$.city"
      url: "$.link"
```

A single `JobBoardConnector` class reads this config, handles pagination and rate limiting generically, and maps each source's response fields to the shared `JobPosting` schema via the `field_mapping` (JSONPath-style). Boards needing HTML scraping instead of a REST API get a `type: html_scrape` variant with CSS selectors in place of `field_mapping` — same registry, same loader interface, different extraction strategy under the hood. This is the mechanism that lets someone outside India point the tool at their own local job board without touching Python.

### 9.5 Known Limitation
bluedoor.sh's postings are predominantly US-based. For a Bengaluru-relevant demo, either supplement with an India-specific source or explicitly frame the demo around remote/global roles where bluedoor's coverage is stronger. Document this limitation in the README rather than overselling coverage.

### 9.6 Acceptance Criteria
- [ ] Match scores correlate sensibly with manual eyeballing on a test set of 10 postings
- [ ] Apply links resolve to the actual posting, not a dead/expired link (basic liveness check before surfacing)
- [ ] Aggregate gap analysis correctly identifies a skill missing in >50% of postings on a synthetic test batch
- [ ] Setting `location_preference` to a city other than Bengaluru returns relevant postings for that city without requiring any code or config changes — location logic is fully parameterized, not hardcoded
- [ ] Adding a new job board to `job_boards.yaml` and setting `enabled: true` surfaces its postings in `/jobs/match` without any Python changes, for a board that fits the existing `rest_api` type
- [ ] A synthetic ghost-job posting (vague description, no company info, inflated comp) is flagged rather than surfaced as a clean match
- [ ] A posting containing an explicit no-sponsorship clause is marked as a hard blocker when the user's profile indicates they need sponsorship
- [ ] Re-running the background refresh on an unchanged set of postings does not create duplicate entries for the same role pulled from two sources

---

## 10. Data Model (core entities)

| Entity | Key fields |
|---|---|
| `SearchQuery` | id, raw_query, sub_queries[], timestamp |
| `SearchResult` | id, url, title, cleaned_markdown, fetched_at |
| `Resume` | id, raw_file_ref, parsed_sections{}, ats_visible_text |
| `ResumeBullet` | id, resume_id, section, text, embedding |
| `JobDescription` | id, source, raw_text, extracted_keywords[], embedding |
| `MatchResult` | resume_id, jd_id, keyword, tier, bullet_id, confidence |
| `JobPosting` | id, source, title, company, url, jd_id, fetched_at, location, remote_type |
| `UserPreference` | resume_id, location_mode, preferred_cities[], remote_ok |

## 11. Phased Roadmap

| Phase | Duration | Deliverable |
|---|---|---|
| Phase 0 | 2–3 days | Repo scaffold, LLM router wired in as shared dependency, ChromaDB collections defined |
| Phase 1 | Week 1–2 | Stage 1 working end-to-end: `/search` endpoint, Crawl4AI + Tavily integrated, citation mapping |
| Phase 2 | Week 3–5 | Stage 2: parsing sim, keyword matcher, confidence tiers, redline view. This is the largest stage — budget extra time for the honest-substitution logic |
| Phase 3 | Week 6–7 | Stage 3: bluedoor integration, India source, hybrid scoring reusing Stage 2's matcher |
| Phase 4 | Week 8 | Polish: aggregate gap analysis, README with differentiation section, deploy as a demoable service |

## 12. Token & Cost Optimization Strategy

Free-tier API budgets are the binding constraint on this whole system (this is *why* the LLM router exists), so token efficiency isn't a nice-to-have — it directly determines how usable Stage 3 is, since matching one resume against N postings naively means N full LLM calls with the full resume re-sent every time.

### 12.1 Structured resume memory (graph-based, not re-sent full text)

Instead of passing the full resume text into every LLM call (Stage 2 keyword matching, Stage 3 per-posting scoring), parse the resume **once** into a lightweight entity graph and reference it by ID thereafter:

- Nodes: skills, roles, projects, tools, metrics — each extracted once during `/resume/check`
- Edges: "used_in" (skill → project), "demonstrates" (project → metric), "held" (role → date range)
- Store as a simple graph structure (NetworkX + JSON is enough for v1 — no need for a dedicated graph DB at this scale) alongside the existing ChromaDB embeddings

For Stage 3's per-posting loop, instead of re-sending the full resume text N times, pull only the subgraph relevant to that JD's keywords (a handful of nodes + their edges) — this is the single biggest token saver in the whole pipeline, since it turns an O(N × full_resume_tokens) cost into O(N × relevant_subgraph_tokens). This is also a good one to write up explicitly in your portfolio README — "structured memory instead of re-prompting" is a real architectural decision, not just a cost hack.

### 12.2 Embedding-first filtering before any LLM call

Never call an LLM to evaluate a JD-resume pair that embedding similarity has already ruled out. The filter is actually three stages, cheapest first:

1. **Zero-token discovery + dedup** — new postings are deduped against already-seen ones (URL/content hash) and dead/expired listings are dropped via a lightweight liveness check (HTTP HEAD or a fast fetch), with no LLM or embedding call involved at all
2. **Embedding similarity** — cheap vector comparison ranks the surviving postings
3. **LLM evaluation** — expensive calls only run on the top-K survivors of steps 1-2, not the full set

This alone typically cuts LLM call volume by 5-10x in a matching loop, and step 1 alone (dedup + liveness before spending anything) prevents the common failure mode of re-scoring the same stale posting on every refresh.

### 12.3 Prompt/context caching

Route repeated system prompts and the resume subgraph context through whichever provider's prompt-caching feature is available via the router (Anthropic prompt caching, Gemini context caching, etc. — the router should abstract this so the caller doesn't need to know which). The resume context is the same across all N posting comparisons in a session — that's exactly what caching is for.

### 12.4 Response caching / memoization

Extend the same content-hash caching pattern already planned for Stage 1 (`search_cache`) to Stage 2/3: memoize on `hash(resume_version + jd_text)` so re-running a check on an unchanged resume against a previously-seen JD is a cache hit, not a fresh set of calls.

### 12.5 Right-size the model per sub-task via the router

Not every call needs the same model. Keyword extraction and tier classification are cheap, structured tasks — route these to the smallest/fastest free-tier model available. Reserve larger models for the actual bullet-rewrite generation, where quality matters most.

### 12.6 Strip JD boilerplate before embedding or prompting

Most JDs carry 30-50% boilerplate (company blurb, benefits, EEO statements) irrelevant to matching. A cheap regex/heuristic pass to strip these sections before embedding or LLM calls reduces both token cost and noise in the similarity signal.

## 12.7 Frontend Architecture

Recommendation: **React + Vite + TypeScript + Tailwind/shadcn** (reusing the stack from the earlier App Graph Builder UI PRD), served as its own container in the Docker Compose stack, browser-based with zero install.

Rejected/limited-use options:
- **Tauri** — native desktop binary per platform is friction against wide usability, and adds a Rust toolchain to a project whose portfolio value is the RAG/AI engineering. Reasonable v2 idea for an "offline app with bundled local LLM," not a v1 fit.
- **Streamlit / Gradio** — good for fast internal iteration while building each stage's backend (Gradio in particular for file-upload + chat-style testing of Stage 1/2), but not the shipped product. Use as a disposable dev harness, not the final UI.

## 13. Deployment: Docker Compose

Single-command self-hosting is a direct differentiator vs. `ai-job-search` (which requires the Claude Code CLI + a LaTeX toolchain as prerequisites). Goal: `docker compose up` gets a stranger from zero to a running instance.

```yaml
# docker-compose.yml
version: "3.9"

services:
  api:
    build: ./backend
    ports:
      - "8000:8000"
    environment:
      - CHROMA_HOST=chromadb
      - OLLAMA_HOST=ollama
      - TAVILY_API_KEY=${TAVILY_API_KEY}
      - BRAVE_API_KEY=${BRAVE_API_KEY}
      - NVIDIA_NIM_API_KEY=${NVIDIA_NIM_API_KEY}
      - OPENROUTER_API_KEY=${OPENROUTER_API_KEY}
    depends_on:
      - chromadb
      - ollama
      - redis
    volumes:
      - ./data/uploads:/app/uploads

  chromadb:
    image: chromadb/chroma:latest
    ports:
      - "8001:8000"
    volumes:
      - chroma_data:/chroma/chroma

  ollama:
    image: ollama/ollama:latest
    ports:
      - "11434:11434"
    volumes:
      - ollama_data:/root/.ollama
    # GPU passthrough — omit the `deploy` block entirely on machines
    # without an NVIDIA GPU; the router falls back to API inference
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  frontend:
    build: ./frontend
    ports:
      - "3000:3000"
    depends_on:
      - api

volumes:
  chroma_data:
  ollama_data:
```

**Notes:**
- The `ollama` service's GPU `deploy` block is optional — on a machine without an NVIDIA GPU (or without `nvidia-container-toolkit` installed), remove it and the LLM router falls back entirely to NIM/OpenRouter API inference. This is exactly the fallback behavior the router already needs to support, so no special-casing required.
- A `.env.example` should ship in the repo listing every required key (`TAVILY_API_KEY`, `BRAVE_API_KEY`, `NVIDIA_NIM_API_KEY`, `OPENROUTER_API_KEY`, any per-job-board keys from the registry), so setup is copy `.env.example` → `.env` → fill in keys → `docker compose up`.
- `redis` backs the background job queue from the earlier efficiency suggestions (periodic posting refresh) — include it from the start rather than retrofitting.
- Post-launch smoke test: a fresh clone, `docker compose up`, and a successful `/search` call should work in under 5 minutes on a machine with no prior setup. Treat that as an acceptance bar, not just a nice-to-have.

## 14. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| bluedoor.sh's US-focus limits India relevance | Document limitation explicitly; supplement with a second source |
| Scraping India job boards may violate ToS | Check robots.txt/ToS per source before implementing; prefer public API endpoints (LinkedIn guest, similar) over HTML scraping; keep volume low, personal-use framing |
| Free-tier LLM APIs rate-limit under load | This is the entire reason the LLM router exists — make sure Stage 2/3 actually route through it rather than hardcoding one provider |
| Redline logic silently hallucinates a skill | Hard rule: no keyword insertion without a traceable source bullet above the similarity threshold; gaps stay gaps |
| VRAM overload replicating the LocalBrain phi4-mini issue | Cap embedding model context, reuse the known-stable local config, keep synthesis calls on the router (API-side) rather than local inference |

## 15. Open Questions / Future Scope
- Track-changes native `.docx` export (v2)
- Application outcome tracking / dashboard (out of scope for v1, but a natural v2 given how much of `ai-job-search`'s value came from `/outcome` + `/html-report`)
- Interview prep module — explicitly deferred; not a differentiator worth building before the core 3 stages are solid

### 15.1 Fresher Mode (v2) — full design, deferred from Stage 3

Deferred so v1's core three pipelines (already ~75% built and working end-to-end) ship clean, rather than absorbing a new feature axis mid-stream. Full spec preserved here so it's ready to implement without re-deriving it.

**Requirement:** a UI toggle that filters postings to those requiring ≤1 year of experience (0-1 yrs, "entry level," "fresher," "graduate," "no experience required"). Layered extraction, cheapest first:
1. **Structured field first** — some ATS sources (Ashby, Greenhouse) tag postings with an explicit seniority/level field in their API response; map it via the registry's `field_mapping` when present, rather than re-parsing text that's already structured upstream
2. **Regex fallback** — common patterns in the raw JD text: `\d+\s*[-–+]\s*\d*\s*years?`, "entry level," "fresher," "graduate program," "no prior experience"
3. **LLM fallback** — for postings where neither above yields a confident answer; cheap structured-output task, route to the small local model tier per §12.5
4. **Unclear postings get their own section, collapsed by default** — don't silently exclude postings that couldn't be confidently parsed, but don't blend them into the confirmed list either. A false exclusion (hiding a genuinely fresher-friendly role over a parsing gap) is worse than a false inclusion for this audience.

**Data model additions (JobPosting):** `min_experience_years: float | null`, `experience_level: "fresher" | "junior" | "mid" | "senior" | "unclear"`, `experience_source: "structured" | "regex" | "llm"`. **UserPreference addition:** `fresher_mode: bool`.

**API:**
```
GET /jobs/match?resume_id={id}&limit=20
Body/Query params: {
  ...(location_preference as in §9.2)...
  "fresher_only": bool   // filters both arrays below
}
Response: {
  "matches": [ /* same shape as v1, plus min_experience_years, experience_level (never "unclear" here) */ ],
  "unclear_matches": [
    // same shape, experience_level always "unclear", only populated when fresher_only is true.
    // Rendered as a collapsed section — "these might work, but we're not sure" — revealed by
    // a dedicated button, not shown by default. Confirmed list stays trustworthy on its own.
  ],
  "aggregate_gaps": [ ... ]
}
```

**Acceptance criteria (v2):**
- [ ] With `fresher_only: true`, a posting explicitly requiring 3+ years is excluded and one explicitly labeled "entry level"/"fresher" is included
- [ ] A posting with no stated experience requirement lands in `unclear_matches`, not `matches` — never silently dropped, never blended into the confirmed list
- [ ] A posting with a structured level field from the source ATS uses that field directly rather than re-parsing the JD text
### 15.2 Employment-Type Filter / "Freelancer Mode" (v2) — lightweight version

Same shape as Fresher Mode (§15.1) — a classification field plus a toggle — so it's grouped with it rather than treated as a separate vertical. **Explicitly scoped as the lightweight option**: tagging postings already present in existing sources by employment type, not integrating a new freelance marketplace (see §15.3 for that larger, separately-scoped idea).

**Requirement:** surface a toggle that filters `job_postings` to contract/freelance-tagged roles. Several existing sources already carry this signal without any new data source needed:
- Structured field first — Greenhouse, Lever, and Adzuna responses typically include an employment-type field (`full_time`, `contract`, `part_time`, `freelance`/`1099`); map it via the registry's `field_mapping`, same pattern as the experience-level structured-field lookup in §15.1
- Regex/LLM fallback only where the source doesn't expose it structurally, reusing the same layered-extraction pattern and cheap-model routing as §15.1

**Data model addition (JobPosting):** `employment_type: "full_time" | "contract" | "freelance" | "part_time" | "unclear"`. **UserPreference addition:** `employment_type_filter: string[]` (multi-select, since someone might want both full-time and contract roles surfaced together, not an exclusive toggle).

**Why bundle with Fresher Mode rather than build standalone:** both are single-field classification + filter features on postings you're already fetching, both reuse the same structured-field-first / regex / LLM-fallback pattern, and both plug into the same `/jobs/match` request/response shape. Building them together when v2 work starts is more efficient than treating them as two separate mini-projects.

**Acceptance criteria (v2):**
- [ ] A posting tagged `contract` or `freelance` in its structured source field is classified correctly without falling through to regex/LLM
- [ ] Filtering to `employment_type_filter: ["freelance", "contract"]` excludes full-time-only postings and includes both freelance and contract postings together

### 15.3 Full Freelance Marketplace Integration (v3, not yet scoped) — the bigger version

Deliberately kept separate from §15.2 because it's a different scope of work, not a bigger version of the same feature. Noted here so the idea isn't lost, not committed to a timeline.

- **New data source category**: Upwork's GraphQL API supports OAuth-authenticated job search with a 40K requests/day limit, but access requires applying for developer credentials through Upwork's approval process — unlike Adzuna's instant free-tier signup, this isn't guaranteed for a solo portfolio project. Validate access before committing engineering time.
- **ATS-simulation (Stage 2) doesn't apply** — freelance platforms match profile-to-project, not resume-to-JD via ATS parsing.
- **Redlining shifts from resume bullets to proposal drafting** — same "no fabricated claims, confidence-tiered suggestions" principle as Stage 2, different content type and generation target.
- **Natural fit with G5 (human-in-the-loop)**: Upwork's own proposal-submission flow is locked to their UI with no public apply endpoint, so "draft the proposal, human submits it" isn't a workaround — it's the only compliant integration shape anyway.
- **Ghost-job/scam detection (FR3.8) is more valuable here, not less** — client-side scams (unpaid milestones, fake projects) are a well-known problem on freelance marketplaces.

### 15.4 Company Research Brief (v2) — reuses Stage 1, no new pipeline

On clicking into a specific job match, surface a short auto-generated brief (recent funding/news, what the company does, size/stage if discoverable) by calling **Stage 1's existing search agent** with a company-scoped query — not a fourth data pipeline. This is the clearest example in the whole project of the three stages composing into a capability none of them has alone, worth calling out explicitly in the README/portfolio narrative as an architecture decision, not just a feature.

- **FR3.11**: `GET /jobs/{job_id}/brief` triggers a Stage 1 `/search` call scoped to the company name + "funding news company overview," returns the same `{answer, citations}` shape Stage 1 already produces
- Cache the brief per company (not per posting) in `search_cache` — many postings share a company, no reason to re-run the search for each one
- Reuses Stage 1's existing citation/synthesis pipeline as-is; no new extraction, matching, or scoring logic needed

**Acceptance criteria (v2):**
- [ ] Requesting a brief for a company already cached (from a prior posting at the same company) returns instantly without a new search
- [ ] The brief's citations resolve to real, fetchable sources, same standard as Stage 1's existing citation requirement

---

### 15.5 Job Search Analytics Dashboard (v3, not yet scoped)

Tracks match scores, applied-vs-matched funnel, and aggregate skill-gap trends over time; extends into outcome tracking once that exists. Deliberately built as a BI-style dashboard (KPI cards, trend lines) rather than a plain data table — this is a genuine opportunity to bring DAX/Power BI-caliber presentation into an AI project, not just a RAG demo with a table bolted on. Full data model and UI spec deferred until v2 work (Fresher Mode, employment-type filter, company briefs) is closed out and there's real usage data to design the dashboard against.

### 15.6 Live Cost-Savings Counter (v3, not yet scoped)

Surfaces the token/cost savings from §12's optimization work (caching, embedding-first filtering, local-model routing) as a visible number — "this would have cost $X on paid API calls, you paid $0." High demo value, low build cost once §12's instrumentation exists, but needs that instrumentation (call counts, would-be cost per call) in place first, which isn't itself built yet.

### 15.7 Small Eval Suite with Published Numbers (v3, not yet scoped)

A labeled test set (~20-30 resume/JD pairs with known should-match/shouldn't-match answers) with precision/recall reported in the README, following the RAGAS-style evaluation approach used in the earlier Conversational RAG project. Deferred until Stage 2/3 matching logic is stable — evaluating a system that's still changing underneath produces numbers that go stale immediately.

### 15.8 Feedback Loop on Match Quality — parked, not committed

A thumbs up/down on matches to nudge semantic-vs-keyword score weighting per user. Parked rather than scoped: it introduces a telemetry/feedback-collection UI surface with no defined purpose yet, since there's no system in place to actually use that signal (no per-user weighting mechanism, no aggregate analysis pipeline). Revisit only once there's a concrete mechanism the feedback would feed — collecting signal with no defined use is a UI cost without a justified benefit.
