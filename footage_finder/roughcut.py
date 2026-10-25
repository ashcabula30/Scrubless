"""Turn brief search results into a Premiere-importable rough cut (FCP 7 XML).

Layout: spoken lines (A-roll) on V1 + A1; visual matches on V2 over the same stretch.
A line with only a visual gets a b-roll shot on V1. A line with no match leaves a gap
and a MISSING marker. Every line gets a sequence marker listing its backup takes.
"""
import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote

PAD_IN, PAD_OUT = 0.15, 0.25        # breathing room around a spoken line (seconds)
BROLL_MIN, BROLL_MAX = 1.5, 4.0     # b-roll-only shot length
WORDS_PER_SEC = 2.6                 # for estimating gaps when nothing matched


def probe(path: Path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, check=True).stdout
    info = json.loads(out)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    w, h = (int(v["width"]), int(v["height"])) if v else (0, 0)
    rot = 0
    if v:
        for sd in v.get("side_data_list", []):
            rot = int(sd.get("rotation", 0) or 0)
        rot = int(v.get("tags", {}).get("rotate", rot))
    if abs(rot) in (90, 270):
        w, h = h, w
    return {
        "duration": float(info["format"].get("duration", 0)),
        "width": w, "height": h,
        "has_video": v is not None,
        "has_audio": a is not None,
        "channels": int(a.get("channels", 2)) if a else 0,
        "samplerate": int(a.get("sample_rate", 48000)) if a else 48000,
    }


def _rate(parent, fps):
    r = ET.SubElement(parent, "rate")
    ET.SubElement(r, "timebase").text = str(round(fps))
    ET.SubElement(r, "ntsc").text = "TRUE" if abs(fps - round(fps)) > 0.01 else "FALSE"


def _text(parent, tag, value):
    ET.SubElement(parent, tag).text = str(value)


class Timeline:
    def __init__(self, fps):
        self.fps = fps
        self.tracks = {"V1": [], "V2": [], "A1": []}
        self.markers = []
        self.files = {}

    def f(self, seconds):
        return int(round(seconds * self.fps))

    def add(self, track, path, src_in, frames, rec_frame, linked=None):
        """Place `frames` frames of `path` from src_in (seconds) at timeline frame rec_frame.

        The timeline is counted in whole frames so neighbouring clips never overlap or leave gaps
        (rounding start and length separately produced 1-frame overlaps)."""
        path = Path(path)
        if path not in self.files:
            self.files[path] = probe(path)
        start_in = self.f(src_in)
        clip = {"path": path, "in": start_in, "out": start_in + frames, "start": rec_frame, "end": rec_frame + frames}
        clip["linked"] = linked
        self.tracks[track].append(clip)
        return clip


def name_of(location: str) -> str:
    return str(location).replace("\\", "/").rsplit("/", 1)[-1]


def plan(items, fps, resolve=Path):
    """Pick one take per line, avoid reusing the same b-roll moment, and lay clips end to end.

    resolve(location) -> local Path; for Backblaze results it downloads just that clip.
    """
    tl = Timeline(fps)
    t = 0  # timeline position in frames
    used = []  # (location, peak) of b-roll already placed

    def fresh_scene(it):
        """The line's chosen shot (from the app), or the best one not already used."""
        if it.get("no_broll"):
            return None
        if it.get("show_pick") is not None:
            return it["show_pick"]
        scenes = it["shown"]
        for s in scenes:
            if not any(s.location == f and abs(s.peak - p) < 2.0 for f, p in used):
                return s
        return scenes[0] if scenes else None

    def local(location):
        path = Path(resolve(location))
        if path not in tl.files:
            tl.files[path] = probe(path)
        return path, tl.files[path]

    for it in items:
        said, shown = it["said"], it["shown"]
        start = t
        note = []
        if said:
            h = said[0]
            path, info = local(h.location)
            a, b = max(0.0, h.start - PAD_IN), min(info["duration"] or h.end + PAD_OUT, h.end + PAD_OUT)
            length = b - a
            frames = max(1, tl.f(length))
            v = tl.add("V1", path, a, frames, t) if info["has_video"] else None
            if info["has_audio"]:
                au = tl.add("A1", path, a, frames, t, linked=v)
                if v:
                    v["linked"] = au
            note.append(f"Using {name_of(h.location)} @ {h.start:.1f}s \"{h.text}\"")
            for alt in said[1:4]:
                note.append(f"Alt: {name_of(alt.location)} @ {alt.start:.1f}s ({alt.score:.0%}) \"{alt.text}\"")
            s = fresh_scene(it)
            if s:
                used.append((s.location, s.peak))
                spath, info_s = local(s.location)
                b_in = max(0.0, min(s.peak - length / 2, (info_s["duration"] or length) - length))
                tl.add("V2", spath, b_in, frames, t)
                note.append(f"B-roll: {name_of(s.location)} @ {s.peak:.1f}s")
        elif fresh_scene(it):
            s = fresh_scene(it)
            used.append((s.location, s.peak))
            spath, info_s = local(s.location)
            length = min(BROLL_MAX, max(BROLL_MIN, s.end - s.start))
            frames = max(1, tl.f(length))
            b_in = max(0.0, min(s.peak - length / 2, (info_s["duration"] or length) - length))
            tl.add("V1", spath, b_in, frames, t)
            note.append(f"B-roll: {name_of(s.location)} @ {s.peak:.1f}s")
            for alt in shown[1:4]:
                note.append(f"Alt: {name_of(alt.location)} @ {alt.peak:.1f}s")
        else:
            words = len((it["say"] or it["show"]).split())
            frames = tl.f(max(1.5, words / WORDS_PER_SEC))
            note.append("MISSING: no take found. Needs VO, new footage, or a manual pick.")
        name = it["label"] + (" MISSING" if note and note[-1].startswith("MISSING") else "")
        comment = " | ".join(([f'Say: "{it["say"]}"'] if it["say"] else [])
                             + ([f"Show: {it['show']}"] if it["show"] else [])
                             + ([it["note"]] if it.get("note") else []) + note)
        tl.markers.append((name, comment, start))
        t += frames
    return tl


