import { useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@radix-ui/react-tabs";
import { Search, FileText, Briefcase } from "lucide-react";
import SearchPage from "./pages/Search";
import ResumeCheckPage from "./pages/ResumeCheck";
import JobMatchPage from "./pages/JobMatch";

export default function App() {
  const [tab, setTab] = useState("search");

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="border-b bg-card px-6 py-4">
        <div className="mx-auto flex max-w-5xl items-center gap-3">
          <h1 className="text-xl font-semibold tracking-tight">Wayfarer</h1>
          <span className="rounded-md bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
            v0.1
          </span>
          <span className="ml-auto text-sm text-muted-foreground">
            AI-Powered Job Search
          </span>
        </div>
      </header>

      {/* Main content */}
      <main className="mx-auto max-w-5xl px-6 py-8">
        <Tabs value={tab} onValueChange={setTab} className="w-full">
          <TabsList className="mb-6 inline-flex gap-1 rounded-lg bg-muted p-1">
            <TabsTrigger
              value="search"
              className="inline-flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors data-[state=active]:bg-background data-[state=active]:text-foreground data-[state=active]:shadow-sm"
            >
              <Search className="h-4 w-4" />
              Search
            </TabsTrigger>
            <TabsTrigger
              value="resume"
              className="inline-flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors data-[state=active]:bg-background data-[state=active]:text-foreground data-[state=active]:shadow-sm"
            >
              <FileText className="h-4 w-4" />
              Resume Check
            </TabsTrigger>
            <TabsTrigger
              value="jobs"
              className="inline-flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors data-[state=active]:bg-background data-[state=active]:text-foreground data-[state=active]:shadow-sm"
            >
              <Briefcase className="h-4 w-4" />
              Job Match
            </TabsTrigger>
          </TabsList>

          <TabsContent value="search">
            <SearchPage />
          </TabsContent>
          <TabsContent value="resume">
            <ResumeCheckPage />
          </TabsContent>
          <TabsContent value="jobs">
            <JobMatchPage />
          </TabsContent>
        </Tabs>
      </main>
    </div>
  );
}
