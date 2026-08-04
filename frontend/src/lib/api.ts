import type {
  HealthResponse,
  JobMatchResponse,
  ResumeCheckResponse,
  SearchResponse,
} from "./types";
import { buildAuthHeaders } from "@/stores/settings";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...buildAuthHeaders(),
      ...init?.headers,
    },
    ...init,
  });
  if (!res.ok) {
    throw new Error(`API error ${res.status}: ${await res.text()}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  // Health
  health: () => request<HealthResponse>("/health"),

  // Stage 1 — Search
  search: (query: string, maxSources = 5) =>
    request<SearchResponse>("/api/v1/search", {
      method: "POST",
      body: JSON.stringify({ query, max_sources: maxSources }),
    }),

  // Stage 2 — Resume check
  resumeCheck: (resumeFile: File, jdText: string) => {
    const form = new FormData();
    form.append("resume_file", resumeFile);
    form.append("jd_text", jdText);
    return fetch(`${API_BASE}/api/v1/resume/check`, {
      method: "POST",
      headers: buildAuthHeaders(),
      body: form,
    }).then((r) => r.json() as Promise<ResumeCheckResponse>);
  },

  // Stage 3 — Job matching
  jobsMatch: (resumeId: string, limit = 20, test = false) =>
    request<JobMatchResponse>(
      `/api/v1/jobs/match?resume_id=${resumeId}&limit=${limit}${test ? "&test=true" : ""}`
    ),
};
