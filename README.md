# Wayfarer — AI-Powered Job Search Automation Platform

> A locally-hosted, RAG-driven job search platform built in three connected stages:
> a **web search agent**, a **RAG-based ATS resume checker with redlining**, and a
> **live job-posting matcher**. The retrieval, scoring, and matching logic is owned
> and built directly — not delegated to a general-purpose coding agent's context window.

Built and designed to actually be used for the author's own job search. Calls out to 
free-tier APIs as fallback when local inference would blow the 4 GB VRAM budget.

---

## Table of contents

1. [What Wayfarer does](#what-wayfarer-does)
2. [Architecture](#architecture)
3. [Project layout](#project-layout)
4. [Quick start (Docker Compose)](#quick-start-docker-compose)
5. [Local development (no Docker)](#local-development-no-docker)
6. [Configuration](#configuration)
7. [API reference](#api-reference)
8. [The job board registry](#the-job-board-registry)
9. [Testing](#testing)
10. [Cost & token optimization](#cost--token-optimization)
11. [Known limitations](#known-limitations)
12. [Roadmap](#roadmap)

---

## What Wayfarer does

| Stage | What it answers | Key endpoint |
|---|---|---|
| **1. Web Search Agent** | "Search the web for X and synthesize an answer with sources." | `POST /api/v1/search` |
| **2. ATS Resume Checker** | "Check my resume against this JD, tell me exactly what to change and why." | `POST /api/v1/resume/check` |
| **3. Job Matcher** | "Show me live postings ranked by fit, with apply links." | `GET /api/v1/jobs/match` |

Every output is **human-in-the-loop**: the system evaluates, ranks, and drafts — it
never submits, auto-fills, or clicks anything on a third-party site on the user's
behalf.

### Differentiators

- **Owned RAG pipeline** — embeddings, vector store, hybrid scoring are all
  in-process. No `Claude Code + LaTeX` or `prompt orchestration over markdown` here.
- **Honest substitution** — every keyword suggestion in Stage 2 is traceable to a
  real resume bullet. The hard rule: gaps stay gaps, never auto-inserted.
- **Confidence-tiered redlines** — `Verified` / `Reworded` / `Gap`, the third of
  which is genuinely surfaced, not hidden.
- **Multi-provider inference** — rate-limit-aware router with NVIDIA NIM →
  OpenRouter → local Ollama fallback. Free tiers only.
- **Config-driven job boards** — adding a board = a YAML entry, not a code change.

---

## Architecture

```
                    ┌─────────────────────────────┐
                    │        LLM Router            │
                    │  NVIDIA NIM ⇄ OpenRouter      │
                    │  rate-limit-aware fallback    │
                    └───────────────┬───────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        │                           │                           │
┌───────▼─────────┐      ┌───────────▼────────────┐     ┌───────────▼───────────┐
│   Stage 1       │      │       Stage 2          │     │       Stage 3         │
│  Search Agent   │      │  Resume/ATS Checker    │     │   Job Matcher         │
│                 │      │                        │     │                       │
│ Search API      │      │ pdfplumber/python-docx │     │ bluedoor.sh API       │
│ (Tavily/Brave)  │      │ pdftotext ATS sim      │     │ LinkedIn guest (IN)   │
│ + Crawl4AI      │      │ Embedding matcher      │     │ Reuses Stage 2's      │
│ fetch/clean     │      │ Confidence-tiered      │     │ match_keyword_to_     │
│                 │      │ redline generator      │     │ bullet() per posting  │
└─────────────────┘      └────────────────────────┘     └───────────────────────┘
        │                           │                           │
        └───────────────────────────┴───────────────────────────┘
                                    │
                        ┌───────────▼─────────────┐
                        │       ChromaDB          │
                        │  separate collections:  │
                        │   search_cache          │
                        │   resume_sections       │
                        │   job_postings          │
                        │ shared embedding model: │
                        │   nomic-embed-text      │
                        └─────────────────────────┘
```

### Shared infrastructure (build once, used everywhere)

- **LLM Router** — `backend/app/llm_router.py`. Every stage calls inference through
  this module, never directly against a provider. Tracks per-provider rate limits
  with sliding-window buckets, fails over on 429/5xx/timeout, picks the right model
  per task complexity (`simple` = llama-3.1-8b / llama3.2:3b,
  `complex` = llama-3.3-70b / claude-3-5-sonnet / llama3.2:70b).
- **Embedding layer** — `nomic-embed-text` via Ollama, same setup that worked in
  LocalBrain. Local, cheap, no router fallback needed.
- **ChromaDB** — one persistent store, three collections
  (`search_cache`, `resume_sections`, `job_postings`). Sharing the embedding space
  is the architectural lever that lets Stage 2 ↔ Stage 3 reuse the same matching
  engine.
- **Confidence scoring** — `backend/app/core/confidence.py`. The `Verified /
  Reworded / Gap` classifier from the real-estate RAG project, pulled out as a
  standalone utility. **The same `match_keyword_to_bullet` function is used by both
  Stage 2 and Stage 3.**

---

## Project layout

```
wayfarer/
├── backend/                    # FastAPI service
│   ├── app/
│   │   ├── main.py             # FastAPI entry, health, lifespan
│   │   ├── config.py           # Pydantic Settings (.env-driven)
│   │   ├── llm_router.py       # Multi-provider inference router
│   │   ├── vector_store.py     # Multi-collection ChromaDB wrapper
│   │   ├── models/
│   │   │   ├── schemas.py      # Pydantic request/response models
│   │   │   └── job_boards.py   # Board registry models + connector
│   │   ├── core/
│   │   │   └── confidence.py   # Tier classifier + match_keyword_to_bullet
│   │   ├── services/
│   │   │   ├── search_api.py   # Tavily + Brave clients
│   │   │   ├── web_fetch.py    # Crawl4AI concurrency-capped fetcher
│   │   │   ├── search_service.py     # Stage 1 orchestrator
│   │   │   ├── resume_parser.py      # PDF/DOCX parsing
│   │   │   ├── ats_checker.py        # Stage 2 orchestrator
│   │   │   ├── resume_saver.py       # Save with/without overwrite
│   │   │   ├── resume_store.py       # Upload persistence
│   │   │   ├── job_matcher.py        # Stage 3 orchestrator
│   │   │   └── legitimacy.py         # Ghost / no-sponsorship checks
│   │   └── utils/
│   │       └── cache.py        # Content-hash memoization
│   ├── tests/                  # pytest suite (36 tests, all passing)
│   ├── requirements.txt
│   ├── pytest.ini
│   └── Dockerfile
├── frontend/                   # React + Vite + TS + Tailwind
│   ├── src/
│   │   ├── App.tsx             # Tabbed UI shell
│   │   ├── pages/
│   │   │   ├── Search.tsx      # Stage 1 UI
│   │   │   ├── ResumeCheck.tsx # Stage 2 UI (upload + JD)
│   │   │   └── JobMatch.tsx    # Stage 3 UI (ranked listings)
│   │   ├── components/ui/      # Button, Card primitives
│   │   └── lib/{api.ts, types.ts, utils.ts}
│   ├── Dockerfile + nginx.conf # Production build for compose
│   └── package.json
├── config/
│   ├── settings.yaml           # Main config (informational)
│   └── job_boards.yaml         # Stage 3 board registry
├── data/uploads/               # Created on first resume upload
├── docker-compose.yml          # 5-service stack
├── .env.example                # Copy to .env, fill in keys
└── README.md
```

---

## Quick start (Docker Compose)

The PRD's target: `docker compose up` gets a stranger from zero to a running
instance.

### 1. Clone and configure

```bash
git clone <repo-url> wayfarer
cd wayfarer
cp .env.example .env
# edit .env and fill in at least ONE of:
#   NVIDIA_NIM_API_KEY / OPENROUTER_API_KEY
#   TAVILY_API_KEY (for Stage 1 search)
```

### 2. Bring up the stack

```bash
docker compose up
```

This starts five services:

| Service | Port | Purpose |
|---|---|---|
| `api` | 8000 | FastAPI backend |
| `chromadb` | 8001 | Vector store (HTTP API on internal 8000) |
| `ollama` | 11434 | Local inference + embeddings |
| `redis` | 6379 | Background job queue (Stage 3 refresh) |
| `frontend` | 3000 | React UI served by nginx |

First boot will pull all images. The embedding and chat models are **not**
auto-pulled — two manual steps the first time:

```bash
# Pull the embedding model (required for all stages)
docker compose exec ollama ollama pull nomic-embed-text

# Pull the chat model (required for LLM synthesis when using Ollama)
docker compose exec ollama ollama pull llama3.2:3b
```

> **Important:** Do NOT put spaces after `=` in `.env` — e.g.
> `NVIDIA_NIM_API_KEY=nvapi-XXXX` is correct, but
> `NVIDIA_NIM_API_KEY= nvapi-XXXX` will silently break the API key.

### 3. Verify it's up

```bash
curl http://localhost:8000/health
# → 200 OK, JSON with per-dependency status
```

If everything is `up`, you're ready to call the API.

### 4. Use it

Open **http://localhost:3000** in a browser and use the three tabs (Search /
Resume Check / Job Match), or call the endpoints directly — see the
[API reference](#api-reference).

---

## Local development (no Docker)

Useful when iterating on backend code without rebuilding the image.

### Prerequisites

- **Python 3.11 or 3.12** (3.14 doesn't build the pinned `pydantic-core` /
  `chromadb`; that's why a 3.11 venv ships under `backend/.venv`)
- Node.js 20+ (only for frontend work)
- Ollama installed locally (or a `chromadb`/`ollama` reachable on the network)

### 1. Create a venv and install backend deps

```bash
cd backend
python3.11 -m venv .venv
./.venv/Scripts/python.exe -m pip install -U pip
./.venv/Scripts/python.exe -m pip install -r requirements.txt
```

### 2. (Optional) pull local models

```bash
# Embedding model (required for all stages)
ollama pull nomic-embed-text

# Chat model (required for LLM synthesis when using Ollama)
ollama pull llama3.2:3b
```

### 3. (Optional) point at a remote ChromaDB / Ollama

```bash
export CHROMA_HOST=localhost
export CHROMA_PORT=8001
export OLLAMA_ENDPOINT=http://localhost:11434
```

### 4. Run the API

From the project root (so `backend.app.*` resolves cleanly):

```bash
cd ..
./backend/.venv/Scripts/python.exe -m uvicorn backend.app.main:app --reload --port 8000
```

The `--reload` flag auto-restarts on Python changes.

### 5. Hit the API

```bash
curl http://localhost:8000/health
# {"status":"degraded","dependencies":[{"name":"chromadb","status":"up",...},...]}
```

If ChromaDB at `chromadb:8001` isn't reachable (the default Docker hostname), the
wrapper transparently falls back to a persistent local store under `./chroma_db/`.

### 6. Run the frontend (separate terminal)

```bash
cd frontend
npm install
npm run dev
# → http://localhost:3000
```

The Vite dev server proxies `/api` and `/health` to `http://localhost:8000` (see
`frontend/vite.config.ts`).

---

## Configuration

Configuration is layered:

1. **`.env`** — runtime overrides (API keys, hostnames). Highest priority.
2. **`config/settings.yaml`** — informational defaults + structured config
   (rate limits, models per tier, paths).
3. **`config/job_boards.yaml`** — Stage 3 board registry.

### Required `.env` keys

| Variable | Purpose | Required for |
|---|---|---|
| `LLM_PROVIDER` | Primary LLM provider | `nvidia` / `openrouter` / `ollama` |
| `NVIDIA_NIM_API_KEY` | NVIDIA NIM free-tier router | When `LLM_PROVIDER=nvidia` |
| `OPENROUTER_API_KEY` | OpenRouter free-tier router | When `LLM_PROVIDER=openrouter` |
| `TAVILY_API_KEY` | Search API (primary) | Stage 1 |
| `BRAVE_API_KEY` | Search API (fallback) | Stage 1 if Tavily missing |

When `LLM_PROVIDER=ollama` (default), no API keys are needed — everything
runs locally via Ollama. The router always falls back through the other
providers if the primary one fails.

### Optional overrides

| Variable | Default | Notes |
|---|---|---|
| `LLM_PROVIDER` | `nvidia` | Provider preference (`nvidia` / `openrouter` / `ollama`) |
| `CHROMA_HOST` | `chromadb` | Set to `localhost` for non-Docker local dev |
| `CHROMA_PORT` | `8001` | `8000` inside Docker Compose (the api service overrides it); `8001` is the host-mapped port for local Chroma |
| `OLLAMA_ENDPOINT` | `http://ollama:11434` | |
| `REDIS_URL` | `redis://redis:6379` | |

### What the YAML configs hold

- **`config/settings.yaml`** — model-per-tier mapping, rate limits (requests per
  window), collection names, search timeouts. Human-readable reference; the live
  values are still `.env`-driven.
- **`config/job_boards.yaml`** — the **only** place to add/remove job sources.
  See [the next section](#the-job-board-registry).

---

## API reference

### `GET /health`

Reports the status of every external dependency.

```json
{
  "status": "ok",
  "dependencies": [
    {"name": "chromadb", "status": "up", "detail": "connected"},
    {"name": "ollama", "status": "up", "detail": "model list OK"},
    {"name": "redis", "status": "up", "detail": "ping OK"},
    {"name": "nvidia_nim", "status": "up", "detail": "API reachable"},
    {"name": "openrouter", "status": "down", "detail": "no API key"}
  ]
}
```

### `POST /api/v1/search` — Stage 1

```json
// Request
{
  "query": "top GenAI engineer roles in Bengaluru for freshers",
  "max_sources": 5
}

// Response
{
  "answer": "Based on the sources...",
  "citations": [
    {"id": 1, "url": "https://...", "title": "...", "snippet": "..."}
  ],
  "sub_queries_used": ["GenAI engineer roles Bengaluru", "..."],
  "cached": false
}
```

```bash
curl -X POST http://localhost:8000/api/v1/search \
  -H 'Content-Type: application/json' \
  -d '{"query": "RAG system design best practices", "max_sources": 3}'
```

### `POST /api/v1/resume/check` — Stage 2

Multipart upload. Returns the ATS score, structural issues, and per-keyword
suggestions with their confidence tier.

```bash
curl -X POST http://localhost:8000/api/v1/resume/check \
  -F "resume_file=@./my_resume.pdf;type=application/pdf" \
  -F "jd_text=Looking for an ML engineer with Python and PyTorch experience"
```

```json
// Response (truncated)
{
  "resume_id": "abc123def456",
  "ats_score": 0.78,
  "structural_issues": [
    {"location": "table on page 1", "issue": "Table header 'Tools' not visible in ATS text..."}
  ],
  "keyword_gaps": [
    {
      "keyword": "pytorch",
      "tier": "reworded",
      "bullet_id": "b2",
      "original_text": "Built ML models in Python.",
      "suggested_text": "Built ML models with PyTorch in Python.",
      "rationale": "Real underlying experience exists; bullet rewritten to use JD terminology.",
      "confidence": 0.84
    },
    {
      "keyword": "kubernetes",
      "tier": "gap",
      "confidence": null,
      "rationale": "No supporting evidence found in resume — flagged as a gap."
    }
  ]
}
```

### `POST /api/v1/resume/save` — Stage 2

Apply accepted suggestions. Default mode is **non-destructive** (writes a new
file alongside the original); `overwrite` requires `confirm_overwrite: true` and
the original is retained in `data/uploads/{resume_id}/` until overwrite is
confirmed.

```json
// Request
{
  "resume_id": "abc123def456",
  "accepted_suggestions": [
    {"bullet_id": "b2", "suggested_text": "Built ML models with PyTorch in Python."}
  ],
  "mode": "new_file",  // or "overwrite"
  "confirm_overwrite": false  // required true if mode == "overwrite"
}

// Response
{
  "file_id": "f9c8...",
  "file_ref": "data/uploads/abc123def456/saved_f9c8.docx",
  "mode_applied": "new_file"
}
```

### `GET /api/v1/jobs/match` — Stage 3

Rank live postings by fit against the resume's `resume_id`.

| Query param | Type | Default | Notes |
|---|---|---|---|
| `resume_id` | string | required | from `/resume/check` response |
| `limit` | int 1–100 | 20 | max postings returned |
| `location_mode` | enum | `specific_city` | `specific_city` / `remote_only` / `hybrid` / `open_to_relocation` |
| `cities` | csv string | `""` | comma-separated; used for `specific_city` and `open_to_relocation` |
| `remote_ok` | bool | false | include remote postings alongside city matches |
| `test` | bool | false | return mock sample data (skip live board APIs) |

> Use `?test=true` to see the Job Match UI with realistic sample data when
> board APIs are unavailable or broken.

```bash
curl "http://localhost:8000/api/v1/jobs/match?resume_id=abc123def456&limit=20&location_mode=specific_city&cities=bengaluru&remote_ok=true"
```

```json
// Response
{
  "matches": [
    {
      "job_id": "bluedoor:https://...",
      "title": "ML Engineer",
      "company": "Acme",
      "source": "bluedoor",
      "location": "Bengaluru, Karnataka",
      "match_score": 0.84,
      "location_match": "exact",
      "top_gaps": ["kubernetes", "rust"],
      "apply_url": "https://...",
      "flags": []
    },
    {
      "job_id": "bluedoor:https://...",
      "title": "Remote ML Engineer",
      "company": "",
      "source": "bluedoor",
      "location": "Remote",
      "match_score": 0.71,
      "location_match": "remote",
      "top_gaps": ["pytorch"],
      "apply_url": "https://...",
      "flags": ["vague", "unknown_company"]
    }
  ],
  "aggregate_gaps": [
    {"skill": "kubernetes", "missing_in_pct": 0.6},
    {"skill": "rust", "missing_in_pct": 0.4}
  ]
}
```

The `flags` array carries legitimacy signals from `check_posting` (FR3.8) —
possible values: `vague`, `unknown_company`, `sponsorship`. The Job Match UI
renders these as ⚠ badges; the backend never silently drops a posting, it
flags it for the human-in-the-loop.

---

## The job board registry

Every job source is defined in **`config/job_boards.yaml`**. Adding a new board
is a config change, not a code change — this is the primary lever that makes
Wayfarer usable outside India/Bengaluru without forking the codebase.

### Anatomy of a board entry

```yaml
- name: bluedoor                    # unique identifier
  enabled: true                     # toggle on/off without deleting
  type: rest_api                    # rest_api | html_scrape
  base_url: "https://..."
  auth: none                        # none | api_key
  api_key_env: "CUSTOM_API_KEY"     # env var name when auth == api_key
  rate_limit_per_min: 60
  field_mapping:                    # JSONPath-style for REST APIs
    title: "$.job_title"
    company: "$.employer_name"
    location: "$.location.city"
    url: "$.apply_url"
    description: "$.description_text"
  pagination:
    type: "offset"                  # offset | start_offset | query_param
    param: "page"
    step: 10
    max_pages: 5
```

### Adding a new board (3 steps, no Python changes)

1. **Add the entry** to `config/job_boards.yaml` with `enabled: true`.
2. **(If `auth: api_key`) Add the API key env var** to your `.env` (and the
   `api_key_env` field should match the env var name).
3. **Restart the API** (`docker compose restart api` or, in dev mode, the
   `--reload` watcher will pick it up).

The connector reads the registry on every `match_jobs` call, so no code change
or redeploy is needed beyond the restart.

---

## Testing

```bash
cd backend
./.venv/Scripts/python.exe -m pytest tests/ -v
```

**Current status: 36 tests passing.**

| Test file | Stage | Tests | Coverage |
|---|---|---|---|
| `test_stage1.py` | Stage 1 | 9 | Decomposition fallback, dedup, provider selection, endpoint validation |
| `test_stage2.py` | Stage 2 | 11 | Parser (incl. table-based skills flag), ATS score math, save modes (default non-destructive, overwrite needs confirmation), endpoint |
| `test_stage3.py` | Stage 3 | 16 | All 4 location modes, ghost-job + no-sponsorship flags, config-driven board loading, aggregate gap ranking, `flags` field wiring |

Each test maps to an acceptance criterion from the PRD.

---

## Cost & token optimization

Free-tier API budgets are the binding constraint on this whole system. Per the
PRD §12, every stage is built with cost in mind:

- **Embedding-first filtering** — Stage 3 never calls the LLM on a JD whose
  embedding similarity already rules it out. Top-K survivors only.
- **Structured resume memory** — `match_keyword_to_bullet` operates on parsed
  bullets (extracted once during `/resume/check`), not the raw resume text on
  every call.
- **Right-size the model per sub-task** — keyword extraction and tier
  classification route to the small/fast `simple` tier; bullet rewrite
  generation uses the `complex` tier where quality matters.
- **Prompt caching awareness** — `LLMRouter` passes `cache_control: ephemeral`
  hints to providers that support it (NVIDIA NIM, OpenRouter). The resume context
  is the same across all N posting comparisons in a session — exactly what
  caching is for.
- **Content-hash response memoization** — `utils/cache.py` provides TTL'd
  memoization per stage (`search_cache`, `resume`, `jobs`).
- **JD boilerplate stripping** — `legitimacy._strip_boilerplate` strips benefits/EEO
  boilerplate before ghost detection, reducing noise in the legitimacy signal.

---

## Known limitations

- **VRAM ceiling** — keep embeddings + any local LLM under 4 GB total. Phrase
  prompts are routed via the LLM Router (API-side); only embeddings stay local.
- **`bluedoor.sh` API may be broken** — their endpoint returned 404 during
  testing (August 2026). The board registry is designed for resilience; update
  `config/job_boards.yaml` with the current endpoint when it recovers. Use
  `?test=true` on `/jobs/match` for mock data in the meantime.
- **LinkedIn guest endpoints** return HTML rather than structured JSON for
  most queries; the connector handles this gracefully (falls back to empty).
  Keep volume low and personal-use only.
- **No native `.docx` track-changes export in v1** — the redline view is
  HTML/artifact-style; OOXML track-changes is a v2 stretch.
- **Python 3.11 / 3.12 only** — pinned deps don't build on 3.14.

---

## Roadmap

| Phase | Status | Deliverable |
|---|---|---|
| Phase 0 | ✅ | Shared infra, config, Docker Compose, frontend scaffold |
| Phase 1 | ✅ | Stage 1: `/search` end-to-end |
| Phase 2 | ✅ | Stage 2: parsing sim, keyword matcher, confidence tiers, save |
| Phase 3 | ✅ | Stage 3: bluedoor + India source, hybrid scoring, location/aggregate |
| Phase 4 | ⏳ | Polish: aggregate gap UI, README differentiation, deploy smoke test |

### Stretch / v2 ideas

- Native `.docx` OOXML track-changes export
- Application outcome tracking / dashboard
- Interview prep module
- A second India-specific job board (currently only `bluedoor` + `linkedin_guest`
  are enabled; `custom_board_example` and `naukri_example` are stubbed in the
  registry)

---

## License

Proprietary — built for the author's personal job search automation and as an AI
engineering portfolio piece.