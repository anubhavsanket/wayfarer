import { useState, useEffect } from "react";
import { useMutation } from "@tanstack/react-query";
import { Settings as SettingsIcon, Eye, EyeOff, Save, RotateCcw, CheckCircle2, Upload, User, LogOut, ShieldCheck } from "lucide-react";
import { useSettings } from "@/stores/settings";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Sticker } from "@/components/ui/badge";

const PROVIDERS = [
  { value: "nvidia", label: "NVIDIA NIM (free tier)" },
  { value: "openrouter", label: "OpenRouter (free tier)" },
  { value: "ollama", label: "Ollama (local)" },
  { value: "lmstudio", label: "LM Studio (local)" },
  { value: "custom", label: "Custom OpenAI-compatible" },
];

/* ── User Auth & OAuth Card ─────────────────────────────────────────── */

function UserAuthCard() {
  const [emailInput, setEmailInput] = useState("");
  const [nameInput, setNameInput] = useState("");
  const [currentUser, setCurrentUser] = useState<{
    user_id: string;
    email: string;
    name: string;
  } | null>(null);

  const fetchMe = async () => {
    try {
      const data = await api.getMe();
      if (data && data.user_id !== "local") {
        setCurrentUser(data);
      } else {
        setCurrentUser(null);
      }
    } catch {
      setCurrentUser(null);
    }
  };

  useEffect(() => {
    fetchMe();
  }, []);

  const loginMutation = useMutation({
    mutationFn: (payload: { email: string; name?: string }) => api.authLogin(payload),
    onSuccess: (data) => {
      localStorage.setItem("wayfarer_access_token", data.access_token);
      setCurrentUser({
        user_id: data.user_id,
        email: data.email,
        name: data.name,
      });
      setEmailInput("");
      setNameInput("");
    },
  });

  const handleLogout = () => {
    localStorage.removeItem("wayfarer_access_token");
    setCurrentUser(null);
  };

  return (
    <Card className="p-6">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-5 w-5 text-blue" />
          <h3 className="font-display font-bold">User Account & OAuth</h3>
        </div>
        {currentUser ? (
          <Sticker variant="blue">Authenticated ({currentUser.email})</Sticker>
        ) : (
          <Sticker variant="muted">Local Mode (Unauthenticated)</Sticker>
        )}
      </div>

      {currentUser ? (
        <div className="space-y-3">
          <div className="flex items-center justify-between rounded-lg border border-border bg-beige-deep p-4">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-blue text-white font-bold">
                {currentUser.name ? currentUser.name[0].toUpperCase() : currentUser.email[0].toUpperCase()}
              </div>
              <div>
                <p className="font-semibold text-sm">{currentUser.name || "User"}</p>
                <p className="text-xs font-mono text-muted-foreground">{currentUser.email}</p>
                <p className="text-[10px] font-mono text-muted-foreground/70">ID: {currentUser.user_id}</p>
              </div>
            </div>
            <button
              onClick={handleLogout}
              className="inline-flex items-center gap-1.5 rounded-lg border border-destructive/30 px-3 py-1.5 text-xs font-medium text-destructive transition-colors hover:bg-destructive/10"
            >
              <LogOut className="h-3.5 w-3.5" />
              Sign Out
            </button>
          </div>
          <p className="text-xs text-muted-foreground">
            Your saved job applications, bookmarked postings, and API keys are isolated and securely encrypted for your account.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Sign in to save your application tracker data, bookmarks, and API keys encrypted in your private account space.
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field
              label="Email Address"
              value={emailInput}
              onChange={setEmailInput}
              placeholder="user@example.com"
              required
            />
            <Field
              label="Display Name (optional)"
              value={nameInput}
              onChange={setNameInput}
              placeholder="Alex Smith"
            />
          </div>
          <div className="flex gap-2">
            <button
              disabled={!emailInput || loginMutation.isPending}
              onClick={() => loginMutation.mutate({ email: emailInput, name: nameInput })}
              className="inline-flex items-center gap-2 rounded-lg bg-blue px-4 py-2 text-sm font-semibold text-white shadow-sm transition-all duration-150 hover:bg-blue-deep disabled:opacity-50"
            >
              <User className="h-4 w-4" />
              {loginMutation.isPending ? "Signing in..." : "Sign In / Register"}
            </button>
          </div>
          {loginMutation.isError && (
            <p className="text-sm text-destructive">Sign in failed: {loginMutation.error.message}</p>
          )}
        </div>
      )}
    </Card>
  );
}

/* ── Primary Resume Upload Card ──────────────────────────────────────── */

