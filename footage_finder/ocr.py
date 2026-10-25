"""Read a brief table from a screenshot (e.g. a ClickUp doc table), locally.

1. RapidOCR (ONNX, runs on the CPU in a few seconds) finds every line of text and where it is.
2. The table grid is found from its ruled lines (works on dark and light themes). Without visible
   lines, columns come from the header words ("Script", "Visual") and rows from the section labels.
3. Text is dropped into cells; a bigger vertical gap inside a cell starts a new paragraph.
Returns rows: [{"label", "script", "visual"}] with paragraphs separated by a blank line.
"""
import re
from statistics import median

import numpy as np

SCRIPT_HEAD = re.compile(r"\b(script|vo|voice ?over|dialogue|line|copy|audio)\b", re.I)
VISUAL_HEAD = re.compile(r"\b(visuals?|shots?|b-?roll|scene|video)\b", re.I)

_engine = None


def _ocr(img):
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR

        _engine = RapidOCR()
    result, _ = _engine(img)
    boxes = []
    for pts, text, conf in result or []:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        boxes.append({"x0": min(xs), "x1": max(xs), "y0": min(ys), "y1": max(ys), "text": text.strip(), "conf": conf})
    return [b for b in boxes if b["text"]]


def _cluster(values, gap=4):
    """Merge nearby pixel positions (a 2 px line gives 2 rows) into single coordinates."""
    out = []
    for v in sorted(values):
        if out and v - out[-1][-1] <= gap:
            out[-1].append(v)
        else:
            out.append([v])
    return [int(sum(c) / len(c)) for c in out]


