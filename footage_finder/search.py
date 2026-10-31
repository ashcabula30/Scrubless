"""Find where a line is spoken: fuzzy text match + meaning match, then word-level timing."""
import re
from dataclasses import dataclass
import numpy as np
from rapidfuzz import fuzz, process

from .sources import join
from .store import Index

CONTRACTIONS = {
    "won't": "will not", "can't": "cannot", "n't": " not", "'re": " are", "'ll": " will",
    "'ve": " have", "'m": " am", "'d": " would", "it's": "it is", "that's": "that is",
    "what's": "what is", "there's": "there is", "let's": "let us",
    "he's": "he is", "she's": "she is", "it'll": "it will", "they'll": "they will",
    "you'll": "you will", "we'll": "we will", "who's": "who is", "how's": "how is",
    "where's": "where is", "what're": "what are", "y'all": "you all", "ain't": "is not",
}


PLACEHOLDER = re.compile(r"\{[^}]*\}|\[[^\]]*\]")  # {cat's name}, [product]: the creator says the real thing


def normalize(text: str) -> str:
    t = PLACEHOLDER.sub(" ", text).lower().replace("’", "'").replace("“", '"').replace("”", '"').replace("—", " ").replace("–", " ")
    for k in ("won't", "can't", "it's", "that's", "what's", "there's", "let's", "he's", "she's", "who's", "how's", "where's", "what're", "y'all", "ain't"):
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


def _format_query(model_name: str, text: str) -> str:
    """BGE models require an instruction prefix on queries for accurate retrieval."""
    if "bge" in (model_name or "").lower():
        return f"Represent this sentence for searching relevant passages: {text}"
    return text


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


_QUERY_CACHE = {}


class Searcher:
    """Loads one or more folder indexes once, then answers many queries."""

    def __init__(self, folders):
        self.parts = []
        for f in folders:
            idx = Index(f)
            segs, embs = idx.load_segments()
            if segs:
                self.parts.append(_prepare(idx.base, idx.get_meta("embed"), segs, embs))

    def _embed(self, model_name, text):
        cache_key = (model_name, text)
        if cache_key not in _QUERY_CACHE:
            if len(_QUERY_CACHE) > 1024:
                _QUERY_CACHE.clear()
            _QUERY_CACHE[cache_key] = embedder(model_name).encode(
                [_format_query(model_name, text)], normalize_embeddings=True
            )[0]
        return _QUERY_CACHE[cache_key]

    def _embed_batch(self, model_name, texts):
        if not texts:
            return np.zeros((0, 1024), dtype=np.float32)
        uncached = [t for t in texts if (model_name, t) not in _QUERY_CACHE]
        if uncached:
            formatted = [_format_query(model_name, t) for t in uncached]
            computed = embedder(model_name).encode(formatted, normalize_embeddings=True, batch_size=32)
            if len(_QUERY_CACHE) + len(uncached) > 1024:
                _QUERY_CACHE.clear()
            for t, emb in zip(uncached, computed):
                _QUERY_CACHE[(model_name, t)] = emb
        return np.stack([_QUERY_CACHE[(model_name, t)] for t in texts])

    def find(self, query: str, top=10, min_score=0.55, q_emb_cached=None):
        qn = normalize(query)
        if not qn:
            return []
        hits = []
        meaning_query = PLACEHOLDER.sub(" ", query)
        q_emb = q_emb_cached if q_emb_cached is not None else {}
        for p in self.parts:
            segs, nxt = p["segs"], p["nxt"]
            if p["embed"] not in q_emb:
                q_emb[p["embed"]] = self._embed(p["embed"], meaning_query)
            sem = p["embs"] @ q_emb[p["embed"]]
            sem_next = np.append(sem[1:], 0.0)
            # Each segment alone, and joined with the next one in the same clip (lines often span two).
            for texts, lens, s_vec, joined in ((p["norms"], p["lens"], sem, False),
                                               (p["pair_norms"], p["pair_lens"], (sem + sem_next) / 2, True)):
                # partial_ratio finds the line inside a longer one; a shorter candidate ("Oh")
                # must match as a whole or it scores high on almost anything.
                partial = process.cdist([qn], texts, scorer=fuzz.partial_ratio)[0]
                if joined:
                    # Joined pair norms are virtually always longer than the query; ratio is redundant
                    fz = partial / 100
                else:
                    whole = process.cdist([qn], texts, scorer=fuzz.ratio)[0]
                    fz = np.where(lens >= 0.8 * len(qn), partial, whole) / 100
                score = 0.65 * fz + 0.35 * np.maximum(s_vec, 0.0)
                if joined:
                    score[~nxt] = -1.0
                for i in np.nonzero(score >= min_score)[0]:
                    seg = segs[i]
                    if joined:
                        after = segs[i + 1]
                        words, nwords = seg["words"] + after["words"], seg["nwords"] + after["nwords"]
                        text = seg["text"] + " " + after["text"]
                    else:
                        words, nwords, text = seg["words"], seg["nwords"], seg["text"]
                    s = max(float(s_vec[i]), 0.0)
                    for start, end, matched, r in _windows(qn, words, nwords, seg):
                        # Half the text score comes from this exact stretch, so a repeated
                        # take inside one segment is judged on its own words.
                        sc = 0.65 * (fz[i] + r) / 2 + 0.35 * s
                        if sc >= min_score:
                            hits.append(Hit(p["base"], seg["file"], start, end, matched or text, float(sc)))
        hits = _dedupe(hits)
        _number_takes(hits)
        hits.sort(key=lambda h: -h.score)
        return hits[:top]

    def find_batch(self, queries: list[str], top=10, min_score=0.55):
        """Search multiple lines in a single batched model forward pass (e.g. for brief tables)."""
        if not queries:
            return []
        q_embs_by_model = {}
        for p in self.parts:
            m = p["embed"]
            if m not in q_embs_by_model:
                clean_queries = [PLACEHOLDER.sub(" ", q) for q in queries]
                q_embs_by_model[m] = self._embed_batch(m, clean_queries)

        results = []
        for idx, q in enumerate(queries):
            if not q.strip():
                results.append([])
                continue
            q_emb = {m: embs[idx] for m, embs in q_embs_by_model.items()}
            results.append(self.find(q, top, min_score, q_emb_cached=q_emb))
        return results


