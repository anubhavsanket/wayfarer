// Mirrors backend Pydantic schemas

export type ConfidenceTier = "verified" | "reworded" | "gap";
export type SaveMode = "new_file" | "overwrite" | "set_as_primary";

// Health

export interface DependencyStatus {
  name: string;
  status: "up" | "down";
  detail?: string;
}

export interface HealthResponse {
  status: "ok" | "degraded";
  dependencies: DependencyStatus[];
}

// Stage 1 — Search

export interface Citation {
  id: number;
  url: string;
  title: string;
  snippet: string;
}

export interface SearchResponse {
  answer: string;
  citations: Citation[];
  sub_queries_used: string[];
  cached?: boolean;
}

// Stage 2 — Resume / ATS

export interface StructuralIssue {
  location: string;
  issue: string;
}

export interface KeywordGap {
  keyword: string;
  tier: ConfidenceTier;
  bullet_id?: string | null;
  original_text?: string | null;
  suggested_text?: string | null;
  rationale: string;
  confidence?: number | null;
}

export interface ResumeCheckResponse {
  resume_id: string;
  ats_score: number;
  structural_issues: StructuralIssue[];
  keyword_gaps: KeywordGap[];
}

// Stage 3 — Job matching

export type LocationMode =
  | "specific_city"
  | "remote_only"
  | "hybrid"
  | "open_to_relocation";

export type LocationMatch =
  | "exact"
  | "remote"
  | "relocation_required"
  | "none";

export interface JobMatch {
  job_id: string;
  title: string;
  company: string;
  source: string;
  location: string;
  match_score: number;
  location_match: LocationMatch;
  top_gaps: string[];
  apply_url: string;
  flags?: string[];
  experience_level?: "fresher" | "junior" | "mid" | "senior" | "unclear";
  min_experience_years?: number | null;
  employment_type?: "full_time" | "contract" | "freelance" | "part_time" | "unclear";
}

export interface AggregateGap {
  skill: string;
  missing_in_pct: number;
}

export interface JobMatchResponse {
  matches: JobMatch[];
  unclear_matches?: JobMatch[];
  aggregate_gaps: AggregateGap[];
}

// Primary resume management (§8.6)

export interface ResumePrimaryInfo {
  resume_id: string;
  filename: string;
  uploaded_at: string;
}
