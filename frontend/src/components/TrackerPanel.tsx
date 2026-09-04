import { useEffect, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {
  Briefcase, Bookmark, X, ExternalLink, Trash2, FileText, Check,
} from "lucide-react";

import { api, ApiError } from "@/lib/api";
import type { Application, ApplicationStatus, SavedJob } from "@/lib/types";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Sticker } from "@/components/ui/badge";
import { LoadingIndicator } from "@/components/LoadingIndicator";

const STATUS_OPTIONS: ApplicationStatus[] = ["applied", "interview", "offer", "rejected"];
const STATUS_VARIANT: Record<ApplicationStatus, string> = {
  applied: "cyan",
  interview: "blue",
  offer: "verified",
  rejected: "muted",
};

/* ── Cover letter modal ─────────────────────────────────────────────── */

function CoverLetterModal({
  open, onOpenChange, resumeId, job,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  resumeId: string;
  job: { title: string; company: string; job_id: string };
}) {
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!open) return;
    setText("");
    setError(null);
    setCopied(false);
    setLoading(true);
    api
      .coverLetter(resumeId, job)
      .then((r) => setText(r.cover_letter))
      .catch((e) =>
        setError(e instanceof ApiError ? e.message : "Failed to draft cover letter."),
      )
      .finally(() => setLoading(false));
  }, [open, resumeId, job]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[min(92vw,680px)] -translate-x-1/2 -translate-y-1/2 rounded-lg border border-border bg-white p-6 shadow-lg dark:border-border dark:bg-card">
          <div className="mb-3 flex items-start justify-between gap-4">
            <div>
              <Dialog.Title className="font-display text-lg font-bold">
                Cover Letter
              </Dialog.Title>
              <Dialog.Description className="text-xs text-muted-foreground">
                {job.title} at {job.company} — drafted from your resume.
              </Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <button className="rounded-md p-1 hover:bg-beige-deep" aria-label="Close">
                <X className="h-4 w-4" />
              </button>
            </Dialog.Close>
          </div>

          {loading && <LoadingIndicator message="Drafting cover letter" />}
          {error && (
            <div className="rounded-md border border-destructive bg-destructive/10 p-3 text-sm text-destructive">
              {error}
            </div>
          )}
          {!loading && !error && (
            <>
              <div className="max-h-[50vh] overflow-y-auto whitespace-pre-wrap rounded-md border border-border bg-background p-4 text-sm leading-relaxed">
                {text}
              </div>
              <div className="mt-3 flex justify-end gap-2">
                <Button onClick={copy} variant="outline" size="sm">
                  {copied ? <Check className="h-3.5 w-3.5" /> : <FileText className="h-3.5 w-3.5" />}
                  {copied ? "Copied" : "Copy"}
                </Button>
              </div>
            </>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/* ── Tracker panel ──────────────────────────────────────────────────── */

export function TrackerPanel({
  open, onOpenChange, resumeId,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  resumeId: string;
}) {
  const [saved, setSaved] = useState<SavedJob[]>([]);
  const [applications, setApplications] = useState<Application[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [coverJob, setCoverJob] = useState<{
    job_id: string; title: string; company: string;
  } | null>(null);

  const reload = () => {
    setLoading(true);
    setError(null);
    Promise.all([api.listSaved(), api.listApplications()])
      .then(([s, a]) => {
        setSaved(s);
        setApplications(a);
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load tracker."))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    if (open) reload();
  }, [open]);

  const unsave = (jobId: string) =>
    api.unsaveJob(jobId).then(reload).catch((e) => setError(e.message));

  const updateStatus = (jobId: string, status: ApplicationStatus) =>
    api.updateApplication(jobId, { status }).then(reload).catch((e) => setError(e.message));

  const removeApplication = (jobId: string) =>
    api.deleteApplication(jobId).then(reload).catch((e) => setError(e.message));

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[min(94vw,720px)] -translate-x-1/2 -translate-y-1/2 rounded-lg border border-border bg-white p-6 shadow-lg dark:border-border dark:bg-card">
          <div className="mb-4 flex items-start justify-between">
            <div>
              <Dialog.Title className="font-display text-lg font-bold">
                Application Tracker
              </Dialog.Title>
              <Dialog.Description className="text-xs text-muted-foreground">
                Bookmark postings and track the jobs you apply to.
              </Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <button className="rounded-md p-1 hover:bg-beige-deep" aria-label="Close">
                <X className="h-4 w-4" />
              </button>
            </Dialog.Close>
          </div>

          {error && (
            <div className="mb-3 rounded-md border border-destructive bg-destructive/10 p-3 text-sm text-destructive">
              {error}
            </div>
          )}
          {loading && <LoadingIndicator message="Loading tracker" />}
          {!loading && (
            <div className="max-h-[60vh] space-y-5 overflow-y-auto">
              {/* Applications */}
              <section>
                <h3 className="mb-2 flex items-center gap-1.5 text-sm font-semibold">
                  <Briefcase className="h-4 w-4" /> Applications ({applications.length})
                </h3>
                {applications.length === 0 ? (
                  <Card className="p-4 text-center text-xs text-muted-foreground">
                    Mark matching postings as "Applied" to start tracking.
                  </Card>
                ) : (
                  <div className="space-y-2">
                    {applications.map((a) => (
                      <div
                        key={a.id}
                        className="rounded-md border border-border bg-background p-3"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <div className="min-w-0">
                            <p className="truncate text-sm font-semibold">{a.title}</p>
                            <p className="truncate text-xs text-muted-foreground">@{a.company}</p>
                          </div>
                          <div className="flex shrink-0 items-center gap-2">
                            <Sticker variant={STATUS_VARIANT[a.status] as never}>{a.status}</Sticker>
                            <button
                              onClick={() => removeApplication(a.job_id)}
                              aria-label="Remove application"
                              className="rounded p-1 text-muted-foreground hover:text-destructive"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        </div>
                        <div className="mt-2 flex flex-wrap items-center gap-2">
                          <select
                            value={a.status}
                            onChange={(e) => updateStatus(a.job_id, e.target.value as ApplicationStatus)}
                            className="rounded-md border border-border bg-beige-deep px-2 py-1 text-xs"
                          >
                            {STATUS_OPTIONS.map((s) => (
                              <option key={s} value={s}>{s}</option>
                            ))}
                          </select>
                          {a.apply_url && (
                            <a
                              href={a.apply_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex items-center gap-1 text-xs text-blue underline"
                            >
                              posting <ExternalLink className="h-3 w-3" />
                            </a>
                          )}
                          <button
                            onClick={() => setCoverJob({ job_id: a.job_id, title: a.title, company: a.company })}
                            className="text-xs text-muted-foreground underline hover:text-foreground"
                          >
                            Draft cover letter
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </section>

              {/* Saved jobs */}
              <section>
                <h3 className="mb-2 flex items-center gap-1.5 text-sm font-semibold">
                  <Bookmark className="h-4 w-4" /> Saved ({saved.length})
                </h3>
                {saved.length === 0 ? (
                  <Card className="p-4 text-center text-xs text-muted-foreground">
                    Hit the bookmark on a match to save it for later.
                  </Card>
                ) : (
                  <div className="space-y-2">
                    {saved.map((s) => (
                      <div
                        key={s.job_id}
                        className="flex items-center justify-between gap-2 rounded-md border border-border bg-background p-3"
                      >
                        <div className="min-w-0">
                          <p className="truncate text-sm font-semibold">{s.title}</p>
                          <p className="truncate text-xs text-muted-foreground">@{s.company}</p>
                        </div>
                        <div className="flex shrink-0 items-center gap-2">
                          <a
                            href={s.apply_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            aria-label="Open posting"
                            className="rounded p-1 text-muted-foreground hover:text-blue"
                          >
                            <ExternalLink className="h-3.5 w-3.5" />
                          </a>
                          <button
                            onClick={() => unsave(s.job_id)}
                            aria-label="Unsave"
                            className="rounded p-1 text-muted-foreground hover:text-destructive"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </section>
            </div>
          )}

          {coverJob && (
            <CoverLetterModal
              open
              onOpenChange={(v) => { if (!v) setCoverJob(null); }}
              resumeId={resumeId}
              job={coverJob}
            />
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
