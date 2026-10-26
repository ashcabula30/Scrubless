"""Visual scene search: sample frames with FFmpeg, embed with SigLIP 2, match plain-English descriptions."""
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .env import NO_WINDOW

VIDEO = {".mov", ".mp4", ".m4v", ".mxf", ".mkv", ".avi", ".mts", ".m2ts", ".webm"}


def _tensor(out):
    """transformers 5 returns a model output object here; older versions return the tensor."""
    return out if hasattr(out, "norm") else out.pooler_output


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

    def embed_images(self, frames):
        """frames: uint8 array (n, side, side, 3) -> normalized (n, d)."""
        torch = self.torch
        out = []
        with torch.no_grad():
            for i in range(0, len(frames), 32):
                inp = self.proc(images=list(frames[i:i + 32]), return_tensors="pt").to(self.device)
                inp["pixel_values"] = inp["pixel_values"].to(self.dtype)
                f = _tensor(self.model.get_image_features(**inp))
                out.append((f / f.norm(dim=-1, keepdim=True)).float().cpu().numpy())
        return np.concatenate(out) if out else np.zeros((0, 1), dtype=np.float32)

    def embed_text(self, text: str):
        torch = self.torch
        inp = self.proc(text=[text.lower()], padding="max_length", max_length=64,
                        return_tensors="pt").to(self.device)
        with torch.no_grad():
            f = _tensor(self.model.get_text_features(**inp))
        return (f / f.norm(dim=-1, keepdim=True))[0].float().cpu().numpy()

    def prob(self, cos):
        """SigLIP's calibrated 'does this text describe this image' probability."""
        scale = self.model.logit_scale.exp().item()
        bias = self.model.logit_bias.item()
        return 1 / (1 + np.exp(-(np.asarray(cos) * scale + bias)))


def iter_frames(path: Path, fps: float, side: int, chunk=64):
    """Yield (times, frames) chunks, decoded and squashed to side x side by FFmpeg."""
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-i", str(path), "-an",
           "-vf", f"fps={fps},scale={side}:{side}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
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
    times, embs, thumbs = [], [], []
    for t, frames in iter_frames(path, fps, vis.side):
        times.extend(t)
        embs.append(vis.embed_images(frames))
        if keep_thumbs:
            for f in frames:
                buf = io.BytesIO()
                Image.fromarray(f).resize((max(1, round(thumb_h * aspect)), thumb_h)).save(buf, "JPEG", quality=72)
                thumbs.append(buf.getvalue())
    return times, np.concatenate(embs), thumbs


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
                self.parts.append((idx, idx.get_meta("vision"), float(idx.get_meta("vision_fps") or 1),
                                   frames, embs))

    def _vision(self, model_id):
        return vision_model(model_id)

    def find(self, query: str, top=10, spread=0.02):
        scenes = []
        for idx, model_id, fps, frames, embs in self.parts:
            vis = self._vision(model_id)
            sims = embs @ vis.embed_text(query)
            # Group each file's frames into contiguous runs around its best-matching moments.
            by_file = {}
            for i, (rel, _) in enumerate(frames):
                by_file.setdefault(rel, []).append(i)
            for rel, ids in by_file.items():
                s = sims[ids]
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


def save_thumb(path: Path, t: float, out: Path, height=360):
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-ss", f"{t:.2f}", "-i", str(path),
                    "-frames:v", "1", "-vf", f"scale=-2:{height}", str(out)], check=True, **NO_WINDOW)
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
