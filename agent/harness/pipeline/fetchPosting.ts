/**
 * Fetch one posting's readable text through the browser (navigate, snapshot,
 * settle while loading, wait a few times while the page is still a thin
 * client-rendered shell). Returns the text or an explicit unreadable marker;
 * never throws.
 */
import { navigateAndSnapshot, settleIfLoading } from '../builtins/harvestNavigate.js';
import type { BrowserToolCall } from '../builtins/harvestTypes.js';

/** A posting whose text could not be read, with the blocker to record. */
export interface UnreadablePosting {
  unreadable: true;
  /** `record_screening` screening_blocker value. */
  blocker: 'unreadable' | 'login_required';
  reason: string;
}

/** A posting whose text was read. */
export interface ReadablePosting {
  unreadable?: false;
  text: string;
}

export type FetchedPosting = ReadablePosting | UnreadablePosting;

/** Snapshots shorter than this carry no posting body. */
export const MIN_READABLE_CHARS = 200;

/** Phrases marking a sign-in wall instead of a posting. */
const LOGIN_WALL_RE = /\b(sign in to (?:view|continue|apply)|log in to (?:view|continue)|please (?:sign|log) in)\b/i;

/** Max extra snapshot retries while a page body is still thin. */
export const THIN_SETTLE_ATTEMPTS = 4;

/** Seconds to wait before each thin-page retry. */
export const THIN_SETTLE_SECONDS = 2;

/** Whole-line header markers and column-0 header fields of a Playwright MCP snapshot. */
const HEADER_LINE_RE = /^(?:(?:### Page|### Snapshot|```\w*)\s*$|- (?:Page URL|Page Title|Console):)/;

/**
 * The posting body of a Playwright MCP snapshot: header lines (`### Page`,
 * `### Snapshot`, page URL/title/console lines, code fences) dropped, every
 * `[ref=…]` token stripped, whitespace collapsed. Role/name text is kept.
 *
 * @param snapshot Raw snapshot text.
 */
export function postingBodyText(snapshot: string): string {
  return snapshot
    .split('\n')
    .filter((line) => !HEADER_LINE_RE.test(line))
    .join('\n')
    .replace(/\[ref=[^\]]*\]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

/** Re-snapshot a thin, non-login page up to THIN_SETTLE_ATTEMPTS times. */
async function settleIfThin(call: BrowserToolCall, snapshot: string): Promise<string> {
  let text = snapshot;
  if (LOGIN_WALL_RE.test(text)) return text;
  for (let i = 0; i < THIN_SETTLE_ATTEMPTS; i++) {
    if (postingBodyText(text).length >= MIN_READABLE_CHARS) break;
    try {
      await call('browser_wait_for', { time: THIN_SETTLE_SECONDS });
      const snap = await call('browser_snapshot', {});
      if (snap.isError) return text;
      text = snap.content;
    } catch {
      return text;
    }
  }
  return text;
}

/**
 * Navigate to `url` and return its readable text.
 *
 * @param call Browser tool caller (allow-listed by tools.ts in production).
 * @param url The posting URL.
 */
export async function fetchPosting(call: BrowserToolCall, url: string): Promise<FetchedPosting> {
  try {
    const nav = await navigateAndSnapshot(call, url);
    if ('error' in nav) return { unreadable: true, blocker: 'unreadable', reason: nav.error };
    const text = await settleIfThin(call, await settleIfLoading(call, nav.snapshot));
    if (postingBodyText(text).length < MIN_READABLE_CHARS) {
      return LOGIN_WALL_RE.test(text)
        ? { unreadable: true, blocker: 'login_required', reason: 'sign-in wall' }
        : { unreadable: true, blocker: 'unreadable', reason: 'page had no readable posting text' };
    }
    if (LOGIN_WALL_RE.test(text) && text.length < MIN_READABLE_CHARS * 5) {
      return { unreadable: true, blocker: 'login_required', reason: 'sign-in wall' };
    }
    return { text };
  } catch (err) {
    return { unreadable: true, blocker: 'unreadable', reason: err instanceof Error ? err.message : String(err) };
  }
}
