import { useState } from "react";
import { Settings as SettingsIcon, Eye, EyeOff, Save, RotateCcw, CheckCircle2 } from "lucide-react";
import { useSettings } from "@/stores/settings";
import { Card } from "@/components/ui/card";

const PROVIDERS = [
  { value: "nvidia", label: "NVIDIA NIM (free tier)" },
  { value: "openrouter", label: "OpenRouter (free tier)" },
  { value: "ollama", label: "Ollama (local)" },
  { value: "lmstudio", label: "LM Studio (local)" },
  { value: "custom", label: "Custom OpenAI-compatible" },
];

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
    <div className="space-y-1">
      <label className="text-sm font-medium text-foreground">
        {label} {required && <span className="text-destructive">*</span>}
      </label>
      <div className="flex gap-2">
        <input
          type={isPassword && !show ? "password" : "text"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className="flex-1 rounded-md border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring"
        />
        {isPassword && (
          <button
            type="button"
            onClick={() => setShow(!show)}
            className="rounded-md border px-2 text-muted-foreground hover:bg-muted"
          >
            {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
        )}
      </div>
    </div>
  );
}

export default function SettingsPage() {
  const { settings, update, reset } = useSettings();
  const [saved, setSaved] = useState(false);

  const handleSave = () => {
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <Card className="p-6">
        <div className="flex items-center gap-2 mb-2">
          <SettingsIcon className="h-5 w-5" />
          <h2 className="text-lg font-semibold">API Keys & Settings</h2>
        </div>
        <p className="text-sm text-muted-foreground">
          Enter your API keys here. Keys are stored in your browser's localStorage
          and sent as headers to the backend — they are never committed to git.
          You can also use the <code>.env</code> file for Docker deployments.
        </p>
      </Card>

      {/* LLM Provider */}
      <Card className="p-6">
        <h3 className="mb-4 font-medium">LLM Provider</h3>
        <div className="space-y-4">
          <div className="space-y-1">
            <label className="text-sm font-medium">Primary Provider</label>
            <select
              value={settings.llm_provider}
              onChange={(e) => update({ llm_provider: e.target.value })}
              className="w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring"
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
        <h3 className="mb-4 font-medium">Search APIs (Stage 1)</h3>
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
        <h3 className="mb-4 font-medium">Job Board APIs (Stage 3)</h3>
        <div className="space-y-4">
          <Field label="bluedoor.sh API Key" value={settings.bluedoor_api_key}
            onChange={(v) => update({ bluedoor_api_key: v })}
            placeholder="jobs_live_..." type="password" />
          <p className="text-xs text-muted-foreground">
            Get a free key at{" "}
            <a href="https://bluedoor.sh/apis/job-postings" target="_blank"
              className="text-primary underline underline-offset-2">
              bluedoor.sh/apis/job-postings
            </a>{" "}
            (100 req/s free tier)
          </p>
        </div>
      </Card>

      {/* Actions */}
      <Card className="p-6">
        <div className="flex gap-3">
          <button
            onClick={handleSave}
            className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            {saved ? <CheckCircle2 className="h-4 w-4" /> : <Save className="h-4 w-4" />}
            {saved ? "Saved!" : "Save Settings"}
          </button>
          <button
            onClick={reset}
            className="inline-flex items-center gap-2 rounded-md border px-4 py-2 text-sm font-medium hover:bg-muted"
          >
            <RotateCcw className="h-4 w-4" />
            Reset to Defaults
          </button>
        </div>
      </Card>
    </div>
  );
}
