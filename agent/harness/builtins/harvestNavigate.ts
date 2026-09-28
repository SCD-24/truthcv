/**
 * Navigation safety and search-box driving for `harvest_postings` — refusing
 * an obvious sign-in URL before ever navigating to it, classifying a
 * navigation failure without over-claiming a board is dead, and typing a
 * board's keywords into its detected search box. Split out of
 * harvestPostings.ts; see that module's own doc for the tool's behaviour as
 * a whole.
 */

import { blockedResult, matchesAny } from './harvestClassify.js';
import { isLocationFieldLine } from './harvestLocation.js';
import type { BlockKind, BrowserToolCall, HarvestBoardRequest, HarvestBoardResult } from './harvestTypes.js';

/** URL path segments unambiguously naming a sign-in/authentication flow.
 * Deliberately narrow (whole path segments, common ATS/OAuth terms) so an
 * ordinary careers/search URL is never mistaken for one. Includes both the
 * hyphenated (`sign-in`) and Rails/Devise-standard underscored (`sign_in`)
 * spellings — `/users/sign_in` is that stack's standard path, and a
 * hyphen-only pattern previously missed it entirely. */
const SIGN_IN_URL_RE = /\/(?:login|log-in|signin|sign-in|sign_in|sso|oauth2?|authorize|auth)(?:[/?#]|$)/i;

/** A query-STRING parameter whose entire value names a sign-in flow, e.g.
 * `?action=login` — distinct from {@link SIGN_IN_URL_RE}, which only ever
 * matches a whole PATH segment and so never saw a login signal carried in
 * the query string. Anchored full-value match so an ordinary value merely
 * containing the word (`loginpage-promo`) never matches. */
const SIGN_IN_QUERY_VALUE_RE = /^(?:login|log-in|signin|sign-in|sign_in)$/i;

/** Regexes matching a Chromium DNS/connection-class net error — the narrow
 * subset of navigation failures that mean a URL genuinely could not be
 * reached at all, as opposed to a merely SLOW but reachable board whose
 * navigation timed out after actually connecting. Only these map to
 * `blockKind: 'unreachable'`; see {@link isUnreachableNavigationError}. */
const UNREACHABLE_NET_ERROR_PATTERNS: readonly RegExp[] = [
  /ERR_NAME_NOT_RESOLVED/i,
  /ERR_CONNECTION_REFUSED/i,
  /ERR_CONNECTION_RESET/i,
  /ERR_CONNECTION_CLOSED/i,
  /ERR_CONNECTION_FAILED/i,
  /ERR_ADDRESS_UNREACHABLE/i,
  /ERR_INTERNET_DISCONNECTED/i,
  /ERR_DNS_TIMED_OUT/i,
  /ERR_NETWORK_CHANGED/i,
  /getaddrinfo ENOTFOUND/i,
  /ECONNREFUSED/i,
];

/** Regexes matching a Chromium navigation-timeout-class error — distinct
 * from {@link UNREACHABLE_NET_ERROR_PATTERNS}: the page WAS reachable (or at
 * least attempted) but did not finish loading within the timeout, rather
 * than a confirmed DNS/connection failure. Retried once; a second timeout
 * maps to `blockKind: 'timeout'`. */
const TIMEOUT_NAV_ERROR_PATTERNS: readonly RegExp[] = [
  /Timeout \d+ms exceeded/i,
  /ERR_TIMED_OUT/i,
  /ERR_CONNECTION_TIMED_OUT/i,
  /did not load/i,
];

/** Match a searchbox/textbox line and capture its `[ref=...]` element ref. */
const SEARCH_BOX_RE = /-\s*(?:searchbox|textbox)[^\n[]*\[ref=([^\]]+)]/i;

/** Strips every `[ref=...]` token from a snapshot before comparing two
 * snapshots for an actual content change — refs are reassigned on every
 * `browser_snapshot` call, so comparing raw text would see a "change" even
 * when nothing on the page actually moved. */
const REF_TOKEN_RE = /\[ref=[^\]]+]/g;

/** An input-field snapshot line's trailing `: <value>` — Playwright's aria
 * snapshot renders a filled searchbox/textbox/combobox as
 * `- textbox "Search": backend`, so merely TYPING the keywords changes the
 * snapshot even when the submit itself never did anything. Captures the
 * line without that value so it can be dropped before comparing. Applied
 * after {@link REF_TOKEN_RE}. */
const FIELD_VALUE_RE = /^(\s*-\s*(?:searchbox|textbox|combobox)\b[^\n]*?):\s[^\n]*$/gim;

/** Seconds to wait, via `browser_wait_for`, for a client-side search submit
 * that has not visibly changed the page yet — some boards debounce or
 * animate their results in rather than updating synchronously. */
const SEARCH_SETTLE_SECONDS = 2;

/** The `[ref=...]` of the first line in `snapshot` that looks like a plain
 * keyword box — a searchbox/textbox line, in document order, SKIPPING any
 * line {@link isLocationFieldLine} names a location field, so a board that
 * lists its location field before its keyword box never has the location
 * field mistaken for the keyword box. */
function findKeywordFieldRef(snapshot: string): string | undefined {
  for (const line of snapshot.split('\n')) {
    if (isLocationFieldLine(line)) continue;
    const match = SEARCH_BOX_RE.exec(line);
    if (match) return match[1];
  }
  return undefined;
}

/** Whether `url` looks like a sign-in/login/auth flow rather than an
 * ordinary board page — by its path, or by a query-string parameter whose
 * value names one (`?action=login`). */
export function isSignInUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    if (SIGN_IN_URL_RE.test(parsed.pathname)) return true;
    for (const value of parsed.searchParams.values()) {
      if (SIGN_IN_QUERY_VALUE_RE.test(value)) return true;
    }
    return false;
  } catch {
    return SIGN_IN_URL_RE.test(url);
  }
}

