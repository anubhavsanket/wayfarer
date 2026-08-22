import { useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@radix-ui/react-tabs";
import { Search, FileText, Briefcase, Settings, Sun, Moon, Github } from "lucide-react";
import { useTheme } from "@/stores/theme";
import { Reveal } from "@/components/Reveal";
import SearchPage from "./pages/Search";
import ResumeCheckPage from "./pages/ResumeCheck";
import JobMatchPage from "./pages/JobMatch";
import SettingsPage from "./pages/Settings";

export default function App() {
  const [tab, setTab] = useState("search");
  const { theme, toggle } = useTheme();

  return (
    <div className="flex min-h-screen flex-col bg-background">
      {/* ── Header ───────────────────────────────────────────── */}
      <header className="sticky top-0 z-40 border-b-2 border-ink bg-card shadow-hard-sm">
        <div className="mx-auto flex max-w-5xl items-center gap-4 px-6 py-3">
          <h1 className="font-display text-2xl font-bold tracking-tight">
            Wayfarer
          </h1>

          <span className="ml-2 hidden text-[11px] font-semibold uppercase tracking-widest text-muted-foreground sm:block">
            AI-Powered Job Search
          </span>

          <span className="flex-1" />

          {/* Theme toggle */}
          <button
            onClick={toggle}
            aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
            className="flex h-9 w-9 items-center justify-center rounded-md border-2 border-[#2e3848] dark:border-ink bg-[#2e3848] dark:bg-[#f3c48b] shadow-hard-sm transition-all duration-150 hover:-translate-y-0.5 hover:shadow-hard active:translate-y-0.5 active:shadow-hard-none"
          >
            <span className="relative h-4 w-4">
              <Sun
                className={`absolute inset-0 h-4 w-4 text-ink transition-all duration-300 ${
                  theme === "dark"
                    ? "rotate-0 scale-100 opacity-100"
                    : "rotate-90 scale-0 opacity-0"
                }`}
              />
              <Moon
                className={`absolute inset-0 h-4 w-4 text-[#fffaf0] transition-all duration-300 ${
                  theme === "dark"
                    ? "-rotate-90 scale-0 opacity-0"
                    : "rotate-0 scale-100 opacity-100"
                }`}
              />
            </span>
          </button>
        </div>
      </header>

      {/* ── Main content ─────────────────────────────────────── */}
      <main className="mx-auto w-full max-w-5xl flex-1 px-6 py-6">
        <Tabs value={tab} onValueChange={setTab} className="w-full">
          <TabsList className="mb-6 inline-flex gap-2 rounded-lg border-2 border-ink bg-beige-deep p-1.5 shadow-hard-sm">
            {([
              ["search",    Search,     "Search"],
              ["resume",    FileText,   "Resume Check"],
              ["jobs",      Briefcase,  "Job Match"],
              ["settings",  Settings,   "Settings"],
            ] as const).map(([val, Icon, label]) => (
              <TabsTrigger
                key={val}
                value={val}
                className="inline-flex items-center gap-2 rounded-md border-2 border-transparent px-4 py-2.5 text-sm font-semibold transition-all duration-150 data-[state=active]:border-ink data-[state=active]:bg-blue data-[state=active]:text-white dark:data-[state=active]:text-ink data-[state=active]:shadow-hard-blue data-[state=inactive]:text-ink dark:data-[state=inactive]:text-white dark:data-[state=inactive]:hover:bg-accent dark:data-[state=inactive]:hover:text-accent-foreground"
              >
                <Icon className="h-4 w-4" />
                {label}
              </TabsTrigger>
            ))}
          </TabsList>

          {/* Each TabsContent mounts its child when activated → Reveal fires on switch */}
          <div className="space-y-6">
            <TabsContent value="search">
              <Reveal>
                <SearchPage />
              </Reveal>
            </TabsContent>
            <TabsContent value="resume">
              <Reveal>
                <ResumeCheckPage />
              </Reveal>
            </TabsContent>
            <TabsContent value="jobs">
              <Reveal>
                <JobMatchPage />
              </Reveal>
            </TabsContent>
            <TabsContent value="settings">
              <Reveal>
                <SettingsPage />
              </Reveal>
            </TabsContent>
          </div>
        </Tabs>
      </main>

      {/* ── Footer ───────────────────────────────────────────── */}
      <footer className="border-t-2 border-ink bg-card py-5">
        <div className="mx-auto flex max-w-5xl flex-col items-center gap-3 px-6 sm:flex-row sm:justify-between">
          <div className="flex items-center gap-3">
            <span className="font-display text-sm font-bold">Wayfarer</span>
            <span className="sticker bg-cyan text-white text-[10px]" style={{ transform: "rotate(-1deg)" }}>v1.1</span>
            <span className="text-xs text-muted-foreground">No data leaves your machine.</span>
          </div>
          <nav className="flex items-center gap-4 text-xs font-semibold text-muted-foreground">
            <button onClick={() => setTab("search")} className="hover:text-foreground transition-colors">Search</button>
            <button onClick={() => setTab("resume")} className="hover:text-foreground transition-colors">Resume</button>
            <button onClick={() => setTab("jobs")} className="hover:text-foreground transition-colors">Jobs</button>
            <button onClick={() => setTab("settings")} className="hover:text-foreground transition-colors">Settings</button>
            <a
              href="https://github.com/anubhavsanket/wayfarer"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 hover:text-foreground transition-colors"
            >
              <Github className="h-3.5 w-3.5" />
              GitHub
            </a>
          </nav>
        </div>
      </footer>
    </div>
  );
}