def _grid(img):
    """(xs, ys) of the table's vertical and horizontal ruled lines, or ([], [])."""
    import cv2

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.int16)
    bg = int(np.median(gray))
    mask = (np.abs(gray - bg) > 10).astype(np.uint8)
    h, w = mask.shape
    horiz = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(40, w // 4), 1)))
    vert = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(40, h // 6))))
    ys = _cluster(np.where(horiz.sum(axis=1) > w * 0.25)[0])
    xs = _cluster(np.where(vert.sum(axis=0) > h * 0.15)[0])
    return xs, ys


def _lines(boxes):
    """Group OCR boxes in one cell into text lines (top to bottom), then into paragraphs."""
    if not boxes:
        return ""
    boxes = sorted(boxes, key=lambda b: (b["y0"] + b["y1"]) / 2)
    lines = []
    for b in boxes:
        cy = (b["y0"] + b["y1"]) / 2
        if lines and abs(cy - lines[-1]["cy"]) < (b["y1"] - b["y0"]) * 0.5:
            lines[-1]["boxes"].append(b)
        else:
            lines.append({"cy": cy, "boxes": [b]})
    heights = [max(b["y1"] for b in l["boxes"]) - min(b["y0"] for b in l["boxes"]) for l in lines]
    step = median([b["cy"] - a["cy"] for a, b in zip(lines, lines[1:])] or [median(heights) * 1.2])
    paras, cur, prev = [], [], None
    for l in lines:
        text = " ".join(b["text"] for b in sorted(l["boxes"], key=lambda b: b["x0"]))
        if prev is not None and l["cy"] - prev > max(step * 1.6, median(heights) * 1.9):
            paras.append(" ".join(cur))
            cur = []
        cur.append(text)
        prev = l["cy"]
    paras.append(" ".join(cur))
    # OCR sometimes drops the space after a comma ("room,cat").
    tidy = lambda p: re.sub(r"([,;:!?])(?=[A-Za-z])", r"\1 ", re.sub(r"\s+", " ", p)).strip()
    return "\n\n".join(tidy(p) for p in paras if p.strip())


def _roles(header_cells):
    """Map column index -> 'label' | 'script' | 'visual' from the header row text."""
    roles = {}
    for i, t in enumerate(header_cells):
        if VISUAL_HEAD.search(t):
            roles[i] = "visual"
        elif SCRIPT_HEAD.search(t):
            roles[i] = "script"
    n = len(header_cells)
    if "script" not in roles.values():  # no header words: guess by position
        if n >= 3:
            roles = {0: "label", 1: "script", 2: "visual"}
        elif n == 2:
            roles = {0: "script", 1: "visual"}
    for i in range(n):
        roles.setdefault(i, "label" if i < min((k for k, v in roles.items() if v == "script"), default=0) else "other")
    return roles


def _rows_from_cells(table):
    """table: list of rows, each a list of cell texts. Finds the header and builds brief rows."""
    head_i = next((i for i, r in enumerate(table) if any(SCRIPT_HEAD.search(c) or VISUAL_HEAD.search(c) for c in r)), None)
    roles = _roles(table[head_i] if head_i is not None else table[0])
    body = table[head_i + 1:] if head_i is not None else table
    rows = []
    for r in body:
        row = {"label": "", "script": "", "visual": ""}
        for i, text in enumerate(r):
            role = roles.get(i, "other")
            if role in row and text:
                row[role] = (row[role] + "\n\n" + text).strip() if row[role] else text
        if row["script"] or row["visual"]:
            rows.append(row)
    return rows


def read_brief_image(data: bytes):
    """Image bytes (PNG/JPG) -> brief rows."""
    import cv2

    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("That file isn't an image I can read.")
    if img.shape[1] < 640:  # only tiny screenshots get enlarged; enlarging normal ones loses spaces
        f = 640 / img.shape[1]
        img = cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
        boxes = _ocr(img)
    else:
        # RapidOCR's own image loader reads more accurately than a decoded copy (it kept spaces
        # between words that went missing with the OpenCV array).
        boxes = _ocr(data)
    if not boxes:
        raise ValueError("No text found in the image.")
    xs, ys = _grid(img)

    if len(xs) >= 3 and len(ys) >= 2:
        # Ruled table: cells between consecutive lines. Text past the last line (a screenshot
        # cut off mid-row) still counts as one more row.
        bottom = max(b["y1"] for b in boxes)
        if bottom > ys[-1] + 5:
            ys = ys + [int(bottom) + 5]
        table = []
        for r in range(len(ys) - 1):
            row = []
            for c in range(len(xs) - 1):
                inside = [b for b in boxes
                          if xs[c] <= (b["x0"] + b["x1"]) / 2 < xs[c + 1] and ys[r] <= (b["y0"] + b["y1"]) / 2 < ys[r + 1]]
                row.append(_lines(inside))
            table.append(row)
        rows = _rows_from_cells(table)
        if rows:
            return rows

    # No ruled lines: columns from the header words, rows from the labels in the first column.
    heads = [b for b in boxes if SCRIPT_HEAD.fullmatch(b["text"]) or VISUAL_HEAD.fullmatch(b["text"])]
    if not heads:
        raise ValueError("Couldn't find the table's Script / Visual headers in the image.")
    head_y = max(b["y1"] for b in heads)
    cols = sorted(heads, key=lambda b: b["x0"])
    edges = [c["x0"] - 12 for c in cols] + [10 ** 6]
    below = [b for b in boxes if b["y0"] > head_y]
    labels = sorted([b for b in below if b["x1"] < edges[0]], key=lambda b: b["y0"])
    starts = [l["y0"] - 6 for l in labels] or [head_y + 1]
    starts = starts + [10 ** 6]
    table = []
    for r in range(len(starts) - 1):
        in_row = [b for b in below if starts[r] <= b["y0"] < starts[r + 1]]
        label = " ".join(b["text"] for b in in_row if b["x1"] < edges[0])
        row = [label] + [_lines([b for b in in_row if edges[i] <= b["x0"] < edges[i + 1]]) for i in range(len(cols))]
        table.append(row)
    header = [""] + [c["text"] for c in cols]
    return _rows_from_cells([header] + table)
