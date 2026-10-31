"""Command line: footage app | serve | index | find | scene | brief | roughcut | get | ls | list | doctor."""
import argparse
import json
import sys
from pathlib import Path

from .env import DATA_DIR, setup


def tc(seconds: float) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:04.1f}"


def print_hits(hits, show_path=False):
    if not hits:
        print("  No match found.")
        return
    width = max(len(h.location if show_path else h.file) for h in hits)
    for i, h in enumerate(hits, 1):
        name = h.location if show_path else h.file
        take = f"take {h.take} of {h.takes} in this file" if h.takes > 1 else ""
        print(f"  {i:>2}. {name:<{width}}  {tc(h.start)}-{tc(h.end)}  {h.score:>4.0%}  \"{h.text}\"  {take}")


def print_scenes(scenes, show_path=False):
    if not scenes:
        print("  No match found.")
        return
    width = max(len(s.location if show_path else s.file) for s in scenes)
    for i, s in enumerate(scenes, 1):
        name = s.location if show_path else s.file
        # SigLIP's probability is very conservative (correct shots can read 5%); show a plain label.
        label = "strong" if s.score >= 0.5 else "good" if s.score >= 0.05 else "possible"
        print(f"  {i:>2}. {name:<{width}}  {tc(s.start)}-{tc(s.end)}  best frame {tc(s.peak)}  {label}")


def read_text_arg(src: str) -> str:
    if src == "-":
        return sys.stdin.read()
    if len(src) < 260 and Path(src).is_file():
        return Path(src).read_text(encoding="utf-8")
    return src


def folders_for(args):
    """Index folders to search: --in (a footage folder or b2:// URI), else everything indexed."""
    from .sources import open_source
    from .store import Index, load_registry

    folders = [open_source(f).index_dir for f in args.in_] if args.in_ else [Path(f) for f in load_registry()]
    folders = [f for f in folders if Index.exists(f)]
    if not folders:
        raise SystemExit("No indexed footage yet. Run:  footage index \"<footage folder or b2://bucket/folder/>\"")
    return folders


def make_sheet(scenes, out: Path, title_prefix=""):
    from .sources import is_remote
    from .visual import contact_sheet, save_thumb

    thumbs_dir = DATA_DIR / "thumbs"
    items = []
    for i, s in enumerate(scenes, 1):
        thumb = s.index.thumb(s.file, s.peak) if s.index else None
        if thumb is None:
            if is_remote(s.location):
                continue
            thumb = thumbs_dir / f"{abs(hash((s.location, round(s.peak, 1))))}.jpg"
            if not thumb.exists():
                save_thumb(Path(s.location), s.peak, thumb)
        items.append((f"{title_prefix}{i}. {s.file} @ {tc(s.peak)}", thumb))
    return contact_sheet(items, out, height=240 if any(is_remote(s.location) for s in scenes) else 360)


def download_results(locations, dest):
    """Fetch every distinct Backblaze file among the results into dest (local files are left alone)."""
    from .sources import fetch_to, is_remote

    seen = []
    for loc in locations:
        if is_remote(loc) and loc not in seen:
            seen.append(loc)
    if not seen:
        print("Nothing to download: these results are already on this PC.")
        return
    print(f"\nDownloading {len(seen)} clip(s) to {dest}")
    for loc in seen:
        print(f"  {fetch_to(loc, Path(dest))}")


def hit_json(h):
    return {"file": h.location, "start": round(h.start, 3), "end": round(h.end, 3),
            "text": h.text, "score": round(h.score, 3), "take": h.take, "takes": h.takes}


def scene_json(s):
    return {"file": s.location, "start": round(s.start, 3), "end": round(s.end, 3),
            "peak": round(s.peak, 3), "score": round(s.score, 3)}


