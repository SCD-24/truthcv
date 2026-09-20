/**
 * Navigation safety and search-box driving for `harvest_postings` — refusing
 * an obvious sign-in URL before ever navigating to it, classifying a
 * navigation failure without over-claiming a board is dead, and typing a
 * board's keywords into its detected search box. Split out of
 * harvestPostings.ts; see that module's own doc for the tool's behaviour as
 * a whole.
 */

import { blockedResult, matchesAny } from './harvestClassify.js';
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

/** Match a searchbox/textbox line and capture its `[ref=...]` element ref. */
const SEARCH_BOX_RE = /-\s*(?:searchbox|textbox)[^\n[]*\[ref=([^\]]+)]/i;

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

/** Navigate to `url` and take one snapshot, or a `blocked`-shaped error
 * otherwise. `blockKind: 'unreachable'` is set ONLY for a confirmed
 * DNS/connection-class navigation failure ({@link isUnreachableNavigationError});
 * any other navigation failure (a generic timeout, a page-level error) is
 * reported with NO `blockKind` at all rather than mislabelling a possibly
 * slow-but-reachable board as a dead URL — see `HarvestBoardResult.blockKind`. */
export async function navigateAndSnapshot(
  call: BrowserToolCall,
  url: string,
): Promise<{ snapshot: string } | { error: string; blockKind?: BlockKind }> {
  const nav = await call('browser_navigate', { url });
  if (nav.isError) {
    if (isUnreachableNavigationError(nav.content)) {
      return { error: `board unreachable: navigation failed: ${nav.content}`, blockKind: 'unreachable' };
    }
    return { error: `navigation failed (not a confirmed dead URL — could be a slow or erroring page): ${nav.content}` };
  }
  const snap = await call('browser_snapshot', {});
  if (snap.isError) return { error: `snapshot failed: ${snap.content}` };
  return { snapshot: snap.content };
}

/** Type `keywords` into the first detected search box, then re-snapshot; falls
 * back to the original `snapshot` unchanged when no search box is found or
 * either call errors. */
export async function searchAndSnapshot(call: BrowserToolCall, snapshot: string, keywords: string): Promise<string> {
  const ref = SEARCH_BOX_RE.exec(snapshot)?.[1];
  if (!ref) return snapshot;
  const typed = await call('browser_type', { element: 'search box', ref, text: keywords, submit: true });
  if (typed.isError) return snapshot;
  const snap = await call('browser_snapshot', {});
  return snap.isError ? snapshot : snap.content;
}