def _join(words):
    text = " ".join(w[2] for w in words)
    return re.sub(r"\s+(?=[.,!?;:%])|(?<=\b[ap])\s+(?=\.m\.)", "", text)


def _prepare(base, embed, segs, embs):
    """Normalise every transcript line once at load, so a search only scores (it used to
    re-normalise ~16,000 strings per query)."""
    nxt = np.array([i + 1 < len(segs) and segs[i + 1]["file"] == s["file"] for i, s in enumerate(segs)], bool)
    norms = [normalize(s["text"]) for s in segs]
    pair_norms = [normalize(s["text"] + " " + segs[i + 1]["text"]) if nxt[i] else "" for i, s in enumerate(segs)]
    for s in segs:
        s["nwords"] = [normalize(w[2]) for w in s["words"]]
    return {"base": base, "embed": embed, "segs": segs, "embs": embs, "nxt": nxt,
            "norms": norms, "lens": np.array([len(t) for t in norms]),
            "pair_norms": pair_norms, "pair_lens": np.array([len(t) for t in pair_norms])}


def _windows(qn, words, nwords, seg):
    """Narrow a match to the word stretches that best line up with the query.

    Returns every non-overlapping stretch close to the best one, so a line said twice
    in one breath gives two takes. Each item: (start, end, text, ratio 0-1).
    nwords: the words already normalised (joining them equals normalising the joined text).
    """
    if not words:
        return [(seg["start"], seg["end"], None, 0.0)]
    n = len(qn.split())
    min_size = max(1, n - 3)
    max_size = min(len(words), max(n + 6, int(n * 1.6)))
    scored = []
    for size in range(min_size, max_size + 1):
        for i in range(0, max(1, len(words) - size + 1)):
            j = min(i + size, len(words))
            cand = " ".join(w for w in nwords[i:j] if w)
            if not cand:
                continue
            r = fuzz.ratio(qn, cand)
            ts = fuzz.token_set_ratio(qn, cand)
            # Combined score: token_set ensures key phrase words are covered; ratio rewards tightness
            comb = 0.45 * r + 0.55 * ts
            scored.append((comb, i, j))
    if not scored:
        return [(seg["start"], seg["end"], None, 0.0)]
    scored.sort(key=lambda x: -x[0])
    best = scored[0][0]
    picked = []
    for sc, i, j in scored:
        if sc < max(best - 12, 60) and picked:
            break
        if all(j <= a or i >= b for _, a, b in picked):
            picked.append((sc, i, j))
    if len(picked) == 1 and picked[0][2] - picked[0][1] >= 0.7 * len(words):
        # The match is most of this stretch: take all of it so no word gets clipped.
        picked = [(picked[0][0], 0, len(words))]
    return [(words[i][0], words[j - 1][1], _join(words[i:j]), sc / 100) for sc, i, j in picked]


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
        if (row.get("text") or "").strip():  # the On-screen text column
            notes.append("On-screen text: " + " ".join(row["text"].split()))
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
    return [{"label": it["label"], "script": it["say"], "visual": it["show"], "text": ""} for it in items]


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
