import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Search as SearchIcon } from "lucide-react";

import { api } from "@/lib/api";
import type { SearchResponse } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<SearchResponse | null>(null);

  const mutation = useMutation({
    mutationFn: (q: string) => api.search(q),
    onSuccess: (data) => setResult(data),
  });

  return (
    <div className="space-y-6">
      <Card className="p-6">
        <h2 className="mb-4 text-lg font-semibold">Web Search Agent</h2>
        <p className="mb-4 text-sm text-muted-foreground">
          Search the web and get synthesized answers with inline citations.
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (query.trim()) mutation.mutate(query.trim());
          }}
          className="flex gap-3"
        >
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="e.g. top GenAI engineer roles in Bengaluru..."
            className="flex-1 rounded-md border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring"
          />
          <Button type="submit" disabled={mutation.isPending}>
            <SearchIcon className="mr-2 h-4 w-4" />
            {mutation.isPending ? "Searching..." : "Search"}
          </Button>
        </form>
      </Card>

      {mutation.isError && (
        <Card className="border-destructive p-4 text-sm text-destructive">
          Error: {mutation.error.message}
        </Card>
      )}

      {result && (
        <>
          <Card className="p-6">
            <h3 className="mb-2 font-medium">Answer</h3>
            <p className="whitespace-pre-wrap text-sm leading-relaxed">
              {result.answer}
            </p>
            {result.sub_queries_used.length > 0 && (
              <div className="mt-4 text-xs text-muted-foreground">
                Sub-queries:{" "}
                {result.sub_queries_used.map((q, i) => (
                  <span key={i} className="mr-2 inline-block rounded bg-muted px-1.5 py-0.5">
                    {q}
                  </span>
                ))}
              </div>
            )}
          </Card>

          {result.citations.length > 0 && (
            <Card className="p-6">
              <h3 className="mb-3 font-medium">Citations</h3>
              <ul className="space-y-2">
                {result.citations.map((c) => (
                  <li key={c.id} className="text-sm">
                    <span className="mr-1 font-mono text-xs text-muted-foreground">
                      [{c.id}]
                    </span>
                    <a
                      href={c.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-primary underline-offset-2 hover:underline"
                    >
                      {c.title}
                    </a>
                    <p className="mt-0.5 pl-6 text-xs text-muted-foreground">
                      {c.snippet}
                    </p>
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
