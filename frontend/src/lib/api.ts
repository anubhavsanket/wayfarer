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
  resumeCheck: (jdText: string, resumeFile?: File, resumeId?: string) => {
    const form = new FormData();
    if (resumeFile) {
      form.append("resume_file", resumeFile);
    } else if (resumeId) {
      form.append("resume_id", resumeId);
    }
    form.append("jd_text", jdText);
    return fetch(`${API_BASE}/api/v1/resume/check`, {
      method: "POST",
      headers: buildAuthHeaders(),
      body: form,
    }).then((r) => {
      if (!r.ok) {
        return r.text().then((t) => {
          throw new Error(`API error ${r.status}: ${t}`);
        });
      }
      return r.json() as Promise<ResumeCheckResponse>;
    });
  },

  // Stage 3 — Job matching
  jobsMatch: (resumeId: string, limit = 20, test = false, fresherOnly = false) =>
    request<JobMatchResponse>(
      `/api/v1/jobs/match?resume_id=${resumeId}&limit=${limit}${test ? "&test=true" : ""}${fresherOnly ? "&fresher_only=true" : ""}`
    ),
};
