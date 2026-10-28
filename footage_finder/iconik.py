"""Iconik (creator footage) as a footage source: read-only, with an App ID + Auth Token.

A collection is indexed like a Backblaze folder, through temporary downloads. Indexing and previews
use each asset's proxy (a small MP4), so they're quick; clips you pick for a rough cut or Download
come down as the full-quality original.
Locations look like iconik://<collection id>/<sub collection>/<asset title>.
"""
import hashlib
import json
import re
import shutil
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from .env import DATA_DIR
from .sources import MEDIA, _Remote, skipped

API = "https://app.iconik.io/API"
KEYS_FILE = DATA_DIR / "iconik.json"
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
NOT_FOOTAGE = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".psd", ".ai", ".pdf", ".txt", ".doc", ".docx",
               ".zip", ".srt", ".xml", ".prproj", ".aep"}


def load_keys():
    try:
        d = json.loads(KEYS_FILE.read_text(encoding="utf-8"))
        return d.get("app_id", "").strip(), d.get("auth_token", "").strip()
    except (FileNotFoundError, ValueError):
        return "", ""


def save_keys(app_id, token):
    KEYS_FILE.parent.mkdir(parents=True, exist_ok=True)
    KEYS_FILE.write_text(json.dumps({"app_id": app_id.strip(), "auth_token": token.strip()}), encoding="utf-8")


def _get(path, params=None, keys=None):
    app_id, token = keys or load_keys()
    if not (app_id and token):
        raise ValueError("Add your Iconik App ID and Auth Token in Settings first.")
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"App-ID": app_id, "Auth-Token": token, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise ValueError("Iconik didn't accept the App ID / Auth Token (or they can't see this). Check Settings.")
        if e.code == 404:
            raise ValueError("Iconik couldn't find that (check the collection link).")
        raise ValueError(f"Iconik error {e.code}")
    except urllib.error.URLError as e:
        raise ValueError(f"Can't reach Iconik: {e.reason}")


def whoami(keys=None):
    u = _get("/users/v1/users/current/", keys=keys)
    return " ".join(x for x in (u.get("first_name"), u.get("last_name")) if x) or u.get("email") or "connected"


def collection_id_from(link: str) -> str:
    m = UUID.search(link or "")
    if not m:
        raise ValueError("That doesn't look like an Iconik collection link (no collection id in it).")
    return m.group(0).lower()


def contents(cid):
    """Everything directly inside a collection (assets and sub-collections), all pages."""
    page, out = 1, []
    while True:
        r = _get(f"/assets/v1/collections/{cid}/contents/", {"per_page": 500, "page": page})
        out += r.get("objects") or []
        if page >= int(r.get("pages") or 1):
            return out
        page += 1


def _title(o):
    return (o.get("title") or o.get("id") or "untitled").replace("/", "_").replace("\\", "_").strip()


def _epoch(iso):
    try:
        return datetime.fromisoformat(iso).timestamp()
    except (TypeError, ValueError):
        return 0.0


def browse(link_or_id):
    """A collection's title, sub-collections and how many assets sit directly in it."""
    cid = collection_id_from(link_or_id)
    info = _get(f"/assets/v1/collections/{cid}/")
    subs, assets = [], 0
    for o in contents(cid):
        if o.get("object_type") == "collections":
            subs.append({"id": o["id"], "title": _title(o)})
        elif o.get("object_type") == "assets":
            assets += 1
    return {"id": cid, "title": info.get("title") or cid, "collections": subs, "assets": assets}


class IconikSource(_Remote):
    def __init__(self, uri: str):
        self.cid = collection_id_from(uri)
        self.uri = f"iconik://{self.cid}/"
        self.index_dir = DATA_DIR / "remote" / "iconik" / self.cid
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self._ids_file = self.index_dir / "iconik_assets.json"  # rel -> asset id, for downloads later
        self._ids = None

    def title(self):
        return _get(f"/assets/v1/collections/{self.cid}/").get("title") or self.cid

    def _walk(self, cid, prefix, depth=0):
        for o in contents(cid):
            kind, title = o.get("object_type"), _title(o)
            if kind == "collections" and depth < 8 and not skipped(f"{title}/x"):
                yield from self._walk(o["id"], f"{prefix}{title}/", depth + 1)
            elif kind == "assets":
                ext = Path(title).suffix.lower()
                if ext in NOT_FOOTAGE:
                    continue
                # Iconik titles often drop the extension; the proxy we index is an MP4 anyway.
                yield prefix + (title if ext in MEDIA else title + ".mp4"), o

    def list(self):
        ids = {}
        for rel, o in self._walk(self.cid, ""):
            ids[rel] = o["id"]
            # Size isn't in the listing; the modified date is enough to spot changed assets.
            yield rel, 0, _epoch(o.get("date_modified") or o.get("date_created"))
        self._ids = ids
        self._ids_file.write_text(json.dumps(ids), encoding="utf-8")

    def asset_id(self, rel):
        if self._ids is None:
            try:
                self._ids = json.loads(self._ids_file.read_text(encoding="utf-8"))
            except (FileNotFoundError, ValueError):
                self._ids = {}
        aid = self._ids.get(rel.replace("\\", "/"))
        if not aid:
            raise ValueError(f"Unknown Iconik asset {rel} (run Update on this collection).")
        return aid

    def _proxy_url(self, aid):
        proxies = _get(f"/files/v1/assets/{aid}/proxies/").get("objects") or []
        for p in proxies:
            url = p.get("url") or _get(f"/files/v1/assets/{aid}/proxies/{p['id']}/").get("url")
            if url:
                return url
        raise ValueError("This Iconik asset has no proxy yet (Iconik may still be processing it).")

    def _original_url(self, aid):
        for f in _get(f"/files/v1/assets/{aid}/files/").get("objects") or []:
            try:
                url = _get(f"/files/v1/assets/{aid}/files/{f['id']}/download_url/").get("url")
                if url:
                    return url
            except ValueError:
                continue
        return None

    def download(self, rel, dest: Path, original=False):
        aid = self.asset_id(rel)
        url = (self._original_url(aid) if original else None) or self._proxy_url(aid)
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        with urllib.request.urlopen(url, timeout=60) as r, open(part, "wb") as f:  # signed URL: no headers needed
            shutil.copyfileobj(r, f, 1 << 20)
        part.replace(dest)
        return dest


def fetch(location: str, dest_dir: Path, original=True) -> Path:
    """Download one iconik:// result. The asset id goes in the file name, since phone clips reuse
    names (IMG_1234) across creators; an existing copy is reused."""
    rest = location[len("iconik://"):]
    cid, _, rel = rest.partition("/")
    src = IconikSource(f"iconik://{cid}/")
    aid = src.asset_id(rel)
    name = Path(rel).name
    tag = hashlib.sha1(aid.encode()).hexdigest()[:6] + ("" if original else "-proxy")
    dest = dest_dir / f"{Path(name).stem}_{tag}{Path(name).suffix}"
    return dest if dest.exists() else src.download(rel, dest, original=original)
