import { useState } from "react";
import { api, Job } from "../api";
import { useApp } from "../App";
import ProgressBar from "../components/ProgressBar";
import B2Browser from "../components/B2Browser";

function ago(t: number) {
  const s = Date.now() / 1000 - t;
  if (s < 90) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400 * 2) return `${Math.round(s / 3600)} h ago`;
  return new Date(t * 1000).toLocaleDateString();
}

function JobRow({ j }: { j: Job }) {
  const [open, setOpen] = useState(false);
  const running = j.status === "running";
  const badge = { queued: "", running: "blue", done: "ok", error: "bad", cancelled: "warn" }[j.status];
  return (
    <div className="job">
      <div className="row">
        <span className={`badge ${badge}`}>{j.status}</span>
        <span className="strong ellipsis grow" title={j.title}>{j.title}</span>
        {running && j.total > 0 && (
          <span className="muted small">
            {j.n} / {j.total}
          </span>
        )}
        {(running || j.status === "queued") && (
          <button className="btn sm danger" onClick={() => api.cancel(j.id)}>
            {running ? "Stop" : "Cancel"}
          </button>
        )}
        <button className="btn sm ghost" onClick={() => setOpen(!open)}>
          {open ? "Hide log" : "Log"}
        </button>
      </div>
      {running && <ProgressBar n={j.n} total={j.total} running />}
      {running && j.file && <span className="hint ellipsis">Working on {j.file}</span>}
      {j.status === "error" && <span className="error small">{j.error}</span>}
      {j.status === "cancelled" && <span className="hint">Stopped. Files finished so far stay indexed; Update picks up the rest.</span>}
      {open && <div className="log mono">{j.log.join("\n") || "(nothing yet)"}</div>}
    </div>
  );
}

export default function LibraryPage() {
  const { sources, jobs, refresh, toast, track, status, go } = useApp();
  const [path, setPath] = useState("");
  const [showB2, setShowB2] = useState(false);

  const add = async (p: string) => {
    if (!p.trim()) return;
    try {
      const j = await api.addSource(p.trim());
      track(j.id);
      setPath("");
      toast("Indexing started. You can keep searching meanwhile.");
    } catch (e) {
      toast((e as Error).message, true);
    }
  };

  const browse = async () => {
    const r = await api.pickFolder();
    if (r.path) setPath(r.path);
  };

  const remove = async (id: string, name: string) => {
    if (!window.confirm(`Remove "${name}" from Scrubless?\n\nThis deletes its search index only. Your footage is not touched.`)) return;
    await api.removeSource(id);
    refresh();
  };

  return (
    <div className="page">
      <div className="results scroll pad col" style={{ gap: 18 }}>
        <div className="col">
          <h1>Library</h1>
          <span className="hint">
            Scrubless listens to and looks at each folder once, on this PC. After that, searching it is instant. Re-run
            Update when new clips arrive: only new or changed files are processed.
          </span>
        </div>

        <div className="card-block" style={{ maxWidth: "none" }}>
          <h2>Add a footage folder</h2>
          <div className="row">
            <input
              className="input grow"
              placeholder="E:\Footage\Client\October"
              value={path}
              onChange={(e) => setPath(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && add(path)}
            />
            <button className="btn" onClick={browse}>
              Browse…
            </button>
            <button className="btn primary" onClick={() => add(path)} disabled={!path.trim()}>
              Add and index
            </button>
          </div>
          <span className="hint">
            Or drag a footage folder from Explorer onto this window. Subfolders are included. Search data is kept on D:, not
            inside the footage folder.
          </span>
        </div>

        <div className="col" style={{ gap: 6 }}>
          <h2>Indexed folders</h2>
          {sources.length ? (
            <table className="table panel">
              <thead>
                <tr>
                  <th>Folder</th>
                  <th>Clips</th>
                  <th>Footage</th>
                  <th>Preset</th>
                  <th>Updated</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {sources.map((s) => (
                  <tr key={s.id}>
                    <td style={{ maxWidth: 420 }}>
                      <div className="row">
                        {s.remote && <span className="badge blue">B2</span>}
                        <span className="strong">{s.name}</span>
                        {s.busy && <span className="badge">indexing…</span>}
                      </div>
                      <div className="hint ellipsis" title={s.source}>{s.source}</div>
                    </td>
                    <td>{s.files}</td>
                    <td>{s.hours < 1 ? `${Math.round(s.hours * 60)} min` : `${s.hours.toFixed(1)} h`}</td>
                    <td>{s.tier}</td>
                    <td className="muted">{ago(s.indexed_at)}</td>
                    <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                      <button className="btn sm" disabled={s.busy} onClick={() => api.reindex(s.id).then((j) => track(j.id))}>
                        Update
                      </button>{" "}
                      <button className="btn sm danger" disabled={s.busy} onClick={() => remove(s.id, s.name)}>
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="panel empty">Nothing indexed yet. Add a folder above.</div>
          )}
        </div>

        <div className="col" style={{ gap: 6 }}>
          <div className="row">
            <h2 className="grow">Backblaze</h2>
            <button className="btn sm" onClick={() => setShowB2(!showB2)}>
              {showB2 ? "Hide" : "Show"}
            </button>
          </div>
          {showB2 &&
            (status?.b2_key.set && status.b2_bucket ? (
              <>
                <span className="hint">
                  Browse to a shoot folder and index it. Clips stream down one at a time, get indexed, and are deleted; only
                  clips you pick are downloaded for keeps.
                </span>
                <B2Browser bucket={status.b2_bucket} onIndex={add} />
              </>
            ) : (
              <div className="panel pad row">
                <span className="grow">Backblaze needs the bucket name and a read-only key first.</span>
                <button className="btn" onClick={() => go("settings")}>
                  Set up in Settings
                </button>
              </div>
            ))}
        </div>
      </div>

      <div className="side">
        <div className="pad section">
          <h2>Jobs</h2>
        </div>
        <div className="scroll" style={{ flex: "1 1 auto" }}>
          {jobs.length ? jobs.map((j) => <JobRow key={j.id} j={j} />) : <div className="empty">No jobs yet.</div>}
        </div>
      </div>
    </div>
  );
}
