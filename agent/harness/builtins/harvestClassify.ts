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
import { GOOGLE_HOST_RE, extractDorkPostings, parseDorkTarget } from './harvestDork.js';
import { compactSnapshot } from './harvestExcerpt.js';
import { globToRegExp, resolveLinks, resolveSnapshotBase, sameSiteLinkQualifies, stripHash, type ResolvedLink } from './harvestLinks.js';

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
  /\bbefore you continue to google\b/i,
  /\bbevor (?:sie|du) zu google weiter/i,
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
  'keine ergebnisse',
  'keine treffer',
  'keine jobs gefunden',
  'keine stellen gefunden',
  'keine stellenangebote gefunden',
  'did not match any documents',
  'übereinstimmenden dokumente gefunden',
];

/** Matches an explicit "zero results" count on a NUMBER boundary, so "10
 * results"/"30 results" can never match — the exact substring bug that used
 * to suppress the tier-3 fallback for a board with real, unextracted
 * content. */
const ZERO_RESULTS_RE = /(?<!\d)0\s+(?:results?|jobs?|openings?|positions?|matches?)\b/i;

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

/** Max chars of a needs_review result's raw snapshot excerpt. */
const RAW_SNAPSHOT_MAX_CHARS = 6000;

/** Which known ATS's URL shape `url` matches, or `''` if none does. */
function detectAts(url: string): string {
  const hit = ATS_URL_PATTERNS.find((entry) => entry.pattern.test(url));
  return hit ? hit.ats : '';
}

/** Minimum distinct qualifying URLs the same-site tier requires before it
 * counts at all — a single stray nav/category link must never alone flip a
 * board to `searched`. */
const MIN_SAME_SITE_LINKS = 2;

/** One link paired with the `ats` tier it was matched under, before dedupe. */
interface TieredLink extends ResolvedLink {
  ats: string;
}

/** Dedupe `entries` by resolved URL, trim titles, cap at
 * {@link MAX_POSTINGS_PER_BOARD}, preserving document order. */
function dedupeCap(entries: TieredLink[]): HarvestedPosting[] {
  const seen = new Set<string>();
  const postings: HarvestedPosting[] = [];
  for (const e of entries) {
    const url = e.url.href;
    if (seen.has(url)) continue;
    seen.add(url);
    postings.push({ url, title: e.title.trim(), ats: e.ats });
    if (postings.length >= MAX_POSTINGS_PER_BOARD) break;
  }
  return postings;
}

/** Tier 1: links whose URL matches a known ATS shape. */
function extractAtsPostings(links: ResolvedLink[]): HarvestedPosting[] {
  const entries = links
    .map((l) => ({ ...l, ats: detectAts(l.url.href) }))
    .filter((e) => e.ats !== '');
  return dedupeCap(entries);
}

/** Tier 2: links matching the board's own `postingUrlPattern` glob. */
function extractPatternPostings(links: ResolvedLink[], pattern: string): HarvestedPosting[] {
  const re = globToRegExp(pattern);
  const entries = links.filter((l) => re.test(l.url.href)).map((l) => ({ ...l, ats: 'board-pattern' }));
  return dedupeCap(entries);
}

/** `base`'s hostname, or `''` if `base` fails to parse. */
function safeHostname(base: string): string {
  try {
    return new URL(base).hostname;
  } catch {
    return '';
  }
}

/** Tier 3: the general same-site job-link rule — counts only when at least
 * {@link MIN_SAME_SITE_LINKS} distinct qualifying URLs are found, so one
 * stray nav/category link can never alone flip a board to `searched`. */
function extractSameSitePostings(links: ResolvedLink[], board: HarvestBoardRequest, baseUrl: string): HarvestedPosting[] {
  const baseHost = safeHostname(baseUrl);
  if (baseHost === '') return [];
  const excludeHrefs = new Set([stripHash(baseUrl), stripHash(board.url)]);
  const qualifying = links.filter((l) => sameSiteLinkQualifies(l, baseHost, excludeHrefs));
  const distinct = new Set(qualifying.map((l) => stripHash(l.url.href)));
  if (distinct.size < MIN_SAME_SITE_LINKS) return [];
  return dedupeCap(qualifying.map((l) => ({ ...l, ats: 'board-heuristic' })));
}

