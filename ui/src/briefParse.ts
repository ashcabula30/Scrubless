// Turn whatever was pasted (a ClickUp table, a spreadsheet, a markdown table) into brief rows.

export type Row = { label: string; script: string; visual: string; text: string }; // text: On-screen text

const SCRIPT_HEAD = /\b(script|vo|voice ?over|dialogue|line|copy|audio)\b/i;
const VISUAL_HEAD = /\b(visuals?|shots?|b-?roll|scene|video)\b/i;
const TEXT_HEAD = /\b(on[- ]?screen|ost|supers?|text overlay|captions?)\b/i;

export const emptyRow = (): Row => ({ label: "", script: "", visual: "", text: "" });

/** Rows of cell texts -> brief rows, using the header row ("Script", "Visual") to find the columns. */
export function rowsFromCells(table: string[][]): Row[] {
  table = table.filter((r) => r.some((c) => c.trim()));
  if (!table.length) return [];
  const headIdx = table.findIndex((r) => r.some((c) => SCRIPT_HEAD.test(c) || VISUAL_HEAD.test(c)));
  const head = headIdx >= 0 ? table[headIdx] : null;
  const width = Math.max(...table.map((r) => r.length));
  let scriptCol = head ? head.findIndex((c) => SCRIPT_HEAD.test(c) && !VISUAL_HEAD.test(c)) : -1;
  let visualCol = head ? head.findIndex((c) => VISUAL_HEAD.test(c) && !TEXT_HEAD.test(c)) : -1;
  const textCol = head ? head.findIndex((c) => TEXT_HEAD.test(c)) : -1;
  if (scriptCol < 0 && visualCol < 0) {
    // No header: Section | Script | Visual, or Script | Visual
    [scriptCol, visualCol] = width >= 3 ? [1, 2] : [0, 1];
  } else if (scriptCol < 0) scriptCol = Math.max(0, visualCol - 1);
  const labelCol = scriptCol > 0 ? scriptCol - 1 : -1;
  const body = headIdx >= 0 ? table.slice(headIdx + 1) : table;
  return body
    .map((r) => ({
      label: labelCol >= 0 ? (r[labelCol] ?? "").trim() : "",
      script: (r[scriptCol] ?? "").trim(),
      visual: visualCol >= 0 ? (r[visualCol] ?? "").trim() : "",
      text: textCol >= 0 ? (r[textCol] ?? "").trim() : "",
    }))
    .filter((r) => r.script || r.visual || r.text);
}

/** Text of an HTML table cell, keeping paragraphs (ClickUp puts each in its own block). */
function cellText(el: Element): string {
  const paras: string[] = [];
  let cur = "";
  const flush = () => {
    if (cur.trim()) paras.push(cur.replace(/[ \t]+/g, " ").trim());
    cur = "";
  };
  const walk = (n: Node) => {
    if (n.nodeType === Node.TEXT_NODE) {
      cur += n.textContent ?? "";
      return;
    }
    if (!(n instanceof Element)) return;
    const tag = n.tagName.toLowerCase();
    if (tag === "br") {
      cur += "\n";
      return;
    }
    const block = /^(p|div|li|h[1-6]|blockquote|pre|ul|ol)$/.test(tag);
    if (block) flush();
    n.childNodes.forEach(walk);
    if (block) flush();
  };
  el.childNodes.forEach(walk);
  flush();
  return paras.join("\n\n");
}

export function rowsFromHtml(html: string): Row[] | null {
  const doc = new DOMParser().parseFromString(html, "text/html");
  const table = doc.querySelector("table");
  if (!table) return null;
  const cells = Array.from(table.querySelectorAll("tr")).map((tr) =>
    Array.from(tr.querySelectorAll(":scope > td, :scope > th")).map(cellText),
  );
  const rows = rowsFromCells(cells);
  return rows.length ? rows : null;
}

/** Tab-separated text (spreadsheets, some table copies), with quoted multi-line cells. */
function parseTsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') {
        cell += '"';
        i++;
      } else if (ch === '"') quoted = false;
      else cell += ch;
    } else if (ch === '"' && cell === "") quoted = true;
    else if (ch === "\t") {
      row.push(cell);
      cell = "";
    } else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i++;
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else cell += ch;
  }
  if (cell || row.length) {
    row.push(cell);
    rows.push(row);
  }
  return rows;
}

function parseMarkdown(text: string): string[][] {
  return text
    .split(/\r?\n/)
    .filter((l) => l.trim().startsWith("|") && !/^\s*\|?\s*:?-{3,}/.test(l))
    .map((l) =>
      l
        .trim()
        .replace(/^\|/, "")
        .replace(/\|$/, "")
        .split("|")
        .map((c) => c.trim().replace(/<br\s*\/?>/gi, "\n")),
    );
}

/** Plain text that is really a table (tabs or markdown pipes) -> rows; otherwise null. */
export function rowsFromTableText(text: string): Row[] | null {
  if (text.includes("\t")) {
    const rows = rowsFromCells(parseTsv(text));
    if (rows.length) return rows;
  }
  if (/^\s*\|.*\|/m.test(text)) {
    const rows = rowsFromCells(parseMarkdown(text));
    if (rows.length) return rows;
  }
  return null;
}
