import type {
  HealthResponse,
  JobMatchResponse,
  ResumeCheckResponse,
  ResumePrimaryInfo,
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
  // FR2.10 (§8.6): resumeFile is optional — omit to use primary resume
  resumeCheck: (resumeFile: File | null, jdText: string) => {
    const form = new FormData();
    if (resumeFile) form.append("resume_file", resumeFile);
    form.append("jd_text", jdText);
    return fetch(`${API_BASE}/api/v1/resume/check`, {
      method: "POST",
      headers: buildAuthHeaders(),
      body: form,
    }).then((r) => r.json() as Promise<ResumeCheckResponse>);
  },

  // Primary resume management (§8.6 FR2.9)
  getResumePrimary: () => request<ResumePrimaryInfo>("/api/v1/resume/primary"),

  setResumePrimary: (file: File) => {
    const form = new FormData();
    form.append("resume_file", file);
    return fetch(`${API_BASE}/api/v1/resume/primary`, {
      method: "POST",
      headers: buildAuthHeaders(),
      body: form,
    }).then((r) => r.json() as Promise<ResumePrimaryInfo>);
  },

  // Stage 3 — Job matching
  // FR2.12 (§8.6): resumeId is optional — omit to use primary resume
  jobsMatch: (resumeId = "", limit = 20, test = false, fresherOnly = false) => {
    const params = new URLSearchParams();
    if (resumeId) params.set("resume_id", resumeId);
    params.set("limit", limit.toString());
    if (test) params.set("test", "true");
    if (fresherOnly) params.set("fresher_only", "true");
    return request<JobMatchResponse>(`/api/v1/jobs/match?${params.toString()}`);
  },
};
