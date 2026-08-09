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
  resumeCheck: async (resumeFile: File | null, jdText: string): Promise<ResumeCheckResponse> => {
    const form = new FormData();
    if (resumeFile) form.append("resume_file", resumeFile);
    form.append("jd_text", jdText);
    const res = await fetch(`${API_BASE}/api/v1/resume/check`, {
      method: "POST",
      headers: buildAuthHeaders(),
      body: form,
    });
    if (!res.ok) throw new Error(`Resume check failed (${res.status}): ${await res.text()}`);
    return res.json();
  },

  // Primary resume management (§8.6 FR2.9)
  getResumePrimary: () => request<ResumePrimaryInfo>("/api/v1/resume/primary"),

  setResumePrimary: async (file: File): Promise<ResumePrimaryInfo> => {
    const form = new FormData();
    form.append("resume_file", file);
    const res = await fetch(`${API_BASE}/api/v1/resume/primary`, {
      method: "POST",
      headers: buildAuthHeaders(),
      body: form,
    });
    if (!res.ok) throw new Error(`Upload failed (${res.status}): ${await res.text()}`);
    return res.json();
  },

  // Stage 3 — Job matching
  // FR2.12 (§8.6): resumeId is optional — omit to use primary resume
  jobsMatch: (
    resumeId = "",
    limit = 20,
    test = false,
    fresherOnly = false,
    opts: { maxAgeDays?: number; minScore?: number; cities?: string; locationMode?: string; remoteOk?: boolean; sources?: string } = {},
  ) => {
    const params = new URLSearchParams();
    if (resumeId) params.set("resume_id", resumeId);
    params.set("limit", limit.toString());
    if (test) params.set("test", "true");
    if (fresherOnly) params.set("fresher_only", "true");
    if (opts.maxAgeDays != null) params.set("max_age_days", opts.maxAgeDays.toString());
    if (opts.minScore != null) params.set("min_score", opts.minScore.toString());
    if (opts.cities) params.set("cities", opts.cities);
    if (opts.locationMode) params.set("location_mode", opts.locationMode);
    if (opts.remoteOk != null) params.set("remote_ok", opts.remoteOk.toString());
    if (opts.sources) params.set("sources", opts.sources);
    return request<JobMatchResponse>(`/api/v1/jobs/match?${params.toString()}`);
  },

  // Resume save
  resumeSave: (body: {
    resume_id: string;
    accepted_suggestions: { bullet_id: string; suggested_text: string }[];
    mode: string;
    confirm_overwrite: boolean;
  }) => request<{ file_id: string; file_ref: string; mode_applied: string }>("/api/v1/resume/save", {
    method: "POST",
    body: JSON.stringify(body),
  }),
};
