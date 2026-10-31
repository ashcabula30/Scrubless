"""Where footage lives: a local folder, or a folder (prefix) in a Backblaze B2 bucket.

Both give the indexer the same three things: a file listing with size + modified time,
a way to get each file onto local disk (a temporary download for B2), and a location
string for results. Remote indexes live under DATA_DIR/remote, since the bucket is read-only.
"""
import hashlib
import json
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .env import DATA_DIR
from .store import INDEX_DIR

MEDIA = {".mov", ".mp4", ".m4v", ".mxf", ".mkv", ".avi", ".mts", ".m2ts", ".webm",
         ".wav", ".mp3", ".m4a", ".aac", ".flac"}
KEYS_FILE = DATA_DIR / "backblaze.json"


REMOTE = ("b2://", "iconik://")

# Folders that hold finished edits or app caches, not footage: their clips would show up as matches
# for every line of the brief they were cut from.
SKIP_DIRS = {"exports", "export", "finals", "final", "renders", "render", "outputs", "output", "previews",
             "rough cuts", "adobe premiere pro auto-save", "adobe premiere pro video previews",
             "adobe premiere pro audio previews", "adobe premiere pro preview files", "scrubless rough cuts"}


def skipped(rel: str) -> bool:
    """True when a file sits under an exports/renders/previews folder (any depth)."""
    parts = rel.replace("\\", "/").split("/")[:-1]
    return any(p.strip().lower() in SKIP_DIRS or p.strip().lower().endswith(" - air update") for p in parts)


def join(base: str, rel: str) -> str:
    """Full location of a file: a local path, or a b2:// / iconik:// URI."""
    if base.startswith(REMOTE):
        return base.rstrip("/") + "/" + rel.replace("\\", "/")
    return str(Path(base) / rel)


def is_remote(location: str) -> bool:
    return str(location).startswith(REMOTE)


class LocalSource:
    remote = False

    def __init__(self, folder):
        self.folder = Path(folder).resolve()
        self.uri = str(self.folder)
        # Older indexes live inside the footage folder; new ones go on D so nothing extra lands in
        # synced folders (C:\SynologyDrive would push index files to the NAS and every teammate).
        if (self.folder / INDEX_DIR / "index.db").is_file():
            self.index_dir = self.folder
        else:
            key = hashlib.sha1(self.uri.lower().encode()).hexdigest()[:16]
            self.index_dir = DATA_DIR / "indexes" / f"{self.folder.name[:40]}-{key}"

    def list(self):
        for p in sorted(self.folder.rglob("*")):
            try:
                if p.is_file() and p.suffix.lower() in MEDIA and INDEX_DIR not in p.parts:
                    rel = str(p.relative_to(self.folder))
                    if not skipped(rel):
                        st = p.stat()
                        yield rel, st.st_size, st.st_mtime
            except (OSError, PermissionError, FileNotFoundError):
                continue

    def iter_local(self, rels):
        for rel in rels:
            yield rel, self.folder / rel


def load_keys():
    """Read-only B2 key: env vars B2_APPLICATION_KEY_ID / B2_APPLICATION_KEY, or backblaze.json."""
    kid, key = os.environ.get("B2_APPLICATION_KEY_ID"), os.environ.get("B2_APPLICATION_KEY")
    if not (kid and key):
        try:
            data = json.loads(KEYS_FILE.read_text(encoding="utf-8"))
            kid, key = data.get("key_id", "").strip(), data.get("application_key", "").strip()
        except (FileNotFoundError, ValueError):
            pass
    if not (kid and key):
        raise SystemExit(
            f"No Backblaze key yet. Open {KEYS_FILE} and paste a read-only key_id and application_key "
            "(see README: Backblaze)."
        )
    return kid, key


class _Remote:
    """Shared by cloud sources: index through temporary downloads (subclasses provide download())."""

    remote = True

    def iter_local(self, rels):
        """Yield (rel, temp path), downloading the next file while the current one is processed.

        Each temp copy is deleted as soon as the caller moves on.
        """
        tmp = DATA_DIR / "tmp"
        tmp.mkdir(parents=True, exist_ok=True)

        def fetch(rel):
            name = hashlib.sha1(rel.encode()).hexdigest()[:16] + Path(rel).suffix
            return self.download(rel, tmp / name)

        rels = list(rels)
        with ThreadPoolExecutor(max_workers=1) as pool:
            nxt = pool.submit(fetch, rels[0]) if rels else None
            for i, rel in enumerate(rels):
                fut = nxt
                nxt = pool.submit(fetch, rels[i + 1]) if i + 1 < len(rels) else None
                try:
                    path = fut.result()
                except Exception as e:
                    yield rel, e
                    continue
                try:
                    yield rel, path
                finally:
                    path.unlink(missing_ok=True)


