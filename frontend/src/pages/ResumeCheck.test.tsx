import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import ResumeCheckPage from "./ResumeCheck";
import { api } from "@/lib/api";

// Mock the api module so we can assert how resumeCheck is invoked
vi.mock("@/lib/api", () => ({
  api: {
    resumeCheck: vi.fn(),
  },
}));

const mockedResumeCheck = vi.mocked(api.resumeCheck);

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ResumeCheckPage />
    </QueryClientProvider>
  );
}

function mockSuccess() {
  mockedResumeCheck.mockResolvedValue({
    resume_id: "abc123",
    ats_score: 0.85,
    structural_issues: [],
    keyword_gaps: [],
  });
}

describe("ResumeCheckPage — stored-resume flow", () => {
  beforeEach(() => {
    localStorage.clear();
    mockedResumeCheck.mockReset();
  });

  it("uses resume_id from localStorage when no file is picked", async () => {
    localStorage.setItem("resume_id", "stored-42");
    localStorage.setItem("resume_filename", "main_resume.docx");
    mockSuccess();

    renderPage();

    // Stored resume banner is shown
    expect(screen.getByText(/main_resume\.docx/)).toBeInTheDocument();

    // Type a JD and click Check
    fireEvent.change(screen.getByPlaceholderText(/Paste job description/), {
      target: { value: "Python developer with FastAPI" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Check Resume/ }));

    await waitFor(() => {
      expect(mockedResumeCheck).toHaveBeenCalledTimes(1);
    });
    // Third arg is the stored id, second arg (file) is undefined
    expect(mockedResumeCheck).toHaveBeenCalledWith(
      "Python developer with FastAPI",
      undefined,
      "stored-42"
    );

    // Result renders
    expect(await screen.findByText("85%")).toBeInTheDocument();
  });

  it("uploads the picked file instead of using the stored resume", async () => {
    localStorage.setItem("resume_id", "stored-42");
    localStorage.setItem("resume_filename", "main_resume.docx");
    mockSuccess();

    renderPage();

    // Click "Use a different resume" to switch to upload mode
    fireEvent.click(screen.getByText(/Use a different resume/));

    // Pick a replacement file — the file input is now visible
    const file = new File(["hello"], "new_resume.docx", {
      type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    });
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [file] } });

    // Now the dashed upload box shows the picked file name
    expect(await screen.findByText(/new_resume\.docx/)).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText(/Paste job description/), {
      target: { value: "Java developer" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Check Resume/ }));

    await waitFor(() => {
      expect(mockedResumeCheck).toHaveBeenCalledTimes(1);
    });
    // First arg jdText, second arg the actual File, no resume_id
    const [jd, picked, resumeId] = mockedResumeCheck.mock.calls[0];
    expect(jd).toBe("Java developer");
    expect(picked).toBeInstanceOf(File);
    expect(picked?.name).toBe("new_resume.docx");
    expect(resumeId).toBeUndefined();
  });

  it("shows the stored-resume banner when a resume is in localStorage", () => {
    localStorage.setItem("resume_id", "stored-42");
    localStorage.setItem("resume_filename", "main_resume.docx");

    renderPage();

    expect(screen.getByText(/main_resume\.docx/)).toBeInTheDocument();
    expect(screen.getByText(/stored-42/)).toBeInTheDocument();
  });

  it("shows the upload prompt when no resume is stored", () => {
    renderPage();

    expect(screen.getByText(/Upload resume \(PDF\/DOCX\)/)).toBeInTheDocument();
  });

  it("handles fresh file upload when no resume is stored in localStorage", async () => {
    mockSuccess();
    renderPage();

    const file = new File(["dummy"], "first_resume.pdf", { type: "application/pdf" });
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [file] } });

    fireEvent.change(screen.getByPlaceholderText(/Paste job description/), {
      target: { value: "Fullstack Developer with Node" },
    });

    const button = screen.getByRole("button", { name: /Check Resume/ });
    expect(button).not.toBeDisabled();
    fireEvent.click(button);

    await waitFor(() => {
      expect(mockedResumeCheck).toHaveBeenCalledTimes(1);
    });
    expect(mockedResumeCheck).toHaveBeenCalledWith(
      "Fullstack Developer with Node",
      file
    );
  });

  it("clears a stale resume_id from localStorage on a 404", async () => {
    localStorage.setItem("resume_id", "stale-id");
    localStorage.setItem("resume_filename", "old.doc");
    mockedResumeCheck.mockRejectedValue(new Error("API error 404: resume not found"));

    renderPage();

    fireEvent.change(screen.getByPlaceholderText(/Paste job description/), {
      target: { value: "Python developer" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Check Resume/ }));

    await waitFor(() => {
      expect(mockedResumeCheck).toHaveBeenCalledTimes(1);
    });
    expect(mockedResumeCheck).toHaveBeenCalledWith("Python developer", undefined, "stale-id");

    // The stale id should be cleared so the UI falls back to the upload prompt
    await waitFor(() => {
      expect(localStorage.getItem("resume_id")).toBeNull();
      expect(localStorage.getItem("resume_filename")).toBeNull();
    });
  });
});