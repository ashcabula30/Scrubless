"""Per-folder index (SQLite in <folder>/.footage-index) plus a registry of indexed folders."""
import json
import sqlite3
from pathlib import Path

import numpy as np

from .env import DATA_DIR

INDEX_DIR = ".footage-index"
REGISTRY = DATA_DIR / "registry.json"

SCHEMA = """
create table if not exists meta (key text primary key, value text);
create table if not exists files (
    id integer primary key, rel text unique, size integer, mtime real, duration real, error text
);
create table if not exists segments (
    id integer primary key, file_id integer, start real, end real, text text, words text, emb blob
);
create index if not exists seg_file on segments(file_id);
create table if not exists vfiles (rel text primary key, size integer, mtime real, error text);
create table if not exists vframes (rel text, t real, emb blob);
create index if not exists vframe_rel on vframes(rel);
"""


class Index:
    def __init__(self, folder: Path):
        self.folder = Path(folder).resolve()
        d = self.folder / INDEX_DIR
        d.mkdir(parents=True, exist_ok=True)
        # The app server reads indexes from worker threads; each Index is used by one thread at a time.
        self.db = sqlite3.connect(d / "index.db", check_same_thread=False)
        self.db.executescript(SCHEMA)

    @property
    def base(self) -> str:
        """Where the footage lives: the folder itself, or a b2:// URI for a remote index."""
        return self.get_meta("source") or str(self.folder)

    @staticmethod
    def exists(folder: Path) -> bool:
        return (Path(folder) / INDEX_DIR / "index.db").is_file()

    def get_meta(self, key):
        row = self.db.execute("select value from meta where key=?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key, value):
        self.db.execute("insert or replace into meta values (?, ?)", (key, value))
        self.db.commit()

    def file_state(self):
        return {rel: (size, mtime) for rel, size, mtime in self.db.execute("select rel, size, mtime from files")}

    def remove_file(self, rel):
        row = self.db.execute("select id from files where rel=?", (rel,)).fetchone()
        if row:
            self.db.execute("delete from segments where file_id=?", (row[0],))
            self.db.execute("delete from files where id=?", (row[0],))
            self.db.commit()

    def clear(self):
        self.db.executescript("delete from segments; delete from files; delete from meta; "
                              "delete from vfiles; delete from vframes;")
        self.db.commit()
        import shutil

        shutil.rmtree(self.folder / INDEX_DIR / "thumbs", ignore_errors=True)

    # Visual index: sampled frames per file with image embeddings.
    def vfile_state(self):
        return {rel: (size, mtime) for rel, size, mtime in self.db.execute("select rel, size, mtime from vfiles")}

    def remove_vfile(self, rel):
        import shutil

        shutil.rmtree(self._thumb_dir(rel), ignore_errors=True)
        self.db.execute("delete from vframes where rel=?", (rel,))
        self.db.execute("delete from vfiles where rel=?", (rel,))
        self.db.commit()

    def put_vfile(self, rel, size, mtime, times, embs, error=None):
        self.remove_vfile(rel)
        self.db.execute("insert into vfiles values (?, ?, ?, ?)", (rel, size, mtime, error))
        self.db.executemany(
            "insert into vframes values (?, ?, ?)",
            [(rel, float(t), np.asarray(e, dtype=np.float32).tobytes()) for t, e in zip(times, embs)],
        )
        self.db.commit()

    # Small JPGs of the sampled frames: result thumbnails and contact sheets without running ffmpeg.
    def has_thumbs(self, rel):
        d = self._thumb_dir(rel)
        return d.is_dir() and any(d.iterdir())

    def _thumb_dir(self, rel):
        import hashlib

        return self.folder / INDEX_DIR / "thumbs" / hashlib.sha1(rel.encode()).hexdigest()[:16]

    def put_thumbs(self, rel, times, jpgs):
        d = self._thumb_dir(rel)
        d.mkdir(parents=True, exist_ok=True)
        for t, data in zip(times, jpgs):
            (d / f"{int(round(t * 1000))}.jpg").write_bytes(data)

    def thumb(self, rel, t):
        """Path of the stored frame closest to time t, or None."""
        d = self._thumb_dir(rel)
        files = list(d.glob("*.jpg")) if d.is_dir() else []
        if not files:
            return None
        return min(files, key=lambda p: abs(int(p.stem) / 1000 - t))

    def load_frames(self):
        rows = self.db.execute("select rel, t, emb from vframes order by rel, t").fetchall()
        frames = [(rel, t) for rel, t, _ in rows]
        embs = np.stack([np.frombuffer(r[2], dtype=np.float32) for r in rows]) if rows else np.zeros((0, 1))
        return frames, embs

    def put_file(self, rel, size, mtime, duration, segments, embs, error=None):
        self.remove_file(rel)
        cur = self.db.execute(
            "insert into files (rel, size, mtime, duration, error) values (?, ?, ?, ?, ?)",
            (rel, size, mtime, duration, error),
        )
        fid = cur.lastrowid
        for seg, emb in zip(segments, embs):
            self.db.execute(
                "insert into segments (file_id, start, end, text, words, emb) values (?, ?, ?, ?, ?, ?)",
                (fid, seg["start"], seg["end"], seg["text"], json.dumps(seg["words"]),
                 np.asarray(emb, dtype=np.float32).tobytes()),
            )
        self.db.commit()

    def load_segments(self):
        """All segments, ordered by file then time, with embeddings as one matrix."""
        rows = self.db.execute(
            "select f.rel, s.start, s.end, s.text, s.words, s.emb from segments s "
            "join files f on f.id = s.file_id order by f.rel, s.start"
        ).fetchall()
        segs = [
            {"file": rel, "start": st, "end": en, "text": tx, "words": json.loads(w)}
            for rel, st, en, tx, w, _ in rows
        ]
        embs = np.stack([np.frombuffer(r[5], dtype=np.float32) for r in rows]) if rows else np.zeros((0, 1))
        return segs, embs

    def stats(self):
        files = self.db.execute("select count(*), coalesce(sum(duration), 0) from files").fetchone()
        errors = self.db.execute("select count(*) from files where error is not null").fetchone()[0]
        vfiles = self.db.execute("select count(*) from vfiles where error is null").fetchone()[0]
        vframes = self.db.execute("select count(*) from vframes").fetchone()[0]
        return {"files": files[0], "hours": files[1] / 3600, "errors": errors,
                "vfiles": vfiles, "vframes": vframes, "source": self.base,
                "tier": self.get_meta("tier"), "whisper": self.get_meta("whisper")}


def load_registry():
    try:
        return json.loads(REGISTRY.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return []


def unregister(folder: Path):
    f = str(Path(folder).resolve())
    folders = [x for x in load_registry() if x != f]
    REGISTRY.write_text(json.dumps(folders, indent=2), encoding="utf-8")


def register(folder: Path):
    folders = load_registry()
    f = str(Path(folder).resolve())
    if f not in folders:
        folders.append(f)
        REGISTRY.parent.mkdir(parents=True, exist_ok=True)
        REGISTRY.write_text(json.dumps(folders, indent=2), encoding="utf-8")
