import { useEffect, useState } from "react";
import {
  LayoutDashboard, ExternalLink, Trash2, ChevronDown,
  Briefcase, BarChart3, Clock, Target, PieChart,
} from "lucide-react";

import { api, ApiError } from "@/lib/api";
import type { Application, ApplicationStatus, TrackerStats } from "@/lib/types";
import { Card } from "@/components/ui/card";
import { Sticker } from "@/components/ui/badge";
import { LoadingIndicator } from "@/components/LoadingIndicator";

const STATUSES: ApplicationStatus[] = ["applied", "interview", "offer", "rejected"];
const STATUS_COLORS: Record<ApplicationStatus, string> = {
  applied: "bg-cyan/10 border-cyan/30",
  interview: "bg-blue/10 border-blue/30",
  offer: "bg-verified/10 border-verified/30",
  rejected: "bg-muted border-border",
};

export default function TrackerPage() {
  const [applications, setApplications] = useState<Application[]>([]);
  const [stats, setStats] = useState<TrackerStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = () => {
    setLoading(true);
    setError(null);
    Promise.all([api.listApplications(), api.getTrackerStats()])
      .then(([apps, st]) => {
        setApplications(apps);
        setStats(st);
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load tracker."))
      .finally(() => setLoading(false));
  };

  useEffect(() => { reload(); }, []);

  const updateStatus = (jobId: string, status: ApplicationStatus) =>
    api.updateApplication(jobId, { status }).then(reload).catch((e) => setError(e.message));

  const removeApplication = (jobId: string) =>
    api.deleteApplication(jobId).then(reload).catch((e) => setError(e.message));

  const appsByStatus = (status: ApplicationStatus) =>
    applications.filter((a) => a.status === status);

  return (
    <div className="max-w-7xl mx-auto space-y-8 pb-12">
      {/* Header */}
      <div className="border-b border-ink/10 pb-6">
        <div className="flex items-center gap-3">
          <LayoutDashboard className="h-8 w-8 text-blue" />
          <h1 className="font-display text-4xl font-black text-ink dark:text-foreground">Pipeline</h1>
        </div>
        <p className="mt-2 text-sm text-muted-foreground">
          Track your applications from first apply to offer.
        </p>
      </div>

      {error && (
        <div className="rounded-md border border-destructive bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {loading && <LoadingIndicator message="Loading pipeline" />}

      {!loading && stats && (
        <>
          {/* Stats Row */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <StatCard
              icon={<Briefcase className="h-4 w-4" />}
              label="Total Applied"
              value={stats.total}
            />
            <StatCard
              icon={<Target className="h-4 w-4" />}
              label="Interview Rate"
              value={`${(stats.interview_rate * 100).toFixed(0)}%`}
            />
            <StatCard
              icon={<BarChart3 className="h-4 w-4" />}
              label="Avg Match Score"
              value={`${(stats.avg_match_score * 100).toFixed(0)}%`}
            />
            <StatCard
              icon={<Clock className="h-4 w-4" />}
              label="Longest Pending"
              value={stats.oldest_pending_days !== null ? `${stats.oldest_pending_days}d` : "—"}
            />
          </div>

          {/* Source Breakdown */}
          {Object.keys(stats.source_breakdown).length > 0 && (
            <Card className="p-4">
              <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
                <PieChart className="h-4 w-4" /> Sources
              </h3>
              <div className="flex flex-wrap gap-3">
                {Object.entries(stats.source_breakdown).map(([source, count]) => (
                  <div key={source} className="flex items-center gap-1.5 text-xs">
                    <span className="font-medium capitalize">{source}</span>
                    <Sticker variant="cyan">{count}</Sticker>
                  </div>
                ))}
              </div>
            </Card>
          )}

          {/* Kanban Board */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            {STATUSES.map((status) => (
              <KanbanColumn
                key={status}
                status={status}
                applications={appsByStatus(status)}
                daysInStage={stats.days_in_stage}
                onUpdateStatus={updateStatus}
                onDelete={removeApplication}
              />
            ))}
          </div>
        </>
      )}

      {!loading && applications.length === 0 && (
        <Card className="p-12 text-center text-sm text-muted-foreground">
          No applications yet. Go to Job Match, find a posting, and mark it as "Applied" to start tracking.
        </Card>
      )}
    </div>
  );
}

/* ── Stat Card ────────────────────────────────────────────────────── */

function StatCard({ icon, label, value }: { icon: React.ReactNode; label: string; value: string | number }) {
  return (
    <Card className="p-4">
      <div className="flex items-center gap-2 text-xs text-muted-foreground mb-1">
        {icon}
        {label}
      </div>
      <div className="text-2xl font-bold text-foreground">{value}</div>
    </Card>
  );
}

/* ── Kanban Column ────────────────────────────────────────────────── */

function KanbanColumn({
  status, applications, daysInStage, onUpdateStatus, onDelete,
}: {
  status: ApplicationStatus;
  applications: Application[];
  daysInStage: Record<string, number>;
  onUpdateStatus: (jobId: string, status: ApplicationStatus) => void;
  onDelete: (jobId: string) => void;
}) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold capitalize flex items-center gap-1.5">
          {status}
          <Sticker variant="muted">{applications.length}</Sticker>
        </h3>
      </div>
      <div className={`rounded-lg border p-2 space-y-2 min-h-[200px] ${STATUS_COLORS[status]}`}>
        {applications.map((app) => (
          <KanbanCard
            key={app.id}
            app={app}
            daysInStage={daysInStage[app.job_id]}
            onUpdateStatus={onUpdateStatus}
            onDelete={onDelete}
          />
        ))}
        {applications.length === 0 && (
          <div className="h-full flex items-center justify-center p-4 text-xs text-muted-foreground">
            No items
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Kanban Card ──────────────────────────────────────────────────── */

function KanbanCard({
  app, daysInStage, onUpdateStatus, onDelete,
}: {
  app: Application;
  daysInStage?: number;
  onUpdateStatus: (jobId: string, status: ApplicationStatus) => void;
  onDelete: (jobId: string) => void;
}) {
  const [showMenu, setShowMenu] = useState(false);

  return (
    <div className="rounded-md bg-card border border-border p-3 shadow-sm space-y-2">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-semibold truncate">{app.title}</p>
          <p className="text-xs text-muted-foreground truncate">@{app.company}</p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {app.apply_url && (
            <a
              href={app.apply_url}
              target="_blank"
              rel="noopener noreferrer"
              className="rounded p-1 text-muted-foreground hover:text-blue"
            >
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          )}
          <button
            onClick={() => onDelete(app.job_id)}
            className="rounded p-1 text-muted-foreground hover:text-destructive"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <div className="flex items-center justify-between text-xs text-muted-foreground">
        {daysInStage !== undefined && (
          <span className="flex items-center gap-1">
            <Clock className="h-3 w-3" /> {daysInStage}d
          </span>
        )}
        <div className="relative ml-auto">
          <button
            onClick={() => setShowMenu(!showMenu)}
            className="flex items-center gap-1 rounded border border-border px-2 py-0.5 hover:bg-accent"
          >
            Move <ChevronDown className="h-3 w-3" />
          </button>
          {showMenu && (
            <div className="absolute right-0 bottom-full mb-1 z-10 w-32 rounded-md border border-border bg-card shadow-md">
              {STATUSES.filter((s) => s !== app.status).map((s) => (
                <button
                  key={s}
                  onClick={() => {
                    onUpdateStatus(app.job_id, s);
                    setShowMenu(false);
                  }}
                  className="w-full text-left px-3 py-1.5 text-xs hover:bg-accent capitalize"
                >
                  {s}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
