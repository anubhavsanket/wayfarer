import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Briefcase, ExternalLink, AlertTriangle, ChevronDown, ChevronUp,
  GraduationCap, MapPin, ToggleLeft, ToggleRight,
} from "lucide-react";

import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";

function locationBadge(match: string) {
  if (match === "exact") return "bg-green-100 text-green-800";
  if (match === "remote") return "bg-blue-100 text-blue-800";
  if (match === "relocation_required") return "bg-yellow-100 text-yellow-800";
  return "bg-gray-100 text-gray-800";
}

function experienceBadge(level: string) {
  if (level === "fresher") return "bg-emerald-100 text-emerald-800";
  if (level === "junior") return "bg-sky-100 text-sky-800";
  if (level === "mid") return "bg-orange-100 text-orange-800";
  if (level === "senior") return "bg-purple-100 text-purple-800";
  return "bg-gray-100 text-gray-600";
}

function sourceColor(source: string) {
  if (source === "bluedoor") return "bg-teal-50 text-teal-700 border-teal-200";
  if (source === "linkedin") return "bg-blue-50 text-blue-700 border-blue-200";
  return "bg-gray-50 text-gray-700 border-gray-200";
}

function JobCard({ job }: { job: any }) {
  return (
    <Card className="p-4 hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <Briefcase className="h-4 w-4 text-muted-foreground shrink-0" />
            <span className="font-medium truncate">{job.title}</span>
            <span className="text-sm text-muted-foreground shrink-0">@ {job.company}</span>
          </div>
          <div className="mt-1.5 flex items-center gap-2 flex-wrap">
            <span className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium ${locationBadge(job.location_match)}`}>
              <MapPin className="h-3 w-3" />
              {job.location || "Location N/A"}
            </span>
            <span className={`rounded border px-1.5 py-0.5 text-xs font-medium ${sourceColor(job.source)}`}>
              {job.source}
            </span>
            <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${experienceBadge(job.experience_level)}`}>
              {job.experience_level === "fresher" && <GraduationCap className="inline h-3 w-3 mr-0.5" />}
              {job.experience_level}
            </span>
            {job.flags?.map((flag: string) => (
              <span
                key={flag}
                className="rounded bg-red-50 px-1.5 py-0.5 font-medium text-red-700 text-xs"
                title="Potential legitimacy issue — review before applying"
              >
                ⚠ {flag}
              </span>
            ))}
          </div>
          {job.top_gaps?.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {job.top_gaps.map((g: string, i: number) => (
                <span
                  key={i}
                  className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground"
                >
                  {g}
                </span>
              ))}
            </div>
          )}
        </div>
        <div className="flex flex-col items-end gap-2 pl-4 shrink-0">
          <span className="text-2xl font-bold">
            {(job.match_score * 100).toFixed(0)}%
          </span>
          {job.apply_url && (
            <a
              href={job.apply_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 rounded bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90"
            >
              Apply
              <ExternalLink className="h-3 w-3" />
            </a>
          )}
        </div>
      </div>
    </Card>
  );
}

export default function JobMatchPage() {
  const [testMode, setTestMode] = useState(true);
  const [fresherOnly, setFresherOnly] = useState(false);
  const [showUnclear, setShowUnclear] = useState(false);

  // FR2.12 (§8.6): resolve primary resume from backend
  const { data: primary } = useQuery({
    queryKey: ["resume-primary"],
    queryFn: () => api.getResumePrimary(),
    retry: false,
  });

  const resumeId = localStorage.getItem("resume_id") ?? "";
  const resumeFileName = primary?.filename || (localStorage.getItem("resume_filename") ?? "");
  const hasResume = !!primary || !!resumeId;

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["jobs", resumeId, testMode, fresherOnly, primary?.resume_id],
    queryFn: () => api.jobsMatch(resumeId, 20, testMode, fresherOnly),
    enabled: hasResume,
  });

  return (
    <div className="space-y-6">
      {/* Controls */}
      <Card className="p-6">
        <h2 className="mb-2 text-lg font-semibold">Job Matcher</h2>
        <p className="mb-4 text-sm text-muted-foreground">
          {hasResume
            ? "Matching postings against your main resume."
            : "Upload your resume in Settings first, then come back here."}
        </p>
        {hasResume ? (
          <div className="mb-3 flex items-center gap-2 rounded-md bg-muted p-3 text-sm">
            <Briefcase className="h-4 w-4" />
            <span>{resumeFileName || "Resume loaded"}</span>
            <span className="text-xs text-muted-foreground">
              ({primary?.resume_id || resumeId})
            </span>
            <button
              onClick={() => refetch()}
              disabled={isLoading}
              className="ml-auto rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              {isLoading ? "Loading..." : "Find Matches"}
            </button>
          </div>
        ) : (
          <div className="rounded-md bg-yellow-50 p-3 text-sm text-yellow-800">
            No resume uploaded yet. Go to <strong>Settings</strong> → Primary Resume to upload your resume.
          </div>
        )}
        <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={testMode}
              onChange={(e) => setTestMode(e.target.checked)}
              className="rounded"
            />
            Sample data
          </label>
          <button
            onClick={() => setFresherOnly(!fresherOnly)}
            className="flex items-center gap-1 cursor-pointer"
          >
            {fresherOnly ? <ToggleRight className="h-4 w-4 text-primary" /> : <ToggleLeft className="h-4 w-4" />}
            Fresher mode
          </button>
        </div>
      </Card>

      {/* Loading / Error */}
      {isLoading && (
        <Card className="p-6 text-center text-sm text-muted-foreground">Loading postings...</Card>
      )}
      {error && (
        <Card className="border-destructive p-4 text-sm text-destructive">Error: {error.message}</Card>
      )}

      {/* Results */}
      {data && (
        <>
          {data.matches.length === 0 && !isLoading && (
            <Card className="p-6 text-center text-sm text-muted-foreground">
              No matches found. Upload a resume first, then try again.
            </Card>
          )}

          {data.matches.length > 0 && (
            <div>
              <p className="mb-3 text-sm font-medium text-muted-foreground">
                {data.matches.length} confirmed match{data.matches.length !== 1 ? "es" : ""}
                {fresherOnly ? " (fresher/junior only)" : ""}
              </p>
              <div className="space-y-3">
                {data.matches.map((job: any) => (
                  <JobCard key={job.job_id} job={job} />
                ))}
              </div>
            </div>
          )}

          {/* Unclear matches (collapsed by default) */}
          {data.unclear_matches && data.unclear_matches.length > 0 && (
            <div className="mt-4">
              <button
                onClick={() => setShowUnclear(!showUnclear)}
                className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground mb-2"
              >
                {showUnclear ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                {data.unclear_matches.length} unclear match{data.unclear_matches.length !== 1 ? "es" : ""}
                <span className="text-xs">(experience level couldn't be determined)</span>
              </button>
              {showUnclear && (
                <div className="space-y-3">
                  {data.unclear_matches.map((job: any) => (
                    <JobCard key={job.job_id} job={job} />
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Aggregate gaps */}
          {data.aggregate_gaps && data.aggregate_gaps.length > 0 && (
            <Card className="p-6">
              <h3 className="mb-3 font-medium">
                <AlertTriangle className="mr-1 inline h-4 w-4" />
                Top Missing Skills Across Matched Postings
              </h3>
              <ul className="space-y-1 text-sm">
                {data.aggregate_gaps.map((g: any, i: number) => (
                  <li key={i} className="flex justify-between">
                    <span>{g.skill}</span>
                    <span className="text-muted-foreground">
                      missing in {(g.missing_in_pct * 100).toFixed(0)}%
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
