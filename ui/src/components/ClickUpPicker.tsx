import { useEffect, useState } from "react";
import { api, BriefRow, ClickUpTask } from "../api";
import { useApp } from "../App";

type Imported = { rows: BriefRow[]; task: { name: string; url: string; client: string } };

// Pull a brief from ClickUp: paste a task link, or pick one of your open editing tasks.
// Subtasks ("Video Editing") read the brief from their parent asset task.
export default function ClickUpPicker({ onImport, onClose }: { onImport: (b: Imported) => void; onClose: () => void }) {
  const { status, go, toast } = useApp();
  const [link, setLink] = useState("");
  const [tasks, setTasks] = useState<ClickUpTask[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);

  useEffect(() => {
    if (!status?.clickup) return;
    api.clickupTasks().then(setTasks).catch((e) => setErr((e as Error).message));
  }, [status?.clickup]);

  const load = async (what: string) => {
    if (!what.trim()) return;
    setBusy(what);
    try {
      onImport(await api.clickupBrief(what.trim()));
      onClose();
    } catch (e) {
      toast((e as Error).message, true);
    } finally {
      setBusy(null);
    }
  };

  const modal = (body: React.ReactNode) => (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal col" role="dialog" aria-modal="true" aria-label="Import a brief from ClickUp">
        <div className="row">
          <h2 className="grow">Import from ClickUp</h2>
          <button className="btn ghost sm" title="Close (Esc)" onClick={onClose}>
            ×
          </button>
        </div>
        {body}
      </div>
    </div>
  );

  if (!status?.clickup) {
    return modal(
      <div className="row">
        <span className="grow">Connect ClickUp once with your personal API token, then briefs import in one click.</span>
        <button className="btn primary" onClick={() => go("settings")}>
          Set up in Settings
        </button>
      </div>,
    );
  }

  return modal(
    <>
      <div className="row">
        <input
          className="input grow"
          placeholder="Paste a ClickUp task link (the asset or its Video Editing subtask)"
          value={link}
          onChange={(e) => setLink(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && load(link)}
          autoFocus
        />
        <button className="btn primary" onClick={() => load(link)} disabled={!link.trim() || !!busy}>
          {busy === link ? "Importing…" : "Import"}
        </button>
      </div>
      <span className="hint">Or pick one of your tasks in an editing status:</span>
      {err && <span className="error small">{err}</span>}
      {!tasks && !err && <span className="hint">Loading your ClickUp tasks…</span>}
      {tasks && !tasks.length && <span className="hint">No tasks of yours are in an editing status right now.</span>}
      {tasks && tasks.length > 0 && (
        <div className="cu-list">
          {tasks.map((t) => (
            <button key={t.id} className="cu-task" onClick={() => load(t.url || t.id)} disabled={!!busy}>
              <span className="strong ellipsis">{t.name}</span>
              <span className="muted ellipsis">
                {t.client}
                {t.subtask ? ` · ${t.subtask}` : ""}
              </span>
              <span className="badge blue">{busy === (t.url || t.id) ? "importing…" : t.status}</span>
              {t.due && <span className="muted small">due {new Date(t.due).toLocaleDateString(undefined, { month: "short", day: "numeric" })}</span>}
            </button>
          ))}
        </div>
      )}
    </>,
  );
}
