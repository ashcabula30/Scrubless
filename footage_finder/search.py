"""Find where a line is spoken: fuzzy text match + meaning match, then word-level timing."""
import re
from dataclasses import dataclass
import numpy as np
from rapidfuzz import fuzz

from .sources import join
from .store import Index

CONTRACTIONS = {
    "won't": "will not", "can't": "cannot", "n't": " not", "'re": " are", "'ll": " will",
    "'ve": " have", "'m": " am", "'d": " would", "it's": "it is", "that's": "that is",
    "what's": "what is", "there's": "there is", "let's": "let us",
}


PLACEHOLDER = re.compile(r"\{[^}]*\}|\[[^\]]*\]")  # {cat's name}, [product]: the creator says the real thing


def normalize(text: str) -> str:
    t = PLACEHOLDER.sub(" ", text).lower().replace("’", "'")
    for k in ("won't", "can't", "it's", "that's", "what's", "there's", "let's"):
        t = t.replace(k, CONTRACTIONS[k])
    for k in ("n't", "'re", "'ll", "'ve", "'m", "'d"):
        t = t.replace(k, CONTRACTIONS[k])
    t = re.sub(r"[^a-z0-9' ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


_EMBEDDERS = {}  # shared by every Searcher, so the app loads each model once


def embedder(model_name):
    if model_name not in _EMBEDDERS:
        from . import tiers
        from .indexer import load_embedder

        _EMBEDDERS[model_name] = load_embedder(model_name, "cuda" if tiers.gpu_info() else "cpu")
    return _EMBEDDERS[model_name]


@dataclass
class Hit:
    base: str  # folder path or b2:// URI the index was built from
    file: str
    start: float
    end: float
    text: str
    score: float
    take: int = 0
    takes: int = 0

    @property
    def location(self) -> str:
        return join(self.base, self.file)


class Searcher:
    """Loads one or more folder indexes once, then answers many queries."""

    def __init__(self, folders):
        self.parts = []
        for f in folders:
            idx = Index(f)
            segs, embs = idx.load_segments()
            if segs:
                self.parts.append((idx.base, idx.get_meta("embed"), segs, embs))

    def _embed(self, model_name, text):
        return embedder(model_name).encode([text], normalize_embeddings=True)[0]

    def find(self, query: str, top=10, min_score=0.55):
        qn = normalize(query)
        if not qn:
            return []
        hits = []
        meaning_query = PLACEHOLDER.sub(" ", query)
        for base, embed_name, segs, embs in self.parts:
            sem = embs @ self._embed(embed_name, meaning_query)
            for i, seg in enumerate(segs):
                # Score the segment alone and joined with the next one (lines often span two).
                cands = [(seg["words"], seg["text"], sem[i])]
                if i + 1 < len(segs) and segs[i + 1]["file"] == seg["file"]:
                    nxt = segs[i + 1]
                    cands.append((seg["words"] + nxt["words"], seg["text"] + " " + nxt["text"],
                                  (sem[i] + sem[i + 1]) / 2))
                for words, text, s in cands:
                    tn = normalize(text)
                    # partial_ratio finds the line inside a longer one; a shorter candidate
                    # ("Oh") must match as a whole or it scores high on almost anything.
                    fz = (fuzz.partial_ratio(qn, tn) if len(tn) >= 0.8 * len(qn) else fuzz.ratio(qn, tn)) / 100
                    score = 0.65 * fz + 0.35 * max(float(s), 0.0)
                    if score < min_score:
                        continue
                    for start, end, matched, r in _windows(qn, words, seg):
                        # Half the text score comes from this exact stretch, so a repeated
                        # take inside one segment is judged on its own words.
                        sc = 0.65 * (fz + r) / 2 + 0.35 * max(float(s), 0.0)
                        if sc >= min_score:
                            hits.append(Hit(base, seg["file"], start, end, matched or text, sc))
        hits = _dedupe(hits)
        _number_takes(hits)
        hits.sort(key=lambda h: -h.score)
        return hits[:top]


def _join(words):
    text = " ".join(w[2] for w in words)
    return re.sub(r"\s+(?=[.,!?;:%])|(?<=\b[ap])\s+(?=\.m\.)", "", text)


def _windows(qn, words, seg):
    """Narrow a match to the word stretches that best line up with the query.

    Returns every non-overlapping stretch close to the best one, so a line said twice
    in one breath gives two takes. Each item: (start, end, text, ratio 0-1).
    """
    if not words:
        return [(seg["start"], seg["end"], None, 0.0)]
    n = len(qn.split())
    scored = []
    for size in range(max(1, n - 3), n + 4):
        for i in range(0, max(1, len(words) - size + 1)):
            j = min(i + size, len(words))
            scored.append((fuzz.ratio(qn, normalize(_join(words[i:j]))), i, j))
    scored.sort(key=lambda x: -x[0])
    best = scored[0][0]
    picked = []
    for r, i, j in scored:
        if r < max(best - 12, 60) and picked:
            break
        if all(j <= a or i >= b for _, a, b in picked):
            picked.append((r, i, j))
    if len(picked) == 1 and picked[0][2] - picked[0][1] >= 0.6 * len(words):
        # The match is most of this stretch: take all of it so no word gets clipped.
        picked = [(picked[0][0], 0, len(words))]
    return [(words[i][0], words[j - 1][1], _join(words[i:j]), r / 100) for r, i, j in picked]


def _dedupe(hits):
    """Keep the best hit where several overlap in the same file."""
    hits.sort(key=lambda h: -h.score)
    kept = []
    for h in hits:
        if not any(k.base == h.base and k.file == h.file and h.start < k.end and k.start < h.end
                   for k in kept):
            kept.append(h)
    return kept


def _number_takes(hits):
    by_file = {}
    for h in hits:
        by_file.setdefault((h.base, h.file), []).append(h)
    for group in by_file.values():
        group.sort(key=lambda h: h.start)
        for i, h in enumerate(group, 1):
            h.take, h.takes = i, len(group)


NOTE = re.compile(r"^\s*(on[- ]screen text|ost|text on screen|super|caption|title card)\s*:", re.I)
SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z{\[\"'])")


def visual_query(show: str) -> str:
    """Shot descriptions in briefs run long; the image model reads ~64 tokens, so search with the
    first sentence (capped) and keep the full note for the editor."""
    first = re.split(r"(?<=[.!?])\s", show.strip(), maxsplit=1)[0]
    return " ".join(first.split()[:28])


def _paras(text: str):
    return [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]


def rows_to_items(rows):
    """Brief table rows ({label, script, visual}, paragraphs split by blank lines) -> search items.

    - Script paragraphs are split into sentences: a whole paragraph never matches one take.
    - Visual paragraph i goes with script paragraph i (ClickUp briefs line them up); extra visual
      paragraphs join the last one. Each sentence of a paragraph shares its visual.
    - "On-screen text: ..." paragraphs are notes for the editor, not shots to search for.
    """
    items = []
    names = [(r.get("label") or "").strip() or "Row" for r in rows]
    seen = {}
    for row, name in zip(rows, names):
        # Briefs repeat section names (Body, Body): number them so every line has its own label.
        seen[name] = seen.get(name, 0) + 1
        label = f"{name} {seen[name]}" if names.count(name) > 1 else name
        script = _paras(row.get("script", ""))
        visual, notes = [], []
        for p in _paras(row.get("visual", "")):
            (notes if NOTE.match(p) else visual).append(p)
        if len(visual) > max(1, len(script)):
            visual = visual[: max(1, len(script)) - 1] + [" ".join(visual[max(1, len(script)) - 1:])]
        row_items = []
        for i, para in enumerate(script or [""]):
            show = visual[i] if i < len(visual) else ""
            for sentence in (SENTENCE.split(para) if para else [""]):
                if sentence.strip() or show:
                    row_items.append({"say": sentence.strip(), "show": show})
        for k, it in enumerate(row_items, 1):
            letter = "abcdefghijklmnopqrstuvwxyz"[min(k, 26) - 1]
            # "Body 2" -> "Body 2a"; "Body" -> "Body a"
            it["label"] = label if len(row_items) == 1 else f"{label}{'' if label[-1].isdigit() else ' '}{letter}"
            it["row"] = label
            it["note"] = " / ".join(notes) if k == 1 else ""
        items.extend(row_items)
    return items


def items_to_rows(items):
    """parse_brief() items (one per text line) -> table rows, for pasting plain text into the table."""
    return [{"label": it["label"], "script": it["say"], "visual": it["show"]} for it in items]


LABEL = re.compile(r"^((?:hook|line|vo|cta|body|scene|a-?roll|b-?roll)\s*\d*)\s*[:\-–—]\s*(.*)$", re.I)
VISUAL = re.compile(r"\b(?:visuals?|b-?roll|shot)\s*:\s*", re.I)


def _clean(s: str) -> str:
    return s.strip().strip("|;,").strip().strip("\"'“”").strip()


def parse_brief(text: str):
    """Pull script lines out of a brief: one per row, or split on ' / '.

    Returns [{"label", "say", "show"}]: "say" is the spoken line, "show" the visual note.
    A row that is only "Visual: ..." attaches to the line above it (or stands alone).
    """
    items = []
    for raw in re.split(r"\n|\s/\s", text):
        line = raw.strip().lstrip("-*• ").strip()
        if not line:
            continue
        label = ""
        m = LABEL.match(line)
        if m:
            label, line = m.group(1).strip(), m.group(2)
            if label.lower().replace("-", "") == "broll":
                line = "Visual: " + line
        parts = VISUAL.split(line, maxsplit=1)
        say = _clean(parts[0])
        show = _clean(parts[1]) if len(parts) > 1 else ""
        if not say and show and items and not items[-1]["show"]:
            items[-1]["show"] = show
            continue
        if len(say.split()) < 2:
            say = ""
        if say or show:
            items.append({"label": label or f"Line {len(items) + 1}", "say": say, "show": show})
    return items
