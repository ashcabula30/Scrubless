import { useState } from "react";
import { api } from "../api";

type Coll = { id: string; title: string; collections: { id: string; title: string }[]; assets: number };

// Paste an Iconik collection link, click into sub-collections, then index the one you're in.
export default function IconikBrowser({ onIndex }: { onIndex: (link: string) => void }) {
  const [link, setLink] = useState("");
  const [trail, setTrail] = useState<Coll[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const open = async (idOrLink: string, keep: Coll[]) => {
    setLoading(true);
    setErr(null);
    try {
      const c = await api.iconikBrowse(idOrLink);
      setTrail([...keep, c]);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const here = trail.at(-1);
  return (
    <div className="panel">
      <div className="row" style={{ padding: "10px 12px", borderBottom: "1px solid var(--outline-variant)" }}>
        <input
          className="input grow"
          placeholder="Paste an Iconik collection link (e.g. the client's month or creator collection)"
          value={link}
          onChange={(e) => setLink(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && link.trim() && open(link.trim(), [])}
        />
        <button className="btn" disabled={!link.trim() || loading} onClick={() => open(link.trim(), [])}>
          Open
        </button>
      </div>
      {trail.length > 0 && (
        <div className="row" style={{ padding: "8px 12px", borderBottom: "1px solid var(--outline-variant)" }}>
          <div className="crumbs grow">
            {trail.map((c, i) => (
              <span key={c.id}>
                <button onClick={() => setTrail(trail.slice(0, i + 1))}>{c.title}</button>
                {i < trail.length - 1 && <span className="muted">/</span>}
              </span>
            ))}
          </div>
          {here && (
            <button className="btn primary sm" onClick={() => onIndex(`iconik://${here.id}/`)}>
              Index this collection
            </button>
          )}
        </div>
      )}
      {loading && <div className="empty">Loading…</div>}
      {err && <div className="empty error">{err}</div>}
      {!loading && !err && here && (
        <div style={{ maxHeight: 280, overflowY: "auto" }}>
          {here.collections.map((c) => (
            <div key={c.id} className="folder-row" onClick={() => open(c.id, trail)}>
              <span className="strong grow">{c.title}</span>
              <span className="muted">›</span>
            </div>
          ))}
          {here.assets > 0 && <div className="folder-row muted">{here.assets} asset(s) directly in this collection</div>}
          {!here.collections.length && !here.assets && <div className="empty">Empty collection</div>}
        </div>
      )}
    </div>
  );
}
