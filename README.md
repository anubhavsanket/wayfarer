# Wayfarer — AI-Powered Job Search Automation Platform

> A locally-hosted, RAG-driven job search platform built in three connected stages:
> a **web search agent**, a **RAG-based ATS resume checker with redlining**, and a
> **live job-posting matcher**. The retrieval, scoring, and matching logic is owned
> and built directly — not delegated to a general-purpose coding agent's context window.

Built and designed to actually be used for the author's own job search. Calls out to
free-tier APIs as fallback when local inference would blow the 4 GB VRAM budget.

**Version: 1.1** — includes Fresher Mode, employment-type classification, LinkedIn
integration, and background pipeline maintenance.

---

## One-Command Setup

```bash
curl -sSL https://raw.githubusercontent.com/anubhavsanket/wayfarer/main/setup.sh | bash
```

Or clone manually:
```bash
git clone https://github.com/anubhavsanket/wayfarer.git
cd wayfarer
bash setup.sh
```

The script clones the repo, creates `.env`, pulls Docker images, starts all 5 services,
and pulls the embedding model. Takes about 2 minutes on first run.

After setup, open **http://localhost:3000** and go to the **Settings** tab to enter
your API keys — or edit `.env` directly.

---

## Table of contents

1. [What Wayfarer does](#what-wayfarer-does)
2. [Architecture](#architecture)
3. [Quick start](#quick-start-docker-compose)
4. [Local development](#local-development-no-docker)
5. [Configuration](#configuration)
6. [API reference](#api-reference)
7. [The job board registry](#the-job-board-registry)
8. [Testing](#testing)
9. [What's in v1.1](#whats-in-v11)
10. [Known limitations](#known-limitations)

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
- **Fresher Mode** — filter postings to entry-level/junior roles using a small
  local LLM (qwen3:0.6b) for experience-level classification.

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
┌───────▼────────┐      ┌───────────▼──────────┐     ┌───────────▼──────────┐
│   Stage 1       │      │       Stage 2         │     │       Stage 3         │
│  Search Agent   │      │  Resume/ATS Checker    │     │   Job Matcher         │
│                 │      │                        │     │                       │
│ Search API      │      │ pdfplumber/python-docx │     │ bluedoor + LinkedIn   │
│ (Tavily/Brave)  │      │ pdftotext ATS sim      │     │ Fresher Mode          │
│ + Crawl4AI      │      │ Embedding matcher      │     │ Hybrid scoring        │
│ fetch/clean     │      │ Confidence-tiered      │     │ Legitimacy checks     │
│                 │      │ redline generator      │     │ Background refresh    │
└─────────────────┘      └────────────────────────┘     └───────────────────────┘
        │                           │                           │
        └───────────────────────────┴───────────────────────────┘
                                    │
                        ┌───────────▼───────────┐
                        │       ChromaDB          │
                        │  search_cache           │
                        │  resume_sections        │
                        │  job_postings           │
                        └─────────────────────────┘
```

**Shared infrastructure (build once, used in all 3 stages):**
- **LLM Router** — `backend/app/llm_router.py`. Every stage calls inference through
  this module, never directly against a provider. Supports 5 providers: NVIDIA NIM,
  OpenRouter, Ollama (local), LM Studio (local), and any custom OpenAI-compatible
  endpoint. Tracks per-provider rate limits and falls back automatically.
- **Embedding layer** — `nomic-embed-text` via Ollama, kept local. Embeddings are
  cheap enough on a GTX 1650 that they don't need router fallback.
- **ChromaDB** — one persistent store, three separate collections (`search_cache`,
  `resume_sections`, `job_postings`). Sharing the embedding space enables Stage 2
  ↔ Stage 3 reuse.
- **Confidence scoring** — `backend/app/core/confidence.py`. The `Verified /
  Reworded / Gap` classifier from the real-estate RAG project. **The same
  `match_keyword_to_bullet` function is used by both Stage 2 and Stage 3.**
- **Resume graph** — `backend/app/core/resume_graph.py`. Graph-based structured
  resume memory for token-efficient per-posting matching.

---

## Quick start (Docker Compose)

### Prerequisites
- [Docker](https://docs.docker.com/get-docker/) + Docker Compose (v2+)
- An NVIDIA GPU is optional but recommended (router falls back to API inference without one)

### 1. Clone and configure

```bash
git clone https://github.com/anubhavsanket/wayfarer.git
cd wayfarer
cp .env.example .env
# edit .env and fill in at least ONE of:
#   NVIDIA_NIM_API_KEY / OPENROUTER_API_KEY
#   TAVILY_API_KEY (for Stage 1 search)
```

### 2. Bring up the stack

```bash
docker compose up --build
```

This starts five services:

| Service | Port | Purpose |
|---|---|---|
| `api` | 8000 | FastAPI backend |
| `chromadb` | 8001 | Vector store |
| `ollama` | 11434 | Local inference + embeddings |
| `redis` | 6379 | Background job queue |
| `frontend` | 3000 | React UI served by nginx |

### 3. Pull models (first time only)

```bash
# Embedding model (required for all stages)
docker compose exec ollama ollama pull nomic-embed-text

# Chat model (only if using Ollama for inference)
docker compose exec ollama ollama pull llama3.2:3b
```

### 4. Verify

```bash
curl http://localhost:8000/health
# → 200 OK with per-dependency status
```

### 5. Use it

- **Frontend:** http://localhost:3000 — Settings tab for API keys, then Search/Resume/Job Match tabs
- **API docs:** http://localhost:8000/docs — interactive Swagger UI

---

## Local development (no Docker)

### Prerequisites
- Python 3.11 or 3.12 (3.14 doesn't build the pinned dependencies)
- Node.js 20+ (only for frontend work)
- Ollama installed locally (or Docker for ChromaDB/Ollama)

### 1. Create a venv and install backend deps

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate  # Linux/Mac
# or .venv\Scripts\activate     # Windows
pip install -r requirements.txt
```

### 2. Pull models

```bash
ollama pull nomic-embed-text
# For local LLM inference:
ollama pull llama3.2:3b
```

### 3. Run the API

From the project root:
```bash
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

ChromaDB falls back to a persistent local store at `./chroma_db/` automatically.

### 4. Run the frontend

```bash
cd frontend
npm install
npm run dev  # → http://localhost:3000 (proxies /api to :8000)
```

---

## Configuration

Configuration is layered:
1. **`.env`** — runtime overrides (API keys, hostnames). Highest priority.
2. **Settings tab** in the frontend — stores keys in localStorage, sends as
   request headers. No keys in git.
3. **`config/job_boards.yaml`** — Stage 3 board registry (add a board = config change).

### Supported LLM providers

| Provider | `.env` setting | API key needed? | Notes |
|---|---|---|---|
| `nvidia` | `LLM_PROVIDER=nvidia` | `NVIDIA_NIM_API_KEY` | Free tier, fast |
| `openrouter` | `LLM_PROVIDER=openrouter` | `OPENROUTER_API_KEY` | Free tier, wide model selection |
| `ollama` | `LLM_PROVIDER=ollama` | No | Local, pull model first |
| `lmstudio` | `LLM_PROVIDER=lmstudio` | No | Set `LMSTUDIO_ENDPOINT` + `LMSTUDIO_MODEL` |
| `custom` | `LLM_PROVIDER=custom` | `CUSTOM_LLM_API_KEY` | Any OpenAI-compatible endpoint |

The router always falls back through the provider list if the primary fails.

---

## API reference

### `GET /health`

```json
{"status":"ok","dependencies":[{"name":"chromadb","status":"up"},...]}
```

### `POST /api/v1/search` — Stage 1

```bash
curl -X POST http://localhost:8000/api/v1/search \
  -H 'Content-Type: application/json' \
  -d '{"query": "best practices for RAG?", "max_sources": 3}'
```

```json
{
  "answer": "Based on the provided sources...",
  "citations": [{"id":1, "url":"...", "title":"...", "snippet":"..."}],
  "sub_queries_used": ["best practices for RAG"],
  "cached": false
}
```

### `POST /api/v1/resume/check` — Stage 2

```bash
curl -X POST http://localhost:8000/api/v1/resume/check \
  -F "resume_file=@my_resume.pdf" \
  -F "jd_text=Looking for an ML engineer with Python, PyTorch, and AWS."
```

```json
{
  "resume_id": "abc123",
  "ats_score": 0.85,
  "structural_issues": [{"location": "table on page 1", "issue": "..."}],
  "keyword_gaps": [
    {"keyword": "pytorch", "tier": "reworded", "confidence": 0.84, "rationale": "..."}
  ]
}
```

### `POST /api/v1/resume/save` — Stage 2

Default mode is non-destructive (writes a new file). Overwrite requires `confirm_overwrite: true`.

### `GET /api/v1/jobs/match` — Stage 3

| Param | Type | Default | Notes |
|---|---|---|---|
| `resume_id` | string | required | from `/resume/check` response |
| `limit` | int | 20 | max results |
| `location_mode` | enum | `specific_city` | `specific_city` / `remote_only` / `hybrid` / `open_to_relocation` |
| `cities` | csv | `""` | comma-separated cities |
| `remote_ok` | bool | false | include remote postings |
| `fresher_only` | bool | false | filter to fresher/junior roles only |
| `test` | bool | false | return sample data |

```bash
curl "http://localhost:8000/api/v1/jobs/match?resume_id=abc123&fresher_only=true&limit=10"
```

### `POST /api/v1/jobs/refresh` — Stage 3 background

Re-fetches from all enabled boards and stores in ChromaDB.

---

## The job board registry

Every job source is defined in **`config/job_boards.yaml`**. Adding a new board
is a config change, not a code change.

```yaml
- name: bluedoor
  enabled: true
  type: rest_api
  base_url: "https://api.bluedoor.sh/job-postings/v1/jobs/search"
  auth: api_key
  api_key_env: "BLUEDOOR_API_KEY"
  rate_limit_per_min: 100
  field_mapping:
    title: "$.title"
    company: "$.org_name"
    location: "$.city"
    url: "$.apply_url"
  pagination:
    type: "none"
    param: ""
    max_pages: 1
```

---

## Testing

```bash
# Unit tests (no Docker required, needs Python 3.11)
cd backend
python -m pytest tests/test_stage1.py tests/test_stage2.py tests/test_stage3.py -v

# E2E tests (requires all Docker services running)
python -m pytest tests/test_docker_e2e.py -v
```

**Current status: 48 tests** (36 unit + 12 E2E), all passing.

---

## What's in v1.1

| Feature | Status | Description |
|---|---|---|
| **Fresher Mode** | ✅ | Filter postings to entry-level/junior roles via qwen3:0.6b classification |
| **Employment type** | ✅ | full_time/contract/freelance/part_time field on JobMatch |
| **LinkedIn integration** | ✅ | HTML parsing of guest API (50+ Indian job postings) |
| **Background refresh** | ✅ | `POST /api/v1/jobs/refresh` — dedup, normalize, stale-drop |
| **Pipeline integrity** | ✅ | Dedup across sources, TTL cleanup, location normalization |
| **Structured resume memory** | ✅ | Graph-based entity extraction for token-efficient matching |
| **Settings dashboard** | ✅ | API keys stored in localStorage, not in git |
| **LM Studio / custom** | ✅ | Any OpenAI-compatible endpoint works |
| **Side-by-side redlines** | ✅ | Original vs. suggested view in Resume Check |
| **One-command setup** | ✅ | `bash setup.sh` or curl link |

---

## Known limitations

- **`bluedoor.sh` descriptions** — the API doesn't return JD descriptions in search
  results, so experience classification uses titles only (often "unclear").
- **LinkedIn guest API** — returns HTML (parsed via regex), not structured JSON.
  Keep volume low, personal-use only.
- **VRAM ceiling** — keep embeddings + local LLM under 4 GB total. Heavy inference
  is routed to APIs via the LLM Router.
- **No `.docx` track-changes export** — redline view is HTML-based for MVP.
  OOXML track-changes is a v2 stretch goal.
- **Python 3.11 / 3.12 only** — pinned dependencies don't build on 3.14.

---

## License

Proprietary — built for the author's personal job search automation and as an AI
engineering portfolio piece.
