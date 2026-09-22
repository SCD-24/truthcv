/**
 * Per-board harvesting for `harvest_postings`: the SERIAL single-shared-tab
 * path, the CONCURRENT tab-per-board path, and the bounded worker pool that
 * drives the latter. Split out of harvestPostings.ts; see that module's own
 * doc for the tool's behaviour as a whole.
 *
 * Both paths share the same per-board failure containment: a THROWN failure
 * (a transport error, an unexpected rejection) is confined to that one
 * board's own result, never propagating out to discard every other board
 * already harvested.
 */

import { blockedResult, classifySnapshot } from './harvestClassify.js';
import { navigateAndSnapshot, refuseSignInUrl, searchAndSnapshot } from './harvestNavigate.js';
import { callOnBoardTab, closeAllOpenedTabs, createAsyncLock, createBoardTab, selectAndNavigate } from './harvestTabs.js';
import type { AsyncLock } from './harvestTabs.js';
import type { BrowserToolCall, HarvestBoardRequest, HarvestBoardResult } from './harvestTypes.js';

/** How many boards harvest concurrently, each in its own tab, in the
 * TAB-PER-BOARD FALLBACK path — taken when the session-per-worker path
 * (agent/harness/builtins/harvestSessions.ts) has fewer than two available
 * browser sessions. Kept small deliberately — these tabs share one Chromium
 * profile and one MCP connection. */
export const MAX_CONCURRENT_HARVEST_TABS = 3;

/** Coerce an unknown thrown value into a message string. */
export function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** Harvest one board on whatever tab `call` is currently scoped to — the
 * degraded serial path's per-board step; see {@link harvestSerial}. */
async function harvestOneBoard(call: BrowserToolCall, board: HarvestBoardRequest): Promise<HarvestBoardResult> {
  const refused = refuseSignInUrl(board);
  if (refused) return refused;
  const navigated = await navigateAndSnapshot(call, board.url);
  if ('error' in navigated) return blockedResult(board, navigated.error, navigated.blockKind);
  const finalSnapshot = board.keywords ? await searchAndSnapshot(call, navigated.snapshot, board.keywords) : navigated.snapshot;
  return classifySnapshot(board, finalSnapshot);
}

/**
 * Harvest one board in its own freshly opened tab, carrying that tab's
 * resolved INDEX through every step of its own sequence (navigate, type,
 * re-snapshot) rather than re-resolving "this board's tab" by URL at each
 * step — the index is stable for the rest of the harvest because no tab
 * closes until every board is done (see {@link closeAllOpenedTabs}), so it
 * can never drift to a same-origin sibling board's tab, and never gets lost
 * when a search submit changes the tab's URL. The tab is left open; closing
 * is deferred until every board has finished. `createdIndices` records this
 * board's tab index the moment it is created, regardless of what happens
 * afterward, so a board whose navigation then fails still gets its tab
 * closed at the end instead of leaking it.
 */
async function harvestInTab(
  call: BrowserToolCall,
  lock: AsyncLock,
  board: HarvestBoardRequest,
  createdIndices: number[],
): Promise<HarvestBoardResult> {
  const refused = refuseSignInUrl(board);
  if (refused) return refused;
  const created = await createBoardTab(call, lock);
  if ('error' in created) return blockedResult(board, created.error);
  createdIndices.push(created.index);
  const navigated = await selectAndNavigate(call, lock, created.index, board.url);
  if ('error' in navigated) return blockedResult(board, navigated.error, navigated.blockKind);
  const tabCall: BrowserToolCall = (toolName, args) => callOnBoardTab(call, lock, created.index, toolName, args);
  const finalSnapshot = board.keywords ? await searchAndSnapshot(tabCall, navigated.snapshot, board.keywords) : navigated.snapshot;
  return classifySnapshot(board, finalSnapshot);
}

/** Harvest one board, confining any THROWN failure to this board's own
 * result, never letting it propagate out and discard every other board
 * already harvested. */
async function harvestBoardSafely(
  call: BrowserToolCall,
  lock: AsyncLock,
  board: HarvestBoardRequest,
  createdIndices: number[],
): Promise<HarvestBoardResult> {
  try {
    return await harvestInTab(call, lock, board, createdIndices);
  } catch (err) {
    return blockedResult(board, `harvest failed: ${errorMessage(err)}`);
  }
}

/** Same per-board failure containment as {@link harvestBoardSafely}, for the
 * degraded serial path's single shared tab — also reused as-is by
 * harvestSessions.ts's session-per-worker path, whose leased session plays
 * the same "one call scoped to one board at a time" role a serial `call`
 * plays here, so the same containment applies unchanged. */
export async function harvestOneBoardSafely(call: BrowserToolCall, board: HarvestBoardRequest): Promise<HarvestBoardResult> {
  try {
    return await harvestOneBoard(call, board);
  } catch (err) {
    return blockedResult(board, `harvest failed: ${errorMessage(err)}`);
  }
}

/**
 * Harvest every board serially, one at a time, in whatever tab `call` is
 * currently scoped to — no `browser_tab_*` calls at all. Taken when the
 * tab-management tools are not advertised at all, OR when they are
 * advertised but this invocation's own tab-listing probe could not parse
 * them (see harvestTabs.ts's `probeTabListing`); same per-board
 * classification and result shape as the concurrent tab-per-board path,
 * just no concurrency.
 */
export async function harvestSerial(call: BrowserToolCall, boards: HarvestBoardRequest[]): Promise<HarvestBoardResult[]> {
  const results: HarvestBoardResult[] = [];
  for (const board of boards) {
    results.push(await harvestOneBoardSafely(call, board));
  }
  return results;
}

/**
 * Harvest every board with a bounded worker pool: at most
 * {@link MAX_CONCURRENT_HARVEST_TABS} boards are in flight — each in its own
 * tab — at once. Every tab stays open until every board is done; then every
 * tab this invocation created is closed by its own tracked creation index
 * (see {@link closeAllOpenedTabs}), regardless of how each board's own
 * harvest turned out.
 */
export async function harvestBounded(call: BrowserToolCall, boards: HarvestBoardRequest[]): Promise<HarvestBoardResult[]> {
  const lock = createAsyncLock();
  const createdIndices: number[] = [];
  const results: HarvestBoardResult[] = new Array(boards.length);
  let next = 0;
  async function worker(): Promise<void> {
    while (next < boards.length) {
      const i = next++;
      results[i] = await harvestBoardSafely(call, lock, boards[i], createdIndices);
    }
  }
  const workerCount = Math.min(MAX_CONCURRENT_HARVEST_TABS, boards.length);
  await Promise.all(Array.from({ length: workerCount }, worker));
  await closeAllOpenedTabs(call, lock, createdIndices);
  return results;
}
