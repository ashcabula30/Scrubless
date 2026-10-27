"""Environment setup: data locations and CUDA DLLs on Windows."""
import os
import site
import sys
from pathlib import Path

# Internal NTFS SSD. Not E: (external exFAT: no journaling, may be unplugged) and not C: (nearly full).
# Pass to subprocess calls: without it, each ffmpeg/ffprobe started from the windowless app flashes a console.
NO_WINDOW = {"creationflags": 0x08000000} if sys.platform == "win32" else {}  # CREATE_NO_WINDOW

# Decode video on the NVIDIA GPU (NVDEC). CPU decoding of 4K HEVC iPhone clips cost ~30 s of CPU per
# 4 s preview; GPU decoding cut that to ~8 s. None = not tried yet, False = this PC can't.
HWDEC = ["-hwaccel", "cuda"]
hwdec_ok = None


def ffmpeg(args, **kw):
    """Run ffmpeg (args = everything after "ffmpeg") with GPU decoding, falling back to the CPU."""
    import subprocess

    global hwdec_ok
    if hwdec_ok is not False:
        r = subprocess.run(["ffmpeg", *HWDEC, *args], **NO_WINDOW, **kw)
        if r.returncode == 0:
            hwdec_ok = True
            return r
    r = subprocess.run(["ffmpeg", *args], **NO_WINDOW, **kw)
    if r.returncode == 0 and hwdec_ok is None:
        hwdec_ok = False  # the CPU managed what the GPU couldn't on the first try: no NVDEC here
    return r

DATA_DIR = Path(os.environ.get("FF_DATA", r"D:\footage-finder-data"))


def setup() -> None:
    # Models live on the data drive, not in the user profile on C.
    os.environ.setdefault("HF_HOME", str(DATA_DIR / "models"))
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    # Library chatter (token hints, config notes) hides the results; keep real errors only.
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
    os.environ.setdefault("HF_HUB_VERBOSITY", "error")
    import logging
    import warnings

    warnings.filterwarnings("ignore")
    logging.getLogger("torch.distributed.elastic.multiprocessing.redirects").setLevel(logging.ERROR)
    if sys.platform == "win32":
        # faster-whisper (CTranslate2) needs cuBLAS/cuDNN DLLs from the nvidia-* wheels.
        for sp in site.getsitepackages():
            for lib in ("cublas", "cudnn"):
                d = Path(sp) / "nvidia" / lib / "bin"
                if d.is_dir():
                    os.add_dll_directory(str(d))
                    os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
