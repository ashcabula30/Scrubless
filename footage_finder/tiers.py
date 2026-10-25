"""Hardware presets. Same features on every tier; heavier models on stronger machines."""

TIERS = {
    "low": {
        "whisper": "small",
        "device": "cpu",
        "compute": "int8",
        "embed": "BAAI/bge-small-en-v1.5",
        "vision": "google/siglip2-base-patch16-224",
        "fps": 0.5,
    },
    "mid": {
        "whisper": "large-v3-turbo",
        "device": "cuda",
        "compute": "int8_float16",
        "embed": "BAAI/bge-base-en-v1.5",
        "vision": "google/siglip2-base-patch16-224",
        "fps": 1,
    },
    "high": {
        "whisper": "large-v3",
        "device": "cuda",
        "compute": "float16",
        "embed": "BAAI/bge-large-en-v1.5",
        "vision": "google/siglip2-so400m-patch14-384",
        "fps": 2,
    },
}


def gpu_info():
    """Return (name, vram_gb) for the first CUDA GPU, or None."""
    try:
        import torch

        if torch.cuda.is_available():
            p = torch.cuda.get_device_properties(0)
            return p.name, p.total_memory / 2**30
    except Exception:
        pass
    return None


def detect() -> str:
    gpu = gpu_info()
    if gpu is None:
        return "low"
    return "high" if gpu[1] >= 12 else "mid" if gpu[1] >= 6 else "low"


def resolve(name: str) -> str:
    return detect() if name == "auto" else name