function ResumeUploadCard() {
  const [resumeFile, setResumeFile] = useState<File | null>(null);
  const [storedResumeId, setStoredResumeId] = useState(
    () => localStorage.getItem("resume_id") ?? ""
  );
  const [storedFileName, setStoredFileName] = useState(
    () => localStorage.getItem("resume_filename") ?? ""
  );

  const mutation = useMutation({
    mutationFn: (file: File) => api.resumeCheck("placeholder", file),
    onSuccess: (data) => {
      setStoredResumeId(data.resume_id);
      setStoredFileName(resumeFile?.name ?? "");
      localStorage.setItem("resume_id", data.resume_id);
      localStorage.setItem("resume_filename", resumeFile?.name ?? "");
    },
  });

  return (
    <Card className="p-6">
      <h3 className="font-display mb-1 font-bold">Primary Resume</h3>
      <p className="mb-4 text-sm text-muted-foreground">
        Upload your resume once. It will be used automatically by Resume Check
        and Job Match — no need to re-upload each time.
      </p>

      {storedResumeId && (
        <div className="mb-4 flex items-center gap-2 rounded-lg bg-blue-pale p-3 text-sm border border-blue/20">
          <CheckCircle2 className="h-4 w-4 shrink-0 text-blue" />
          <span className="font-medium">{storedFileName || "Resume uploaded"}</span>
          <span className="text-xs font-mono text-muted-foreground">({storedResumeId})</span>
        </div>
      )}

      <label className="flex cursor-pointer items-center gap-2 rounded-lg border border-dashed border-border bg-beige-deep p-4 text-sm text-muted-foreground transition-colors hover:bg-border">
        <Upload className="h-4 w-4" />
        {mutation.isPending
          ? "Uploading..."
          : storedResumeId
            ? "Replace resume"
            : "Upload resume (PDF/DOCX)"}
        <input
          type="file"
          accept=".pdf,.docx"
          className="hidden"
          disabled={mutation.isPending}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) {
              setResumeFile(file);
              mutation.mutate(file);
            }
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
          className="flex-1 rounded-lg border border-border bg-card px-3 py-2 text-sm font-mono placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-cyan focus:ring-offset-2 focus:ring-offset-card"
        />
        {isPassword && (
          <button
            type="button"
            onClick={() => setShow(!show)}
            className="flex items-center justify-center rounded-lg border border-border bg-beige-deep px-3 text-muted-foreground shadow-sm transition-all duration-150 hover:bg-border active:scale-95"
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
    <div className="max-w-4xl mx-auto space-y-8 pb-12">
      {/* Header */}
      <div className="border-b-2 border-ink pb-6">
        <div className="flex items-center gap-3">
          <SettingsIcon className="h-8 w-8 text-blue" />
          <h1 className="font-display text-4xl font-black text-ink">System Config</h1>
        </div>
        <p className="mt-2 text-sm text-ink-soft max-w-lg">
          Configure your LLM providers, search API keys, and manage your Wayfarer account identity. Changes are saved locally or synchronized to your secure account.
        </p>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <UserAuthCard />
        <ResumeUploadCard />
      </div>

      {/* LLM Provider */}
      <Card className="p-6">
        <div className="flex items-center justify-between mb-6">
          <h3 className="font-display text-xl font-bold text-ink">LLM Engine</h3>
          <span className="text-xs font-mono text-ink-soft uppercase tracking-wider">Tier: Complex/Simple</span>
        </div>
        <div className="space-y-6">
          <div className="space-y-1.5">
            <label className="text-sm font-semibold">Primary Provider</label>
            <select
              value={settings.llm_provider}
              onChange={(e) => update({ llm_provider: e.target.value })}
              className="w-full rounded-lg border-2 border-ink bg-card px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue"
            >
              {PROVIDERS.map((p) => (
                <option key={p.value} value={p.value}>{p.label}</option>
              ))}
            </select>
          </div>

          <div className="grid md:grid-cols-2 gap-4 border-t border-ink/10 pt-6">
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
              <Field label="Ollama Endpoint" value={settings.ollama_endpoint}
                onChange={(v) => update({ ollama_endpoint: v })}
                placeholder="http://localhost:11434" />
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
                <Field label="Custom Endpoint" value={settings.custom_llm_endpoint}
                  onChange={(v) => update({ custom_llm_endpoint: v })}
                  placeholder="http://localhost:8080/v1" />
                <Field label="API Key" value={settings.custom_llm_api_key}
                  onChange={(v) => update({ custom_llm_api_key: v })}
                  placeholder="any string" type="password" />
                <Field label="Model Name" value={settings.custom_llm_model}
                  onChange={(v) => update({ custom_llm_model: v })}
                  placeholder="e.g. your-model-name" />
              </>
            )}
          </div>
        </div>
      </Card>

      {/* Search & Job Board APIs */}
      <div className="grid gap-6 md:grid-cols-2">
        <Card className="p-6">
          <h3 className="font-display mb-6 font-bold text-xl text-ink">Search API</h3>
          <div className="space-y-4">
            <Field label="Tavily API Key" value={settings.tavily_api_key}
              onChange={(v) => update({ tavily_api_key: v })}
              placeholder="tvly-dev-..." type="password" />
            <Field label="Brave Search API Key" value={settings.brave_api_key}
              onChange={(v) => update({ brave_api_key: v })}
              placeholder="BSA..." type="password" />
          </div>
        </Card>
        <Card className="p-6">
          <h3 className="font-display mb-6 font-bold text-xl text-ink">Job Board API</h3>
          <div className="space-y-4">
            <Field label="bluedoor.sh API Key" value={settings.bluedoor_api_key}
              onChange={(v) => update({ bluedoor_api_key: v })}
              placeholder="jobs_live_..." type="password" />
          </div>
        </Card>
      </div>

      {/* Actions */}
      <div className="flex items-center gap-3 pt-6 border-t border-ink/10">
        <button
          onClick={handleSave}
          className="inline-flex items-center gap-2 rounded-lg border-2 border-ink bg-blue px-6 py-2.5 font-bold text-white shadow-hard hover:shadow-hard-lg hover:-translate-y-0.5 active:translate-y-0.5 active:shadow-hard-none transition-all"
        >
          {saved ? <CheckCircle2 className="h-5 w-5" /> : <Save className="h-5 w-5" />}
          {saved ? "Saved Configuration" : "Save Changes"}
        </button>
        <button
          onClick={reset}
          className="inline-flex items-center gap-2 rounded-lg border-2 border-ink bg-card px-6 py-2.5 font-bold text-ink hover:bg-beige-deep shadow-hard hover:shadow-hard active:translate-y-0.5 transition-all"
        >
          <RotateCcw className="h-5 w-5" />
          Reset
        </button>
      </div>
    </div>
  );
}
