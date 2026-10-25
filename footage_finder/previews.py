"""Small playable previews and still frames for the app.

iPhone footage is usually HEVC, which the app window (Edge WebView2) can't play without the paid
HEVC extension, so a match is cut into a short H.264 clip with the GPU encoder (CPU fallback).
Everything is cached under DATA_DIR, keyed by file + time range.
"""
import hashlib
import subprocess
from pathlib import Path

from .env import DATA_DIR
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
    return fetch_to(location, REMOTE_CACHE) if is_remote(location) else Path(location)


def _encode(src: Path, start: float, length: float, out: Path, codec: str) -> bool:
    venc = ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "27"] if codec == "nvenc" \
        else ["-c:v", "libx264", "-preset", "veryfast", "-crf", "26"]
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-y", "-ss", f"{start:.3f}", "-i", str(src),
           "-t", f"{length:.3f}", "-vf", SCALE, *venc, "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-movflags", "+faststart", str(out)]
    return subprocess.run(cmd, capture_output=True).returncode == 0 and out.exists() and out.stat().st_size > 0


def preview(location: str, start: float, end: float) -> Path:
    """H.264 preview of start..end with a little lead-in and tail."""
    global _nvenc_ok
    a = max(0.0, start - LEAD)
    length = min(MAX_LEN, max(1.0, end + TAIL - a))
    out = PREVIEWS / f"{_key(location, round(a, 2), round(length, 2))}.mp4"
    if out.exists():
        return out
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


def still(location: str, t: float, height=360, index=None, rel=None) -> Path:
    """One frame as JPG. Backblaze files use frames stored at index time when there are any."""
    if is_remote(location) and index is not None and rel is not None:
        stored = index.thumb(rel, t)
        if stored is not None:
            return stored
    out = STILLS / f"{_key(location, round(t, 1), height)}.jpg"
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    src = local_path(location)
    subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-ss", f"{max(0.0, t):.2f}", "-i", str(src),
                    "-frames:v", "1", "-vf", f"scale=-2:{height}", "-q:v", "4", str(out)], check=True)
    return out
