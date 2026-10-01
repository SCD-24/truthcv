/**
 * Fetch one posting's readable text through the browser (navigate, snapshot,
 * settle while loading, wait a few times while the page is still a thin
 * client-rendered shell). The snapshot is pruned to plain posting text
 * (chrome, urls and refs removed) before measuring and returning. LinkedIn
 * pages additionally wait until the "Primary content" region is filled, and
 * rely on the operator's persisted signed-in browser profile (Agents → Site
 * sign-ins); an authwall/login URL is reported as a sign-in wall.
 * Returns the text or an explicit unreadable marker; never throws.
 */
import { navigateAndSnapshot, settleIfLoading } from '../builtins/harvestNavigate.js';
import type { BrowserToolCall } from '../builtins/harvestTypes.js';
import { pruneSnapshot } from './snapshotPrune.js';

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

/** Page URL header of a snapshot that landed on a LinkedIn sign-in page. */
const LINKEDIN_SIGNED_OUT_RE = /^- Page URL:\s*https?:\/\/(?:[\w-]+\.)*linkedin\.com\/(?:(?:authwall|login|uas\/login|signup)(?:[/?#]|\s*$)|checkpoint\/)/im;

/**
 * Whether a raw snapshot's page URL is a LinkedIn sign-in/authwall page.
 *
 * @param snapshot Raw snapshot text.
 */
export function linkedInSignedOut(snapshot: string): boolean {
  return LINKEDIN_SIGNED_OUT_RE.test(snapshot);
}

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

/** Line opening LinkedIn's job-details region. */
const PRIMARY_CONTENT_RE = /^(\s*)-\s*region "Primary content"/;

/** Markers of LinkedIn's job description still loading. */
const LINKEDIN_LOADING_RE = /loading (?:the )?job (?:description|details)/i;

/** Reason recorded when a LinkedIn job never rendered. */
const LINKEDIN_UNREADY_REASON = 'LinkedIn job details did not load';

function indentOf(line: string): number {
  return line.length - line.trimStart().length;
}

/** Whether `url` is on linkedin.com or a subdomain. */
function isLinkedInUrl(url: string): boolean {
  try {
    const host = new URL(url).hostname.toLowerCase();
    return host === 'linkedin.com' || host.endsWith('.linkedin.com');
  } catch {
    return false;
  }
}

/**
 * Whether a LinkedIn snapshot has a filled `region "Primary content"` (a more
 * indented line follows it) and no job-details loading marker.
 *
 * @param snapshot Raw snapshot text.
 */
export function linkedInJobReady(snapshot: string): boolean {
  if (LINKEDIN_LOADING_RE.test(snapshot)) return false;
  const lines = snapshot.split('\n');
  const at = lines.findIndex((l) => PRIMARY_CONTENT_RE.test(l));
  if (at === -1) return false;
  const next = lines[at + 1];
  return next !== undefined && next.trim() !== '' && indentOf(next) > indentOf(lines[at]);
}

/** Length of pruned text with whitespace runs collapsed (the API's measure). */
function readableLength(pruned: string): number {
  return pruned.replace(/\s+/g, ' ').trim().length;
}

/** Whether the page text is settled enough to stop waiting. */
function isSettled(text: string, linkedIn: boolean): boolean {
  if (readableLength(pruneSnapshot(text)) < MIN_READABLE_CHARS) return false;
  return !linkedIn || linkedInJobReady(text);
}

/** Re-snapshot a thin (or unready LinkedIn), non-login page up to THIN_SETTLE_ATTEMPTS times. */
async function settleIfThin(call: BrowserToolCall, snapshot: string, linkedIn: boolean): Promise<string> {
  let text = snapshot;
  if (LOGIN_WALL_RE.test(pruneSnapshot(text))) return text;
  if (linkedIn && linkedInSignedOut(text)) return text;
  for (let i = 0; i < THIN_SETTLE_ATTEMPTS; i++) {
    if (isSettled(text, linkedIn)) break;
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

const signInWall: UnreadablePosting = { unreadable: true, blocker: 'login_required', reason: 'sign-in wall' };

/** Classify the settled raw snapshot as readable text or an unreadable marker. */
function judgePosting(raw: string, linkedIn: boolean): FetchedPosting {
  if (linkedIn && linkedInSignedOut(raw)) return signInWall;
  const text = pruneSnapshot(raw);
  const wall = LOGIN_WALL_RE.test(text);
  const length = readableLength(text);
  if (length < MIN_READABLE_CHARS && wall) return signInWall;
  if (linkedIn && !wall && !linkedInJobReady(raw)) {
    return { unreadable: true, blocker: 'unreadable', reason: LINKEDIN_UNREADY_REASON };
  }
  if (length < MIN_READABLE_CHARS) {
    return { unreadable: true, blocker: 'unreadable', reason: 'page had no readable posting text' };
  }
  return wall && length < MIN_READABLE_CHARS * 5 ? signInWall : { text };
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
    const linkedIn = isLinkedInUrl(url);
    const raw = await settleIfThin(call, await settleIfLoading(call, nav.snapshot), linkedIn);
    return judgePosting(raw, linkedIn);
  } catch (err) {
    return { unreadable: true, blocker: 'unreadable', reason: err instanceof Error ? err.message : String(err) };
  }
}
