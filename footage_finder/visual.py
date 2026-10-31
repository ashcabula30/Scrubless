"""Visual scene search: sample frames with FFmpeg, embed with SigLIP 2, match plain-English descriptions."""
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import env
from .env import NO_WINDOW

VIDEO = {".mov", ".mp4", ".m4v", ".mxf", ".mkv", ".avi", ".mts", ".m2ts", ".webm"}


def _tensor(out):
    """transformers 5 returns a model output object here; older versions return the tensor."""
    return out if hasattr(out, "norm") else out.pooler_output


_VISION_QUERY_CACHE = {}


class Vision:
    def __init__(self, model_id: str, device: str):
        import torch
        from transformers import AutoModel, AutoProcessor

        from .indexer import quiet_transformers

        quiet_transformers()
        self.torch = torch
        self.device = device
        self.dtype = torch.float16 if device == "cuda" else torch.float32
        self.model = AutoModel.from_pretrained(model_id, dtype=self.dtype).to(device).eval()
        self.proc = AutoProcessor.from_pretrained(model_id)
        size = self.proc.image_processor.size
        self.side = size.get("height") or size.get("shortest_edge") or 224
        self._scale = float(self.model.logit_scale.exp().item())
        self._bias = float(self.model.logit_bias.item())

    def embed_images(self, frames):
        """frames: uint8 array (n, side, side, 3) -> normalized (n, d)."""
        torch = self.torch
        out = []
        ip = self.proc.image_processor
        mean = torch.tensor(ip.image_mean, device=self.device, dtype=self.dtype).view(1, 3, 1, 1)
        std = torch.tensor(ip.image_std, device=self.device, dtype=self.dtype).view(1, 3, 1, 1)
        with torch.no_grad():
            for i in range(0, len(frames), 64):
                # Frames arrive already side x side, so only rescale + normalize remain: done on the GPU
                # (the processor did it on the CPU image by image, which capped indexing at ~50 frames/s).
                x = torch.from_numpy(np.ascontiguousarray(frames[i:i + 64])).to(self.device).permute(0, 3, 1, 2)
                x = (x.to(self.dtype) * ip.rescale_factor - mean) / std
                f = _tensor(self.model.get_image_features(pixel_values=x))
                out.append((f / f.norm(dim=-1, keepdim=True)).float().cpu().numpy())
        return np.concatenate(out) if out else np.zeros((0, 1), dtype=np.float32)

    def embed_text(self, text: str):
        key = text.lower().strip()
        if key not in _VISION_QUERY_CACHE:
            if len(_VISION_QUERY_CACHE) > 1024:
                _VISION_QUERY_CACHE.clear()
            torch = self.torch
            inp = self.proc(text=[key], padding="max_length", max_length=64,
                            return_tensors="pt").to(self.device)
            with torch.no_grad():
                f = _tensor(self.model.get_text_features(**inp))
            _VISION_QUERY_CACHE[key] = (f / f.norm(dim=-1, keepdim=True))[0].float().cpu().numpy()
        return _VISION_QUERY_CACHE[key]

    def embed_texts(self, texts: list[str]):
        if not texts:
            return np.zeros((0, self.model.config.text_config.hidden_size), dtype=np.float32)
        uncached = [t.lower().strip() for t in texts if t.lower().strip() not in _VISION_QUERY_CACHE]
        if uncached:
            torch = self.torch
            inp = self.proc(text=uncached, padding="max_length", max_length=64,
                            return_tensors="pt").to(self.device)
            with torch.no_grad():
                f = _tensor(self.model.get_text_features(**inp))
            computed = (f / f.norm(dim=-1, keepdim=True)).float().cpu().numpy()
            if len(_VISION_QUERY_CACHE) + len(uncached) > 1024:
                _VISION_QUERY_CACHE.clear()
            for t, emb in zip(uncached, computed):
                _VISION_QUERY_CACHE[t] = emb
        return np.stack([_VISION_QUERY_CACHE[t.lower().strip()] for t in texts])

    def prob(self, cos):
        """SigLIP's calibrated 'does this text describe this image' probability."""
        return 1.0 / (1.0 + np.exp(-(np.asarray(cos) * self._scale + self._bias)))


def keyframe_times(path: Path):
    """Keyframe times from the container's packet list (no decoding, well under a second)."""
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts_time,flags",
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True, **NO_WINDOW)
    t = sorted(float(a) for a, _, f in (ln.partition(",") for ln in r.stdout.split()) if f.startswith("K") and a not in ("", "N/A"))
    return [x - t[0] for x in t] if t else []


