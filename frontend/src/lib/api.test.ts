import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { api } from "./api";

describe("api.resumeCheck — FormData construction", () => {
  function mockFetch(responseBody: unknown) {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(responseBody),
      text: () => Promise.resolve(""),
    });
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  beforeEach(() => {
    localStorage.clear();
  });

  it("builds FormData with resume_file when a file is provided", async () => {
    const fetchMock = mockFetch({ resume_id: "new-1", ats_score: 0.9, structural_issues: [], keyword_gaps: [] });
    const file = new File(["x"], "resume.docx", { type: "text/plain" });

    await api.resumeCheck("JD text", file);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/api/v1/resume/check");
    const body = init.body as FormData;
    expect(body.get("resume_file")).toBe(file);
    expect(body.get("jd_text")).toBe("JD text");
    expect(body.has("resume_id")).toBe(false);
  });

  it("builds FormData with resume_id when only an id is provided", async () => {
    const fetchMock = mockFetch({ resume_id: "abc123", ats_score: 0.7, structural_issues: [], keyword_gaps: [] });

    await api.resumeCheck("JD text", undefined, "abc123");

    const [, init] = fetchMock.mock.calls[0];
    const body = init.body as FormData;
    expect(body.get("resume_id")).toBe("abc123");
    expect(body.get("jd_text")).toBe("JD text");
    expect(body.has("resume_file")).toBe(false);
  });

  it("does not send resume_id when a file is present (file wins)", async () => {
    const fetchMock = mockFetch({ resume_id: "new-1", ats_score: 0.9, structural_issues: [], keyword_gaps: [] });
    const file = new File(["x"], "resume.docx", { type: "text/plain" });

    await api.resumeCheck("JD text", file, "stale-id");

    const [, init] = fetchMock.mock.calls[0];
    const body = init.body as FormData;
    expect(body.has("resume_file")).toBe(true);
    expect(body.has("resume_id")).toBe(false);
  });

  it("throws a descriptive error on non-2xx response", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      json: () => Promise.resolve({}),
      text: () => Promise.resolve('{"detail": "Resume does-not-exist not found"}'),
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.resumeCheck("JD", undefined, "does-not-exist")).rejects.toThrow(
      /API error 404/
    );
  });
});