import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Search as SearchIcon } from "lucide-react";

import { api } from "@/lib/api";
import type { SearchResponse } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Sticker } from "@/components/ui/badge";
import { Reveal, Stagger } from "@/components/Reveal";
import { LoadingIndicator } from "@/components/LoadingIndicator";

const EXAMPLE_QUERIES = [
  "Best practices for RAG pipelines?",
  "How to optimize Ollama inference speed?",
  "LLM prompt caching strategies 2026",
  "Remote ML engineer jobs India",
];

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<SearchResponse | null>(null);

  const mutation = useMutation({
    mutationFn: (q: string) => api.search(q),
    onSuccess: (data) => setResult(data),
  });

  const handleSubmit = (q: string) => {
    if (q.trim()) {
      setQuery(q.trim());
      mutation.mutate(q.trim());
    }
  };

  return (
    <div className="space-y-4">
      {/* Hero search card */}
      <Card className="relative overflow-hidden p-6">
        {/* Decorative corner accent */}
        <div className="absolute -right-3 -top-3 h-16 w-16 rotate-12 rounded-lg border-2 border-ink/10 bg-cyan/10" />
        <h2 className="mb-4 font-display text-xl font-bold">Web Search Agent</h2>
        <p className="mb-5 text-sm text-muted-foreground">
          Search the web and get synthesized answers with inline citations.
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleSubmit(query);
          }}
          className="flex gap-3"
        >
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Ask anything — e.g. top GenAI roles in Bengaluru..."
            className="flex-1 rounded-lg border border-border bg-card px-4 py-3 text-sm font-mono placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-cyan focus:ring-offset-2 focus:ring-offset-card"
          />
          <Button type="submit" disabled={mutation.isPending} size="lg">
            <SearchIcon className="mr-2 h-4 w-4" />
            {mutation.isPending ? "Searching..." : "Search"}
          </Button>
        </form>

        {/* Example queries — only show when no results yet */}
        {!result && !mutation.isPending && (
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Try:
            </span>
            {EXAMPLE_QUERIES.map((q) => (
              <button
                key={q}
                onClick={() => handleSubmit(q)}
                className="rounded-lg border border-border bg-beige-deep px-3 py-1 text-xs font-medium text-foreground transition-colors hover:border-cyan hover:bg-cyan-pale/30"
              >
                {q}
              </button>
            ))}
          </div>
        )}
      </Card>

      {/* Error */}
      {mutation.isError && (
        <Card className="border-destructive p-4 text-sm text-destructive">
          Error: {mutation.error.message}
        </Card>
      )}

      {/* Loading */}
      {mutation.isPending && (
        <Reveal>
          <LoadingIndicator message="Searching the web" />
        </Reveal>
      )}

      {/* Results */}
      {result && (
        <Stagger className="space-y-4">
          {/* Answer */}
          <Card className="p-6">
            <div className="mb-3">
              <Sticker variant="blue">Answer</Sticker>
            </div>
            <p className="whitespace-pre-wrap text-sm leading-relaxed">
              {result.answer}
            </p>

            {result.sub_queries_used.length > 0 && (
              <div className="mt-4 flex flex-wrap gap-2">
                <span className="text-xs font-semibold uppercase text-muted-foreground">Queries:</span>
                {result.sub_queries_used.map((q, i) => (
                  <Sticker key={i} variant="muted">
                    {q}
                  </Sticker>
                ))}
              </div>
            )}
          </Card>

          {/* Citations */}
          {result.citations.length > 0 && (
            <Card className="p-6">
              <div className="mb-4">
                <Sticker variant="cyan">Sources</Sticker>
              </div>
              <ul className="space-y-3">
                {result.citations.map((c) => (
                  <li key={c.id} className="text-sm">
                    <div className="flex items-start gap-3">
                      <Sticker variant="ink" className="mt-0 shrink-0">
                        [{c.id}]
                      </Sticker>
                      <div className="min-w-0">
                        <a
                          href={c.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="font-semibold text-blue break-words hover:underline"
                        >
                          {c.title}
                        </a>
                        <p className="mt-0.5 text-xs text-muted-foreground">
                          {c.snippet}
                        </p>
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </Stagger>
      )}
    </div>
  );
}
