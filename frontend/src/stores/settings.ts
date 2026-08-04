import { useState } from "react";

const STORAGE_KEY = "wayfarer_api_settings";

export interface ApiSettings {
  llm_provider: string;
  nvidia_api_key: string;
  nvidia_endpoint: string;
  openrouter_api_key: string;
  openrouter_endpoint: string;
  ollama_endpoint: string;
  lmstudio_endpoint: string;
  lmstudio_model: string;
  tavily_api_key: string;
  brave_api_key: string;
  bluedoor_api_key: string;
}

const DEFAULTS: ApiSettings = {
  llm_provider: "nvidia",
  nvidia_api_key: "",
  nvidia_endpoint: "https://integrate.api.nvidia.com/v1",
  openrouter_api_key: "",
  openrouter_endpoint: "https://openrouter.ai/api/v1",
  ollama_endpoint: "http://ollama:11434",
  lmstudio_endpoint: "http://localhost:1234/v1",
  lmstudio_model: "",
  tavily_api_key: "",
  brave_api_key: "",
  bluedoor_api_key: "",
};

function load(): ApiSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULTS };
    return { ...DEFAULTS, ...JSON.parse(raw) };
  } catch {
    return { ...DEFAULTS };
  }
}

function save(settings: ApiSettings) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
}

export function useSettings() {
  const [settings, setSettings] = useState<ApiSettings>(load);

  const update = (partial: Partial<ApiSettings>) => {
    setSettings((prev) => {
      const next = { ...prev, ...partial };
      save(next);
      return next;
    });
  };

  const reset = () => {
    save(DEFAULTS);
    setSettings({ ...DEFAULTS });
  };

  return { settings, update, reset };
}

/** Build headers to send API keys to the backend (reads from localStorage). */
export function buildAuthHeaders(): Record<string, string> {
  const s = load();
  const headers: Record<string, string> = {};
  if (s.llm_provider) headers["X-LLM-Provider"] = s.llm_provider;
  if (s.nvidia_api_key) headers["X-NVIDIA-API-Key"] = s.nvidia_api_key;
  if (s.nvidia_endpoint) headers["X-NVIDIA-Endpoint"] = s.nvidia_endpoint;
  if (s.openrouter_api_key) headers["X-OpenRouter-API-Key"] = s.openrouter_api_key;
  if (s.openrouter_endpoint) headers["X-OpenRouter-Endpoint"] = s.openrouter_endpoint;
  if (s.ollama_endpoint) headers["X-Ollama-Endpoint"] = s.ollama_endpoint;
  if (s.lmstudio_endpoint) headers["X-LMStudio-Endpoint"] = s.lmstudio_endpoint;
  if (s.lmstudio_model) headers["X-LMStudio-Model"] = s.lmstudio_model;
  if (s.tavily_api_key) headers["X-Tavily-API-Key"] = s.tavily_api_key;
  if (s.brave_api_key) headers["X-Brave-API-Key"] = s.brave_api_key;
  if (s.bluedoor_api_key) headers["X-Bluedoor-API-Key"] = s.bluedoor_api_key;
  return headers;
}
