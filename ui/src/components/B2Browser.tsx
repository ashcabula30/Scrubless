import { useEffect, useState } from "react";
import { api } from "../api";

// Click through Backblaze folders (like Cyberduck), then index the one you're in.
export default function B2Browser({ bucket, onIndex }: { bucket: string; onIndex: (uri: string) => void }) {
  const [uri, setUri] = useState(`b2://${bucket}/`);
  const [folders, setFolders] = useState<string[]>([]);
  const [files, setFiles] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    setErr(null);
    api
      .b2ls(uri)
      .then((r) => {
        setFolders(r.folders);
        setFiles(r.files);
      })
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false));
  }, [uri]);

  const parts = uri.slice("b2://".length).split("/").filter(Boolean);
  const crumbTo = (i: number) => setUri("b2://" + parts.slice(0, i + 1).join("/") + "/");

  return (
    <div className="panel">
      <div className="row" style={{ padding: "8px 10px", borderBottom: "1px solid var(--divider)" }}>
        <div className="crumbs grow">
          {parts.map((p, i) => (
            <span key={i}>
              <button onClick={() => crumbTo(i)}>{p}</button>
              <span className="muted">/</span>
            </span>
          ))}
        </div>
        <button className="btn primary sm" disabled={!!err || parts.length < 2} onClick={() => onIndex(uri)}>
          Index this folder
        </button>
      </div>
      {loading && <div className="empty">Loading…</div>}
      {err && <div className="empty error">{err}</div>}
      {!loading && !err && (
        <div style={{ maxHeight: 280, overflowY: "auto" }}>
          {parts.length > 1 && (
            <div className="folder-row muted" onClick={() => crumbTo(parts.length - 2)}>
              ↑ ..
            </div>
          )}
          {folders.map((f) => (
            <div key={f} className="folder-row" onClick={() => setUri(uri + f + "/")}>
              <span className="strong grow">{f}</span>
              <span className="muted">›</span>
            </div>
          ))}
          {files > 0 && <div className="folder-row muted">{files} video/audio file(s) in this folder</div>}
          {!folders.length && !files && <div className="empty">Empty folder</div>}
        </div>
      )}
    </div>
  );
}
