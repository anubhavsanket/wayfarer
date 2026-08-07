import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Settings as SettingsIcon, Eye, EyeOff, Save, RotateCcw, CheckCircle2, Upload } from "lucide-react";
import { useSettings } from "@/stores/settings";
import { api } from "@/lib/api";
import type { ResumePrimaryInfo } from "@/lib/types";
import { Card } from "@/components/ui/card";
import { Sticker } from "@/components/ui/badge";

const PROVIDERS = [
  { value: "nvidia", label: "NVIDIA NIM (free tier)" },
  { value: "openrouter", label: "OpenRouter (free tier)" },
  { value: "ollama", label: "Ollama (local)" },
  { value: "lmstudio", label: "LM Studio (local)" },
  { value: "custom", label: "Custom OpenAI-compatible" },
];

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

/* ── Field ──────────────────────────────────────────────────────────── */

interface FieldProps {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
  required?: boolean;
}

function Field({ label, value, onChange, placeholder, type = "text", required }: FieldProps) {
  const [show, setShow] = useState(false);
  const isPassword = type === "password";

  return (
    <div className="space-y-1.5">
      <label className="text-sm font-semibold text-foreground">
        {label} {required && <span className="text-destructive">*</span>}
      </label>
      <div className="flex gap-2">
        <input
          type={isPassword && !show ? "password" : "text"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className="flex-1 rounded-md border-2 border-ink bg-cream px-3 py-2 text-sm font-mono placeholder:text-ink/40 focus:outline-none focus:ring-2 focus:ring-cyan focus:ring-offset-2 focus:ring-offset-card"
        />
        {isPassword && (
          <button
            type="button"
            onClick={() => setShow(!show)}
            className="flex items-center justify-center rounded-md border-2 border-ink bg-cream px-2 text-muted-foreground shadow-hard-sm transition-all duration-150 hover:-translate-y-0.5 hover:shadow-hard active:translate-y-0.5 active:shadow-hard-none"
          >
            {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
        )}
      </div>
    </div>
  );
}

/* ── Main Page ──────────────────────────────────────────────────────── */

export default function SettingsPage() {
  const { settings, update, reset } = useSettings();
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
          <h2 className="font-display text-lg font-bold">API Keys & Settings</h2>
        </div>
        <p className="text-sm text-muted-foreground">
          Enter your API keys here. Keys are stored in your browser's localStorage
          and sent as headers to the backend — they are never committed to git.
          You can also use the <code className="rounded bg-beige-deep px-1 font-mono text-xs">.env</code> file for Docker deployments.
        </p>
      </Card>

      {/* LLM Provider */}
      <Card className="p-6">
        <h3 className="font-display mb-4 font-bold">LLM Provider</h3>
        <div className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-sm font-semibold">Primary Provider</label>
            <select
              value={settings.llm_provider}
              onChange={(e) => update({ llm_provider: e.target.value })}
              className="w-full rounded-md border-2 border-ink bg-cream px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-cyan"
            >
              {PROVIDERS.map((p) => (
                <option key={p.value} value={p.value}>{p.label}</option>
              ))}
            </select>
          </div>

          {settings.llm_provider === "nvidia" && (
            <>
              <Field label="NVIDIA NIM API Key" value={settings.nvidia_api_key}
                onChange={(v) => update({ nvidia_api_key: v })}
                placeholder="nvapi-..." type="password" />
              <Field label="NVIDIA NIM Endpoint" value={settings.nvidia_endpoint}
                onChange={(v) => update({ nvidia_endpoint: v })}
                placeholder="https://integrate.api.nvidia.com/v1" />
            </>
          )}

          {settings.llm_provider === "openrouter" && (
            <>
              <Field label="OpenRouter API Key" value={settings.openrouter_api_key}
                onChange={(v) => update({ openrouter_api_key: v })}
                placeholder="sk-or-..." type="password" />
              <Field label="OpenRouter Endpoint" value={settings.openrouter_endpoint}
                onChange={(v) => update({ openrouter_endpoint: v })}
                placeholder="https://openrouter.ai/api/v1" />
            </>
          )}

          {settings.llm_provider === "ollama" && (
            <>
              <Field label="Ollama Endpoint" value={settings.ollama_endpoint}
                onChange={(v) => update({ ollama_endpoint: v })}
                placeholder="http://localhost:11434" />
              <Field label="Model" value={settings.ollama_model || ""}
                onChange={(v) => update({ ollama_model: v })}
                placeholder="lfm2.5-thinking" />
              <p className="text-xs text-muted-foreground">
                Default: lfm2.5-thinking (1.2B). Pull with:{" "}
                <code className="rounded bg-beige-deep px-1 font-mono text-xs">
                  docker compose exec ollama ollama pull lfm2.5-thinking
                </code>
              </p>
            </>
          )}

          {settings.llm_provider === "lmstudio" && (
            <>
              <Field label="LM Studio Endpoint" value={settings.lmstudio_endpoint}
                onChange={(v) => update({ lmstudio_endpoint: v })}
                placeholder="http://localhost:1234/v1" />
              <Field label="LM Studio Model" value={settings.lmstudio_model}
                onChange={(v) => update({ lmstudio_model: v })}
                placeholder="e.g. llama-3.1-8b-instruct" />
            </>
          )}

          {settings.llm_provider === "custom" && (
            <>
              <Field label="Custom Endpoint" value={settings.lmstudio_endpoint}
                onChange={(v) => update({ lmstudio_endpoint: v })}
                placeholder="http://localhost:8080/v1" />
              <Field label="API Key" value={settings.openrouter_api_key}
                onChange={(v) => update({ openrouter_api_key: v })}
                placeholder="any string" type="password" />
              <Field label="Model Name" value={settings.lmstudio_model}
                onChange={(v) => update({ lmstudio_model: v })}
                placeholder="e.g. your-model-name" />
            </>
          )}
        </div>
      </Card>

      {/* Search APIs */}
      <Card className="p-6">
        <h3 className="font-display mb-4 font-bold">Search APIs (Stage 1)</h3>
        <div className="space-y-4">
          <Field label="Tavily API Key" value={settings.tavily_api_key}
            onChange={(v) => update({ tavily_api_key: v })}
            placeholder="tvly-dev-..." type="password" />
          <Field label="Brave Search API Key (optional)" value={settings.brave_api_key}
            onChange={(v) => update({ brave_api_key: v })}
            placeholder="BSA..." type="password" />
        </div>
      </Card>

      {/* Job Board APIs */}
      <Card className="p-6">
        <h3 className="font-display mb-4 font-bold">Job Board APIs (Stage 3)</h3>
        <div className="space-y-4">
          <Field label="bluedoor.sh API Key" value={settings.bluedoor_api_key}
            onChange={(v) => update({ bluedoor_api_key: v })}
            placeholder="jobs_live_..." type="password" />
          <p className="text-xs text-muted-foreground">
            Get a free key at{" "}
            <a
              href="https://bluedoor.sh/apis/job-postings"
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue underline underline-offset-2 hover:text-blue/80"
            >
              bluedoor.sh/apis/job-postings
            </a>{" "}
            (100 req/s free tier)
          </p>
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
