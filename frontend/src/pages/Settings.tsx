import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Settings as SettingsIcon, Save, RotateCcw, CheckCircle2, Upload } from "lucide-react";
import { useSettings } from "@/stores/settings";
import { api } from "@/lib/api";
import type { ResumePrimaryInfo } from "@/lib/types";
import { Card } from "@/components/ui/card";
import { Sticker } from "@/components/ui/badge";

/* ── Primary Resume Upload Card (§8.6 FR2.9) ───────────────────────── */

function ResumeUploadCard() {
  const queryClient = useQueryClient();

  const { data: primary } = useQuery({
    queryKey: ["resume-primary"],
    queryFn: () => api.getResumePrimary(),
    retry: false,
  });

  const mutation = useMutation({
    mutationFn: (file: File) => api.setResumePrimary(file),
    onSuccess: (data: ResumePrimaryInfo) => {
      queryClient.setQueryData(["resume-primary"], data);
      localStorage.setItem("resume_id", data.resume_id);
      localStorage.setItem("resume_filename", data.filename);
    },
  });

  return (
    <Card className="p-6">
      <h3 className="font-display mb-1 font-bold">Primary Resume</h3>
      <p className="mb-4 text-sm text-muted-foreground">
        Upload your resume once. It will be used automatically by Resume Check
        and Job Match — no need to re-upload each time.
      </p>

      {primary && (
        <div className="mb-4 flex items-center gap-2 rounded-md bg-blue-pale p-3 text-sm border-2 border-ink/20">
          <CheckCircle2 className="h-4 w-4 shrink-0 text-blue" />
          <span className="font-medium">{primary.filename || "Resume uploaded"}</span>
          <span className="text-xs text-muted-foreground">({primary.resume_id})</span>
          {primary.uploaded_at && (
            <span className="text-xs text-muted-foreground">
              · {new Date(primary.uploaded_at).toLocaleDateString()}
            </span>
          )}
        </div>
      )}

      <label className="flex cursor-pointer items-center gap-2 rounded-md border-2 border-dashed border-ink bg-cream p-4 text-sm text-muted-foreground transition-colors hover:bg-beige-deep">
        <Upload className="h-4 w-4" />
        {mutation.isPending
          ? "Uploading..."
          : primary
            ? "Replace resume"
            : "Upload resume (PDF/DOCX)"}
        <input
          type="file"
          accept=".pdf,.docx"
          className="hidden"
          disabled={mutation.isPending}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) mutation.mutate(file);
          }}
        />
      </label>

      {mutation.isError && (
        <p className="mt-2 text-sm text-destructive">Upload failed: {mutation.error.message}</p>
      )}
      {mutation.isPending && (
        <p className="mt-2 text-sm text-muted-foreground">Processing resume...</p>
      )}
      {mutation.isSuccess && (
        <div className="mt-2">
          <Sticker variant="blue">✓ Resume uploaded successfully</Sticker>
        </div>
      )}
    </Card>
  );
}


/* ── Main Page ──────────────────────────────────────────────────────── */

export default function SettingsPage() {
  const { reset } = useSettings();
  const [saved, setSaved] = useState(false);

  const handleSave = () => {
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <Card className="p-6">
        <div className="mb-2 flex items-center gap-2">
          <SettingsIcon className="h-5 w-5 text-blue" />
          <h2 className="font-display text-lg font-bold">Settings</h2>
        </div>
        <p className="text-sm text-muted-foreground">
          Manage your primary resume and view system configuration.
          API keys are configured via the <code className="rounded bg-beige-deep px-1 font-mono text-xs">.env</code> file.
        </p>
      </Card>

      {/* API Configuration */}
      <Card className="p-6">
        <h3 className="font-display mb-4 font-bold">API Configuration</h3>
        <p className="mb-3 text-sm text-muted-foreground">
          API keys, LLM provider, and job board keys are configured via the{" "}
          <code className="rounded bg-beige-deep px-1 font-mono text-xs">.env</code> file
          and read by the backend at startup.
        </p>
        <div className="rounded-md border-2 border-ink/20 bg-beige-deep p-4 text-sm">
          <p className="mb-2 font-semibold">To configure:</p>
          <ol className="list-decimal space-y-1 pl-4 text-muted-foreground">
            <li>Edit <code className="font-mono text-xs">.env</code> in the project root</li>
            <li>Set your API keys (Tavily, NVIDIA NIM, bluedoor, etc.)</li>
            <li>Restart the backend: <code className="font-mono text-xs">docker compose up -d api</code></li>
          </ol>
        </div>
      </Card>

      {/* Resume Upload */}
      <ResumeUploadCard />

      {/* Actions */}
      <Card className="p-6">
        <div className="flex gap-3">
          <button
            onClick={handleSave}
            className="inline-flex items-center gap-2 rounded-md border-2 border-ink bg-blue px-4 py-2 text-sm font-semibold text-white shadow-hard-blue transition-all duration-150 hover:-translate-y-0.5 hover:shadow-hard-lg active:translate-y-0.5 active:shadow-hard-none"
          >
            {saved ? <CheckCircle2 className="h-4 w-4" /> : <Save className="h-4 w-4" />}
            {saved ? "Saved!" : "Save Settings"}
          </button>
          <button
            onClick={reset}
            className="inline-flex items-center gap-2 rounded-md border-2 border-ink bg-cream px-4 py-2 text-sm font-semibold text-ink shadow-hard-sm transition-all duration-150 hover:-translate-y-0.5 hover:shadow-hard active:translate-y-0.5 active:shadow-hard-none"
          >
            <RotateCcw className="h-4 w-4" />
            Reset to Defaults
          </button>
        </div>
      </Card>
    </div>
  );
}
