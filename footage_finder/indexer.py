"""Index a footage source: transcribe speech (word-timed) and sample frames for visual search.

Each file is opened once for both passes, so a Backblaze file is downloaded only once.
"""
import gc
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from . import tiers
from .env import NO_WINDOW
from .sources import open_source
from .store import Index, register

VIDEO = {".mov", ".mp4", ".m4v", ".mxf", ".mkv", ".avi", ".mts", ".m2ts", ".webm"}


def load_audio(path: Path, sr=16000):
    """Decode any media file's audio to 16 kHz mono float32 with FFmpeg (what Whisper expects)."""
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-i", str(path), "-vn", "-ac", "1", "-ar", str(sr),
         "-f", "f32le", "-"],
        capture_output=True, **NO_WINDOW,
    )
    if out.returncode != 0 or not out.stdout:
        raise RuntimeError(out.stderr.decode(errors="replace").strip()[:300] or "no audio track")
    return np.frombuffer(out.stdout, np.float32)


def quiet_transformers():
    """Hide the 'Loading weights' bar (downloads still show progress)."""
    try:
        from transformers.utils import logging as tlog

        tlog.disable_progress_bar()
    except Exception:
        pass


def load_embedder(name: str, device: str):
    from sentence_transformers import SentenceTransformer

    quiet_transformers()
    return SentenceTransformer(name, device=device)


class Models:
    """Loads each model the first time it is needed and keeps it for the whole run."""

    def __init__(self, cfg, log):
        self.cfg, self.log = cfg, log
        self._whisper = self._embedder = self._vision = None

    def whisper(self):
        if self._whisper is None:
            from faster_whisper import WhisperModel

            self.log("Loading speech model (the first run downloads it)...")
            self._whisper = WhisperModel(self.cfg["whisper"], device=self.cfg["device"],
                                         compute_type=self.cfg["compute"])
        return self._whisper

    # The app's search already holds these models: share them. Indexing used to load second copies
    # (~3 GB of graphics memory), which pushed a 16 GB card into swapping and slowed everything down.
    def embedder(self):
        if self._embedder is None:
            from .search import embedder

            self._embedder = embedder(self.cfg["embed"])
        return self._embedder

    def vision(self):
        if self._vision is None:
            from .visual import vision_model

            self.log("Loading vision model (the first run downloads it)...")
            self._vision = vision_model(self.cfg["vision"])
        return self._vision


def transcribe(models, path, language):
    seg_iter, info = models.whisper().transcribe(
        load_audio(path),
        language=language,
        word_timestamps=True,
        vad_filter=True,
        # Off so repeated takes of the same line are not skipped as "already said".
        condition_on_previous_text=False,
        beam_size=5,
    )
    segments = []
    for s in seg_iter:
        text = s.text.strip()
        if text:
            words = [[round(w.start, 3), round(w.end, 3), w.word.strip()] for w in (s.words or [])]
            segments.append({"start": s.start, "end": s.end, "text": text, "words": words})
    embs = models.embedder().encode([s["text"] for s in segments], normalize_embeddings=True) if segments else []
    return info.duration, segments, embs


class Cancelled(Exception):
    pass