/**
 * Refuse to navigate an obvious sign-in/login/auth URL — `harvest_postings`
 * must NEVER drive a sign-in flow through a shared browser tab: a sign-in
 * there is visible to every concurrently harvesting board and to the
 * attended profile through the shared cookies. Returns a structured refusal,
 * or `undefined` when `board.url` is not obviously a sign-in URL.
 */
export function refuseSignInUrl(board: HarvestBoardRequest): HarvestBoardResult | undefined {
  if (!isSignInUrl(board.url)) return undefined;
  return blockedResult(board, 'refused: url looks like a sign-in/login/auth page — harvest never drives a sign-in flow', 'login');
}

/** Whether a `browser_navigate` failure's own message names a DNS/
 * connection-class net error — the only case narrow enough to confidently
 * call the board's URL unreachable rather than merely slow or otherwise
 * erroring. */
function isUnreachableNavigationError(message: string): boolean {
  return matchesAny(message, UNREACHABLE_NET_ERROR_PATTERNS);
}

/** Whether a `browser_navigate` failure's own message names a timeout-class
 * error — see {@link TIMEOUT_NAV_ERROR_PATTERNS}. Checked only once the
 * message is already confirmed NOT unreachable, so `ERR_DNS_TIMED_OUT`
 * (a confirmed DNS failure) always stays `'unreachable'`, never `'timeout'`. */
function isTimeoutNavigationError(message: string): boolean {
  return matchesAny(message, TIMEOUT_NAV_ERROR_PATTERNS);
}

/** Replace every `{keywords}`/`{location}` placeholder in a board's
 * `searchUrl` template with the URI-encoded keywords/location — `{keywords}`
 * with `encodeURIComponent(keywords ?? '')`, `{location}` likewise for
 * `location`, every occurrence of each. Used for direct boards with no
 * on-page search box: the built URL replaces `board.url` outright, is
 * navigated to directly, and its snapshot classified with no search-box
 * typing at all. */
export function buildSearchUrl(template: string, keywords?: string, location?: string): string {
  return template
    .split('{keywords}').join(encodeURIComponent(keywords ?? ''))
    .split('{location}').join(encodeURIComponent(location ?? ''));
}

/** Navigate to `url` and take one snapshot, or a `blocked`-shaped error
 * otherwise. `blockKind: 'unreachable'` is set ONLY for a confirmed
 * DNS/connection-class navigation failure ({@link isUnreachableNavigationError});
 * a timeout-class failure ({@link isTimeoutNavigationError}) is retried once
 * via {@link navigateOnce}, and `blockKind: 'timeout'` set only if the retry
 * also times out; any OTHER navigation failure (a page-level error) is
 * reported with NO `blockKind` at all rather than mislabelling a possibly
 * slow-but-reachable board as a dead URL — see `HarvestBoardResult.blockKind`. */
export async function navigateAndSnapshot(
  call: BrowserToolCall,
  url: string,
): Promise<{ snapshot: string } | { error: string; blockKind?: BlockKind }> {
  const navError = await navigateOnce(call, url);
  if (navError) return navError;
  const snap = await call('browser_snapshot', {});
  if (snap.isError) return { error: `snapshot failed: ${snap.content}` };
  return { snapshot: snap.content };
}

