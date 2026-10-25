import { useEffect, useRef, useState } from "react";
import { api, Result, folderOf, previewUrl, tc } from "../api";
import { useApp } from "../App";

// Plays a short H.264 preview of the match (iPhone HEVC won't play in the app window directly).
export default function PreviewPlayer({ r }: { r: Result | null }) {
  const { toast, track } = useApp();
  const video = useRef<HTMLVideoElement>(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);

  useEffect(() => {
    setFailed(null);
    setLoading(!!r);
  }, [r?.location, r?.start, r?.end]);

  if (!r) {
    return (
      <div className="side">
        <div className="player">
          <span className="muted">Pick a result to preview it</span>
        </div>
        <div className="side-body hint">
          <div>
            <kbd>←</kbd> <kbd>→</kbd> move between results · <kbd>Space</kbd> play / pause
          </div>
        </div>
      </div>
    );
  }

  const at = r.kind === "said" ? r.start : r.peak ?? r.start;
  const copy = () => {
    navigator.clipboard.writeText(`${r.location} @ ${tc(at)}`);
    toast("Copied path and timecode");
  };
  const download = async () => {
    const dest = await api.pickFolder();
    if (!dest.path) return;
    const job = await api.download([r.location], dest.path);
    track(job.id);
    toast(`Downloading ${r.file}…`);
  };

  return (
    <div className="side">
      <div className="player">
        {failed ? (
          <span className="error small" style={{ padding: 20 }}>
            {failed}
          </span>
        ) : (
          <>
            {loading && <span className="muted small" style={{ position: "absolute" }}>Making preview…</span>}
            <video
              ref={video}
              key={previewUrl(r)}
              src={previewUrl(r)}
              controls
              autoPlay
              onCanPlay={() => setLoading(false)}
              onError={() => {
                setLoading(false);
                setFailed(r.remote ? "Couldn't load this Backblaze clip (check the key in Settings)." : "Couldn't make a preview of this clip.");
              }}
            />
          </>
        )}
      </div>
      <div className="side-body">
        {r.kind === "said" && <div className="quote">“{r.text}”</div>}
        <div className="kv">
          <span className="k">File</span>
          <span className="strong" style={{ wordBreak: "break-all" }}>{r.file}</span>
          <span className="k">{r.kind === "said" ? "Said at" : "Best frame"}</span>
          <span className="mono">{tc(at)}</span>
          <span className="k">Range</span>
          <span className="mono">
            {tc(r.start)} – {tc(r.end)}
          </span>
          <span className="k">{r.kind === "said" ? "Match" : "Visual"}</span>
          <span>{r.kind === "said" ? `${Math.round(r.score * 100)}%` : r.label}</span>
          {r.takes && r.takes > 1 ? (
            <>
              <span className="k">Take</span>
              <span>
                {r.take} of {r.takes} in this clip
              </span>
            </>
          ) : null}
          <span className="k">Folder</span>
          <span className="muted" style={{ wordBreak: "break-all" }}>{folderOf(r.location)}</span>
        </div>
        <div className="row" style={{ flexWrap: "wrap" }}>
          {r.remote ? (
            <button className="btn primary" onClick={download}>
              Download clip…
            </button>
          ) : (
            <button className="btn" onClick={() => api.reveal(r.location).catch((e) => toast(e.message, true))}>
              Show in Explorer
            </button>
          )}
          <button className="btn" onClick={copy}>
            Copy path + time
          </button>
        </div>
      </div>
    </div>
  );
}
