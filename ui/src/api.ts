// Typed calls to the local Scrubless server (footage_finder/server.py).

export type Result = {
  kind: "said" | "shown";
  location: string;
  file: string;
  start: number;
  end: number;
  peak?: number;
  text?: string;
  score: number;
  label?: "strong" | "good" | "possible";
  take?: number;
  takes?: number;
  remote: boolean;
  source: string | null;
  thumb_t: number;
};

export type Source = {
  id: string;
  source: string;
  remote: boolean;
  name: string;
  files: number;
  hours: number;
  videos: number;
  frames: number;
  tier: string;
  model: string;
  indexed_at: number;
  busy: boolean;
};

export type Job = {
  id: string;
  kind: "index" | "roughcut" | "download";
  title: string;
  source: string | null;
  status: "queued" | "running" | "done" | "error" | "cancelled";
  n: number;
  total: number;
  file: string;
  log: string[];
  error: string | null;
  result: Record<string, unknown> | null;
  created: number;
};

export type Status = {
  gpu: string | null;
  tier: string;
  auto_tier: string;
  ready: boolean;
  data_dir: string;
  b2_key: { set: boolean; key_id_tail?: string };
  b2_bucket: string;
  sources: number;
};

export type BriefLine = {
  label: string;
  row: string;
  say: string;
  show: string;
  note: string;
  said: Result[];
  shown: Result[];
};

export type BriefRow = { label: string; script: string; visual: string };

async function call<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const opts: RequestInit = { ...init };
  if (init?.json !== undefined) {
    opts.body = JSON.stringify(init.json);
    opts.headers = { "Content-Type": "application/json" };
    opts.method = init.method ?? "POST";
  }
  const res = await fetch(path, opts);
  if (!res.ok) {
    let msg = `${res.status}`;
    try {
      msg = (await res.json()).detail ?? msg;
    } catch {
      /* not JSON */
    }
    throw new Error(msg);
  }
  return res.json();
}

export const api = {
  status: () => call<Status>("/api/status"),
  sources: () => call<Source[]>("/api/sources"),
  addSource: (path: string) => call<Job>("/api/sources", { json: { path } }),
  reindex: (id: string, rebuild = false) => call<Job>(`/api/sources/${id}/index?rebuild=${rebuild}`, { method: "POST" }),
  removeSource: (id: string) => call<{ ok: boolean }>(`/api/sources/${id}`, { method: "DELETE" }),
  jobs: () => call<Job[]>("/api/jobs"),
  cancel: (id: string) => call<Job>(`/api/jobs/${id}/cancel`, { method: "POST" }),
  search: (q: string, mode: string, sources: string[] | null) =>
    call<{ said: Result[]; shown: Result[]; ms: number }>("/api/search", { json: { q, mode, sources } }),
  brief: (rows: BriefRow[], sources: string[] | null) =>
    call<{ lines: BriefLine[]; ms: number }>("/api/brief", { json: { rows, sources } }),
  briefOcr: async (image: Blob) => {
    const form = new FormData();
    form.append("file", image, "brief.png");
    return call<{ rows: BriefRow[] }>("/api/brief/ocr", { method: "POST", body: form });
  },
  rowsFromText: (text: string) => call<{ rows: BriefRow[] }>("/api/brief/rows-from-text", { json: { text } }),
  roughcut: (body: unknown) => call<Job>("/api/roughcut", { json: body }),
  download: (locations: string[], dest: string) => call<Job>("/api/download", { json: { locations, dest } }),
  reveal: (path: string) => call<{ ok: boolean }>("/api/reveal", { json: { path } }),
  pickFolder: () => call<{ path: string | null }>("/api/pick-folder", { method: "POST" }),
  settings: () => call<{ tier: string; auto_tier: string; tiers: Record<string, Record<string, string | number>> }>("/api/settings"),
  setTier: (tier: string) => call("/api/settings", { method: "PUT", json: { tier } }),
  setBucket: (b2_bucket: string) => call("/api/settings", { method: "PUT", json: { b2_bucket } }),
  setKey: (key_id: string, application_key: string) =>
    call<{ set: boolean }>("/api/b2/key", { method: "PUT", json: { key_id, application_key } }),
  b2ls: (uri: string) => call<{ uri: string; folders: string[]; files: number }>(`/api/b2/ls?uri=${encodeURIComponent(uri)}`),
};

export const thumbUrl = (r: Result, h = 360) =>
  `/api/thumb?loc=${encodeURIComponent(r.location)}&t=${r.thumb_t}&h=${h}${r.source ? `&src=${r.source}` : ""}`;

export const previewUrl = (r: Result) =>
  `/api/preview?loc=${encodeURIComponent(r.location)}&start=${r.start}&end=${r.end}`;

export function tc(sec: number): string {
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${h ? pad(h) + ":" : ""}${pad(m)}:${s.toFixed(1).padStart(4, "0")}`;
}

export function folderOf(location: string): string {
  const i = Math.max(location.lastIndexOf("/"), location.lastIndexOf("\\"));
  return i > 0 ? location.slice(0, i) : location;
}
