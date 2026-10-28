"""Local app server (127.0.0.1 only): keeps the models loaded, runs indexing jobs, serves the UI.

The same API is meant for the desktop window, the Editing Assistant Premiere panel, Claude and n8n.
"""
import hashlib
import json
import queue
import shutil
import subprocess
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import tiers
from .env import DATA_DIR
from .sources import KEYS_FILE, fetch_to, is_remote, open_source
from .store import INDEX_DIR, Index, load_registry, unregister

PORT = 7792
STATIC = Path(__file__).parent / "static"
SETTINGS = DATA_DIR / "settings.json"
WINDOW = None  # set by app.py when running in the desktop window (for native dialogs)

@asynccontextmanager
async def lifespan(_app):
    threading.Thread(target=engine.warm, daemon=True).start()  # models load while the UI opens
    yield


app = FastAPI(title="Scrubless", lifespan=lifespan)


# ---------------------------------------------------------------- settings
def load_settings():
    try:
        return {"tier": "auto", **json.loads(SETTINGS.read_text(encoding="utf-8"))}
    except (FileNotFoundError, ValueError):
        return {"tier": "auto"}


def save_settings(s):
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(s, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- sources
def source_id(index_dir) -> str:
    return hashlib.sha1(str(Path(index_dir).resolve()).lower().encode()).hexdigest()[:12]


def indexed():
    """{id: index_dir} for every registered, existing index."""
    return {source_id(f): Path(f) for f in load_registry() if Index.exists(f)}


def db_mtime(index_dir: Path) -> float:
    try:
        return (index_dir / INDEX_DIR / "index.db").stat().st_mtime
    except FileNotFoundError:
        return 0.0


def source_info(sid, index_dir):
    st = Index(index_dir).stats()
    base = st["source"]
    return {"id": sid, "source": base, "remote": is_remote(base),
            "name": base.rstrip("/\\").replace("\\", "/").rsplit("/", 1)[-1],
            "files": st["files"], "hours": round(st["hours"], 2), "videos": st["vfiles"],
            "frames": st["vframes"], "tier": st["tier"], "model": st["whisper"],
            "indexed_at": db_mtime(index_dir), "busy": jobs.busy_with(base)}


def allowed(location: str) -> bool:
    """Only serve media from indexed sources (stops other web pages using the API to read files)."""
    loc = location.replace("\\", "/").lower()
    for d in indexed().values():
        base = Index(d).base.replace("\\", "/").lower().rstrip("/") + "/"
        if loc.startswith(base):
            return True
    return False


# ---------------------------------------------------------------- search engine
class Engine:
    """Searchers built once and reused until an index changes; one search at a time on the GPU."""

    def __init__(self):
        self.lock = threading.Lock()
        self._key = None
        self._speech = self._scenes = None
        self.ready = False

    def _folders(self, ids):
        idx = indexed()
        return [idx[i] for i in (ids or idx) if i in idx]

    def searchers(self, ids, visual):
        from .search import Searcher
        from .visual import SceneSearcher

        folders = self._folders(ids)
        key = tuple((str(f), db_mtime(f)) for f in folders)
        if key != self._key:
            self._key, self._speech, self._scenes = key, Searcher(folders), None
        if visual and self._scenes is None:
            self._scenes = SceneSearcher(folders)
        return self._speech, self._scenes

    def warm(self):
        """Load the models in the background at startup so the first search is quick."""
        try:
            from .search import embedder
            from .visual import vision_model

            with self.lock:
                for d in indexed().values():
                    i = Index(d)
                    if i.get_meta("embed"):
                        embedder(i.get_meta("embed")).encode(["warm up"])
                    if i.get_meta("vision"):
                        vision_model(i.get_meta("vision")).embed_text("warm up")
        finally:
            self.ready = True


engine = Engine()


def hit_dict(h, sid_by_base):
    return {"kind": "said", "location": h.location, "file": h.file, "start": round(h.start, 3),
            "end": round(h.end, 3), "text": h.text, "score": round(h.score, 3), "take": h.take,
            "takes": h.takes, "remote": is_remote(h.location), "source": sid_by_base.get(h.base),
            "thumb_t": round((h.start + h.end) / 2, 2)}


def scene_dict(s, sid_by_base):
    label = "strong" if s.score >= 0.5 else "good" if s.score >= 0.05 else "possible"
    return {"kind": "shown", "location": s.location, "file": s.file, "start": round(s.start, 3),
            "end": round(s.end, 3), "peak": round(s.peak, 3), "score": round(s.score, 4), "label": label,
            "remote": is_remote(s.location), "source": sid_by_base.get(s.base), "thumb_t": round(s.peak, 2)}


def bases():
    return {Index(d).base: sid for sid, d in indexed().items()}


# ---------------------------------------------------------------- jobs
class Jobs:
    """Indexing runs one at a time in a worker thread; downloads and rough cuts run alongside."""

    def __init__(self):
        self.jobs = {}
        self.q = queue.Queue()
        threading.Thread(target=self._worker, daemon=True).start()

    def _new(self, kind, title, source=None):
        job = {"id": uuid.uuid4().hex[:10], "kind": kind, "title": title, "source": source,
               "status": "queued", "n": 0, "total": 0, "file": "", "log": [], "error": None,
               "result": None, "created": time.time(), "cancel": threading.Event()}
        self.jobs[job["id"]] = job
        return job

    def public(self, job):
        return {k: v for k, v in job.items() if k != "cancel"} | {"log": job["log"][-60:]}

    def busy_with(self, base):
        return any(j["source"] == base and j["status"] in ("queued", "running") for j in self.jobs.values())

    def index(self, spec, rebuild=False):
        src = open_source(spec)
        job = self._new("index", f"Index {src.uri}", src.uri)
        job["spec"], job["rebuild"] = spec, rebuild
        self.q.put(job["id"])
        return job

    def run_now(self, kind, title, fn):
        job = self._new(kind, title)

        def go():
            job["status"] = "running"
            try:
                job["result"] = fn(job)
                job["status"] = "done"
            except Exception as e:
                job["status"], job["error"] = "error", str(e)

        threading.Thread(target=go, daemon=True).start()
        return job

    def _worker(self):
        from .indexer import Cancelled, index_folder

        while True:
            job = self.jobs[self.q.get()]
            if job["cancel"].is_set():
                job["status"] = "cancelled"
                continue
            job["status"] = "running"
            log = lambda line: job["log"].append(str(line))
            try:
                index_folder(job["spec"], load_settings()["tier"], rebuild=job["rebuild"], log=log,
                             progress=lambda p: job.update(n=p["n"], total=p["total"], file=p["file"]),
                             cancel=job["cancel"])
                job["status"] = "done"
            except Cancelled:
                job["status"] = "cancelled"
            except SystemExit as e:  # friendly errors from the engine (missing key, preset mismatch)
                job["status"], job["error"] = "error", str(e)
            except Exception as e:
                job["status"], job["error"] = "error", f"{type(e).__name__}: {e}"


jobs = Jobs()


# ---------------------------------------------------------------- API models
class AddSource(BaseModel):
    path: str


class SearchReq(BaseModel):
    q: str
    mode: str = "both"  # said | shown | both
    sources: list[str] | None = None
    top: int = 24
    min: float = 0.55


class BriefRow(BaseModel):
    label: str = ""
    script: str = ""
    visual: str = ""


class BriefReq(BaseModel):
    text: str = ""                     # old one-line-per-row format
    rows: list[BriefRow] | None = None  # table format (Section | Script | Visual), like ClickUp
    sources: list[str] | None = None
    top: int = 6
    min: float = 0.55


class RoughcutLine(BaseModel):
    label: str
    say: str = ""
    show: str = ""
    note: str = ""
    said: list[dict] = []
    shown: list[dict] = []
    said_pick: int = 0       # index into said; -1 = no spoken take
    show_pick: int | None = None  # index into shown; -1 = no b-roll; None = automatic


class RoughcutReq(BaseModel):
    lines: list[RoughcutLine]
    out_dir: str
    name: str = "Scrubless rough cut"
    width: int = 1080
    height: int = 1920
    fps: float = 30


class DownloadReq(BaseModel):
    locations: list[str]
    dest: str


class KeyReq(BaseModel):
    key_id: str
    application_key: str


class SettingsReq(BaseModel):
    tier: str | None = None
    b2_bucket: str | None = None  # e.g. the bucket Cyberduck shows under its Backblaze connection


class RevealReq(BaseModel):
    path: str


# ---------------------------------------------------------------- routes
@app.get("/api/status")
def status():
    gpu = tiers.gpu_info()
    s = load_settings()
    return {"gpu": f"{gpu[0]} ({gpu[1]:.0f} GB)" if gpu else None, "tier": s["tier"],
            "auto_tier": tiers.detect(), "ready": engine.ready, "data_dir": str(DATA_DIR),
            "b2_key": key_status(), "b2_bucket": s.get("b2_bucket", ""), "sources": len(indexed())}


@app.get("/api/sources")
def sources():
    out = [source_info(sid, d) for sid, d in indexed().items()]
    return sorted(out, key=lambda s: -s["indexed_at"])


@app.post("/api/sources")
def add_source(req: AddSource):
    path = req.path.strip().strip('"')
    if not is_remote(path) and not Path(path).is_dir():
        raise HTTPException(400, f"Folder not found: {path}")
    return jobs.public(jobs.index(path))


@app.post("/api/sources/{sid}/index")
def reindex(sid: str, rebuild: bool = False):
    d = indexed().get(sid)
    if not d:
        raise HTTPException(404, "Unknown source")
    return jobs.public(jobs.index(Index(d).base, rebuild=rebuild))


@app.delete("/api/sources/{sid}")
def remove_source(sid: str):
    """Forget a folder: deletes its index data only. The footage is never touched."""
    d = indexed().get(sid)
    if not d:
        raise HTTPException(404, "Unknown source")
    unregister(d)
    shutil.rmtree(Path(d) / INDEX_DIR, ignore_errors=True)
    if str(d).startswith(str(DATA_DIR)):
        shutil.rmtree(d, ignore_errors=True)
    return {"ok": True}


@app.get("/api/jobs")
def list_jobs():
    return sorted((jobs.public(j) for j in jobs.jobs.values()), key=lambda j: -j["created"])[:30]


@app.post("/api/jobs/{jid}/cancel")
def cancel_job(jid: str):
    job = jobs.jobs.get(jid)
    if not job:
        raise HTTPException(404, "Unknown job")
    job["cancel"].set()
    return jobs.public(job)


@app.post("/api/search")
def search(req: SearchReq):
    q = req.q.strip()
    if not q:
        return {"said": [], "shown": [], "ms": 0}
    t0 = time.time()
    want_said, want_shown = req.mode in ("said", "both"), req.mode in ("shown", "both")
    with engine.lock:
        speech, scenes = engine.searchers(req.sources, want_shown)
        sb = bases()
        said = [hit_dict(h, sb) for h in speech.find(q, req.top, req.min)] if want_said else []
        shown = [scene_dict(s, sb) for s in scenes.find(q, req.top)] if want_shown and scenes else []
    prefetch_previews([*said[:3], *shown[:2]])
    return {"said": said, "shown": shown, "ms": int((time.time() - t0) * 1000)}


_prefetch = {"gen": 0}


def prefetch_previews(results):
    """Encode previews of the top results in the background, so the first clicks play at once
    (each preview takes ~2-3 s to encode). A newer search stops the older prefetch."""
    from .previews import preview

    _prefetch["gen"] += 1
    gen = _prefetch["gen"]
    todo = [r for r in results if not r["remote"]]  # remote previews would download the whole clip

    def run():
        for r in todo:
            if _prefetch["gen"] != gen:
                return
            try:
                preview(r["location"], r["start"], r["end"])
            except Exception:
                pass  # the click will try again and show the error

    threading.Thread(target=run, daemon=True).start()


@app.post("/api/brief")
def brief(req: BriefReq):
    from .search import parse_brief, rows_to_items, visual_query

    items = rows_to_items([r.model_dump() for r in req.rows]) if req.rows else parse_brief(req.text)
    t0 = time.time()
    with engine.lock:
        speech, scenes = engine.searchers(req.sources, any(it["show"] for it in items))
        sb = bases()
        out = []
        for it in items:
            out.append({
                "label": it["label"], "row": it.get("row", it["label"]), "say": it["say"], "show": it["show"],
                "note": it.get("note", ""),
                "said": [hit_dict(h, sb) for h in speech.find(it["say"], req.top, req.min)] if it["say"] else [],
                "shown": [scene_dict(s, sb) for s in scenes.find(visual_query(it["show"]), req.top)]
                if it["show"] and scenes else [],
            })
    prefetch_previews([l["said"][0] for l in out if l["said"]][:4])  # the picked takes of the first lines
    return {"lines": out, "ms": int((time.time() - t0) * 1000)}


@app.post("/api/brief/ocr")
async def brief_ocr(file: UploadFile):
    """Screenshot of a brief table -> rows (read on this PC)."""
    from .ocr import read_brief_image

    data = await file.read()
    try:
        rows = await run_in_threadpool(read_brief_image, data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"rows": rows}


class TextReq(BaseModel):
    text: str


@app.post("/api/brief/rows-from-text")
def rows_from_text(req: TextReq):
    """Plain-text brief (one line per row, 'Visual:' notes) -> table rows."""
    from .search import items_to_rows, parse_brief

    return {"rows": items_to_rows(parse_brief(req.text))}


def _ns(d):
    """Result dict from the UI -> the attribute object roughcut.plan() reads."""
    return SimpleNamespace(location=d["location"], start=float(d["start"]), end=float(d["end"]),
                           text=d.get("text", ""), score=float(d.get("score", 0)),
                           peak=float(d.get("peak", d["start"])))


@app.post("/api/roughcut")
def roughcut(req: RoughcutReq):
    from .roughcut import build_roughcut

    if not req.lines:
        raise HTTPException(400, "The brief has no lines to build from.")
    if not Path(req.out_dir).is_absolute():
        raise HTTPException(400, "Choose a folder to save the rough cut in.")
    items = []
    for ln in req.lines:
        said = [_ns(d) for d in ln.said]
        shown = [_ns(d) for d in ln.shown]
        if ln.said_pick < 0:
            said = []
        elif 0 < ln.said_pick < len(said):
            said.insert(0, said.pop(ln.said_pick))  # the chosen take goes first
        it = {"label": ln.label, "say": ln.say, "show": ln.show, "note": ln.note, "said": said, "shown": shown}
        if ln.show_pick == -1:
            it["no_broll"] = True
        elif ln.show_pick is not None and 0 <= ln.show_pick < len(shown):
            it["show_pick"] = shown[ln.show_pick]
        items.append(it)
    safe = "".join(c for c in req.name if c not in '<>:"/\\|?*').strip() or "rough cut"
    out = Path(req.out_dir) / f"{safe}.xml"

    def run(job):
        log = lambda line: job["log"].append(str(line))
        path = build_roughcut(items, out, req.name, req.width, req.height, req.fps, log=log)
        return {"xml": str(path), "media": str(out.with_name(out.stem + " media"))}

    return jobs.public(jobs.run_now("roughcut", f"Build “{safe}”", run))


@app.post("/api/download")
def download(req: DownloadReq):
    locs = [l for l in dict.fromkeys(req.locations) if allowed(l)]

    def run(job):
        job["total"] = len(locs)
        paths = []
        for n, loc in enumerate(locs, 1):
            job["file"] = loc
            paths.append(str(fetch_to(loc, Path(req.dest))))
            job["n"] = n
        return {"paths": paths}

    return jobs.public(jobs.run_now("download", f"Download {len(locs)} clip(s)", run))


@app.get("/api/preview")
def preview(loc: str, start: float, end: float):
    from .previews import preview as make

    if not allowed(loc):
        raise HTTPException(403, "Not in an indexed folder")
    try:
        return FileResponse(make(loc, start, end), media_type="video/mp4")
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/thumb")
def thumb(loc: str, t: float, src: str | None = None, h: int = 360):
    from .indexer import VIDEO
    from .previews import still

    if not allowed(loc):
        raise HTTPException(403, "Not in an indexed folder")
    if Path(loc).suffix.lower() not in VIDEO:  # voiceovers and music: no picture (the card shows an audio tile)
        raise HTTPException(404, "Audio only")
    idx = None
    rel = None
    if src and src in indexed():
        idx = Index(indexed()[src])
        base = idx.base.rstrip("/\\")
        rel = loc[len(base):].lstrip("/\\")
    try:
        return FileResponse(still(loc, t, h, idx, rel), media_type="image/jpeg",
                            headers={"Cache-Control": "max-age=86400"})
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/reveal")
def reveal(req: RevealReq):
    p = Path(req.path)
    if not p.exists():
        raise HTTPException(404, "Not on this PC (download it first)")
    subprocess.Popen(f'explorer /select,"{p}"' if p.is_file() else f'explorer "{p}"')
    return {"ok": True}


@app.post("/api/pick-folder")
def pick_folder():
    """Native folder picker: the app window's own dialog, or a Windows dialog when used in a browser."""
    if WINDOW is not None:
        import webview

        kind = getattr(getattr(webview, "FileDialog", None), "FOLDER", None) or webview.FOLDER_DIALOG
        res = WINDOW.create_file_dialog(kind)
        return {"path": res[0] if res else None}
    import tkinter
    from tkinter import filedialog

    root = tkinter.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    path = filedialog.askdirectory()
    root.destroy()
    return {"path": path or None}


@app.get("/api/settings")
def get_settings():
    return load_settings() | {"auto_tier": tiers.detect(), "tiers": tiers.TIERS, "b2_key": key_status()}


@app.put("/api/settings")
def put_settings(req: SettingsReq):
    s = load_settings()
    if req.tier is not None:
        if req.tier not in ("auto", "low", "mid", "high"):
            raise HTTPException(400, "Unknown preset")
        s["tier"] = req.tier
    if req.b2_bucket is not None:
        s["b2_bucket"] = req.b2_bucket.strip().removeprefix("b2://").strip("/")
    save_settings(s)
    return s


# ---------------------------------------------------------------- Backblaze
def key_status():
    try:
        from .sources import load_keys

        kid, _ = load_keys()
        return {"set": True, "key_id_tail": kid[-4:]}
    except SystemExit:
        return {"set": False}


@app.put("/api/b2/key")
def put_key(req: KeyReq):
    KEYS_FILE.parent.mkdir(parents=True, exist_ok=True)
    KEYS_FILE.write_text(json.dumps({"key_id": req.key_id.strip(),
                                     "application_key": req.application_key.strip()}, indent=2),
                         encoding="utf-8")
    from .sources import B2Source

    B2Source._api = None  # log in again with the new key
    return key_status()


@app.get("/api/b2/ls")
def b2_ls(uri: str = ""):
    from .sources import B2Source

    if not uri:
        bucket = load_settings().get("b2_bucket", "").strip()
        if not bucket:
            raise HTTPException(400, "Set the Backblaze bucket name in Settings first.")
        uri = f"b2://{bucket}/"
    try:
        src = B2Source(uri)
        folders, files = src.ls()
    except SystemExit as e:
        raise HTTPException(400, str(e))
    return {"uri": src.uri, "folders": folders, "files": len(files)}


@app.middleware("http")
async def no_stale_ui(request, call_next):
    """WebView2 kept serving the old index.html (and its old assets) after an update, so the
    app looked unchanged. Hashed files under /assets/ can be cached; everything else re-checks."""
    response = await call_next(request)
    if not request.url.path.startswith(("/assets/", "/api/thumb")):
        response.headers["Cache-Control"] = "no-cache"
    return response


if STATIC.is_dir():
    app.mount("/", StaticFiles(directory=STATIC, html=True), name="ui")


def serve(port=PORT):
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