def to_xml(tl: Timeline, name, width, height):
    fps = tl.fps
    root = ET.Element("xmeml", version="4")
    seq = ET.SubElement(root, "sequence", id="sequence-1")
    _text(seq, "name", name)
    total = max([c["end"] for tr in tl.tracks.values() for c in tr] + [m[2] + 1 for m in tl.markers] + [1])
    _text(seq, "duration", total)
    _rate(seq, fps)
    media = ET.SubElement(seq, "media")

    video = ET.SubElement(media, "video")
    fmt = ET.SubElement(ET.SubElement(video, "format"), "samplecharacteristics")
    _rate(fmt, fps)
    _text(fmt, "width", width)
    _text(fmt, "height", height)
    _text(fmt, "pixelaspectratio", "square")
    _text(fmt, "fielddominance", "none")
    audio = ET.SubElement(media, "audio")

    file_ids = {p: f"file-{i}" for i, p in enumerate(tl.files, 1)}
    written = set()
    clip_ids = {}
    n = 0
    for track in ("V1", "V2", "A1"):
        for i, c in enumerate(tl.tracks[track], 1):
            n += 1
            clip_ids[id(c)] = (f"clipitem-{n}", track, i)

    def file_el(parent, path):
        fid = file_ids[path]
        el = ET.SubElement(parent, "file", id=fid)
        if fid in written:
            return
        written.add(fid)
        info = tl.files[path]
        _text(el, "name", path.name)
        _text(el, "pathurl", "file://localhost/" + quote(path.as_posix(), safe="/"))
        _rate(el, fps)
        _text(el, "duration", tl.f(info["duration"]))
        m = ET.SubElement(el, "media")
        if info["has_video"]:
            sc = ET.SubElement(ET.SubElement(m, "video"), "samplecharacteristics")
            _rate(sc, fps)
            _text(sc, "width", info["width"])
            _text(sc, "height", info["height"])
        if info["has_audio"]:
            au = ET.SubElement(m, "audio")
            sc = ET.SubElement(au, "samplecharacteristics")
            _text(sc, "depth", 16)
            _text(sc, "samplerate", info["samplerate"])
            _text(au, "channelcount", info["channels"])

    def link_el(parent, c):
        cid, track, idx = clip_ids[id(c)]
        link = ET.SubElement(parent, "link")
        _text(link, "linkclipref", cid)
        _text(link, "mediatype", "audio" if track.startswith("A") else "video")
        _text(link, "trackindex", 1)
        _text(link, "clipindex", idx)

    for track in ("V1", "V2", "A1"):
        parent = audio if track.startswith("A") else video
        tr = ET.SubElement(parent, "track")
        for c in tl.tracks[track]:
            cid = clip_ids[id(c)][0]
            ci = ET.SubElement(tr, "clipitem", id=cid)
            _text(ci, "name", c["path"].name)
            _text(ci, "enabled", "TRUE")
            _text(ci, "duration", tl.f(tl.files[c["path"]]["duration"]))
            _rate(ci, fps)
            _text(ci, "start", c["start"])
            _text(ci, "end", c["end"])
            _text(ci, "in", c["in"])
            _text(ci, "out", c["out"])
            file_el(ci, c["path"])
            if track.startswith("A"):
                st = ET.SubElement(ci, "sourcetrack")
                _text(st, "mediatype", "audio")
                _text(st, "trackindex", 1)
            if c["linked"] is not None:
                link_el(ci, c)
                link_el(ci, c["linked"])

    for mname, comment, at in tl.markers:
        m = ET.SubElement(seq, "marker")
        _text(m, "name", mname)
        _text(m, "comment", comment)
        _text(m, "in", at)
        _text(m, "out", -1)

    ET.indent(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + ET.tostring(root, encoding="unicode")


def build_roughcut(items, out: Path, name, width, height, fps, media_dir: Path = None, log=print):
    """media_dir: where Backblaze clips used in the cut are downloaded (default: '<xml name> media')."""
    from .sources import fetch_to, is_remote

    media_dir = Path(media_dir) if media_dir else out.with_name(out.stem + " media")

    def resolve(location):
        if is_remote(location):
            log(f"  downloading {name_of(location)} -> {media_dir}")
        return fetch_to(location, media_dir)

    tl = plan(items, fps, resolve)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(to_xml(tl, name, width, height), encoding="utf-8")
    return out