def sample_plan(path: Path, fps: float):
    """Decode only keyframes when they fall about as often as we sample (phone footage: ~1 per
    second). Decoding every frame of 4K HEVC just to keep 2 a second was 6x slower.
    Returns (keyframe times, keep mask), or None to decode every frame and sample at fps."""
    kf = keyframe_times(path)
    if len(kf) < 2:
        return None
    gaps = np.diff(kf)
    if np.median(gaps) > max(1.5, 1.5 / fps) or np.median(gaps) < 0.4 / fps:
        return None  # sparse keyframes (screen recordings) or all-intra codecs: the fps path is as cheap
    keep, last = [], -1e9
    for t in kf:
        keep.append(t - last >= 0.8 / fps)
        if keep[-1]:
            last = t
    return kf, np.array(keep)


def iter_frames(path: Path, fps: float, side: int, chunk=64, hw=False, plan=None):
    """Yield (times, frames) chunks, decoded (and resized, on the GPU if hw) to side x side by FFmpeg.
    plan: from sample_plan(), to decode keyframes only."""
    pre = ["-skip_frame", "nokey"] if plan else []
    if hw:
        pre += ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
        size = f"scale_cuda={side}:{side}:format=nv12,hwdownload,format=nv12"
    else:
        size = f"scale={side}:{side}"
    vf = size if plan else f"fps={fps},{size}"
    cmd = ["ffmpeg", "-v", "error", "-nostdin", *pre, "-i", str(path), "-an", "-vf", vf,
           *(["-fps_mode", "passthrough"] if plan else []), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    frame_bytes = side * side * 3
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **NO_WINDOW)
    n = 0
    try:
        while True:
            buf = proc.stdout.read(frame_bytes * chunk)
            k = len(buf) // frame_bytes
            if k == 0:
                break
            frames = np.frombuffer(buf[:k * frame_bytes], np.uint8).reshape(k, side, side, 3)
            if plan:
                kf, keep = plan
                k = min(k, len(kf) - n)  # never more frames than keyframes listed
                if k <= 0:
                    break
                m = keep[n:n + k]
                yield np.asarray(kf[n:n + k])[m], frames[:k][m]
            else:
                yield np.arange(n, n + k) / fps, frames
            n += k
    finally:
        proc.stdout.close()
        err = proc.stderr.read().decode(errors="replace")
        proc.wait()
    if n == 0:
        raise RuntimeError(err.strip()[:300] or "no video frames")


def display_aspect(path: Path) -> float:
    """Width / height as the video plays (phone footage is often rotated by metadata)."""
    from .roughcut import probe

    info = probe(path)
    return info["width"] / info["height"] if info["width"] and info["height"] else 9 / 16


def embed_file(vis, path: Path, fps: float, keep_thumbs=False, thumb_h=240):
    """Sample frames, embed them; optionally return small JPGs (aspect restored) for contact sheets."""
    import io

    from PIL import Image

    aspect = display_aspect(path) if keep_thumbs else None

    plan = sample_plan(path, fps)

    def run(hw):
        times, embs, thumbs = [], [], []
        for t, frames in iter_frames(path, fps, vis.side, hw=hw, plan=plan):
            if not len(frames):
                continue
            times.extend(t)
            embs.append(vis.embed_images(frames))
            if keep_thumbs:
                for f in frames:
                    buf = io.BytesIO()
                    Image.fromarray(f).resize((max(1, round(thumb_h * aspect)), thumb_h)).save(buf, "JPEG", quality=72)
                    thumbs.append(buf.getvalue())
        return times, np.concatenate(embs), thumbs

    if env.hwdec_ok is not False:
        try:
            out = run(hw=True)
            env.hwdec_ok = True
            return out
        except RuntimeError:  # no frames on the GPU path: retry on the CPU below
            pass
    out = run(hw=False)
    if env.hwdec_ok is None:
        env.hwdec_ok = False
    return out


_VISION = {}  # shared by every SceneSearcher, so the app loads each model once


def vision_model(model_id):
    if model_id not in _VISION:
        from . import tiers

        _VISION[model_id] = Vision(model_id, "cuda" if tiers.gpu_info() else "cpu")
    return _VISION[model_id]


@dataclass
class Scene:
    base: str  # folder path or b2:// URI the index was built from
    file: str
    start: float
    end: float
    peak: float  # time of the best-matching frame
    score: float
    index: object = None  # the Index, for stored thumbnails

    @property
    def location(self) -> str:
        from .sources import join

        return join(self.base, self.file)


