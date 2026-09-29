/**
 * Fetch one posting's readable text through the browser (navigate, snapshot,
 * settle while loading). Returns the text or an explicit unreadable marker;
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
    const text = await settleIfLoading(call, nav.snapshot);
    if (text.trim().length < MIN_READABLE_CHARS) {
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
