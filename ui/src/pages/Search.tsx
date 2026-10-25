import { useEffect, useMemo, useRef, useState } from "react";
import { api, Result } from "../api";
import { useApp } from "../App";
import ResultCard from "../components/ResultCard";
import PreviewPlayer from "../components/PreviewPlayer";

type Mode = "both" | "said" | "shown";

export function SourceFilter({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const { sources } = useApp();
  return (
    <select className="select" value={value} onChange={(e) => onChange(e.target.value)} style={{ maxWidth: 240 }}>
      <option value="">All folders ({sources.length})</option>
      {sources.map((s) => (
        <option key={s.id} value={s.id}>
          {s.remote ? "B2 · " : ""}
          {s.name}
        </option>
      ))}
    </select>
  );
}

export default function SearchPage() {
  const { sources, go, toast } = useApp();
  const [q, setQ] = useState(() => sessionStorage.getItem("ff.q") ?? "");
  const [mode, setMode] = useState<Mode>("both");
  const [src, setSrc] = useState("");
  const [said, setSaid] = useState<Result[]>([]);
  const [shown, setShown] = useState<Result[]>([]);
  const [sel, setSel] = useState(0);
  const [busy, setBusy] = useState(false);
  const [ms, setMs] = useState<number | null>(null);
  const [searched, setSearched] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const all = useMemo(() => [...said, ...shown], [said, shown]);

  const run = async () => {
    if (!q.trim()) return;
    sessionStorage.setItem("ff.q", q);
    setBusy(true);
    try {
      const r = await api.search(q, mode, src ? [src] : null);
      setSaid(r.said);
      // In Both mode a spoken line also matches random shots weakly; keep only real visual matches
      // (or a few "possible" ones when there is nothing better).
      const good = r.shown.filter((s) => s.label !== "possible");
      setShown(mode === "both" ? (good.length ? good : r.shown.slice(0, 4)) : r.shown);
      setSel(0);
      setMs(r.ms);
      setSearched(true);
    } catch (e) {
      toast((e as Error).message, true);
    } finally {
      setBusy(false);
    }
  };

  // Re-run when the mode or folder filter changes.
  useEffect(() => {
    if (searched) run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, src]);

  useEffect(() => input.current?.focus(), []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (e.key === "ArrowRight" || e.key === "ArrowDown") {
        setSel((s) => Math.min(all.length - 1, s + 1));
        e.preventDefault();
      } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
        setSel((s) => Math.max(0, s - 1));
        e.preventDefault();
      } else if (e.key === " ") {
        const v = document.querySelector<HTMLVideoElement>(".player video");
        if (v) (v.paused ? v.play() : v.pause());
        e.preventDefault();
      } else if (e.key === "/") {
        input.current?.focus();
        e.preventDefault();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [all.length]);

  useEffect(() => {
    document.querySelector(".card.sel")?.scrollIntoView({ block: "nearest" });
  }, [sel]);

  if (!sources.length) {
    return (
      <div className="page">
        <div className="empty grow">
          <h1>No footage indexed yet</h1>
          <p>Add a footage folder in the Library first. Scrubless transcribes it and looks at every shot once.</p>
          <button className="btn primary" onClick={() => go("library")}>
            Go to Library
          </button>
        </div>
      </div>
    );
  }

  const current = all[sel] ?? null;
  const group = (title: string, hint: string, list: Result[], offset: number) => (
    <div style={{ marginBottom: 22 }}>
      <div className="group-head">
        <h2>{title}</h2>
        <span className="hint">{hint}</span>
      </div>
      {list.length ? (
        <div className="grid">
          {list.map((r, i) => (
            <ResultCard key={r.location + r.start + r.kind} r={r} selected={sel === offset + i} onClick={() => setSel(offset + i)} />
          ))}
        </div>
      ) : (
        <div className="hint" style={{ padding: "6px 0 10px" }}>
          No match.
        </div>
      )}
    </div>
  );

  return (
    <>
      <div className="topbar">
        <input
          ref={input}
          className="input big grow"
          placeholder={'Type a line ("I can\'t stop drinking this tea") or describe a shot ("hand pouring tea, close-up")'}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && run()}
        />
        <div className="seg">
          {(["both", "said", "shown"] as Mode[]).map((m) => (
            <button key={m} className={mode === m ? "on" : ""} onClick={() => setMode(m)}>
              {m === "both" ? "Both" : m === "said" ? "Said" : "Shown"}
            </button>
          ))}
        </div>
        <SourceFilter value={src} onChange={setSrc} />
        <button className="btn primary big" onClick={run} disabled={busy || !q.trim()}>
          {busy ? "Searching…" : "Search"}
        </button>
      </div>
      <div className="page">
        <div className="results scroll pad">
          {!searched && (
            <div className="empty">
              <p className="strong">Search by what's said or what's on screen.</p>
              <p>
                <b>Said</b> finds every take of a line, even when the wording differs. <b>Shown</b> finds shots that look like
                your description.
              </p>
            </div>
          )}
          {searched && (
            <>
              <div className="hint" style={{ marginBottom: 10 }}>
                {all.length} result{all.length === 1 ? "" : "s"}
                {ms !== null && ` · ${ms} ms`}
              </div>
              {mode !== "shown" && group("Said", "where the line is spoken", said, 0)}
              {mode !== "said" && group("Shown", "shots that look like this", shown, said.length)}
            </>
          )}
        </div>
        <PreviewPlayer r={current} />
      </div>
    </>
  );
}