def run_brief(text, folders, top, min_score, want_visual=True):
    """Search every line of a brief. Returns [{label, say, show, said: [...], shown: [...]}]."""
    from .search import Searcher, parse_brief, visual_query

    items = parse_brief(text)
    if not items:
        raise SystemExit("Couldn't find any script lines in that brief.")
    speech = Searcher(folders)
    scenes = None

    say_queries = [it["say"] for it in items if it.get("say")]
    unique_says = list(dict.fromkeys(q for q in say_queries if q))
    if unique_says:
        batch_said = speech.find_batch(unique_says, top, min_score)
        said_map = dict(zip(unique_says, batch_said))
    else:
        said_map = {}

    show_queries = [visual_query(it["show"]) for it in items if it.get("show") and want_visual]
    unique_shows = list(dict.fromkeys(q for q in show_queries if q))
    if unique_shows:
        from .visual import SceneSearcher

        scenes = SceneSearcher(folders)
        batch_shown = scenes.find_batch(unique_shows, top)
        shown_map = dict(zip(unique_shows, batch_shown))
    else:
        shown_map = {}

    for it in items:
        it["said"] = said_map.get(it["say"], []) if it.get("say") else []
        it["shown"] = shown_map.get(visual_query(it["show"]), []) if it.get("show") and want_visual else []
    return items


def cmd_index(args):
    from .indexer import index_folder

    stats = index_folder(args.folder, args.tier, args.language, args.rebuild, visual=not args.no_visual)
    print(f"Indexed: {stats['files']} files, {stats['hours']:.1f} h of media"
          + (f", {stats['errors']} without speech/audio" if stats["errors"] else "")
          + f"; {stats['vfiles']} videos with {stats['vframes']} frames for visual search")


def cmd_find(args):
    from .search import Searcher

    hits = Searcher(folders_for(args)).find(args.query, args.top, args.min)
    if args.json:
        print(json.dumps([hit_json(h) for h in hits], indent=2))
        return
    print(f'"{args.query}"')
    print_hits(hits, args.paths)
    if args.download:
        download_results([h.location for h in hits], args.download)


def cmd_scene(args):
    from .visual import SceneSearcher

    scenes = SceneSearcher(folders_for(args)).find(args.query, args.top)
    if args.json:
        print(json.dumps([scene_json(s) for s in scenes], indent=2))
        return
    print(f"[visual] {args.query}")
    print_scenes(scenes, args.paths)
    if args.sheet and scenes:
        print(f"Contact sheet: {make_sheet(scenes, Path(args.sheet))}")
    if args.download:
        download_results([s.location for s in scenes], args.download)


def cmd_brief(args):
    items = run_brief(read_text_arg(args.text), folders_for(args), args.top, args.min)
    if args.json:
        print(json.dumps([{"label": it["label"], "say": it["say"], "show": it["show"],
                           "said": [hit_json(h) for h in it["said"]],
                           "shown": [scene_json(s) for s in it["shown"]]} for it in items], indent=2))
        return
    for it in items:
        print(f"\n{it['label']}" + (f' - "{it["say"]}"' if it["say"] else ""))
        if it["say"]:
            print_hits(it["said"], args.paths)
        if it["show"]:
            print(f"  [visual] {it['show']}")
            print_scenes(it["shown"], args.paths)
    if args.sheet:
        allscenes = [s for it in items for s in it["shown"][:5]]
        if allscenes:
            print(f"\nContact sheet: {make_sheet(allscenes, Path(args.sheet))}")
    if args.download:
        download_results([x.location for it in items for x in it["said"] + it["shown"]], args.download)


def cmd_roughcut(args):
    from .roughcut import build_roughcut

    items = run_brief(read_text_arg(args.text), folders_for(args), 5, args.min)
    out = build_roughcut(items, Path(args.out), args.name, args.width, args.height, args.fps,
                         media_dir=Path(args.media) if args.media else None)
    print(f"Rough cut written: {out}")
    print("In Premiere: File > Import..., pick the .xml. Backup takes are listed in the sequence markers.")


def cmd_get(args):
    from .sources import fetch_to

    for loc in args.location:
        print(fetch_to(loc, Path(args.to)))


def cmd_ls(args):
    from .sources import open_source

    src = open_source(args.where)
    if not src.remote:
        raise SystemExit("ls is for Backblaze: footage ls b2://<bucket>/<folder>/")
    folders, files = src.ls()
    for f in folders:
        print(f"  {f}/")
    if files:
        media = sum(1 for _ in files)
        print(f"  ({media} media file(s) directly in this folder)")
    if not folders and not files:
        print("  (empty)")


def cmd_app(args):
    from .app import main as run_app

    run_app()


def cmd_serve(args):
    from .server import PORT, serve

    print(f"Scrubless server on http://127.0.0.1:{PORT}  (Ctrl+C to stop)")
    serve()


def cmd_list(args):
    from .store import Index, load_registry

    for f in load_registry():
        if Index.exists(f):
            st = Index(f).stats()
            print(f"{st['source']}\n    {st['files']} files, {st['hours']:.1f} h, preset {st['tier']} ({st['whisper']}), "
                  f"{st['vframes']} frames indexed")