/** Call `browser_navigate`, retrying exactly ONCE on a timeout-class error
 * ({@link isTimeoutNavigationError}) — a second timeout in a row returns
 * `blockKind: 'timeout'` rather than retrying indefinitely. Shared by
 * {@link navigateAndSnapshot} and harvestTabs.ts's `selectAndNavigate`, so
 * both the single-shared-tab and tab-per-board paths get the same retry.
 * Resolves to `null` on success, else the navigation error. */
export async function navigateOnce(call: BrowserToolCall, url: string): Promise<{ error: string; blockKind?: BlockKind } | null> {
  const nav = await call('browser_navigate', { url });
  if (!nav.isError) return null;
  if (isUnreachableNavigationError(nav.content)) {
    return { error: `board unreachable: navigation failed: ${nav.content}`, blockKind: 'unreachable' };
  }
  if (isTimeoutNavigationError(nav.content)) {
    const retry = await call('browser_navigate', { url });
    if (!retry.isError) return null;
    if (isUnreachableNavigationError(retry.content)) {
      return { error: `board unreachable: navigation failed: ${retry.content}`, blockKind: 'unreachable' };
    }
    if (isTimeoutNavigationError(retry.content)) {
      return { error: `navigation timed out twice: ${retry.content}`, blockKind: 'timeout' };
    }
    return { error: `navigation failed (not a confirmed dead URL — could be a slow or erroring page): ${retry.content}` };
  }
  return { error: `navigation failed (not a confirmed dead URL — could be a slow or erroring page): ${nav.content}` };
}

/** Outcome of {@link searchAndSnapshot}: `snapshot` is always the best one
 * obtained (the pre-search snapshot on any failure or non-submission,
 * otherwise the post-search one); `submitted` is true only once the page is
 * confirmed to have actually changed; `reason` explains a `false` `submitted`
 * and is absent when `submitted` is true. */
export interface KeywordSearchResult {
  snapshot: string;
  submitted: boolean;
  reason?: string;
}

/** Strip every `[ref=...]` token, every input field's typed value (see
 * {@link FIELD_VALUE_RE}) and surrounding whitespace so two snapshots can be
 * compared for an actual content change rather than reassigned refs or the
 * keywords just typed into the box. */
function normaliseForComparison(snapshot: string): string {
  return snapshot.replace(REF_TOKEN_RE, '').replace(FIELD_VALUE_RE, '$1').trim();
}

/** Re-snapshot after an inconclusive submit and give the page one more
 * chance to settle — waits, then takes one more snapshot. Falls back to
 * `previous` (both as the returned snapshot and for the unchanged check)
 * when this final snapshot itself errors. */
async function waitAndResnapshot(call: BrowserToolCall, previous: string): Promise<string> {
  await call('browser_wait_for', { time: SEARCH_SETTLE_SECONDS });
  const snap = await call('browser_snapshot', {});
  return snap.isError ? previous : snap.content;
}

/** Type `keywords` into the first detected search box, submit, and confirm
 * the page actually changed — comparing snapshots with `[ref=...]` tokens
 * stripped, since those are reassigned on every `browser_snapshot` call and
 * would otherwise look like a change on their own. When the first post-type
 * snapshot looks unchanged, waits {@link SEARCH_SETTLE_SECONDS} seconds for a
 * debounced/animated result and re-snapshots once before giving up. Never
 * throws: any failure or an unconfirmed submit reports `submitted: false`
 * with a `reason`, and `snapshot` is always the best one available. */
export async function searchAndSnapshot(call: BrowserToolCall, snapshot: string, keywords: string): Promise<KeywordSearchResult> {
  const ref = findKeywordFieldRef(snapshot);
  if (!ref) return { snapshot, submitted: false, reason: 'no keyword search box detected' };
  const typed = await call('browser_type', { element: 'search box', ref, text: keywords, submit: true });
  if (typed.isError) return { snapshot, submitted: false, reason: 'keyword browser_type failed' };
  const snap = await call('browser_snapshot', {});
  if (snap.isError) return { snapshot, submitted: false, reason: 'post-search snapshot failed' };
  if (normaliseForComparison(snap.content) !== normaliseForComparison(snapshot)) {
    return { snapshot: snap.content, submitted: true };
  }
  const settled = await waitAndResnapshot(call, snap.content);
  if (normaliseForComparison(settled) === normaliseForComparison(snapshot)) {
    return { snapshot: settled, submitted: false, reason: 'submit did not change the page' };
  }
  return { snapshot: settled, submitted: true };
}
