# Wayfarer Product Enhancement Plan

This plan outlines the evolution of Wayfarer from a "search-and-match" prototype into a complete career-assistant platform. It leverages the existing FastAPI backend, modular services, Redis-backed queue, and pluggable LLM router.

## 1. Personalized Job-Fit Scoring & Explainability
- **User-profile model**: Store skills, years of experience, preferred locations, salary range, work-style, and visa status in the SQLite tracker.
- **Weighted matching engine**: Combine semantic similarity (embeddings), skill-overlap score, location/remote preference, salary-range fit, and company-culture signals.
- **Explainable AI (XAI) snippets**: Highlight which resume keywords drove the match and which missing skills hurt the score.

## 2. Application-Tracking & Automation
- **One-click apply**: Store application status ("Applied") in the tracker and integrate with job board apply links.
- **Automatic follow-up scheduler**: Use the existing `follow_up` service with a Redis-backed cron to send reminders.
- **Application analytics dashboard**: Track conversion rates and average time-to-reply.

## 3. Skill-Gap Learning Paths
- **Course recommendations**: Suggest free/paid courses (Coursera, Udemy, YouTube) based on identified keyword gaps.
- **Micro-credential system**: Allow users to upload certificates to boost match scores.
- **MOOC API Integration**: Fetch real-time course metadata from edX, Coursera, etc.

## 4. Enhanced UX & Accessibility
- **UI Polish**: Dark mode, high-contrast themes, and toast notifications for background tasks.
- **Resume versioning**: Support multiple resume variants (e.g., "tech-focused", "management-focused").
- **Improved uploads**: Drag-and-drop and paste-from-clipboard functionality.

## 5. Data Privacy & Trust
- **Encryption**: AES-256 encryption of resumes at rest using user-managed keys.
- **Audit log**: Immutable logging of all resume parsing and job matching actions.
- **GDPR Compliance**: Implement `/api/v1/me/export` and `/api/v1/me/delete` endpoints.

## 6. Scalability & Reliability
- **Database Migration**: Transition from SQLite to PostgreSQL for higher concurrency.
- **Worker Scaling**: Implement horizontal scaling for the `jobs_queue` worker using RQ or Celery.
- **Resilience**: Add circuit-breaker patterns for external APIs (Tavily, Brave, LLM providers).
- **Observability**: Expose Prometheus metrics and integrate Grafana dashboards.

---

## Implementation Roadmap

| Sprint | Goal | Key Stories |
|---|---|---|
| **Sprint 1** | **User Profile & Fit Scoring** | Profile schema & CRUD; Fit scoring service; Score breakdown in `/jobs/match`. |
| **Sprint 2** | **Tracking & Follow-ups** | Application tracking API; Redis-based follow-up scheduler; Basic analytics. |
| **Sprint 3** | **Upskilling & UX** | Course-recommendation service; Resume versioning; Dark mode & toast notifications. |
| **Sprint 4** | **Privacy & Scaling** | Resume encryption; Audit logging; PostgreSQL migration; Prometheus metrics. |