def cmd_doctor(args):
    from . import tiers
    from .sources import KEYS_FILE, load_keys

    gpu = tiers.gpu_info()
    print(f"Data folder: {DATA_DIR}")
    print(f"GPU: {gpu[0]} ({gpu[1]:.0f} GB)" if gpu else "GPU: none usable (CPU only)")
    t = tiers.detect()
    print(f"Auto preset: {t}  -> {tiers.TIERS[t]}")
    try:
        import ctranslate2

        print(f"CTranslate2 {ctranslate2.__version__}, CUDA devices: {ctranslate2.get_cuda_device_count()}")
    except Exception as e:
        print(f"CTranslate2 problem: {e}")
    try:
        load_keys()
        print(f"Backblaze key: set ({KEYS_FILE})")
    except SystemExit:
        print(f"Backblaze key: not set (fill in {KEYS_FILE})")


def main(argv=None):
    setup()
    p = argparse.ArgumentParser(prog="footage", description="Search footage by what is said and shown.")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("index", help="index a footage folder or b2://bucket/folder/ (only new/changed files)")
    a.add_argument("folder")
    a.add_argument("--tier", default="auto", choices=["auto", "low", "mid", "high"])
    a.add_argument("--language", help="e.g. en; default: detect per clip")
    a.add_argument("--rebuild", action="store_true", help="redo the whole folder")
    a.add_argument("--no-visual", action="store_true", help="speech only (faster)")
    a.set_defaults(func=cmd_index)

    def search_opts(b, top):
        b.add_argument("--in", dest="in_", action="append",
                       help="limit to this indexed folder or b2:// folder (repeatable)")
        b.add_argument("--top", type=int, default=top)
        b.add_argument("--min", type=float, default=0.55, help="minimum speech match score 0-1")
        b.add_argument("--paths", action="store_true", help="show full file paths")
        b.add_argument("--json", action="store_true", help="machine-readable output")
        b.add_argument("--download", metavar="DIR", help="download the Backblaze clips in these results to DIR")

    b = sub.add_parser("find", help="find where a line is said")
    b.add_argument("query")
    search_opts(b, 10)
    b.set_defaults(func=cmd_find)

    b = sub.add_parser("scene", help="find shots that look like a description")
    b.add_argument("query")
    search_opts(b, 10)
    b.add_argument("--sheet", help="also save a contact sheet JPG here")
    b.set_defaults(func=cmd_scene)

    b = sub.add_parser("brief", help="search every line of a brief (text, a .txt file, or - for stdin)")
    b.add_argument("text")
    search_opts(b, 5)
    b.add_argument("--sheet", help="also save a contact sheet of the visual matches")
    b.set_defaults(func=cmd_brief)

    b = sub.add_parser("roughcut", help="build a Premiere rough cut (XML) from a brief")
    b.add_argument("text")
    b.add_argument("--out", required=True, help="where to write the .xml")
    b.add_argument("--media", help="where Backblaze clips used in the cut are downloaded "
                                   "(default: '<xml name> media' next to the xml)")
    b.add_argument("--name", default="Scrubless rough cut")
    b.add_argument("--width", type=int, default=1080)
    b.add_argument("--height", type=int, default=1920)
    b.add_argument("--fps", type=float, default=30)
    b.add_argument("--in", dest="in_", action="append")
    b.add_argument("--min", type=float, default=0.55)
    b.set_defaults(func=cmd_roughcut)

    b = sub.add_parser("get", help="download Backblaze clips (b2:// locations from --paths) to a folder")
    b.add_argument("location", nargs="+")
    b.add_argument("--to", required=True)
    b.set_defaults(func=cmd_get)

    b = sub.add_parser("ls", help="list folders in Backblaze: footage ls b2://<bucket>/<folder>/")
    b.add_argument("where")
    b.set_defaults(func=cmd_ls)

    sub.add_parser("app", help="open the Scrubless app window").set_defaults(func=cmd_app)
    sub.add_parser("serve", help="run the app server only (open http://127.0.0.1:7792)").set_defaults(func=cmd_serve)
    sub.add_parser("list", help="show indexed folders").set_defaults(func=cmd_list)
    sub.add_parser("doctor", help="check GPU, models and Backblaze key").set_defaults(func=cmd_doctor)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
