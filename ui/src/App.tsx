import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api, Job, Source, Status } from "./api";
import SearchPage from "./pages/Search";
import BriefPage from "./pages/Brief";
import LibraryPage from "./pages/Library";
import SettingsPage from "./pages/Settings";

type Page = "search" | "brief" | "library" | "settings";

type AppCtx = {
  status: Status | null;
  sources: Source[];
  jobs: Job[];
  refresh: () => void;
  toast: (msg: string, err?: boolean) => void;
  track: (jobId: string) => void;
  go: (p: Page) => void;
};

const Ctx = createContext<AppCtx>(null as unknown as AppCtx);
export const useApp = () => useContext(Ctx);

const PAGES: { id: Page; label: string }[] = [
  { id: "search", label: "Search" },
  { id: "brief", label: "Brief → Rough cut" },
  { id: "library", label: "Library" },
  { id: "settings", label: "Settings" },
];

export default function App() {
  const [page, setPage] = useState<Page>(() => (localStorage.getItem("ff.page") as Page) || "search");
  const [status, setStatus] = useState<Status | null>(null);
  const [sources, setSources] = useState<Source[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [msg, setMsg] = useState<{ text: string; err: boolean } | null>(null);
  const tracked = useRef<Set<string>>(new Set());
  const timer = useRef<number>();

  const toast = useCallback((text: string, err = false) => {
    setMsg({ text, err });
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setMsg(null), err ? 7000 : 3500);
  }, []);

  const refresh = useCallback(() => {
    api.status().then(setStatus).catch(() => setStatus(null));
    api.sources().then(setSources).catch(() => {});
  }, []);

  const go = (p: Page) => {
    setPage(p);
    try {
      localStorage.setItem("ff.page", p);
    } catch {
      /* storage blocked */
    }
  };

  // Poll jobs fast while something runs, slowly otherwise; refresh sources when a job finishes.
  useEffect(() => {
    let stop = false;
    let prev: Record<string, string> = {};
    const tick = async () => {
      try {
        const js = await api.jobs();
        setJobs(js);
        let changed = false;
        for (const j of js) {
          if (prev[j.id] && prev[j.id] !== j.status && ["done", "error", "cancelled"].includes(j.status)) {
            changed = true;
            if (tracked.current.has(j.id)) {
              if (j.status === "done") toast(`${j.title}: done`);
              if (j.status === "error") toast(`${j.title}: ${j.error}`, true);
            }
          }
        }
        prev = Object.fromEntries(js.map((j) => [j.id, j.status]));
        if (changed) refresh();
        const active = js.some((j) => j.status === "running" || j.status === "queued");
        if (!stop) window.setTimeout(tick, active ? 1000 : 4000);
      } catch {
        if (!stop) window.setTimeout(tick, 4000);
      }
    };
    tick();
    return () => {
      stop = true;
    };
  }, [refresh, toast]);

  // Messages from the desktop window (e.g. a folder dropped onto it).
  useEffect(() => {
    const on = (e: Event) => {
      const d = (e as CustomEvent<{ text: string; err?: boolean }>).detail;
      toast(d.text, d.err);
      refresh();
    };
    window.addEventListener("ff-toast", on);
    return () => window.removeEventListener("ff-toast", on);
  }, [toast, refresh]);

  useEffect(() => {
    refresh();
    const t = window.setInterval(() => api.status().then(setStatus).catch(() => setStatus(null)), 5000);
    return () => window.clearInterval(t);
  }, [refresh]);

  const active = jobs.filter((j) => j.status === "running" || j.status === "queued").length;
  const ctx: AppCtx = { status, sources, jobs, refresh, toast, track: (id) => tracked.current.add(id), go };

  return (
    <Ctx.Provider value={ctx}>
      <div className="shell">
        <nav className="nav">
          <div className="brand">
            Scrubless
            <small>Goodo Studios</small>
          </div>
          {PAGES.map((p) => (
            <button key={p.id} className={`nav-item${page === p.id ? " on" : ""}`} onClick={() => go(p.id)}>
              {p.label}
              {p.id === "library" && active > 0 && <span className="badge blue">{active}</span>}
            </button>
          ))}
          <div className="nav-foot col" style={{ gap: 4 }}>
            <div className="row">
              <span className={`dot ${status ? (status.ready ? "ok" : "warn") : "bad"}`} />
              {status ? (status.ready ? "Ready" : "Loading models…") : "Server not running"}
            </div>
            {status?.gpu && <div className="ellipsis" title={status.gpu}>{status.gpu.replace("NVIDIA GeForce ", "")}</div>}
            <div>
              {sources.length} folder{sources.length === 1 ? "" : "s"} indexed
            </div>
          </div>
        </nav>
        <main className="main">
          {page === "search" && <SearchPage />}
          {page === "brief" && <BriefPage />}
          {page === "library" && <LibraryPage />}
          {page === "settings" && <SettingsPage />}
        </main>
      </div>
      {msg && <div className={`toast${msg.err ? " err" : ""}`}>{msg.text}</div>}
    </Ctx.Provider>
  );
}
