import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Briefcase, ExternalLink, AlertTriangle } from "lucide-react";

import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";

function locationBadge(match: string) {
  if (match === "exact") return "bg-green-100 text-green-800";
  if (match === "remote") return "bg-blue-100 text-blue-800";
  if (match === "relocation_required") return "bg-yellow-100 text-yellow-800";
  return "bg-gray-100 text-gray-800";
}

export default function JobMatchPage() {
  // Read resume_id from localStorage (set by Resume Check page),
  // or allow manual input
  const [resumeIdInput, setResumeIdInput] = useState(
    () => localStorage.getItem("resume_id") ?? ""
  );
  const resumeId = resumeIdInput.trim();
  const [testMode, setTestMode] = useState(true);
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["jobs", resumeId, testMode],
    queryFn: () => api.jobsMatch(resumeId, 20, testMode),
    enabled: !!resumeId,
  });

  return (
    <div className="space-y-6">
      <Card className="p-6">
        <h2 className="mb-4 text-lg font-semibold">Job Matcher</h2>
        <p className="mb-4 text-sm text-muted-foreground">
          Live postings ranked by fit, with apply links and gap analysis.
        </p>
        <div className="flex gap-3">
          <input
            value={resumeIdInput}
            onChange={(e) => setResumeIdInput(e.target.value)}
            placeholder="Enter resume_id from /resume/check"
            className="flex-1 rounded-md border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring"
          />
          <button
            onClick={() => refetch()}
            disabled={!resumeId}
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            Match
          </button>
        </div>
        <label className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={testMode}
            onChange={(e) => setTestMode(e.target.checked)}
            className="rounded"
          />
          Use sample data (skip live board APIs)
        </label>
      </Card>

      {isLoading && (
        <Card className="p-6 text-center text-sm text-muted-foreground">
          Loading postings...
        </Card>
      )}

      {error && (
        <Card className="border-destructive p-4 text-sm text-destructive">
          Error: {error.message}
        </Card>
      )}

      {data && (
        <>
          {data.matches.length === 0 && (
            <Card className="p-6 text-center text-sm text-muted-foreground">
              No matches found yet. Run a search or upload a resume to start.
            </Card>
          )}

          {data.matches.map((job) => (
            <Card key={job.job_id} className="p-4">
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <Briefcase className="h-4 w-4 text-muted-foreground" />
                    <span className="font-medium">{job.title}</span>
                    <span className="text-sm text-muted-foreground">
                      @ {job.company}
                    </span>
                  </div>
                  <div className="mt-1 flex items-center gap-3 text-xs text-muted-foreground">
                    <span>{job.location || "Location not specified"}</span>
                    <span>Source: {job.source}</span>
                    <span
                      className={`rounded px-1.5 py-0.5 font-medium ${locationBadge(job.location_match)}`}
                    >
                      {job.location_match}
                    </span>
                    {job.flags?.map((flag) => (
                      <span
                        key={flag}
                        className="rounded bg-red-50 px-1.5 py-0.5 font-medium text-red-700"
                        title="Potential legitimacy issue — review before applying"
                      >
                        ⚠ {flag}
                      </span>
                    ))}
                  </div>
                  {job.top_gaps.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {job.top_gaps.map((g, i) => (
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
                <div className="flex flex-col items-end gap-2 pl-4">
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
          ))}

          {data.aggregate_gaps.length > 0 && (
            <Card className="p-6">
              <h3 className="mb-3 font-medium">
                <AlertTriangle className="mr-1 inline h-4 w-4" />
                Top Missing Skills Across All Postings
              </h3>
              <ul className="space-y-1 text-sm">
                {data.aggregate_gaps.map((g, i) => (
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
