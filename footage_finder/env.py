"""Environment setup: data locations and CUDA DLLs on Windows."""
import os
import site
import sys
from pathlib import Path

# Internal NTFS SSD. Not E: (external exFAT: no journaling, may be unplugged) and not C: (nearly full).
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