def index_folder(spec, tier: str = "auto", language=None, rebuild=False, visual=True, log=print,
                 progress=None, cancel=None):
    """progress(dict) gets {"n", "total", "file"} per file; cancel is a threading.Event checked
    between files (finished files stay indexed, so a later run picks up where this one stopped)."""
    progress = progress or (lambda info: None)
    src = open_source(spec)
    tier = tiers.resolve(tier)
    cfg = tiers.TIERS[tier]
    idx = Index(src.index_dir)

    # One index = one set of models, so search compares like with like.
    prev = idx.get_meta("whisper"), idx.get_meta("embed"), idx.get_meta("vision")
    if prev != (None, None, None) and prev != (cfg["whisper"], cfg["embed"], cfg["vision"]) and not rebuild:
        raise SystemExit(
            f"This folder was indexed with the '{idx.get_meta('tier')}' preset. "
            f"Use --tier {idx.get_meta('tier')} to update it, or --rebuild to redo it with '{tier}'."
        )
    if rebuild:
        idx.clear()
    for k, v in (("source", src.uri), ("tier", tier), ("whisper", cfg["whisper"]), ("embed", cfg["embed"]),
                 ("vision", cfg["vision"]), ("vision_fps", str(cfg["fps"]))):
        idx.set_meta(k, v)
    if hasattr(src, "title"):  # Iconik collections are ids; keep the human name for the Library
        idx.set_meta("title", src.title())

    log(f"Source: {src.uri}")
    log(f"Preset: {tier}  ({cfg['whisper']} on {cfg['device']})")
    listing = {rel: (size, mtime) for rel, size, mtime in src.list()}
    speech_state, vis_state = idx.file_state(), idx.vfile_state()
    for rel in set(speech_state) - set(listing):
        idx.remove_file(rel)
    for rel in set(vis_state) - set(listing):
        idx.remove_vfile(rel)

    need_speech = {r for r, st in listing.items() if speech_state.get(r) != st}
    # Files indexed before thumbnails were stored for every folder get their frames redone once.
    need_visual = {r for r, st in listing.items()
                   if visual and Path(r).suffix.lower() in VIDEO and (vis_state.get(r) != st or not idx.has_thumbs(r))}
    todo = sorted(need_speech | need_visual)
    gb = sum(listing[r][0] for r in todo) / 1e9
    log(f"{len(listing)} media files, {len(todo)} new or changed"
        + (f" ({gb:.1f} GB to download, one at a time; temp copies are deleted)" if src.remote and todo else "")
        + ".")
    if not todo:
        register(src.index_dir)
        return idx.stats()

    from .visual import embed_file

    models = Models(cfg, log)
    if need_visual:
        models.vision()  # load before the worker thread uses it
    # The visual pass of a file (video decoder + image model) runs while its speech pass (Whisper) does:
    # they mostly use different parts of the GPU, so a file takes about as long as the slower pass.
    pool = ThreadPoolExecutor(max_workers=1)
    t0 = time.time()
    progress({"n": 0, "total": len(todo), "file": todo[0]})
    try:
        for n, (rel, path) in enumerate(src.iter_local(todo), 1):
            if cancel is not None and cancel.is_set():
                log(f"Stopped after {n - 1} of {len(todo)} files.")
                register(src.index_dir)
                raise Cancelled()
            progress({"n": n - 1, "total": len(todo), "file": rel})
            size, mtime = listing[rel]
            notes = []
            if isinstance(path, Exception):  # download failed; try again next run
                log(f"  [{n}/{len(todo)}] {rel}  download failed: {str(path)[:120]}")
                continue
            vis_job = pool.submit(embed_file, models.vision(), path, cfg["fps"], True) if rel in need_visual else None
            if rel in need_speech:
                try:
                    duration, segments, embs = transcribe(models, path, language)
                    idx.put_file(rel, size, mtime, duration, segments, embs)
                    notes.append(f"{duration:.0f}s, {len(segments)} lines")
                except Exception as e:  # e.g. a video with no audio track
                    idx.put_file(rel, size, mtime, 0, [], [], error=str(e)[:300])
                    notes.append("no speech/audio")
            if vis_job is not None:
                try:
                    # Small JPGs of the sampled frames: result cards show these instead of running ffmpeg per card.
                    times, embs, thumbs = vis_job.result()
                    idx.put_vfile(rel, size, mtime, times, embs)
                    if thumbs:
                        idx.put_thumbs(rel, times, thumbs)
                    notes.append(f"{len(times)} frames")
                except Exception as e:
                    idx.put_vfile(rel, size, mtime, [], [], error=str(e)[:300])
                    notes.append(f"no frames: {str(e)[:80]}")
            log(f"  [{n}/{len(todo)}] {rel}  " + ", ".join(notes))
            progress({"n": n, "total": len(todo), "file": rel})
    finally:
        pool.shutdown(wait=False)
    log(f"Done in {time.time() - t0:.0f}s.")
    del models
    gc.collect()
    register(src.index_dir)
    return idx.stats()
