import { useEffect, useRef, useState } from "react";
import { api, BriefLine, Job, Result } from "../api";
import { useApp } from "../App";
import ResultCard from "../components/ResultCard";
import PreviewPlayer from "../components/PreviewPlayer";
import { SourceFilter } from "./Search";
import { emptyRow, Row, rowsFromHtml, rowsFromTableText } from "../briefParse";

// said: index of the chosen take (-1 = none); show: index of the chosen shot (-1 = none, null = automatic)
type Pick = { said: number; show: number | null };

const SIZES: Record<string, [number, number]> = {
  "9:16 (1080×1920)": [1080, 1920],
  "4:5 (1080×1350)": [1080, 1350],
  "1:1 (1080×1080)": [1080, 1080],
  "16:9 (1920×1080)": [1920, 1080],
};

const EXAMPLE: Row[] = [
  { label: "Hook", script: "I literally can't stop drinking this tea.", visual: "Creator holding the mug, talking to camera" },
  { label: "Body", script: "It tastes like dessert but there's no sugar in it.", visual: "Hand pouring tea into a glass, close-up" },
  { label: "CTA", script: "Grab yours at the link below.", visual: "On-screen text: LINK BELOW" },
];

function store(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* storage blocked */
  }
}

function loadRows(): Row[] {
  try {
    const r = JSON.parse(localStorage.getItem("ff.briefRows") ?? "null");
    if (Array.isArray(r) && r.length) return r;
  } catch {
    /* ignore */
  }
  return [emptyRow(), emptyRow(), emptyRow()];
}

const isBlank = (rows: Row[]) => rows.every((r) => !r.label.trim() && !r.script.trim() && !r.visual.trim());

