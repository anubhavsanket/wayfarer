import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Briefcase, ExternalLink, AlertTriangle, ChevronDown, ChevronUp,
  GraduationCap, MapPin, ToggleLeft, ToggleRight, SlidersHorizontal,
} from "lucide-react";

import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Sticker } from "@/components/ui/badge";
import { ScoreBar } from "@/components/ui/progress";
import { Reveal, Stagger } from "@/components/Reveal";
import { LoadingIndicator } from "@/components/LoadingIndicator";

/* ── helpers ────────────────────────────────────────────────────────── */

function locationVariant(match: string) {
  if (match === "exact") return "verified";
  if (match === "remote") return "blue";
  if (match === "relocation_required") return "reworded";
  return "muted";
}

function experienceVariant(level: string) {
  if (level === "fresher") return "cyan";
  if (level === "junior") return "blue";
  if (level === "mid") return "muted";
  if (level === "senior") return "ink";
  return "muted";
}

function sourceVariant(source: string) {
  if (source === "bluedoor") return "cyan";
  if (source === "linkedin") return "blue";
  return "muted";
}

/* ── Job Card ───────────────────────────────────────────────────────── */

function JobCard({ job }: { job: any }) {
  return (
    <Card className="p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          {/* Title + company */}
          <div className="flex items-center gap-2 flex-wrap">
            <Briefcase className="h-4 w-4 shrink-0 text-blue" />
            <span className="font-display truncate font-bold">{job.title}</span>
            <span className="text-sm text-muted-foreground shrink-0">@ {job.company}</span>
          </div>

          {/* Stickers row */}
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Sticker variant={locationVariant(job.location_match)}>
              <MapPin className="h-3 w-3" />
              {job.location || "N/A"}
            </Sticker>
            <Sticker variant={sourceVariant(job.source)}>
              {job.source}
            </Sticker>
            {job.experience_level && (
              <Sticker variant={experienceVariant(job.experience_level)}>
                {job.experience_level === "fresher" && <GraduationCap className="h-3 w-3" />}
                {job.experience_level}
              </Sticker>
            )}
            {job.flags?.map((flag: string) => (
              <span key={flag} title="Potential legitimacy issue — review before applying">
                <Sticker variant="destructive">⚠ {flag}</Sticker>
              </span>
            ))}
          </div>

          {/* Gap chips */}
          {job.top_gaps?.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {job.top_gaps.map((g: string, i: number) => (
                <Sticker key={i} variant="muted">
                  {g}
                </Sticker>
              ))}
            </div>
          )}
        </div>

        {/* Score + Apply */}
        <div className="flex shrink-0 flex-col items-end gap-2 pl-4">
          <span className="font-display text-3xl font-bold tabular-nums leading-none">
            {(job.match_score * 100).toFixed(0)}%
          </span>
          {job.apply_url && (
            <a
              href={job.apply_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 rounded-md border-2 border-ink bg-blue px-3 py-1.5 text-xs font-semibold text-white shadow-hard-sm transition-all duration-150 hover:-translate-y-0.5 hover:shadow-hard active:translate-y-0.5 active:shadow-hard-none"
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

/* ── Filter Panel ───────────────────────────────────────────────────── */

function FilterPanel({
  locationMode, setLocationMode,
  cityFilter, setCityFilter,
  remoteOk, setRemoteOk,
  maxAgeDays, setMaxAgeDays,
  minScore, setMinScore,
  sourceFilter, setSourceFilter,
  onReset, onApply, filtersChanged,
}: {
  locationMode: string; setLocationMode: (v: string) => void;
  cityFilter: string; setCityFilter: (v: string) => void;
  remoteOk: boolean; setRemoteOk: (v: boolean) => void;
  maxAgeDays: number; setMaxAgeDays: (v: number) => void;
  minScore: number; setMinScore: (v: number) => void;
  sourceFilter: string; setSourceFilter: (v: string) => void;
  onReset: () => void;
  onApply: () => void;
  filtersChanged: boolean;
}) {
  const AVAILABLE_SOURCES = [
    "remoteok", "remotive", "jobicy", "arbeitnow", "himalayas",
    "bluedoor", "linkedin_guest", "adzuna",
  ];

  return (
    <div className="mt-4 space-y-4 rounded-lg border-2 border-ink bg-card p-4 shadow-hard-sm">
      {/* Location */}
      <div className="space-y-1.5">
        <label className="text-sm font-semibold">Location</label>
        <div className="flex gap-2">
          <select
            value={locationMode}
            onChange={(e) => setLocationMode(e.target.value)}
            className="rounded-md border-2 border-ink bg-cream px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-cyan"
          >
            <option value="specific_city">Specific city</option>
            <option value="remote_only">Remote only</option>
            <option value="hybrid">Hybrid</option>
            <option value="open_to_relocation">Open to relocation</option>
          </select>
          {locationMode === "specific_city" && (
            <input
              type="text"
              value={cityFilter}
              onChange={(e) => setCityFilter(e.target.value)}
              placeholder="e.g. Bengaluru"
              className="flex-1 rounded-md border-2 border-ink bg-cream px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-cyan"
            />
          )}
        </div>
        {locationMode === "specific_city" && (
          <label className="flex cursor-pointer items-center gap-2 text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={remoteOk}
              onChange={(e) => setRemoteOk(e.target.checked)}
              className="accent-cyan"
            />
            Include remote postings
          </label>
        )}
      </div>

      {/* Posting age slider */}
      <div className="space-y-1.5">
        <label className="text-sm font-semibold">
          Posting age: up to {maxAgeDays} day{maxAgeDays !== 1 ? "s" : ""} old
        </label>
        <input
          type="range"
          min={1} max={90} value={maxAgeDays}
          onChange={(e) => setMaxAgeDays(parseInt(e.target.value))}
          className="w-full accent-blue"
        />
        <div className="flex justify-between text-[10px] font-mono text-muted-foreground">
          <span>1d</span><span>30d</span><span>90d</span>
        </div>
      </div>

      {/* Min score slider */}
      <div className="space-y-1.5">
        <label className="text-sm font-semibold">Minimum match: {minScore}%</label>
        <input
          type="range"
          min={0} max={80} step={5} value={minScore}
          onChange={(e) => setMinScore(parseInt(e.target.value))}
          className="w-full accent-blue"
        />
        <div className="flex justify-between text-[10px] font-mono text-muted-foreground">
          <span>0%</span><span>40%</span><span>80%</span>
        </div>
      </div>

      {/* Job sources */}
      <div className="space-y-1.5">
        <label className="text-sm font-semibold">Job Sources</label>
        <div className="flex flex-wrap gap-2">
          {AVAILABLE_SOURCES.map((src) => (
            <label key={src} className="flex cursor-pointer items-center gap-1.5 text-xs">
              <input
                type="checkbox"
                checked={!sourceFilter || sourceFilter.split(",").includes(src)}
                onChange={(e) => {
                  const current = sourceFilter ? sourceFilter.split(",") : [...AVAILABLE_SOURCES];
                  if (e.target.checked) current.push(src);
                  else {
                    const idx = current.indexOf(src);
                    if (idx >= 0) current.splice(idx, 1);
                  }
                  setSourceFilter(current.join(","));
                }}
                className="accent-blue"
              />
              {src}
            </label>
          ))}
        </div>
        <p className="text-[10px] font-mono text-muted-foreground">
          {sourceFilter ? `${sourceFilter.split(",").length}/${AVAILABLE_SOURCES.length} sources active` : "All sources active"}
        </p>
      </div>

      {/* Reset */}
      <button onClick={onReset} className="text-xs font-semibold text-muted-foreground underline hover:text-foreground">
        Reset all filters
      </button>

      {/* Apply */}
      <Button onClick={onApply} disabled={!filtersChanged} className="w-full">
        Apply Filters
        {filtersChanged && (
          <span className="ml-2 rounded bg-cyan px-1.5 py-0.5 text-[10px] font-bold text-ink">
            unsaved
          </span>
        )}
      </Button>
    </div>
  );
}

/* ── Main Page ──────────────────────────────────────────────────────── */

export default function JobMatchPage() {
  const [fresherOnly, setFresherOnly] = useState(false);
  const [showUnclear, setShowUnclear] = useState(false);
  const [showFilters, setShowFilters] = useState(false);

  // Editable filter state
  const [maxAgeDays, setMaxAgeDays] = useState(30);
  const [minScore, setMinScore] = useState(0);
  const [cityFilter, setCityFilter] = useState("");
  const [locationMode, setLocationMode] = useState("specific_city");
  const [remoteOk, setRemoteOk] = useState(false);
  const [sourceFilter, setSourceFilter] = useState("");

  // Committed filter state (only changes on "Apply" click)
  const [appliedFilters, setAppliedFilters] = useState({
    maxAgeDays: 30, minScore: 0, cityFilter: "", locationMode: "specific_city",
    remoteOk: false, sourceFilter: "",
  });

  const filtersChanged =
    maxAgeDays !== appliedFilters.maxAgeDays ||
    minScore !== appliedFilters.minScore ||
    cityFilter !== appliedFilters.cityFilter ||
    locationMode !== appliedFilters.locationMode ||
    remoteOk !== appliedFilters.remoteOk ||
    sourceFilter !== appliedFilters.sourceFilter;

  const applyFilters = () => {
    setAppliedFilters({ maxAgeDays, minScore, cityFilter, locationMode, remoteOk, sourceFilter });
  };

  const resetFilters = () => {
    setMaxAgeDays(30);
    setMinScore(0);
    setCityFilter("");
    setLocationMode("specific_city");
    setRemoteOk(false);
    setSourceFilter("");
    setAppliedFilters({ maxAgeDays: 30, minScore: 0, cityFilter: "", locationMode: "specific_city", remoteOk: false, sourceFilter: "" });
  };

  // Primary resume
  const { data: primary } = useQuery({
    queryKey: ["resume-primary"],
    queryFn: () => api.getResumePrimary(),
    retry: false,
  });

  const resumeId = localStorage.getItem("resume_id") ?? "";
  const resumeFileName = primary?.filename || (localStorage.getItem("resume_filename") ?? "");
  const hasResume = !!primary || !!resumeId;

  const [hasFetched, setHasFetched] = useState(false);
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["jobs", resumeId, fresherOnly, primary?.resume_id, appliedFilters],
    queryFn: async () => {
      const result = await api.jobsMatch(resumeId, 50, false, fresherOnly, {
        maxAgeDays: appliedFilters.maxAgeDays,
        minScore: appliedFilters.minScore / 100,
        cities: appliedFilters.cityFilter,
        locationMode: appliedFilters.locationMode,
        remoteOk: appliedFilters.remoteOk,
        sources: appliedFilters.sourceFilter,
      });
      setHasFetched(true);
      return result;
    },
    // Disabled initially; auto-refetches when filters change after first fetch
    enabled: hasFetched,
  });

  const totalResults = (data?.matches?.length ?? 0) + (data?.unclear_matches?.length ?? 0);

  return (
    <div className="space-y-4">
      {/* ── Controls ─────────────────────────────────────────── */}
      <Card className="p-6">
        <h2 className="font-display mb-1 text-lg font-bold">Job Matcher</h2>
        <p className="mb-4 text-sm text-muted-foreground">
          {hasResume
            ? "Matching postings against your main resume."
            : "Upload your resume in Settings first, then come back here."}
        </p>

        {hasResume ? (
          <div className="mb-3 flex flex-wrap items-center gap-3 rounded-md bg-beige-deep p-3 text-sm border-2 border-ink/20">
            <div className="flex items-center gap-2 min-w-0">
              <Briefcase className="h-4 w-4 shrink-0 text-blue" />
              <span className="font-medium truncate">{resumeFileName || "Resume loaded"}</span>
              <span className="text-xs text-muted-foreground">
                ({primary?.resume_id || resumeId})
              </span>
            </div>
            <Button
              onClick={() => refetch()}
              disabled={isLoading}
              size="sm"
            >
              {isLoading ? "Loading..." : "Find Matches"}
            </Button>
          </div>
        ) : (
          <div className="rounded-md border-2 border-ink bg-cream p-4 text-sm text-muted-foreground">
            <span className="font-semibold text-foreground">No resume uploaded yet.</span>{" "}
            Go to <strong>Settings</strong> → Primary Resume to upload your resume, then come back here to find matches.
          </div>
        )}

        {/* Toggle row */}
        <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
          <button
            onClick={() => setFresherOnly(!fresherOnly)}
            className="flex cursor-pointer items-center gap-1"
          >
            {fresherOnly
              ? <ToggleRight className="h-4 w-4 text-blue" />
              : <ToggleLeft className="h-4 w-4" />}
            Fresher mode
          </button>
          <button
            onClick={() => setShowFilters(!showFilters)}
            className="flex cursor-pointer items-center gap-1"
          >
            <SlidersHorizontal className="h-4 w-4" />
            Filters
            {filtersChanged && (
              <Sticker variant="cyan" className="text-[10px]">active</Sticker>
            )}
          </button>
        </div>

        {showFilters && (
          <FilterPanel
            locationMode={locationMode} setLocationMode={setLocationMode}
            cityFilter={cityFilter} setCityFilter={setCityFilter}
            remoteOk={remoteOk} setRemoteOk={setRemoteOk}
            maxAgeDays={maxAgeDays} setMaxAgeDays={setMaxAgeDays}
            minScore={minScore} setMinScore={setMinScore}
            sourceFilter={sourceFilter} setSourceFilter={setSourceFilter}
            onReset={resetFilters} onApply={applyFilters} filtersChanged={filtersChanged}
          />
        )}
      </Card>

      {/* Loading */}
      {isLoading && (
        <Reveal>
          <LoadingIndicator message="Finding matches" />
        </Reveal>
      )}

      {/* Error */}
      {error && (
        <Card className="border-destructive p-4 text-sm text-destructive">
          Error: {error.message}
        </Card>
      )}

      {/* ── Results ─────────────────────────────────────────── */}
      {data && (
        <>
          {totalResults === 0 && !isLoading && (
            <Card className="p-8 text-center">
              <p className="mb-2 text-sm font-semibold">No matches found</p>
              <p className="text-xs text-muted-foreground">
                Try adjusting your filters, broadening your search, or uploading a different resume.
              </p>
            </Card>
          )}

          {data.matches.length > 0 && (
            <Stagger className="space-y-3">
              <p className="mb-1 text-sm font-semibold text-muted-foreground">
                {data.matches.length} confirmed match{data.matches.length !== 1 ? "es" : ""}
                {fresherOnly ? " (fresher/junior only)" : ""}
                {minScore > 0 ? ` (≥${minScore}% match)` : ""}
              </p>
              {data.matches.map((job: any) => (
                <JobCard key={job.job_id} job={job} />
              ))}
            </Stagger>
          )}

          {/* Unclear matches */}
          {data.unclear_matches && data.unclear_matches.length > 0 && (
            <div className="mt-4">
              <button
                onClick={() => setShowUnclear(!showUnclear)}
                className="flex items-center gap-2 text-sm font-semibold text-muted-foreground hover:text-foreground"
              >
                {showUnclear
                  ? <ChevronUp className="h-4 w-4" />
                  : <ChevronDown className="h-4 w-4" />}
                {data.unclear_matches.length} unclear match{data.unclear_matches.length !== 1 ? "es" : ""}
                <span className="text-xs font-normal">(experience level couldn't be determined)</span>
              </button>
              {showUnclear && (
                <Stagger className="mt-3 space-y-3">
                  {data.unclear_matches.map((job: any) => (
                    <JobCard key={job.job_id} job={job} />
                  ))}
                </Stagger>
              )}
            </div>
          )}

          {/* Aggregate gaps */}
          {data.aggregate_gaps && data.aggregate_gaps.length > 0 && (
            <Card className="p-6">
              <Sticker variant="alert" className="mb-3">
                <AlertTriangle className="h-3 w-3" /> Top Missing Skills
              </Sticker>
              <ul className="space-y-2">
                {data.aggregate_gaps.map((g: any, i: number) => (
                  <li key={i} className="flex items-center gap-3">
                    <span className="flex-1 text-sm font-medium">{g.skill}</span>
                    <ScoreBar
                      value={g.missing_in_pct * 100}
                      decimals={0}
                      suffix="%"
                      className="w-48"
                    />
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
