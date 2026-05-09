export interface PrdAnchorMatch {
  start: number;
  end: number;
  text: string;
  strategy: "exact" | "quote" | "line" | "token";
}

const NO_ANCHOR_LABELS = new Set(["", "(未标注位置)", "未标注位置", "-"]);

export function findPrdAnchorMatch(
  prd: string,
  anchor: string | undefined,
  evidence?: string,
): PrdAnchorMatch | null {
  if (!prd) return null;
  const cleanedAnchor = normalizeAnchor(anchor);
  const exact = findCandidate(prd, cleanedAnchor);
  if (exact) return { ...exact, strategy: "exact" };

  const quote = findCandidate(prd, normalizeAnchor(evidence));
  if (quote) return { ...quote, strategy: "quote" };

  const line = findLineReference(prd, cleanedAnchor);
  if (line) return line;

  for (const token of anchorTokens(cleanedAnchor)) {
    const found = findCandidate(prd, token);
    if (found) return { ...found, strategy: "token" };
  }
  return null;
}

export function getPrdAnchorSnippet(
  prd: string,
  match: PrdAnchorMatch | null,
  contextChars = 72,
): string {
  if (!prd || !match) return "";
  const radius = Math.max(0, contextChars);
  const start = Math.max(0, match.start - radius);
  const end = Math.min(prd.length, match.end + radius);
  const prefix = start > 0 ? "…" : "";
  const suffix = end < prd.length ? "…" : "";
  return `${prefix}${prd.slice(start, end).replace(/\s+/g, " ").trim()}${suffix}`;
}

export function getPrdAnchorLineLabel(
  prd: string,
  match: PrdAnchorMatch | null,
): string {
  if (!prd || !match) return "";
  const startLine = countLines(prd.slice(0, match.start));
  const endLine = startLine + countNewlines(prd.slice(match.start, match.end));
  return startLine === endLine ? `第 ${startLine} 行` : `第 ${startLine}-${endLine} 行`;
}

function normalizeAnchor(value: string | undefined): string {
  const text = (value ?? "")
    .trim()
    .replace(/^[↳→\-·•]+\s*/, "")
    .replace(/\s+/g, " ");
  return NO_ANCHOR_LABELS.has(text) ? "" : text;
}

function findCandidate(
  prd: string,
  candidate: string,
): Omit<PrdAnchorMatch, "strategy"> | null {
  const text = candidate.trim();
  if (text.length < 2) return null;
  const idx = prd.indexOf(text);
  if (idx >= 0) return { start: idx, end: idx + text.length, text };
  const flexible = findWhitespaceFlexibleCandidate(prd, text);
  if (flexible) return flexible;
  return null;
}

function findWhitespaceFlexibleCandidate(
  prd: string,
  candidate: string,
): Omit<PrdAnchorMatch, "strategy"> | null {
  const compact = candidate.replace(/\s+/g, "");
  if (compact.length < 2 || compact.length > 120) return null;
  const pattern = Array.from(compact).map(escapeRegExp).join("\\s*");
  const match = new RegExp(pattern, "u").exec(prd);
  if (!match) return null;
  return {
    start: match.index,
    end: match.index + match[0].length,
    text: match[0],
  };
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function findLineReference(prd: string, anchor: string): PrdAnchorMatch | null {
  const match = anchor.match(/(?:line|第)\s*(\d+)\s*(?:[-~—至到]\s*(\d+))?\s*(?:行)?/i);
  if (!match) return null;
  const startLineNo = Number(match[1]);
  const parsedEndLineNo = match[2] ? Number(match[2]) : startLineNo;
  if (!Number.isFinite(startLineNo) || startLineNo <= 0) return null;
  if (!Number.isFinite(parsedEndLineNo) || parsedEndLineNo <= 0) return null;
  const endLineNo = Math.max(startLineNo, parsedEndLineNo);

  let cursor = 0;
  let rangeStart = -1;
  let rangeEnd = -1;
  const rangeLines: string[] = [];
  const lines = prd.split(/\r?\n/);
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i] ?? "";
    const lineNo = i + 1;
    const lineEnd = cursor + line.length;
    if (lineNo >= startLineNo && lineNo <= endLineNo) {
      if (rangeStart < 0) rangeStart = cursor;
      rangeEnd = lineEnd;
      rangeLines.push(line);
    }
    cursor = lineEnd + 1;
  }
  if (rangeStart >= 0 && rangeEnd >= rangeStart) {
    const text = rangeLines.join("\n").trim() || rangeLines.join("\n");
    return { start: rangeStart, end: rangeEnd, text, strategy: "line" };
  }
  return null;
}

function anchorTokens(anchor: string): string[] {
  if (!anchor) return [];
  const tokens = anchor
    .split(/[\s,，;；:：、/／>＞|｜()[\]【】「」"'“”‘’]+/u)
    .map((token) => token.trim())
    .filter((token) => token.length >= 2)
    .filter((token) => !["PRD", "prd", "位置", "章节", "line"].includes(token));
  return Array.from(new Set(tokens)).sort((a, b) => b.length - a.length);
}

function countLines(text: string): number {
  return countNewlines(text) + 1;
}

function countNewlines(text: string): number {
  return (text.match(/\n/g) ?? []).length;
}
