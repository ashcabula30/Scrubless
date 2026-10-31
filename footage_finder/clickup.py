"""Read briefs from ClickUp (read-only) with the user's personal API token.

Goodo briefs live in the parent task's description as a markdown table:
    |  | Script | Visual | On-screen text |
The "Video Editing" subtask assigned to the editor has an empty description, so a subtask falls
back to its parent.
"""
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from .env import DATA_DIR

API = "https://api.clickup.com/api/v2"
TOKEN_FILE = DATA_DIR / "clickup.json"
# Statuses where an editor would pull a brief (others are before briefing or after delivery).
ACTIVE = {"ready to edit", "editing", "internal review edits", "client revisions", "export versions",
          "ready for editing queue", "ready for creator"}


def load_token():
    try:
        return json.loads(TOKEN_FILE.read_text(encoding="utf-8")).get("token", "").strip()
    except (FileNotFoundError, ValueError):
        return ""


def save_token(token: str):
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps({"token": token.strip()}), encoding="utf-8")


def _get(path, params=None, token=None):
    token = token or load_token()
    if not token:
        raise ValueError("Add your ClickUp API token in Settings first.")
    url = API + path + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
    req = urllib.request.Request(url, headers={"Authorization": token})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise ValueError("ClickUp didn't accept the token. Check it in Settings.")
        if e.code == 404:
            raise ValueError("ClickUp couldn't find that task (or the token can't see it).")
        raise ValueError(f"ClickUp error {e.code}")
    except urllib.error.URLError as e:
        raise ValueError(f"Can't reach ClickUp: {e.reason}")


def whoami(token=None):
    return _get("/user", token=token)["user"]


def task_id_from(link_or_id: str) -> str:
    """Task id from a ClickUp link (app.clickup.com/t/<id> or /t/<workspace>/<id>) or a bare id."""
    s = link_or_id.strip()
    m = re.search(r"/t/(?:\d+/)?([A-Za-z0-9_-]+)", s)
    return m.group(1) if m else s


def get_task(task_id):
    return _get(f"/task/{task_id}", {"include_markdown_description": "true"})


def _cells(line):
    line = line.strip().strip("|")
    parts = re.split(r"(?<!\\)\|", line)
    return [re.sub(r"<br\s*/?>", "\n", p.replace("\\|", "|")).strip() for p in parts]


def table_rows(markdown: str):
    """The first markdown table with a Script/Visual header, as brief rows (or [])."""
    from .ocr import SCRIPT_HEAD, VISUAL_HEAD, _rows_from_cells

    tables, cur = [], []
    for line in (markdown or "").splitlines():
        if line.lstrip().startswith("|"):
            cur.append(line)
        elif cur:
            tables.append(cur)
            cur = []
    if cur:
        tables.append(cur)
    for t in tables:
        rows = [_cells(l) for l in t if not re.match(r"^\s*\|?\s*:?-{3,}", l.replace(" ", ""))]
        if rows and any(SCRIPT_HEAD.search(c) or VISUAL_HEAD.search(c) for c in rows[0]):
            return _rows_from_cells(rows)
    return []


def brief(link_or_id: str):
    """Rows of the brief behind a task link; subtasks fall back to their parent's description."""
    task = get_task(task_id_from(link_or_id))
    rows, source = table_rows(task.get("markdown_description")), task
    if not rows and task.get("parent"):
        source = get_task(task["parent"])
        rows = table_rows(source.get("markdown_description"))
    if not rows:
        raise ValueError(f"No brief table (Script / Visual columns) in “{source.get('name')}”.")
    client = (source.get("list") or {}).get("name", "").replace(" Project View", "")
    return {"rows": rows, "task": {"name": source["name"], "url": source.get("url"), "client": client}}


def my_tasks():
    """The user's open tasks in editing statuses, named by their parent asset ("October Asset 14")."""
    user = whoami()
    teams = _get("/team")["teams"]
    tasks = []
    for team in teams:
        page = 0
        while True:
            r = _get(f"/team/{team['id']}/task", {"assignees[]": [user["id"]], "subtasks": "true",
                                                  "include_closed": "false", "order_by": "updated", "page": page})
            tasks += [t for t in r.get("tasks", []) if (t.get("status") or {}).get("status", "").lower() in ACTIVE]
            if r.get("last_page", True) or not r.get("tasks"):
                break
            page += 1
    parents = {t["parent"] for t in tasks if t.get("parent")}

    def safe_parent_name(pid):
        try:
            return get_task(pid).get("name", "")
        except Exception:
            return ""

    with ThreadPoolExecutor(8) as pool:
        names = dict(zip(parents, pool.map(safe_parent_name, parents)))
    return [{"id": t["id"], "url": t.get("url"),
             "name": names.get(t.get("parent")) or t["name"],
             "subtask": t["name"] if t.get("parent") else "",
             "client": (t.get("list") or {}).get("name", "").replace(" Project View", ""),
             "status": (t.get("status") or {}).get("status", ""),
             "due": int(t["due_date"]) if t.get("due_date") else None} for t in tasks]
