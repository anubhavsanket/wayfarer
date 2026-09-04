import { useEffect, useState } from "react";
import { BrowserRouter as Router, Routes, Route, NavLink, useLocation } from "react-router-dom";
import { Tabs, TabsList, TabsTrigger } from "@radix-ui/react-tabs";
import { Search, FileText, Briefcase, Settings, Sun, Moon, LayoutDashboard } from "lucide-react";
import { useTheme } from "@/stores/theme";
import { api } from "@/lib/api";
import { Reveal } from "@/components/Reveal";
import SearchPage from "./pages/Search";
import ResumeCheckPage from "./pages/ResumeCheck";
import JobMatchPage from "./pages/JobMatch";
import TrackerPage from "./pages/Tracker";
import SettingsPage from "./pages/Settings";

const PIPELINE_LAST_VISITED_KEY = "last_visited_pipeline_ts";

function NavLinks() {
  const { theme, toggle } = useTheme();
  const location = useLocation();
  const [notifCount, setNotifCount] = useState(0);

  const currentTab = location.pathname === "/" ? "settings" : location.pathname.substring(1).split("/")[0];

  // Check for notifications on mount and when location changes
  useEffect(() => {
    const lastVisited = localStorage.getItem(PIPELINE_LAST_VISITED_KEY);
    if (lastVisited) {
      api
        .getNotifications(lastVisited)
        .then((r) => setNotifCount(r.total))
        .catch(() => {});
    }
  }, []);

  // Dismiss notifications when user visits the pipeline page
  useEffect(() => {
    if (currentTab === "tracker") {
      setNotifCount(0);
    }
  }, [currentTab]);

  return (
    <header className="sticky top-0 z-40 border-b border-border/60 bg-background/80 backdrop-blur-md">
      <div className="mx-auto flex max-w-5xl items-center gap-4 px-6 py-3">
        <h1 className="font-display text-[1.35rem] font-bold tracking-tight text-foreground">
          Wayfarer
        </h1>
        
        <Tabs value={currentTab} className="ml-6">
          <TabsList className="flex items-center gap-0.5 rounded-md bg-transparent p-0.5">
            <NavLink to="/search" end>
              {() => (
                <TabsTrigger value="search" className="group inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[13px] font-medium text-muted-foreground transition-colors hover:text-foreground data-[state=active]:bg-card data-[state=active]:text-foreground data-[state=active]:shadow-sm data-[state=active]:border data-[state=active]:border-border">
                  <Search className="h-3.5 w-3.5" />
                  <span className="hidden sm:inline">Search</span>
                </TabsTrigger>
              )}
            </NavLink>
            <NavLink to="/resume">
              {() => (
                <TabsTrigger value="resume" className="group inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[13px] font-medium text-muted-foreground transition-colors hover:text-foreground data-[state=active]:bg-card data-[state=active]:text-foreground data-[state=active]:shadow-sm data-[state=active]:border data-[state=active]:border-border">
                  <FileText className="h-3.5 w-3.5" />
                  <span className="hidden sm:inline">Resume</span>
                </TabsTrigger>
              )}
            </NavLink>
            <NavLink to="/jobs">
              {() => (
                <TabsTrigger value="jobs" className="group inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[13px] font-medium text-muted-foreground transition-colors hover:text-foreground data-[state=active]:bg-card data-[state=active]:text-foreground data-[state=active]:shadow-sm data-[state=active]:border data-[state=active]:border-border">
                  <Briefcase className="h-3.5 w-3.5" />
                  <span className="hidden sm:inline">Jobs</span>
                </TabsTrigger>
              )}
            </NavLink>
            <NavLink to="/tracker" onClick={() => localStorage.setItem(PIPELINE_LAST_VISITED_KEY, new Date().toISOString())}>
              {() => (
                <TabsTrigger value="tracker" className="group relative inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[13px] font-medium text-muted-foreground transition-colors hover:text-foreground data-[state=active]:bg-card data-[state=active]:text-foreground data-[state=active]:shadow-sm data-[state=active]:border data-[state=active]:border-border">
                  <LayoutDashboard className="h-3.5 w-3.5" />
                  <span className="hidden sm:inline">Pipeline</span>
                  {notifCount > 0 && (
                    <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-destructive px-1 text-[10px] font-bold text-white leading-none">
                      {notifCount > 9 ? "9+" : notifCount}
                    </span>
                  )}
                </TabsTrigger>
              )}
            </NavLink>
            <NavLink to="/">
              {() => (
                <TabsTrigger value="settings" className="group inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[13px] font-medium text-muted-foreground transition-colors hover:text-foreground data-[state=active]:bg-card data-[state=active]:text-foreground data-[state=active]:shadow-sm data-[state=active]:border data-[state=active]:border-border">
                  <Settings className="h-3.5 w-3.5" />
                  <span className="hidden sm:inline">Settings</span>
                </TabsTrigger>
              )}
            </NavLink>
          </TabsList>
        </Tabs>

        <span className="flex-1" />

        {/* Theme toggle */}
        <button
          onClick={toggle}
          aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
          className="flex h-8 w-8 items-center justify-center rounded-lg border border-border bg-beige-deep text-foreground shadow-sm transition-all duration-150 hover:bg-border active:scale-95"
        >
          <span className="relative h-4 w-4">
            <Sun
              className={`absolute inset-0 h-4 w-4 text-foreground transition-all duration-300 ${
                theme === "dark"
                  ? "rotate-0 scale-100 opacity-100"
                  : "rotate-90 scale-0 opacity-0"
              }`}
            />
            <Moon
              className={`absolute inset-0 h-4 w-4 text-foreground transition-all duration-300 ${
                theme === "dark"
                  ? "-rotate-90 scale-0 opacity-0"
                  : "rotate-0 scale-100 opacity-100"
              }`}
            />
          </span>
        </button>
      </div>
    </header>
  );
}

export default function App() {
  return (
    <Router>
      <div className="flex min-h-screen flex-col bg-background">
        <NavLinks />

        <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8 sm:px-6">
          <Reveal>
              <Routes>
              <Route path="/search" element={<SearchPage />} />
              <Route path="/resume" element={<ResumeCheckPage />} />
              <Route path="/jobs" element={<JobMatchPage />} />
              <Route path="/tracker" element={<TrackerPage />} />
              <Route path="/" element={<SettingsPage />} />
            </Routes>
          </Reveal>
        </main>
      </div>
    </Router>
  );
}