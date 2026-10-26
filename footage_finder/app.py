"""Desktop app: the local server in a background thread, the UI in a native window (pywebview).

Behaves like a normal Windows program: its own taskbar icon, one window (opening it again brings
the existing window forward), remembers its size and position, accepts a footage folder dropped
onto it, and asks before closing while indexing is still running.
"""
import json
import os
import sys
import threading
import time
import urllib.request
from pathlib import Path

from . import server
from .env import DATA_DIR

URL = f"http://127.0.0.1:{server.PORT}/"
TITLE = "Scrubless"
APP_ID = "GoodoStudios.Scrubless"
ICON = Path(__file__).with_name("icon.ico")
GEOMETRY = DATA_DIR / "window.json"


def running() -> bool:
    try:
        with urllib.request.urlopen(URL + "api/status", timeout=1) as r:
            return r.status == 200
    except Exception:
        return False


def _api(path, body=None):
    req = urllib.request.Request(URL + path.lstrip("/"), data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"}, method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


# ---------------------------------------------------------------- Windows bits (ctypes, no extra deps)
def _user32():
    import ctypes

    return ctypes.windll.user32 if sys.platform == "win32" else None


def _find_window():
    u = _user32()
    return u.FindWindowW(None, TITLE) if u else 0


def _bring_to_front(hwnd):
    u = _user32()
    if u and hwnd:
        u.ShowWindow(hwnd, 9)  # SW_RESTORE
        u.SetForegroundWindow(hwnd)


def _set_app_id():
    """Own taskbar group and icon, instead of being grouped with other Python programs."""
    if sys.platform == "win32":
        import ctypes

        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:
            pass


def _set_window_icon(hwnd):
    u = _user32()
    if not (u and hwnd and ICON.exists()):
        return
    for size, which in ((32, 1), (16, 0)):  # ICON_BIG = 1, ICON_SMALL = 0
        h = u.LoadImageW(None, str(ICON), 1, size, size, 0x10)  # IMAGE_ICON, LR_LOADFROMFILE
        if h:
            u.SendMessageW(hwnd, 0x80, which, h)  # WM_SETICON


def _message_box(hwnd, text, title=TITLE) -> bool:
    """Yes/No question in a native dialog; True for Yes."""
    u = _user32()
    if not u:
        return True
    return u.MessageBoxW(hwnd, text, title, 0x4 | 0x30) == 6  # MB_YESNO | MB_ICONWARNING -> IDYES


# ---------------------------------------------------------------- window
def _log_to_file():
    """Started from the launcher there is no console; keep output in a log file instead.
    (The venv's pythonw starter passes the child invisible handles, so stdout isn't None there;
    the launcher sets FF_LOG=1 to say so.)"""
    if os.environ.get("FF_LOG") or sys.stdout is None or sys.stderr is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        log = open(DATA_DIR / "app.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log
        print(f"\n--- Scrubless started {time.strftime('%Y-%m-%d %H:%M:%S')}")


def _load_geometry():
    try:
        g = json.loads(GEOMETRY.read_text(encoding="utf-8"))
        if g.get("width", 0) >= 960 and g.get("height", 0) >= 640:
            return g
    except (FileNotFoundError, ValueError):
        pass
    return {"width": 1360, "height": 880}


def _save_geometry(window):
    try:
        g = {"width": window.width, "height": window.height, "x": window.x, "y": window.y}
        if g["x"] is not None and g["x"] > -10000:  # skip the off-screen position of a minimized window
            GEOMETRY.write_text(json.dumps(g), encoding="utf-8")
    except Exception:
        pass


def _busy_jobs():
    try:
        return [j for j in _api("api/jobs") if j["status"] in ("running", "queued")]
    except Exception:
        return []


def _toast(window, text, err=False):
    window.evaluate_js(
        f"window.dispatchEvent(new CustomEvent('ff-toast', {{detail: {json.dumps({'text': text, 'err': err})}}}))")


def _on_drop(window, e):
    """A folder dropped anywhere on the window gets added to the Library and indexed."""
    files = (e.get("dataTransfer") or {}).get("files") or []
    for f in files:
        path = f.get("pywebviewFullPath")
        if path and os.path.isdir(path):
            try:
                _api("api/sources", {"path": path})
                _toast(window, f"Indexing {Path(path).name}… (see Library)")
            except Exception as ex:
                _toast(window, f"Couldn't add {path}: {ex}", True)


PID_FILE = DATA_DIR / "app.pid"
_mutex = None  # kept open for the life of the process


def _claim_single_instance() -> bool:
    """True if this is the first Scrubless. A named mutex can't race the way a window search can:
    two quick double-clicks used to start two copies that both failed to open a window."""
    global _mutex
    if sys.platform != "win32":
        return True
    import ctypes

    k = ctypes.windll.kernel32
    _mutex = k.CreateMutexW(None, False, "Local\\" + APP_ID)
    return k.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def _defer_to_running_copy() -> bool:
    """Another copy owns the app: bring its window forward. If it never shows one (stuck), end it."""
    for _ in range(40):  # it may still be opening its window: wait up to ~20 s
        hwnd = _find_window()
        if hwnd:
            _bring_to_front(hwnd)
            return True
        time.sleep(0.5)
    try:
        pid = int(PID_FILE.read_text())
        if pid != os.getpid():
            print(f"Earlier copy (pid {pid}) never showed a window; ending it.")
            os.kill(pid, 9)
            time.sleep(1)
    except (FileNotFoundError, ValueError, OSError):
        pass
    return False


SPLASH = """<!doctype html><html><body style="margin:0;height:100vh;display:flex;flex-direction:column;
align-items:center;justify-content:center;gap:18px;font:500 15px 'Google Sans','Segoe UI',sans-serif;color:#cac4d0;
background:radial-gradient(65% 60% at 18% -5%,rgba(124,92,224,.62),transparent 72%),#121214">
<img src="data:image/svg+xml;base64,{logo}" width="88" style="animation:s 1.6s cubic-bezier(.34,1.56,.64,1) infinite alternate">
<div>Starting Scrubless…</div><style>@keyframes s{{from{{transform:rotate(-8deg) scale(.94)}}to{{transform:rotate(8deg) scale(1.04)}}}}</style>
</body></html>"""


def _splash():
    import base64

    logo = Path(__file__).with_name("static") / "logo.svg"
    data = base64.b64encode(logo.read_bytes()).decode() if logo.exists() else ""
    return SPLASH.format(logo=data)


def main():
    import webview
    from webview.dom import DOMEventHandler

    _log_to_file()
    _set_app_id()

    if not _claim_single_instance() and _defer_to_running_copy():
        return
    PID_FILE.write_text(str(os.getpid()))

    if not running():
        threading.Thread(target=server.serve, daemon=True).start()

    # The window opens straight away with a "Starting…" screen; the models take ~10 s to load and
    # a blank wait made it look like nothing happened (so people clicked again).
    g = _load_geometry()
    window = webview.create_window(TITLE, html=_splash(), width=g["width"], height=g["height"], x=g.get("x"),
                                   y=g.get("y"), min_size=(960, 640), background_color="#121214", text_select=True)
    server.WINDOW = window

    def open_app():
        for _ in range(300):  # up to ~60 s
            if running():
                window.load_url(URL)
                return
            time.sleep(0.2)
        window.load_html("<body style='background:#121214;color:#f2b8b5;font:15px Segoe UI;padding:40px'>"
                         f"Scrubless couldn't start its engine. Details are in {DATA_DIR / 'app.log'}</body>")

    def on_shown():
        _set_window_icon(_find_window())
        threading.Thread(target=open_app, daemon=True).start()

    def on_loaded():
        if not (window.get_current_url() or "").startswith(URL):
            return  # the splash screen
        doc = window.dom.document
        doc.events.dragover += DOMEventHandler(lambda e: None, prevent_default=True)
        doc.events.drop += DOMEventHandler(lambda e: _on_drop(window, e), prevent_default=True)

    def on_closing():
        busy = _busy_jobs()
        if busy and not _message_box(_find_window(),
                                     f"{len(busy)} job(s) still running (indexing or a rough cut).\n\n"
                                     "Close anyway? Finished files stay indexed; Update picks up the rest later."):
            return False
        _save_geometry(window)
        return True

    window.events.shown += on_shown
    window.events.loaded += on_loaded
    window.events.closing += on_closing
    storage = DATA_DIR / "webview"  # keeps the brief table, last folders etc. between launches
    storage.mkdir(parents=True, exist_ok=True)
    webview.start(private_mode=False, storage_path=str(storage), icon=str(ICON) if ICON.exists() else None)
