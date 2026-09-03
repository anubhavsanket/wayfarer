import type {
  Application,
  ApplicationStatus,
  CoverLetterResponse,
  HealthResponse,
  JobMatchResponse,
  ResumeCheckResponse,
  SavedJob,
  SearchResponse,
} from "./types";
import { buildAuthHeaders } from "@/stores/settings";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";
const DEFAULT_TIMEOUT_MS = 60_000;

/** Normalised API error with status and the FastAPI `detail` message. */
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), DEFAULT_TIMEOUT_MS);
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      headers: {
        "Content-Type": "application/json",
        ...buildAuthHeaders(),
        ...init?.headers,
      },
      ...init,
      signal: controller.signal,
    });
  } catch (err) {
    throw new ApiError(
      0,
      err instanceof DOMException && err.name === "AbortError"
        ? "Request timed out. The server may be busy; try again."
        : "Network error: could not reach the API.",
    );
  } finally {
    clearTimeout(timeout);
  }
  if (!res.ok) {
    let detail = `API error ${res.status}`;
    try {
      const body = await res.json();
      if (body && typeof body.detail === "string") detail = body.detail;
    } catch {
      /* non-JSON body */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  // Health
  health: () => request<HealthResponse>("/health"),

  // Auth
  authLogin: (payload: { email: string; name?: string }) =>
    request<{ access_token: string; user_id: string; email: string; name: string }>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getMe: () =>
    request<{ user_id: string; email: string; name: string }>("/api/v1/auth/me"),

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
  jobsMatch: (
    resumeId: string,
    limit = 20,
    test = false,
    fresherOnly = false,
    locationMode = "specific_city",
    cities = "",
    remoteOk = false
  ) => {
    const params = new URLSearchParams({
      resume_id: resumeId,
      limit: String(limit),
      location_mode: locationMode,
    });
    if (test) params.append("test", "true");
    if (fresherOnly) params.append("fresher_only", "true");
    if (cities) params.append("cities", cities);
    if (remoteOk) params.append("remote_ok", "true");
    return request<JobMatchResponse>(`/api/v1/jobs/match?${params.toString()}`);
  },

  // Tracker — saved jobs
  listSaved: () => request<SavedJob[]>("/api/v1/tracker/saved"),
  saveJob: (job: {
    job_id: string;
    title: string;
    company: string;
    apply_url?: string;
    source?: string;
    location?: string;
    match_score?: number;
  }) =>
    request<SavedJob>("/api/v1/tracker/saved", {
      method: "POST",
      body: JSON.stringify(job),
    }),
  unsaveJob: (jobId: string) =>
    request<{ removed: boolean }>(`/api/v1/tracker/saved/${jobId}`, {
      method: "DELETE",
    }),

  // Tracker — applications
  listApplications: () => request<Application[]>("/api/v1/tracker/applications"),
  createApplication: (job: {
    job_id: string;
    title: string;
    company: string;
    apply_url?: string;
    source?: string;
    location?: string;
    match_score?: number;
    resume_id?: string;
  }) =>
    request<Application>("/api/v1/tracker/applications", {
      method: "POST",
      body: JSON.stringify(job),
    }),
  updateApplication: (
    jobId: string,
    patch: { status?: ApplicationStatus; notes?: string },
  ) =>
    request<Application>(`/api/v1/tracker/applications/${jobId}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  deleteApplication: (jobId: string) =>
    request<{ removed: boolean }>(`/api/v1/tracker/applications/${jobId}`, {
      method: "DELETE",
    }),

  // Cover letter
  coverLetter: (resumeId: string, job: Record<string, unknown>) =>
    request<CoverLetterResponse>("/api/v1/tracker/cover-letter", {
      method: "POST",
      body: JSON.stringify({ resume_id: resumeId, job }),
    }),

  // OAuth & Multi-tenant User Settings
  authLogin: (payload: {
    provider?: string;
    token?: string;
    email?: string;
    name?: string;
    picture?: string;
  }) =>
    request<{
      access_token: string;
      token_type: string;
      user_id: string;
      email: string;
      name: string;
      picture: string;
    }>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getMe: () =>
    request<{ user_id: string; email: string; name: string; picture: string }>(
      "/api/v1/auth/me",
    ),
  getUserSettings: () =>
    request<{ user_id: string; settings: Record<string, unknown> }>(
      "/api/v1/user/settings",
    ),
  saveUserSettings: (settings: Record<string, unknown>) =>
    request<{ user_id: string; settings: Record<string, unknown> }>(
      "/api/v1/user/settings",
      {
        method: "POST",
        body: JSON.stringify({ settings }),
      },
    ),
};