/** Textarea that grows with its content, like a ClickUp table cell. */
function Cell({ value, onChange, placeholder, strong }: { value: string; onChange: (v: string) => void; placeholder?: string; strong?: boolean }) {
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = `${el.scrollHeight + 2}px`;
    }
  }, [value]);
  return (
    <textarea
      ref={ref}
      className={`cell${strong ? " strong" : ""}`}
      rows={1}
      value={value}
      placeholder={placeholder}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

export default function BriefPage() {
  const { toast, track, jobs, sources, go } = useApp();
  const [rows, setRows] = useState<Row[]>(loadRows);
  const [view, setView] = useState<"brief" | "takes">("brief");
  const [src, setSrc] = useState("");
  const [lines, setLines] = useState<BriefLine[]>([]);
  const [picks, setPicks] = useState<Pick[]>([]);
  const [current, setCurrent] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);
  const [reading, setReading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [name, setName] = useState("Rough cut");
  const [size, setSize] = useState(Object.keys(SIZES)[0]);
  const [outDir, setOutDir] = useState(() => localStorage.getItem("ff.outdir") ?? "");
  const [jobId, setJobId] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => store("ff.briefRows", JSON.stringify(rows)), [rows]);

  const job: Job | undefined = jobs.find((j) => j.id === jobId);

  // ---------- getting a brief in ----------
  const useRows = (incoming: Row[], how: string) => {
    if (!incoming.length) return toast(`Couldn't find any brief rows in that ${how}.`, true);
    setRows((cur) => (isBlank(cur) ? incoming : [...cur.filter((r) => r.label || r.script || r.visual), ...incoming]));
    toast(`${incoming.length} row${incoming.length === 1 ? "" : "s"} added from the ${how}`);
  };

  const readImage = async (blob: Blob) => {
    setReading(true);
    try {
      const r = await api.briefOcr(blob);
      useRows(r.rows, "screenshot");
    } catch (e) {
      toast((e as Error).message, true);
    } finally {
      setReading(false);
    }
  };

  const onPaste = async (e: React.ClipboardEvent) => {
    const cd = e.clipboardData;
    const image = Array.from(cd.items).find((i) => i.type.startsWith("image/"))?.getAsFile();
    if (image) {
      e.preventDefault();
      return readImage(image);
    }
    const html = cd.getData("text/html");
    const fromHtml = html ? rowsFromHtml(html) : null;
    if (fromHtml) {
      e.preventDefault();
      return useRows(fromHtml, "pasted table");
    }
    const text = cd.getData("text/plain");
    const fromText = rowsFromTableText(text);
    if (fromText) {
      e.preventDefault();
      return useRows(fromText, "pasted table");
    }
    // Plain text typed into a cell pastes normally; pasted anywhere else it's read as a text brief.
    if ((e.target as HTMLElement).tagName !== "TEXTAREA" && text.trim()) {
      e.preventDefault();
      const r = await api.rowsFromText(text);
      useRows(r.rows, "pasted text");
    }
  };

  const pasteButton = async () => {
    try {
      const items = await navigator.clipboard.read();
      for (const item of items) {
        const img = item.types.find((t) => t.startsWith("image/"));
        if (img) return readImage(await item.getType(img));
        if (item.types.includes("text/html")) {
          const rows = rowsFromHtml(await (await item.getType("text/html")).text());
          if (rows) return useRows(rows, "copied table");
        }
        if (item.types.includes("text/plain")) {
          const text = await (await item.getType("text/plain")).text();
          const rows = rowsFromTableText(text) ?? (await api.rowsFromText(text)).rows;
          return useRows(rows, "copied text");
        }
      }
      toast("The clipboard is empty.", true);
    } catch {
      toast("Click the table and press Ctrl+V to paste.", true);
    }
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    // Screenshots are read here; a dropped folder is picked up by the app window and indexed.
    const f = Array.from(e.dataTransfer.files).find((f) => f.type.startsWith("image/"));
    if (f) readImage(f);
  };

  const setCell = (i: number, key: keyof Row, v: string) => setRows((rs) => rs.map((r, k) => (k === i ? { ...r, [key]: v } : r)));

  // ---------- takes ----------
  const find = async () => {
    const filled = rows.filter((r) => r.script.trim() || r.visual.trim());
    if (!filled.length) return toast("The brief is empty.", true);
    setBusy(true);
    try {
      const r = await api.brief(filled, src ? [src] : null);
      setLines(r.lines);
      setPicks(r.lines.map((l) => ({ said: l.said.length ? 0 : -1, show: l.shown.length ? null : -1 })));
      setCurrent(r.lines.flatMap((l) => [...l.said, ...l.shown])[0] ?? null);
      setView("takes");
    } catch (e) {
      toast((e as Error).message, true);
    } finally {
      setBusy(false);
    }
  };

  const setPick = (i: number, p: Partial<Pick>) => setPicks((ps) => ps.map((x, k) => (k === i ? { ...x, ...p } : x)));

  const browse = async () => {
    const r = await api.pickFolder();
    if (r.path) {
      setOutDir(r.path);
      store("ff.outdir", r.path);
    }
  };

  const build = async () => {
    if (!outDir) return toast("Choose where to save the rough cut first.", true);
    const [width, height] = SIZES[size];
    try {
      const j = await api.roughcut({
        lines: lines.map((l, i) => ({ ...l, said_pick: picks[i].said, show_pick: picks[i].show })),
        out_dir: outDir,
        name,
        width,
        height,
        fps: 30,
      });
      store("ff.outdir", outDir);
      setJobId(j.id);
      track(j.id);
    } catch (e) {
      toast((e as Error).message, true);
    }
  };

  const missing = lines.filter((l, i) => picks[i]?.said === -1 && (picks[i]?.show === -1 || !l.shown.length)).length;

  if (!sources.length) {
    return (
      <div className="page">
        <div className="empty grow">
          <h1>No footage indexed yet</h1>
          <p>Add the footage for this brief in the Library first.</p>
          <button className="btn primary" onClick={() => go("library")}>
            Go to Library
          </button>
        </div>
      </div>
    );
  }

  // ---------- step 1: the brief table ----------
  if (view === "brief") {
    return (
      <div
        className={`page col brief-edit${dragging ? " dragging" : ""}`}
        onPaste={onPaste}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <div className="topbar">
          <div className="col grow" style={{ gap: 2 }}>
            <h1>Brief</h1>
            <span className="hint">
              Copy the brief table in ClickUp and press <kbd>Ctrl</kbd>+<kbd>V</kbd> here, or paste / drop a screenshot of it.
              You can also type in the table.
            </span>
          </div>
          <button className="btn" onClick={pasteButton} disabled={reading}>
            Paste
          </button>
          <button className="btn" onClick={() => fileInput.current?.click()} disabled={reading}>
            Open screenshot…
          </button>
          <input
            ref={fileInput}
            type="file"
            accept="image/*"
            hidden
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) readImage(f);
              e.target.value = "";
            }}
          />
          <button className="btn ghost" onClick={() => setRows([emptyRow(), emptyRow(), emptyRow()])}>
            Clear
          </button>
        </div>
        <div className="scroll pad" style={{ flex: "1 1 auto" }}>
          {reading && <div className="reading">Reading the screenshot…</div>}
          <table className="brief-table">
            <colgroup>
              <col style={{ width: 150 }} />
              <col />
              <col />
              <col style={{ width: 34 }} />
            </colgroup>
            <thead>
              <tr>
                <th />
                <th>Script</th>
                <th>Visual</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  <td>
                    <Cell value={r.label} onChange={(v) => setCell(i, "label", v)} placeholder={i === 0 ? "Hook" : "Body"} strong />
                  </td>
                  <td>
                    <Cell value={r.script} onChange={(v) => setCell(i, "script", v)} placeholder="What the creator says" />
                  </td>
                  <td>
                    <Cell value={r.visual} onChange={(v) => setCell(i, "visual", v)} placeholder="What we see (searched as b-roll)" />
                  </td>
                  <td className="row-x">
                    <button className="btn ghost sm" title="Delete row" onClick={() => setRows((rs) => (rs.length > 1 ? rs.filter((_, k) => k !== i) : [emptyRow()]))}>
                      ×
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="row" style={{ marginTop: 8 }}>
            <button className="btn sm" onClick={() => setRows((rs) => [...rs, emptyRow()])}>
              + Add row
            </button>
            {isBlank(rows) && (
              <button className="btn sm ghost" onClick={() => setRows(EXAMPLE)}>
                Load example
              </button>
            )}
            <span className="hint grow">
              Blank lines inside a cell split paragraphs; each script paragraph is matched with the visual paragraph beside it.{" "}
              <span className="mono">{"{placeholders}"}</span> are ignored and “On-screen text:” is kept as a note for the editor.
            </span>
          </div>
        </div>
        <div className="buildbar">
          <SourceFilter value={src} onChange={setSrc} />
          <span className="grow" />
          {lines.length > 0 && (
            <button className="btn big" onClick={() => setView("takes")}>
              Back to takes
            </button>
          )}
          <button className="btn primary big" onClick={find} disabled={busy || reading}>
            {busy ? "Finding takes…" : "Find takes →"}
          </button>
        </div>
      </div>
    );
  }

  // ---------- step 2: takes, picks and the rough cut ----------
  return (
    <div className="page page-brief">
      <div className="results" style={{ display: "flex", flexDirection: "column" }}>
        <div className="topbar">
          <button className="btn" onClick={() => setView("brief")}>
            ← Edit brief
          </button>
          <span className="hint grow">
            {lines.length} line{lines.length === 1 ? "" : "s"}. Click a take or shot to preview it and use it in the cut (green = in the cut).
          </span>
        </div>
        <div className="scroll pad" style={{ flex: "1 1 auto" }}>
          {lines.map((l, i) => (
            <div key={i}>
              {(i === 0 || lines[i - 1].row !== l.row) && <div className="row-group">{l.row}</div>}
              <div className="line">
                <div className="line-head">
                  <span className="label">{l.label}</span>
                  <span className="grow ellipsis" title={l.say}>
                    {l.say ? `“${l.say}”` : <span className="muted">(no spoken line)</span>}
                  </span>
                  {!l.said.length && l.say && <span className="badge warn">no take found</span>}
                </div>
                {(l.show || l.note) && (
                  <div className="line-notes">
                    {l.show && (
                      <span>
                        <span className="muted">Visual: </span>
                        {l.show}
                      </span>
                    )}
                    {l.note && <span className="badge blue">{l.note}</span>}
                  </div>
                )}
                {l.say && (
                  <div className="strip">
                    <span className="strip-label">Take</span>
                    {l.said.map((r, k) => (
                      <ResultCard
                        key={k}
                        r={r}
                        compact
                        picked={picks[i]?.said === k}
                        selected={current === r}
                        onClick={() => {
                          setPick(i, { said: k });
                          setCurrent(r);
                        }}
                      />
                    ))}
                    <div className={`opt${picks[i]?.said === -1 ? " picked" : ""}`} onClick={() => setPick(i, { said: -1 })}>
                      {l.said.length ? "None (skip)" : "Missing: needs VO or a manual pick"}
                    </div>
                  </div>
                )}
                {l.show && (
                  <div className="strip">
                    <span className="strip-label">{l.say ? "B-roll" : "Shot"}</span>
                    {l.shown.map((r, k) => (
                      <ResultCard
                        key={k}
                        r={r}
                        compact
                        picked={picks[i]?.show === k}
                        selected={current === r}
                        onClick={() => {
                          setPick(i, { show: k });
                          setCurrent(r);
                        }}
                      />
                    ))}
                    <div className={`opt${picks[i]?.show === null ? " picked" : ""}`} onClick={() => setPick(i, { show: null })}>
                      Automatic (best unused)
                    </div>
                    <div className={`opt${picks[i]?.show === -1 ? " picked" : ""}`} onClick={() => setPick(i, { show: -1 })}>
                      None
                    </div>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
        <div className="buildbar">
          <input className="input" style={{ width: 180 }} value={name} onChange={(e) => setName(e.target.value)} title="Sequence and file name" />
          <select className="select" value={size} onChange={(e) => setSize(e.target.value)}>
            {Object.keys(SIZES).map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
          <input className="input grow" placeholder="Save to folder…" value={outDir} onChange={(e) => setOutDir(e.target.value)} />
          <button className="btn" onClick={browse}>
            Browse…
          </button>
          <button className="btn primary big" onClick={build} disabled={job?.status === "running"}>
            {job?.status === "running" ? "Building…" : "Build rough cut"}
          </button>
          <div style={{ flexBasis: "100%" }} className="row small">
            {missing > 0 && <span className="badge warn">{missing} line(s) with nothing picked: they become gaps with a MISSING marker</span>}
            {job?.status === "running" && <span className="muted">{job.log.at(-1) ?? "Building…"}</span>}
            {job?.status === "error" && <span className="error">{job.error}</span>}
            {job?.status === "done" && job.result && (
              <>
                <span className="badge ok">Saved</span>
                <span className="mono ellipsis grow" title={String(job.result.xml)}>
                  {String(job.result.xml).split(/[\\/]/).pop()}
                </span>
                <button className="btn sm" onClick={() => api.reveal(String(job.result!.xml))}>
                  Show in Explorer
                </button>
                <span className="hint">In Premiere: File › Import… and pick the .xml</span>
              </>
            )}
          </div>
        </div>
      </div>
      <PreviewPlayer r={current} />
    </div>
  );
}
