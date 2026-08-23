import { BrowserRouter as Router, Routes, Route, NavLink, useLocation } from 'react-router-dom';
import { Tabs, TabsList, TabsTrigger } from "@radix-ui/react-tabs";
import { Search, FileText, Briefcase, Settings, Sun, Moon } from "lucide-react";
import { useTheme } from "@/stores/theme";
import { Reveal } from "@/components/Reveal";
import SearchPage from "./pages/Search";
import ResumeCheckPage from "./pages/ResumeCheck";
import JobMatchPage from "./pages/JobMatch";
import SettingsPage from "./pages/Settings";

function NavLinks() {
  const { theme, toggle } = useTheme();
  const location = useLocation();

  const currentTab = location.pathname === '/' ? 'settings' : location.pathname.substring(1);

  return (
    <header className="sticky top-0 z-40 border-b-2 border-ink bg-card shadow-hard-sm">
      <div className="mx-auto flex max-w-5xl items-center gap-4 px-6 py-3">
        <h1 className="font-display text-2xl font-bold tracking-tight">
          Wayfarer
        </h1>
        
        <Tabs value={currentTab} className="ml-8">
          <TabsList className="flex items-center gap-1 rounded-lg border-2 border-ink bg-[#dcd3c7] p-1 dark:bg-[#2e3848] shadow-hard-sm">
            <NavLink to="/search" end>
              {() => (
                <TabsTrigger value="search" className="group flex items-center gap-1.5 border-2 border-transparent data-[state=active]:border-ink data-[state=active]:bg-card data-[state=active]:shadow-hard-sm">
                  <Search className="h-4 w-4" />
                  <span className="hidden sm:inline">Search</span>
                </TabsTrigger>
              )}
            </NavLink>
            <NavLink to="/resume">
              {() => (
                <TabsTrigger value="resume" className="group flex items-center gap-1.5 border-2 border-transparent data-[state=active]:border-ink data-[state=active]:bg-card data-[state=active]:shadow-hard-sm">
                  <FileText className="h-4 w-4" />
                  <span className="hidden sm:inline">Resume</span>
                </TabsTrigger>
              )}
            </NavLink>
            <NavLink to="/jobs">
              {() => (
                <TabsTrigger value="jobs" className="group flex items-center gap-1.5 border-2 border-transparent data-[state=active]:border-ink data-[state=active]:bg-card data-[state=active]:shadow-hard-sm">
                  <Briefcase className="h-4 w-4" />
                  <span className="hidden sm:inline">Jobs</span>
                </TabsTrigger>
              )}
            </NavLink>
            <NavLink to="/">
              {() => (
                <TabsTrigger value="settings" className="group flex items-center gap-1.5 border-2 border-transparent data-[state=active]:border-ink data-[state=active]:bg-card data-[state=active]:shadow-hard-sm">
                  <Settings className="h-4 w-4" />
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
              className={`absolute inset-0 h-4 w-4 text-[#f3c48b] transition-all duration-300 ${
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
              <Route path="/" element={<SettingsPage />} />
            </Routes>
          </Reveal>
        </main>
      </div>
    </Router>
  );
}
