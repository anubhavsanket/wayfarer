import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Upload, FileText } from "lucide-react";

import { api } from "@/lib/api";
import type { ResumeCheckResponse } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

function tierColor(tier: string) {
  if (tier === "verified") return "bg-green-100 text-green-800";
  if (tier === "reworded") return "bg-yellow-100 text-yellow-800";
  return "bg-red-100 text-red-800";
}

export default function ResumeCheckPage() {
  const [resumeFile, setResumeFile] = useState<File | null>(null);
  const [jdText, setJdText] = useState("");
  const [result, setResult] = useState<ResumeCheckResponse | null>(null);

  // Check if a resume is already stored from Settings
  const storedResumeId = localStorage.getItem("resume_id") ?? "";
  const storedFileName = localStorage.getItem("resume_filename") ?? "";

  const mutation = useMutation({
    mutationFn: ({ file, jd }: { file?: File; jd: string }) =>
      file
        ? api.resumeCheck(jd, file)
        : api.resumeCheck(jd, undefined, storedResumeId),
    onSuccess: (data) => {
      setResult(data);
      if (data.resume_id) {
        localStorage.setItem("resume_id", data.resume_id);
      }
    },
    onError: (error: Error) => {
      // If the stored resume_id is stale (404 — the server lost the file),
      // clear it and let the user re-upload instead of staying stuck.
      if (/404|not found/i.test(error.message)) {
        localStorage.removeItem("resume_id");
        localStorage.removeItem("resume_filename");
      }
    },
  });

  const canCheck = (storedResumeId || resumeFile) && jdText.trim();

  const handleCheck = () => {
    if (!jdText.trim()) return;
    // Use the uploaded file if present, otherwise fall back to the stored resume
    mutation.mutate({ file: resumeFile ?? undefined, jd: jdText.trim() });
  };

  return (
    <div className="space-y-6">
      <Card className="p-6">
        <h2 className="mb-4 text-lg font-semibold">ATS Resume Checker</h2>
        <p className="mb-4 text-sm text-muted-foreground">
          {storedResumeId
            ? "Using your main resume from Settings. Paste a JD to check."
            : "Upload your resume and paste a JD to get ATS compatibility scores with confidence-tiered redline suggestions."
          }
        </p>

        <div className="mb-4 space-y-3">
          {storedResumeId && !resumeFile ? (
            <div className="flex items-center gap-2 rounded-md bg-muted p-3 text-sm">
              <FileText className="h-4 w-4" />
              <span>{storedFileName || "Resume uploaded"}</span>
              <span className="text-xs text-muted-foreground">({storedResumeId})</span>
              <label className="ml-auto cursor-pointer text-xs text-primary underline">
                Replace
                <input
                  type="file"
                  accept=".pdf,.docx"
                  className="hidden"
                  onChange={(e) => setResumeFile(e.target.files?.[0] ?? null)}
                />
              </label>
            </div>
          ) : (
            <label className="flex cursor-pointer items-center gap-2 rounded-md border border-dashed p-4 text-sm text-muted-foreground hover:bg-muted">
              <Upload className="h-4 w-4" />
              {resumeFile ? resumeFile.name : "Upload resume (PDF/DOCX)"}
              <input
                type="file"
                accept=".pdf,.docx"
                className="hidden"
                onChange={(e) => setResumeFile(e.target.files?.[0] ?? null)}
              />
            </label>
          )}
          <textarea
            value={jdText}
            onChange={(e) => setJdText(e.target.value)}
            rows={6}
            placeholder="Paste job description here..."
            className="w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring"
          />
        </div>

        <Button
          disabled={!canCheck || mutation.isPending}
          onClick={handleCheck}
        >
          <FileText className="mr-2 h-4 w-4" />
          {mutation.isPending ? "Checking..." : "Check Resume"}
        </Button>
      </Card>

      {mutation.isError && (
        <Card className="border-destructive p-4 text-sm text-destructive">
          Error: {mutation.error.message}
        </Card>
      )}

      {result && (
        <>
          <Card className="p-6">
            <h3 className="mb-1 font-medium">ATS Score</h3>
            <p className="text-3xl font-bold">
              {(result.ats_score * 100).toFixed(0)}%
            </p>
          </Card>

          {result.structural_issues.length > 0 && (
            <Card className="p-6">
              <h3 className="mb-3 font-medium">Structural Issues</h3>
              <ul className="space-y-1 text-sm">
                {result.structural_issues.map((issue, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="font-mono text-xs text-muted-foreground">
                      {issue.location}
                    </span>
                    <span>{issue.issue}</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {result.keyword_gaps.length > 0 && (
            <Card className="p-6">
              <h3 className="mb-3 font-medium">Keyword Analysis</h3>
              <ul className="space-y-4">
                {result.keyword_gaps.map((gap, i) => (
                  <li key={i} className="text-sm">
                    <div className="mb-1 flex items-center gap-2">
                      <span className="font-medium">{gap.keyword}</span>
                      <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${tierColor(gap.tier)}`}>
                        {gap.tier}
                      </span>
                      {gap.confidence != null && (
                        <span className="text-xs text-muted-foreground">
                          {(gap.confidence * 100).toFixed(0)}%
                        </span>
                      )}
                    </div>
                    {gap.rationale && (
                      <p className="pl-4 text-xs text-muted-foreground">
                        {gap.rationale}
                      </p>
                    )}
                    {/* Side-by-side redline view when both original and suggested exist */}
                    {gap.original_text && gap.suggested_text ? (
                      <div className="mt-2 ml-4 grid grid-cols-2 gap-2 rounded-md border p-3 text-xs">
                        <div>
                          <span className="mb-1 block font-medium text-destructive">Original</span>
                          <p className="whitespace-pre-wrap text-muted-foreground line-through">
                            {gap.original_text}
                          </p>
                        </div>
                        <div>
                          <span className="mb-1 block font-medium text-green-700">Suggested</span>
                          <p className="whitespace-pre-wrap text-green-700">
                            {gap.suggested_text}
                          </p>
                        </div>
                      </div>
                    ) : gap.suggested_text ? (
                      <p className="mt-1 whitespace-pre-wrap pl-4 text-xs italic text-primary">
                        → {gap.suggested_text}
                      </p>
                    ) : null}
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
