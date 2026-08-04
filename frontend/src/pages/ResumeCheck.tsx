import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Upload, FileText, Save, Star } from "lucide-react";

import { api } from "@/lib/api";
import type { ResumeCheckResponse, SaveMode } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

function tierColor(tier: string) {
  if (tier === "verified") return "bg-green-100 text-green-800";
  if (tier === "reworded") return "bg-yellow-100 text-yellow-800";
  return "bg-red-100 text-red-800";
}

export default function ResumeCheckPage() {
  const [jdText, setJdText] = useState("");
  const [result, setResult] = useState<ResumeCheckResponse | null>(null);
  const [saveMode, setSaveMode] = useState<SaveMode | null>(null);

  // One-off variant upload
  const [useVariant, setUseVariant] = useState(false);
  const [file, setFile] = useState<File | null>(null);

  // FR2.10 (§8.6): check if a primary resume exists
  const { data: primary } = useQuery({
    queryKey: ["resume-primary"],
    queryFn: () => api.getResumePrimary(),
    retry: false,
  });

  const checkMutation = useMutation({
    mutationFn: ({ file, jd }: { file: File | null; jd: string }) =>
      api.resumeCheck(file, jd),
    onSuccess: (data) => {
      setResult(data);
      setSaveMode(null);
      if (data.resume_id) {
        localStorage.setItem("resume_id", data.resume_id);
      }
    },
  });

  const canCheck = jdText.trim() && (primary || useVariant || file);

  const handleCheck = () => {
    if (!jdText.trim()) return;
    if (useVariant && file) {
      checkMutation.mutate({ file, jd: jdText.trim() });
    } else if (primary) {
      checkMutation.mutate({ file: null, jd: jdText.trim() });
    }
  };

  // Save mutation
  const saveMutation = useMutation({
    mutationFn: (mode: SaveMode) =>
      fetch("/api/v1/resume/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          resume_id: result?.resume_id,
          accepted_suggestions: result?.keyword_gaps
            ?.filter((g) => g.suggested_text)
            .map((g) => ({
              bullet_id: g.bullet_id ?? "",
              suggested_text: g.suggested_text ?? "",
            })) ?? [],
          mode,
          confirm_overwrite: mode === "overwrite",
        }),
      }).then((r) => r.json()),
    onSuccess: () => setSaveMode(null),
  });

  return (
    <div className="space-y-6">
      <Card className="p-6">
        <h2 className="mb-4 text-lg font-semibold">ATS Resume Checker</h2>
        <p className="mb-4 text-sm text-muted-foreground">
          {primary
            ? "Using your primary resume from Settings. Paste a JD to check."
            : "Upload your resume and paste a JD to get ATS compatibility scores with confidence-tiered redline suggestions."
          }
        </p>

        <div className="mb-4 space-y-3">
          {/* Primary resume display */}
          {primary && !useVariant && (
            <div className="flex items-center gap-2 rounded-md bg-muted p-3 text-sm">
              <FileText className="h-4 w-4" />
              <span>{primary.filename || "Resume uploaded"}</span>
              <span className="text-xs text-muted-foreground">({primary.resume_id})</span>
              <button
                onClick={() => setUseVariant(true)}
                className="ml-auto text-xs text-primary underline"
              >
                Use a different resume
              </button>
            </div>
          )}

          {/* Variant upload */}
          {(useVariant || !primary) && (
            <div className="space-y-2">
              <label className="flex cursor-pointer items-center gap-2 rounded-md border border-dashed p-4 text-sm text-muted-foreground hover:bg-muted">
                <Upload className="h-4 w-4" />
                {file ? file.name : "Upload resume (PDF/DOCX)"}
                <input
                  type="file"
                  accept=".pdf,.docx"
                  className="hidden"
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                />
              </label>
              {primary && (
                <button
                  onClick={() => { setUseVariant(false); setFile(null); }}
                  className="text-xs text-muted-foreground underline"
                >
                  ← Use primary resume instead
                </button>
              )}
            </div>
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
          disabled={!canCheck || checkMutation.isPending}
          onClick={handleCheck}
        >
          <FileText className="mr-2 h-4 w-4" />
          {checkMutation.isPending ? "Checking..." : "Check Resume"}
        </Button>
      </Card>

      {checkMutation.isError && (
        <Card className="border-destructive p-4 text-sm text-destructive">
          Error: {checkMutation.error.message}
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

          {/* Save actions */}
          <Card className="p-6">
            <h3 className="mb-3 font-medium">Save Changes</h3>
            <p className="mb-3 text-sm text-muted-foreground">
              Choose how to save the keyword suggestions above.
            </p>
            <div className="flex gap-3 flex-wrap">
              <Button
                variant={saveMode === "new_file" ? "default" : "outline"}
                disabled={saveMutation.isPending}
                onClick={() => { setSaveMode("new_file"); saveMutation.mutate("new_file"); }}
              >
                <Save className="mr-2 h-4 w-4" />
                {saveMutation.isPending && saveMode === "new_file" ? "Saving..." : "Save as New File"}
              </Button>
              {result.resume_id && (
                <Button
                  variant={saveMode === "set_as_primary" ? "default" : "outline"}
                  disabled={saveMutation.isPending}
                  onClick={() => { setSaveMode("set_as_primary"); saveMutation.mutate("set_as_primary"); }}
                >
                  <Star className="mr-2 h-4 w-4" />
                  {saveMutation.isPending && saveMode === "set_as_primary" ? "Saving..." : "Set as Primary"}
                </Button>
              )}
            </div>
            {saveMutation.isSuccess && (
              <p className="mt-2 text-sm text-green-700">Changes saved successfully.</p>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
