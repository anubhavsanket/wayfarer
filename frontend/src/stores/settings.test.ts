import { describe, it, expect, beforeEach } from "vitest";
import { buildAuthHeaders } from "./settings";

describe("settings store — buildAuthHeaders", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("builds auth headers from saved localStorage settings", () => {
    const customSettings = {
      llm_provider: "custom",
      nvidia_api_key: "nv-key",
      nvidia_endpoint: "https://integrate.api.nvidia.com/v1",
      openrouter_api_key: "or-key",
      openrouter_endpoint: "https://openrouter.ai/api/v1",
      ollama_endpoint: "http://localhost:11434",
      lmstudio_endpoint: "http://localhost:1234/v1",
      lmstudio_model: "llama3",
      custom_llm_endpoint: "http://my-custom:8080/v1",
      custom_llm_api_key: "my-custom-key",
      custom_llm_model: "my-custom-model",
      tavily_api_key: "tvly-key",
      brave_api_key: "bsa-key",
      bluedoor_api_key: "blue-key",
    };
    localStorage.setItem("wayfarer_api_settings", JSON.stringify(customSettings));

    const headers = buildAuthHeaders();

    expect(headers["X-LLM-Provider"]).toBe("custom");
    expect(headers["X-NVIDIA-API-Key"]).toBe("nv-key");
    expect(headers["X-OpenRouter-API-Key"]).toBe("or-key");
    expect(headers["X-Custom-Endpoint"]).toBe("http://my-custom:8080/v1");
    expect(headers["X-Custom-API-Key"]).toBe("my-custom-key");
    expect(headers["X-Custom-Model"]).toBe("my-custom-model");
    expect(headers["X-Tavily-API-Key"]).toBe("tvly-key");
    expect(headers["X-Brave-API-Key"]).toBe("bsa-key");
    expect(headers["X-Bluedoor-API-Key"]).toBe("blue-key");
  });
});