class SceneSearcher:
    def __init__(self, folders):
        from .store import Index

        self.parts = []
        for f in folders:
            idx = Index(f)
            frames, embs = idx.load_frames()
            if frames:
                # load_frames sorts by file then time, so each file is one contiguous slice: find them once.
                bounds = [0] + [i for i in range(1, len(frames)) if frames[i][0] != frames[i - 1][0]] + [len(frames)]
                files = [(frames[a][0], a, b) for a, b in zip(bounds, bounds[1:])]
                self.parts.append((idx, idx.get_meta("vision"), float(idx.get_meta("vision_fps") or 1),
                                   frames, embs, files))

    def _vision(self, model_id):
        return vision_model(model_id)

    def find(self, query: str, top=10, spread=0.02, q_emb_cached=None):
        if not query.strip():
            return []
        scenes = []
        q_emb = q_emb_cached if q_emb_cached is not None else {}
        for idx, model_id, fps, frames, embs, files in self.parts:
            vis = self._vision(model_id)
            if model_id not in q_emb:
                q_emb[model_id] = vis.embed_text(query)
            sims = embs @ q_emb[model_id]
            # Group each file's frames into contiguous runs around its best-matching moments.
            for rel, a, b in files:
                s = sims[a:b]
                if len(s) == 0 or np.max(s) < 0.05:
                    continue
                ids = range(a, b)
                taken = np.zeros(len(ids), bool)
                for _ in range(3):  # up to 3 separate moments per file
                    cand = np.where(taken, -np.inf, s)
                    p = int(np.argmax(cand))
                    if not np.isfinite(cand[p]):
                        break
                    lo = hi = p
                    while lo > 0 and not taken[lo - 1] and s[lo - 1] >= s[p] - spread:
                        lo -= 1
                    while hi < len(ids) - 1 and not taken[hi + 1] and s[hi + 1] >= s[p] - spread:
                        hi += 1
                    taken[max(0, lo - 1):hi + 2] = True
                    t = [frames[ids[k]][1] for k in (lo, p, hi)]
                    scenes.append(Scene(idx.base, rel, t[0], t[2] + 1 / fps, t[1], float(vis.prob(s[p])), idx))
        scenes.sort(key=lambda sc: -sc.score)
        return scenes[:top]

    def find_batch(self, queries: list[str], top=10, spread=0.02):
        """Batch search multiple visual queries in a single SigLIP text forward pass."""
        if not queries:
            return []
        q_embs_by_model = {}
        for idx, model_id, fps, frames, embs, files in self.parts:
            if model_id not in q_embs_by_model:
                vis = self._vision(model_id)
                q_embs_by_model[model_id] = vis.embed_texts(queries)

        results = []
        for idx, q in enumerate(queries):
            if not q.strip():
                results.append([])
                continue
            q_emb = {m: arr[idx] for m, arr in q_embs_by_model.items()}
            results.append(self.find(q, top, spread, q_emb_cached=q_emb))
        return results


def save_thumb(path: Path, t: float, out: Path, height=360):
    out.parent.mkdir(parents=True, exist_ok=True)
    env.ffmpeg(["-v", "error", "-nostdin", "-y", "-ss", f"{t:.2f}", "-i", str(path),
                "-frames:v", "1", "-vf", f"scale=-2:{height}", str(out)], capture_output=True).check_returncode()
    return out


def contact_sheet(items, out: Path, cols=5, height=360):
    """items: list of (label, image_path). Writes one JPG grid with captions."""
    from PIL import Image, ImageDraw

    imgs = [(label, Image.open(p).convert("RGB")) for label, p in items]
    if not imgs:
        return None
    imgs = [(label, im if im.height == height else im.resize((round(im.width * height / im.height), height)))
            for label, im in imgs]
    w = max(220, max(im.width for _, im in imgs)) + 8  # wide enough for the caption, with a gap
    cap = 36
    cols = min(cols, len(imgs))
    rows = (len(imgs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * w, rows * (height + cap)), "white")
    draw = ImageDraw.Draw(sheet)
    for i, (label, im) in enumerate(imgs):
        x, y = (i % cols) * w, (i // cols) * (height + cap)
        sheet.paste(im, (x + (w - im.width) // 2, y))
        # "3. B-roll/IMG_1.MOV @ 00:00:02.0" -> file on one line, time on the next
        name, _, at = label.rpartition(" @ ")
        for k, line in enumerate((name, "@ " + at) if name else (label,)):
            draw.text((x + 6, y + height + 4 + 14 * k), line[-34:], fill="black")
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, quality=88)
    return out
