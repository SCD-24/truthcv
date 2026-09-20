/**
 * Snapshot classification for `harvest_postings` — deterministic extraction
 * of postings by ATS URL shape, plus classifying a board's final snapshot
 * into `searched`/`empty`/`blocked`. Split out of harvestPostings.ts; see
 * that module's own doc for the tool's behaviour as a whole.
 *
 * Extraction always runs FIRST in {@link classifySnapshot}: postings found
 * always win over any blocked or empty signal, so an incidental reCAPTCHA
 * footer notice on an otherwise readable page can never suppress real
 * results.
 */

import type { BlockKind, HarvestBoardRequest, HarvestBoardResult, HarvestedPosting } from './harvestTypes.js';

/** Cap on postings returned per board — bounds the structured result's size. */
const MAX_POSTINGS_PER_BOARD = 50;

/** Known ATS posting URL shapes — mirrors the four ATSes `jobfeeds/ats.py`
 * already integrates against and `agent/RUNBOOK.md` names by name. Duplicated
 * here on purpose, exactly as `screenPosting.ts` duplicates its own
 * Python-side value sets. */
const ATS_URL_PATTERNS: ReadonlyArray<{ ats: string; pattern: RegExp }> = [
  { ats: 'greenhouse', pattern: /^https?:\/\/(?:boards|job-boards)\.greenhouse\.io\/[^/\s]+\/jobs\/\d+/i },
  { ats: 'lever', pattern: /^https?:\/\/jobs\.lever\.co\/[^/\s]+\/[^/?#\s]+/i },
  { ats: 'ashby', pattern: /^https?:\/\/jobs\.ashbyhq\.com\/[^/\s]+\/[^/?#\s]+/i },
  { ats: 'personio', pattern: /^https?:\/\/[^./\s]+\.jobs\.personio\.(?:de|com)\/job\/\d+/i },
];

/** Regexes matching a sign-in wall's own wording. Anchored to a GATING
 * phrase ("sign in TO continue/view/...") rather than a bare "sign in"/"log
 * in" substring, which also appears in an ordinary page's persistent nav
 * link and must never alone mark an otherwise-empty page blocked. */
const LOGIN_WALL_PATTERNS: readonly RegExp[] = [
  /\bsign[\s-]?in\s+to\s+(?:continue|view|see|access|apply)\b/i,
  /\blog[\s-]?in\s+to\s+(?:continue|view|see|access|apply)\b/i,
  /\bcreate an account\s+(?:or|to)\s+log[\s-]?in\b/i,
  /\bplease sign in to continue\b/i,
];

/** Regexes matching a consent/cookie interstitial's own wording. */
const CONSENT_WALL_PATTERNS: readonly RegExp[] = [
  /\baccept all cookies\b/i,
  /\bwe value your privacy\b/i,
  /\bmanage (?:cookie|consent) preferences\b/i,
];

/** Regexes matching a bot-check interstitial's own wording — deliberately
 * NOT the bare word "captcha", which also appears in an innocuous reCAPTCHA
 * footer notice on an otherwise fully readable page. */
const BOT_CHECK_PATTERNS: readonly RegExp[] = [
  /\bcomplete the captcha\b/i,
  /\bsolve the captcha\b/i,
  /\bcaptcha to continue\b/i,
  /\bverify you are human\b/i,
  /\bnot a robot\b/i,
  /\bunusual traffic\b/i,
  /\baccess denied\b/i,
  /\benable javascript to continue\b/i,
  /\bchecking your browser\b/i,
  /\bplease wait while we (?:check|verify)\b/i,
];

/** Substrings (lowercase) a board uses to state its search genuinely matched nothing. */
const EMPTY_PHRASES: readonly string[] = [
  'no jobs found',
  'no results found',
  'no matching jobs',
  'no positions found',
  'no openings found',
  'no results match your search',
];

/** Matches an explicit "zero results" count on a NUMBER boundary, so "10
 * results"/"30 results" can never match — the exact substring bug that used
 * to suppress the tier-3 fallback for a board with real, unextracted
 * content. */
const ZERO_RESULTS_RE = /(?<!\d)0\s+(?:results?|jobs?|openings?|positions?|matches?)\b/i;

/** Match one accessibility-tree link line and capture its title and URL. */
const LINK_LINE_RE = /-\s*link\s+"([^"]+)"[^\n]*?(https?:\/\/\S+)/gi;

/** Matches ANY accessibility-tree link line, regardless of its URL shape —
 * used only by {@link hasSubstantiveContent} to tell a page that plainly has
 * content (just none of it ATS-shaped) from a bare interstitial, never for
 * extraction itself. Deliberately no `g` flag: a shared `g`-flagged regex
 * would carry stateful `lastIndex` across the separate `.test()` calls this
 * module makes on it. */
const ANY_LINK_LINE_RE = /-\s*link\s+"[^"]+"/i;

/** Below this snapshot length, with no link line at all, a page is deemed to
 * show no substantive content of its own — see {@link hasSubstantiveContent}. */
const MIN_SUBSTANTIVE_SNAPSHOT_LENGTH = 200;

/** Which known ATS's URL shape `url` matches, or `''` if none does. */
function detectAts(url: string): string {
  const hit = ATS_URL_PATTERNS.find((entry) => entry.pattern.test(url));
  return hit ? hit.ats : '';
}

/** Whether `text` (case-insensitively) contains any of `phrases`. */
function containsPhrase(text: string, phrases: readonly string[]): boolean {
  const lower = text.toLowerCase();
  return phrases.some((phrase) => lower.includes(phrase));
}

/** Whether `text` matches any of `patterns`. Exported for reuse by
 * harvestNavigate.ts's own net-error classification. */
export function matchesAny(text: string, patterns: readonly RegExp[]): boolean {
  return patterns.some((re) => re.test(text));
}

/** Whether the page explicitly states its search matched nothing. */
function isExplicitlyEmpty(text: string): boolean {
  return containsPhrase(text, EMPTY_PHRASES) || ZERO_RESULTS_RE.test(text);
}

/** Which kind of unreadable wall `text` shows, or `undefined` if none. */
function detectWallKind(text: string): 'login' | 'wall' | undefined {
  if (matchesAny(text, LOGIN_WALL_PATTERNS)) return 'login';
  if (matchesAny(text, CONSENT_WALL_PATTERNS) || matchesAny(text, BOT_CHECK_PATTERNS)) return 'wall';
  return undefined;
}

/** Whether `snapshot` plainly shows content of its own — any link line at
 * all, or simply a long snapshot — as opposed to a bare interstitial. A
 * consent/bot-check phrase on a page that also shows real content must never
 * discard that content by classifying the page `blocked`; see
 * {@link classifySnapshot}. */
function hasSubstantiveContent(snapshot: string): boolean {
  return ANY_LINK_LINE_RE.test(snapshot) || snapshot.length >= MIN_SUBSTANTIVE_SNAPSHOT_LENGTH;
}

/** Build a `blocked` {@link HarvestBoardResult} for `board`. `blockKind` is
 * left `undefined` when the caller has none to give — see
 * `HarvestBoardResult.blockKind` for what an absent one means. */
export function blockedResult(board: HarvestBoardRequest, note: string, blockKind?: BlockKind): HarvestBoardResult {
  return { board: board.board, url: board.url, outcome: 'blocked', tier: '', postings: [], note, blockKind };
}

/**
 * Extract postings from a `browser_snapshot` accessibility tree by URL-shape
 * heuristics: every `link "title" ... https://...` line whose URL matches a
 * known ATS shape is kept, in document order, de-duplicated by URL, capped at
 * {@link MAX_POSTINGS_PER_BOARD}. A link to an unrecognised URL shape is
 * dropped — never guessed at.
 */
function extractPostings(snapshot: string): HarvestedPosting[] {
  const seen = new Set<string>();
  const postings: HarvestedPosting[] = [];
  for (const match of snapshot.matchAll(LINK_LINE_RE)) {
    const [, title, rawUrl] = match;
    const url = rawUrl.replace(/[).,]+$/, '');
    const ats = detectAts(url);
    if (!ats || seen.has(url)) continue;
    seen.add(url);
    postings.push({ url, title: title.trim(), ats });
    if (postings.length >= MAX_POSTINGS_PER_BOARD) break;
  }
  return postings;
}