class B2Source(_Remote):
    _api = None  # one login per run

    def __init__(self, uri: str):
        rest = uri[len("b2://"):].strip("/")
        self.bucket_name, _, prefix = rest.partition("/")
        if not self.bucket_name:
            raise SystemExit("Give a bucket: b2://<bucket>/<folder>/")
        self.prefix = (prefix.strip("/") + "/") if prefix.strip("/") else ""
        self.uri = f"b2://{self.bucket_name}/{self.prefix}"
        safe = self.prefix.strip("/").replace("/", "__") or "_root"
        self.index_dir = DATA_DIR / "remote" / self.bucket_name / safe
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self._bucket = None

    # --- Backblaze access -------------------------------------------------
    def bucket(self):
        if self._bucket is None:
            fake = os.environ.get("FF_B2_FAKE_ROOT")
            if fake:  # test mode: a local folder stands in for the bucket
                self._bucket = _FakeBucket(Path(fake) / self.bucket_name)
            else:
                if B2Source._api is None:
                    from b2sdk.v2 import B2Api, InMemoryAccountInfo

                    api = B2Api(InMemoryAccountInfo())
                    kid, key = load_keys()
                    try:
                        api.authorize_account("production", kid, key)
                    except Exception as e:
                        raise SystemExit(f"Backblaze login failed: {e}")
                    B2Source._api = api
                try:
                    self._bucket = B2Source._api.get_bucket_by_name(self.bucket_name)
                except Exception as e:
                    raise SystemExit(f"Can't open bucket '{self.bucket_name}': {e}")
        return self._bucket

    def list(self):
        for fv, _ in self.bucket().ls(self.prefix, recursive=True):
            name = fv.file_name
            if Path(name).suffix.lower() in MEDIA and not skipped(name[len(self.prefix):]):
                yield name[len(self.prefix):], fv.size, fv.upload_timestamp / 1000

    def ls(self):
        """Immediate subfolders and media files of this prefix (for browsing the bucket)."""
        folders, files = [], []
        for fv, folder in self.bucket().ls(self.prefix, recursive=False):
            if folder:
                folders.append(folder.rstrip("/")[len(self.prefix):])
            elif Path(fv.file_name).suffix.lower() in MEDIA:
                files.append(fv.file_name[len(self.prefix):])
        return folders, files

    def download(self, rel: str, dest: Path):
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        self.bucket().download_file_by_name(self.prefix + rel).save_to(str(part))
        part.replace(dest)
        return dest


class _FakeVersion:
    def __init__(self, name, path):
        st = path.stat()
        self.file_name, self.size, self.upload_timestamp = name, st.st_size, int(st.st_mtime * 1000)


class _FakeDownload:
    def __init__(self, path):
        self.path = path

    def save_to(self, dest):
        shutil.copyfile(self.path, dest)


class _FakeBucket:
    """Same calls as a b2sdk Bucket, backed by a local folder. For tests only."""

    def __init__(self, root: Path):
        self.root = root

    def ls(self, prefix, recursive=True):
        base = self.root / prefix
        if not base.exists():
            return
        if recursive:
            for p in sorted(base.rglob("*")):
                if p.is_file():
                    yield _FakeVersion(p.relative_to(self.root).as_posix(), p), None
            return
        for p in sorted(base.iterdir()):  # like B2: a folder comes back with its name
            if p.is_dir():
                first = next((q for q in p.rglob("*") if q.is_file()), None)
                if first:
                    yield _FakeVersion(first.relative_to(self.root).as_posix(), first), \
                        p.relative_to(self.root).as_posix() + "/"
            else:
                yield _FakeVersion(p.relative_to(self.root).as_posix(), p), None

    def download_file_by_name(self, name):
        return _FakeDownload(self.root / name)

    def get_file_info_by_name(self, name):
        return _FakeVersion(name, self.root / name)


def open_source(spec):
    spec = str(spec)
    if spec.startswith("iconik://"):
        from .iconik import IconikSource

        return IconikSource(spec)
    return B2Source(spec) if spec.startswith("b2://") else LocalSource(spec)


def fetch_to(location: str, dest_dir: Path, original=True) -> Path:
    """Get one result onto local disk: a local file is returned as is, a b2:// file is
    downloaded into dest_dir (skipped if an identical-size copy is already there).
    Iconik: original=False takes the small proxy (previews), True the full-quality original."""
    if not is_remote(location):
        return Path(location)
    if location.startswith("iconik://"):
        from .iconik import fetch

        return fetch(location, Path(dest_dir), original)
    rest = location[len("b2://"):]
    bucket, _, key = rest.partition("/")
    src = B2Source(f"b2://{bucket}/")
    size = src.bucket().get_file_info_by_name(key).size
    dest = Path(dest_dir) / Path(key).name
    if dest.exists() and dest.stat().st_size != size:
        # Same name, different file (phones reuse IMG_ numbers): keep both.
        dest = dest.with_name(f"{dest.stem}_{hashlib.sha1(key.encode()).hexdigest()[:6]}{dest.suffix}")
    if dest.exists() and dest.stat().st_size == size:
        return dest
    return src.download(key, dest)