/** Human-readable label for the tier that produced `ats`, for the result's `note`. */
function tierLabel(ats: string): string {
  if (ats === 'board-pattern') return "the board's own posting URL pattern";
  if (ats === 'board-heuristic') return 'a general same-site job-link rule';
  if (ats === 'dork-site') return "the dork's site: target domain";
  return "known ATS URL shapes";
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

/** Whether the page explicitly states its search matched nothing — English
 * or German phrasing. Exported for reuse by the location-control retry flow
 * (harvestBoard.ts), which needs the same explicit-empty check to tell a
 * board's location-only control search actually ran and matched nothing
 * from one that merely failed to submit. */
export function isExplicitlyEmpty(text: string): boolean {
  return containsPhrase(text, EMPTY_PHRASES) || ZERO_RESULTS_RE.test(text);
}

/** Prefix of Google's consent host (consent.google.<tld>). */
const GOOGLE_CONSENT_PREFIX = 'consent.';

/** Path prefix of Google's rate-limit interstitial. */
const GOOGLE_SORRY_PATH = '/sorry';

/** Whether `base` is a Google consent (consent.google.<tld>) or rate-limit
 * (google.<tld>/sorry...) interstitial URL. False if `base` fails to parse. */
export function isGoogleInterstitial(base: string): boolean {
  let url: URL;
  try {
    url = new URL(base);
  } catch {
    return false;
  }
  const host = url.hostname.toLowerCase();
  if (host.startsWith(GOOGLE_CONSENT_PREFIX)) return GOOGLE_HOST_RE.test(host.slice(GOOGLE_CONSENT_PREFIX.length));
  return GOOGLE_HOST_RE.test(host) && url.pathname.startsWith(GOOGLE_SORRY_PATH);
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
 * Extract postings from a `browser_snapshot` accessibility tree, trying
 * tiers in order and returning the first that yields anything: (1) known ATS
 * URL shapes; (2) `board.postingUrlPattern`, when set; (3) the general
 * same-site job-link rule, which counts only with ≥{@link MIN_SAME_SITE_LINKS}
 * distinct qualifying URLs. Every candidate link is parsed and resolved by
 * harvestLinks.ts, covering both the same-line and Playwright indented
 * `- /url:` link formats. A link matching no tier is dropped — never guessed at.
 */
function extractPostings(board: HarvestBoardRequest, snapshot: string): HarvestedPosting[] {
  const links = resolveLinks(board, snapshot);
  const atsPostings = extractAtsPostings(links);
  if (atsPostings.length > 0) return atsPostings;
  if (board.postingUrlPattern) {
    const patternPostings = extractPatternPostings(links, board.postingUrlPattern);
    if (patternPostings.length > 0) return patternPostings;
  }
  const base = resolveSnapshotBase(board, snapshot);
  const dorkTarget = parseDorkTarget(base);
  if (dorkTarget) {
    const dorkPostings = extractDorkPostings(links, dorkTarget);
    if (dorkPostings.length > 0) return dorkPostings;
  }
  return extractSameSitePostings(links, board, base);
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
  const postings = extractPostings(board, snapshot);
  if (postings.length > 0) {
    const note = `${postings.length} posting(s) extracted by ${tierLabel(postings[0].ats)}`;
    return { ...base, outcome: 'searched', tier: 'harvest', postings, note };
  }
  if (isGoogleInterstitial(resolveSnapshotBase(board, snapshot))) {
    return blockedResult(board, 'Google consent/rate-limit interstitial blocked the search results from being read', 'wall');
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
  const excerpt = compactSnapshot(snapshot, RAW_SNAPSHOT_MAX_CHARS);
  const truncated = excerpt.truncated ? { rawSnapshotTruncated: true } : {};
  return { ...base, outcome: 'needs_review', tier: '', postings: [], note, rawSnapshot: excerpt.text, ...truncated };
}
