"""Small playable previews and still frames for the app.

iPhone footage is usually HEVC, which the app window (Edge WebView2) can't play without the paid
HEVC extension, so a match is cut into a short H.264 clip with the GPU encoder (CPU fallback).
Everything is cached under DATA_DIR, keyed by file + time range.
"""
import hashlib
import threading
from pathlib import Path

from .env import DATA_DIR, ffmpeg
from .sources import fetch_to, is_remote

PREVIEWS = DATA_DIR / "previews"
STILLS = DATA_DIR / "stills"
REMOTE_CACHE = DATA_DIR / "remote-cache"  # Backblaze clips downloaded for previews
LEAD, TAIL, MAX_LEN = 1.0, 1.0, 20.0
# Fit inside 960 px on the long side, keep aspect, even dimensions.
SCALE = "scale='if(gt(iw,ih),min(960,iw),-2)':'if(gt(iw,ih),-2,min(960,ih))'"

_nvenc_ok = None


def _key(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:20]


def local_path(location: str) -> Path:
    """A local copy of the media: the file itself, or a cached Backblaze download."""
    return fetch_to(location, REMOTE_CACHE, original=False) if is_remote(location) else Path(location)


def _encode(src: Path, start: float, length: float, out: Path, codec: str) -> bool:
    venc = ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "27"] if codec == "nvenc" \
        else ["-c:v", "libx264", "-preset", "veryfast", "-crf", "26"]
    args = ["-v", "error", "-nostdin", "-y", "-ss", f"{start:.3f}", "-i", str(src),
            "-t", f"{length:.3f}", "-vf", SCALE, *venc, "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-movflags", "+faststart", str(out)]
    return ffmpeg(args, capture_output=True).returncode == 0 and out.exists() and out.stat().st_size > 0


_locks = {}  # one lock per preview file: the background prefetch and a click can ask for the same one
_locks_guard = threading.Lock()


def preview(location: str, start: float, end: float) -> Path:
    """H.264 preview of start..end with a little lead-in and tail."""
    a = max(0.0, start - LEAD)
    length = min(MAX_LEN, max(1.0, end + TAIL - a))
    out = PREVIEWS / f"{_key(location, round(a, 2), round(length, 2))}.mp4"
    if out.exists():
        return out
    with _locks_guard:
        lock = _locks.setdefault(out.name, threading.Lock())
    with lock:
        if out.exists():  # made by whoever held the lock
            return out
        return _make_preview(location, a, length, out)


def _make_preview(location, a, length, out):
    global _nvenc_ok
    out.parent.mkdir(parents=True, exist_ok=True)
    src = local_path(location)
    tmp = out.with_suffix(".part.mp4")
    if _nvenc_ok is not False and _encode(src, a, length, tmp, "nvenc"):
        _nvenc_ok = True
    else:
        _nvenc_ok = False if _nvenc_ok is None else _nvenc_ok
        if not _encode(src, a, length, tmp, "x264"):
            raise RuntimeError(f"Couldn't make a preview of {location}")
    tmp.replace(out)
    return out


_still_locks = {}
_still_locks_guard = threading.Lock()


def still(location: str, t: float, height=360, index=None, rel=None) -> Path:
    """One frame as JPG: the nearest frame stored at index time, else extracted with ffmpeg."""
    if index is not None and rel is not None:
        stored = index.thumb(rel, t)
        if stored is not None:
            return stored
    key = _key(location, round(t, 1), height)
    out = STILLS / f"{key}.jpg"
    if out.exists() and out.stat().st_size > 0:
        return out
    with _still_locks_guard:
        lock = _still_locks.setdefault(key, threading.Lock())
    with lock:
        if out.exists() and out.stat().st_size > 0:
            return out
        out.parent.mkdir(parents=True, exist_ok=True)
        src = local_path(location)
        tmp = out.with_suffix(f".part_{threading.get_ident()}.jpg")
        try:
            ffmpeg(["-v", "error", "-nostdin", "-y", "-ss", f"{max(0.0, t):.2f}", "-i", str(src),
                    "-frames:v", "1", "-vf", f"scale=-2:{height}", "-q:v", "4", str(tmp)],
                   capture_output=True).check_returncode()
            if tmp.exists() and tmp.stat().st_size > 0:
                tmp.replace(out)
        finally:
            tmp.unlink(missing_ok=True)
        return out