/**
 * Classify a board's final snapshot into its {@link HarvestBoardResult}.
 * Extraction runs FIRST: postings found always win, even over an incidental
 * blocked/empty phrase elsewhere on the page. Only once extraction found
 * nothing does an explicit "no results" statement, then a login wall, get a
 * say. A consent/bot-check phrase ({@link detectWallKind}'s `'wall'`) blocks
 * ONLY when the page also shows no substantive content of its own
 * ({@link hasSubstantiveContent}) — a cookie banner sitting over a readable
 * careers page must never discard that page's content by reporting it
 * `blocked` with no raw snapshot; when the page does show content, this
 * falls through to the same tier-3 last-resort case as an unrecognised page,
 * with the raw snapshot attached so the model can still recover it.
 */
export function classifySnapshot(board: HarvestBoardRequest, snapshot: string): HarvestBoardResult {
  const base = { board: board.board, url: board.url };
  const postings = extractPostings(snapshot);
  if (postings.length > 0) {
    return { ...base, outcome: 'searched', tier: 'harvest', postings, note: `${postings.length} posting(s) extracted by URL-shape heuristics` };
  }
  if (isExplicitlyEmpty(snapshot)) {
    return { ...base, outcome: 'empty', tier: '', postings: [], note: 'search ran; the board reported no matches' };
  }
  const wallKind = detectWallKind(snapshot);
  if (wallKind === 'login') {
    return { ...base, outcome: 'blocked', tier: '', postings: [], blockKind: 'login', note: 'page requires sign-in: a login wall blocked results from being read' };
  }
  if (wallKind === 'wall' && !hasSubstantiveContent(snapshot)) {
    return { ...base, outcome: 'blocked', tier: '', postings: [], blockKind: 'wall', note: 'page unreadable: CAPTCHA or a consent/bot-check interstitial blocked results from being read' };
  }
  const note = wallKind === 'wall'
    ? 'a consent/bot-check phrase was seen, but the page also shows substantive content of its own; raw snapshot attached for manual review'
    : 'no recognised posting URLs found; raw snapshot attached for manual review';
  return { ...base, outcome: 'empty', tier: '', postings: [], note, rawSnapshot: snapshot };
}
