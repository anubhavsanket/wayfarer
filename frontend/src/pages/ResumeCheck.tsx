import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Upload, FileText, Save, Star } from "lucide-react";

import { api } from "@/lib/api";
import type { ResumeCheckResponse, SaveMode } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Sticker } from "@/components/ui/badge";
import { ScoreBar } from "@/components/ui/progress";
import { Reveal, Stagger } from "@/components/Reveal";
import { LoadingIndicator } from "@/components/LoadingIndicator";

function tierVariant(tier: string): "verified" | "reworded" | "gap" {
  if (tier === "verified") return "verified";
  if (tier === "reworded") return "reworded";
  return "gap";
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

  const canCheck = jdText.trim() && ((primary && !useVariant) || (useVariant && file));

  const handleCheck = () => {
    if (!jdText.trim()) return;
    setResult(null); // Clear previous results before new check
    setSaveMode(null);
    if (useVariant && file) {
      checkMutation.mutate({ file, jd: jdText.trim() });
    } else if (primary) {
      checkMutation.mutate({ file: null, jd: jdText.trim() });
    }
  };

  // Save mutation
  const saveMutation = useMutation({
    mutationFn: (mode: SaveMode) =>
      api.resumeSave({
        resume_id: result?.resume_id ?? "",
        accepted_suggestions: result?.keyword_gaps
          ?.filter((g) => g.suggested_text)
          .map((g) => ({
            bullet_id: g.bullet_id ?? "",
            suggested_text: g.suggested_text ?? "",
          })) ?? [],
        mode,
        confirm_overwrite: mode === "overwrite",
      }),
    onSuccess: () => setSaveMode(null),
  });

  return (
    <div className="space-y-4">
      {/* ── Input card ──────────────────────────────────────── */}
      <Card className="p-6">
        <h2 className="font-display mb-1 text-lg font-bold">ATS Resume Checker</h2>
        <p className="mb-4 text-sm text-muted-foreground">
          {primary
            ? "Using your primary resume from Settings. Paste a JD to check compatibility."
            : "Upload your resume and paste a JD to get ATS compatibility scores with confidence-tiered redline suggestions."}
        </p>

        <div className="mb-4 space-y-3">
          {/* Primary resume display */}
          {primary && !useVariant && (
            <div className="flex items-center gap-2 rounded-md bg-beige-deep p-3 text-sm border-2 border-ink/20">
              <FileText className="h-4 w-4 shrink-0 text-blue" />
              <span className="font-medium truncate">{primary.filename || "Resume uploaded"}</span>
              <span className="text-xs text-muted-foreground">({primary.resume_id})</span>
              <button
                onClick={() => setUseVariant(true)}
                className="ml-auto text-xs font-semibold text-blue underline"
              >
                Use a different resume
              </button>
            </div>
          )}

          {/* Variant upload */}
          {(useVariant || !primary) && (
            <div className="space-y-2">
              <label className="flex cursor-pointer items-center gap-2 rounded-md border-2 border-dashed border-ink bg-cream p-4 text-sm text-muted-foreground transition-colors hover:bg-beige-deep">
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
                  className="text-xs font-semibold text-muted-foreground underline"
                >
                  ← Use primary resume instead
                </button>
              )}
            </div>
          )}

          <textarea
            value={jdText}
            onChange={(e) => setJdText(e.target.value)}
            rows={5}
            placeholder="Paste job description here..."
            className="w-full resize-y rounded-md border-2 border-ink bg-cream px-4 py-2.5 text-sm placeholder:text-ink/40 focus:outline-none focus:ring-2 focus:ring-cyan focus:ring-offset-2 focus:ring-offset-card"
          />
          {jdText.trim().length > 0 && (
            <p className="text-right text-[10px] font-mono text-muted-foreground">
              {jdText.trim().length} chars
            </p>
          )}
        </div>

        <Button
          disabled={!canCheck || checkMutation.isPending}
          onClick={handleCheck}
        >
          <FileText className="mr-2 h-4 w-4" />
          {checkMutation.isPending ? "Checking..." : "Check Resume"}
        </Button>
      </Card>

      {/* Loading */}
      {checkMutation.isPending && (
        <Reveal>
          <LoadingIndicator message="Checking your resume" />
        </Reveal>
      )}

      {/* Error */}
      {checkMutation.isError && (
        <Card className="border-destructive p-4 text-sm text-destructive">
          Error: {checkMutation.error.message}
        </Card>
      )}

      {/* ── Results ─────────────────────────────────────────── */}
      {result && (
        <Stagger className="space-y-4">
          {/* ATS Score */}
          <Card className="p-6">
            <Sticker variant="blue" className="mb-3">ATS Score</Sticker>
            <ScoreBar
              value={result.ats_score * 100}
              decimals={0}
              suffix="%"
              className="max-w-md"
            />
          </Card>

          {/* Structural Issues */}
          {result.structural_issues.length > 0 && (
            <Card className="p-6">
              <Sticker variant="ink" className="mb-3">Structural Issues</Sticker>
              <ul className="space-y-1 text-sm">
                {result.structural_issues.map((issue, i) => (
                  <li key={i} className="flex gap-3">
                    <Sticker variant="muted" className="shrink-0">
                      {issue.location}
                    </Sticker>
                    <span className="leading-relaxed">{issue.issue}</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {/* Keyword Gaps */}
          {result.keyword_gaps.length > 0 && (
            <Card className="p-6">
              <Sticker variant="cyan" className="mb-4">Keyword Analysis</Sticker>
              <ul className="space-y-4">
                {result.keyword_gaps.map((gap, i) => (
                  <li key={i} className="text-sm">
                    <div className="mb-1 flex items-center gap-2">
                      <span className="font-semibold">{gap.keyword}</span>
                      <Sticker variant={tierVariant(gap.tier)}>
                        {gap.tier}
                      </Sticker>
                      {gap.confidence != null && (
                        <span className="font-mono text-xs text-muted-foreground">
                          {(gap.confidence * 100).toFixed(0)}%
                        </span>
                      )}
                    </div>

                    {gap.rationale && (
                      <p className="pl-4 text-xs leading-relaxed text-muted-foreground">
                        {gap.rationale}
                      </p>
                    )}

                    {gap.original_text && gap.suggested_text ? (
                      <div className="mt-2 ml-4 grid grid-cols-2 gap-2 rounded-md border-2 border-ink bg-cream p-3 text-xs">
                        <div>
                          <span className="mb-1 block font-semibold text-destructive">Original</span>
                          <p className="whitespace-pre-wrap text-muted-foreground line-through">
                            {gap.original_text}
                          </p>
                        </div>
                        <div>
                          <span className="mb-1 block font-semibold text-blue">Suggested</span>
                          <p className="whitespace-pre-wrap text-blue">
                            {gap.suggested_text}
                          </p>
                        </div>
                      </div>
                    ) : gap.suggested_text ? (
                      <p className="mt-1 whitespace-pre-wrap pl-4 text-xs italic text-blue">
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
            <Sticker variant="muted" className="mb-3">Save Changes</Sticker>
            <p className="mb-4 text-sm text-muted-foreground">
              Choose how to save the keyword suggestions above.
            </p>
            <div className="flex flex-wrap gap-3">
              <Button
                variant={saveMode === "new_file" ? "default" : "outline"}
                disabled={saveMutation.isPending}
                onClick={() => { setSaveMode("new_file"); saveMutation.mutate("new_file"); }}
              >
                <Save className="mr-2 h-4 w-4" />
                {saveMutation.isPending && saveMode === "new_file" ? "Saving..." : "Save as New File"}
              </Button>

              {result.resume_id && (
                <>
                  <Button
                    variant={saveMode === "set_as_primary" ? "default" : "outline"}
                    disabled={saveMutation.isPending}
                    onClick={() => { setSaveMode("set_as_primary"); saveMutation.mutate("set_as_primary"); }}
                  >
                    <Star className="mr-2 h-4 w-4" />
                    {saveMutation.isPending && saveMode === "set_as_primary" ? "Saving..." : "Set as Primary"}
                  </Button>
                  <Button
                    variant="destructive"
                    disabled={saveMutation.isPending}
                    onClick={() => {
                      if (window.confirm("Overwrite the original resume file? This cannot be undone.")) {
                        setSaveMode("overwrite");
                        saveMutation.mutate("overwrite");
                      }
                    }}
                  >
                    Overwrite Original
                  </Button>
                </>
              )}
            </div>

            {saveMutation.isSuccess && (
              <Reveal className="mt-3">
                <Sticker variant="blue">✓ Changes saved successfully</Sticker>
              </Reveal>
            )}
          </Card>
        </Stagger>
      )}
    </div>
  );
}
