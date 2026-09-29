/**
 * Snapshot excerpting for `harvest_postings` results — keeps a board's raw
 * snapshot useful (link lines, their URLs, result wording) while bounding
 * its size, so the whole tool result fits within the tool-result cap.
 */

import type { HarvestBoardResult } from './harvestTypes.js';

/** Matches a link line (`- link "..."`). */
const LINK_TAG_RE = /^(\s*)-\s*link\s+"([^"]+)"/;

/** Matches a Playwright child `- /url: <href>` line. */
const CHILD_URL_RE = /^\s*-\s*\/url:\s*(\S+)/;

/** Matches the snapshot's own `- Page URL: <url>` line. */
const PAGE_URL_RE = /^\s*-\s*Page URL:\s*(\S+)/i;

/** Matches result/zero-result/count wording worth keeping. */
const RESULT_TEXT_RE = /\b(?:results?|jobs?|openings?|positions?|matches|treffer|ergebnisse|stellen|documents?|dokumente)\b/i;

/** Max fraction of the post-Page-URL budget result-text lines may claim
 * before link lines get their turn. */
const RESULT_TEXT_SHARE = 0.5;

/** Bytes reserved for JSON envelope growth (escaping, notes) when fitting. */
const RESULT_SAFETY_RESERVE_CHARS = 1500;

/** Fraction of a share usable for text, allowing for JSON escaping growth. */
const ESCAPE_ALLOWANCE = 0.75;

/** Smallest per-board share worth keeping an excerpt for. */
const MIN_EXCERPT_CHARS = 200;

/** Max share-halving rounds while the real serialised size exceeds budget. */
const MAX_SHRINK_ITERATIONS = 6;

/** Note suffix appended when a board's raw snapshot was dropped. */
const OMITTED_NOTE = ' (raw snapshot omitted: result budget exhausted; re-harvest this board alone)';

/** Result of {@link compactSnapshot}. */
export interface CompactedSnapshot {
  text: string;
  truncated: boolean;
  omittedChars: number;
}

/** Indent width of `line`. */
function indentOf(line: string): number {
  return (line.match(/^(\s*)/) as RegExpMatchArray)[1].length;
}

/** Mark the `- /url:` child line of the link at `i`, if any. */
function keepChildUrl(lines: string[], i: number, keep: Set<number>): void {
  const parentIndent = indentOf(lines[i]);
  for (let j = i + 1; j < lines.length; j++) {
    if (lines[j].trim() === '') continue;
    if (indentOf(lines[j]) <= parentIndent) return;
    if (CHILD_URL_RE.test(lines[j])) {
      keep.add(j);
      return;
    }
  }
}

/** Cut `text` to `max` chars without splitting a surrogate pair. */
function hardCap(text: string, max: number): string {
  if (text.length <= max) return text;
  let end = max;
  const code = text.charCodeAt(end - 1);
  if (code >= 0xd800 && code <= 0xdbff) end -= 1;
  return text.slice(0, end);
}

/** Line indices of a snapshot, grouped by what {@link compactSnapshot} keeps. */
interface LineClasses {
  pageUrl: number[][];
  results: number[][];
  groups: number[][];
}

/** Split line indices into the Page URL line(s), result-wording lines and
 * link groups (link line plus its `/url:` child), each as index arrays. */
function classifyLines(lines: string[]): LineClasses {
  const pageUrl: number[][] = [];
  const results: number[][] = [];
  const groups: number[][] = [];
  const claimed = new Set<number>();
  lines.forEach((line, i) => {
    if (!LINK_TAG_RE.test(line)) return;
    const group = new Set<number>([i]);
    keepChildUrl(lines, i, group);
    group.forEach((j) => claimed.add(j));
    groups.push([...group].sort((a, b) => a - b));
  });
  // A link's `/url:` child (e.g. ".../jobs/123") must not also take priority
  // budget on its own, or it would crowd out the link lines it belongs to.
  lines.forEach((line, i) => {
    if (claimed.has(i)) return;
    if (PAGE_URL_RE.test(line)) pageUrl.push([i]);
    else if (RESULT_TEXT_RE.test(line)) results.push([i]);
  });
  return { pageUrl, results, groups };
}

