/**
 * Browser-tab lifecycle for `harvest_postings`' CONCURRENT tab-per-board
 * path: a FIFO lock serializing this invocation's own tab-tool calls, tab
 * creation/selection, closing every tab this invocation opened, and probing
 * whether the browser server's tab-listing text can be parsed at all before
 * committing to the concurrent path rather than resting on a guessed text
 * format. Split out of harvestPostings.ts; see that module's own doc for the
 * tool's behaviour as a whole, and harvestBoard.ts for how these pieces
 * compose into one board's harvest.
 */

import { navigateAndSnapshot } from './harvestNavigate.js';
import type { BlockKind, BrowserToolCall } from './harvestTypes.js';

/**
 * A minimal FIFO async mutex: queued work runs one piece at a time, in
 * submission order, regardless of how many callers are waiting.
 *
 * Every browser call this module makes shares ONE MCP connection to the
 * `browser` server, and `@playwright/mcp`'s tab tools switch which tab is
 * "current" for every OTHER tool — there is no per-call tab argument on
 * `browser_navigate`/`browser_snapshot`/`browser_type` themselves. This lock
 * makes "select this board's tab, then act" one atomic unit, so different
 * boards' sequences safely INTERLEAVE instead of racing. Note that this lock
 * alone only serializes calls made by ONE `harvest_postings` invocation —
 * loop.ts's `partitionByServer` is what additionally serializes across
 * several harvest_postings calls, and against model-issued `browser__*`
 * calls, in the same turn.
 */
export interface AsyncLock {
  run<T>(fn: () => Promise<T>): Promise<T>;
}

/** Build a fresh {@link AsyncLock} with an empty queue. */
export function createAsyncLock(): AsyncLock {
  let queue: Promise<unknown> = Promise.resolve();
  return {
    run<T>(fn: () => Promise<T>): Promise<T> {
      const result = queue.then(fn, fn);
      queue = result.then(
        () => undefined,
        () => undefined,
      );
      return result;
    },
  };
}

/**
 * Matches a tab-listing line's leading index, tolerating every plausible
 * rendering rather than resting on one guessed shape: the legacy `[N]` form,
 * a bare `Tab N`, and the pinned @playwright/mcp@0.0.79 `- N: (current)
 * [Title] (https://…)` form (a leading `N:`, optionally after a `- `).
 * Anchored to the START of the line so a digit-colon pair elsewhere on the
 * line (a URL's port number) can never be mistaken for a tab index.
 */
const TAB_LINE_INDEX_RE = /^\s*-?\s*(?:\[(\d+)\]|(\d+):|Tab\s+(\d+))/i;

/** The leading tab index named on one tab-listing line, or `undefined` if
 * the line matches none of {@link TAB_LINE_INDEX_RE}'s recognised shapes. */
function tabIndexOnLine(line: string): number | undefined {
  const match = TAB_LINE_INDEX_RE.exec(line);
  if (!match) return undefined;
  const raw = match[1] ?? match[2] ?? match[3];
  return raw === undefined ? undefined : Number(raw);
}

/** The highest tab index named anywhere in a `browser_tab_list`/
 * `browser_tab_new` result's content. `-1` when no line matches a
 * recognised shape at all — see {@link TAB_LINE_INDEX_RE}. */
export function parseHighestTabIndex(content: string): number {
  const indices = content
    .split('\n')
    .map(tabIndexOnLine)
    .filter((index): index is number => index !== undefined);
  return indices.length > 0 ? Math.max(...indices) : -1;
}

/**
 * Whether the browser server's `browser_tab_list` output can actually be
 * parsed for at least one tab index, on a fresh probe call — the runtime
 * check this tool rests the concurrent tab-per-board path on, instead of
 * assuming a guessed text format. A server whose listing this build cannot
 * recognise at all (an errored call, or zero parseable lines) means the
 * concurrent path must not be trusted; the caller falls back to harvesting
 * every board serially instead of reporting every board blocked. A truly
 * empty listing (no tabs open yet) is indistinguishable from an unparseable
 * one and is treated the same way — a real browser session normally has at
 * least one tab open by the time this tool runs, so this is a safe default,
 * not a lossy one.
 */
export async function probeTabListing(call: BrowserToolCall): Promise<boolean> {
  const listed = await call('browser_tab_list', {});
  if (listed.isError) return false;
  return parseHighestTabIndex(listed.content) >= 0;
}

/**
 * Open a new tab and identify its own index — as ONE locked unit, so the
 * index resolved is unambiguously the tab just created: no other board's
 * creation can run between the `browser_tab_new` call and the
 * `browser_tab_list` read that identifies it. The returned index is this
 * invocation's OWN tracked identity for the tab, independent of whatever the
 * board does with it afterward — see {@link closeAllOpenedTabs}.
 */
export async function createBoardTab(call: BrowserToolCall, lock: AsyncLock): Promise<{ index: number } | { error: string }> {
  return lock.run(async () => {
    const created = await call('browser_tab_new', {});
    if (created.isError) return { error: 'could not open a browser tab for this board' };
    const listed = await call('browser_tab_list', {});
    const index = parseHighestTabIndex(listed.isError ? created.content : listed.content);
    if (index < 0) return { error: 'could not identify the newly opened tab' };
    return { index };
  });
}

/** Select `index`, then navigate it to `url` and take its first snapshot —
 * as ONE locked unit, so no other board's action can run between selecting
 * this board's own freshly created tab and acting on it (the select and the
 * navigate must never be split across a lock boundary, or another board's
 * own select could land in between and steal "current tab" out from under
 * this one). */
export async function selectAndNavigate(
  call: BrowserToolCall,
  lock: AsyncLock,
  index: number,
  url: string,
): Promise<{ snapshot: string } | { error: string; blockKind?: BlockKind }> {
  return lock.run(async () => {
    const selected = await call('browser_tab_select', { index });
    if (selected.isError) return { error: `could not select the newly opened tab: ${selected.content}` };
    return navigateAndSnapshot(call, url);
  });
}

/** Select this board's OWN tracked `index`, then make one browser call on
 * it, as ONE locked unit — the index was resolved once at tab creation and
 * carried through the whole harvest (see harvestBoard.ts), so this never
 * re-resolves the tab by URL and can never be misattributed to a
 * same-origin sibling board, nor lost when a search submit changes the
 * tab's URL. */
export async function callOnBoardTab(
  call: BrowserToolCall,
  lock: AsyncLock,
  index: number,
  toolName: string,
  args: Record<string, unknown>,
) {
  return lock.run(async () => {
    const selected = await call('browser_tab_select', { index });
    if (selected.isError) return selected;
    return call(toolName, args);
  });
}

/**
 * Close every tab THIS invocation created, by the index tracked at its own
 * creation — never by re-resolving a board's tab from its (possibly
 * changed) URL, which is what previously let a tab whose navigation failed
 * (left at `about:blank`, matching no board's URL) leak for the rest of the
 * run. Closed in DESCENDING index order: closing the highest-index tab first
 * never shifts any lower, not-yet-closed index, so every index in
 * `createdIndices` stays valid right up to its own close — without that
 * ordering, closing a lower index first would renumber every higher one out
 * from under this loop. Best-effort: nothing here is reported back, since
 * every board's own result was already decided.
 */
export async function closeAllOpenedTabs(call: BrowserToolCall, lock: AsyncLock, createdIndices: readonly number[]): Promise<void> {
  const descending = [...createdIndices].sort((a, b) => b - a);
  for (const index of descending) {
    await lock.run(() => call('browser_tab_close', { index }));
  }
}