/** Add each whole group not already kept to `keep` in order while it fits
 * `budget`; returns the budget left. */
function fillBudget(lines: string[], groups: number[][], budget: number, keep: Set<number>): number {
  let left = budget;
  for (const group of groups) {
    if (group.every((i) => keep.has(i))) continue;
    const cost = group.reduce((sum, i) => sum + lines[i].length + 1, 0);
    if (cost > left) continue;
    group.forEach((i) => keep.add(i));
    left -= cost;
  }
  return left;
}

/**
 * Reduce `snapshot` to at most `maxChars`, keeping in original order the
 * Page URL line, result-count wording lines and link lines with their
 * `/url:` child. When they exceed `maxChars`, the Page URL is guaranteed
 * first, then result-text lines up to {@link RESULT_TEXT_SHARE} of what is
 * left (so wording cannot crowd out every link), then link lines in document
 * order, then any remaining result-text lines. The result is then hard-capped.
 */
export function compactSnapshot(snapshot: string, maxChars: number): CompactedSnapshot {
  if (snapshot.length <= maxChars) return { text: snapshot, truncated: false, omittedChars: 0 };
  const lines = snapshot.split('\n');
  const keep = new Set<number>();
  const { pageUrl, results, groups } = classifyLines(lines);
  let left = fillBudget(lines, pageUrl, maxChars, keep);
  const resultCap = Math.floor(left * RESULT_TEXT_SHARE);
  left += fillBudget(lines, results, resultCap, keep) - resultCap;
  left = fillBudget(lines, groups, left, keep);
  fillBudget(lines, results, left, keep);
  const kept = lines.filter((_, i) => keep.has(i)).join('\n');
  const text = hardCap(kept, maxChars);
  return { text, truncated: true, omittedChars: snapshot.length - text.length };
}

/** Drop `result`'s raw snapshot, flagging and annotating it. */
function omitSnapshot(result: HarvestBoardResult): HarvestBoardResult {
  return { ...result, rawSnapshot: undefined, rawSnapshotTruncated: true, note: `${result.note}${OMITTED_NOTE}` };
}

/** Re-compact `result`'s raw snapshot to `share` chars. */
function shrinkSnapshot(result: HarvestBoardResult, share: number): HarvestBoardResult {
  const compacted = compactSnapshot(result.rawSnapshot as string, share);
  if (!compacted.truncated) return result;
  return { ...result, rawSnapshot: compacted.text, rawSnapshotTruncated: true };
}

/**
 * Fit every board's raw snapshot into `budgetChars` of total serialised
 * result. Never removes a board entry; a board with no room left loses only
 * its raw snapshot, flagged and noted.
 */
export function fitRawSnapshots(
  results: HarvestBoardResult[],
  budgetChars: number,
  extra: Record<string, unknown> = {},
): HarvestBoardResult[] {
  const holders = results.filter((r) => typeof r.rawSnapshot === 'string').length;
  if (holders === 0) return results;
  const measure = (r: HarvestBoardResult[]): number => JSON.stringify({ results: r, ...extra }).length;
  const stripped = results.map((r) => ({ ...r, rawSnapshot: undefined }));
  const room = budgetChars - measure(stripped) - RESULT_SAFETY_RESERVE_CHARS;
  let share = Math.floor((room / holders) * ESCAPE_ALLOWANCE);
  for (let i = 0; i <= MAX_SHRINK_ITERATIONS && share >= MIN_EXCERPT_CHARS; i++) {
    const fitted = compactAll(results, share);
    if (measure(fitted) <= budgetChars) return fitted;
    share = Math.floor(share / 2);
  }
  return results.map((r) => (typeof r.rawSnapshot === 'string' ? omitSnapshot(r) : r));
}

/** Compact every board's raw snapshot to `share` chars. */
function compactAll(results: HarvestBoardResult[], share: number): HarvestBoardResult[] {
  return results.map((r) => (typeof r.rawSnapshot === 'string' ? shrinkSnapshot(r, share) : r));
}
