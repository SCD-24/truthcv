/**
 * Session-per-worker harvesting for `harvest_postings`: boards run
 * CONCURRENTLY, each on its own LEASED session from the browser session pool
 * (agent/harness/mcp/sessionPool.ts) — no `browser_tab_*` calls, no
 * {@link AsyncLock}, because each worker's session is its OWN independent MCP
 * connection with its own "current tab" state (see sessionPool.ts's module
 * doc for the probe conclusion this rests on). This is the FIRST-preference
 * path in harvestPostings.ts's dispatch order, ahead of the tab-per-board and
 * serial fallbacks in harvestBoard.ts.
 *
 * Split out of harvestPostings.ts; see that module's own doc for the tool's
 * behaviour as a whole, and harvestBoard.ts for the sibling tab-per-board and
 * serial paths this one takes precedence over.
 *
 * Same per-board failure containment as the other two paths
 * ({@link harvestOneBoardSafely}): a thrown failure is confined to that one
 * board's own result, never discarding every other board already harvested.
 * Results land at each board's own REQUEST index, so the returned array
 * matches request order regardless of completion order.
 *
 * A worker leases ONE session up front and keeps it across every board it
 * claims, rather than re-leasing per board — re-leasing per board is what
 * caused the fixed regression below. When a board's own calls throw
 * (transport death, `outcome.dead`), the worker discards that session and
 * tries to lease ONE replacement; if none is available, the worker EXITS
 * immediately without claiming any further board index, rather than looping
 * back to `pool.lease()` returning `undefined` at microtask speed and
 * fabricating a `blocked` result for every remaining board — one dead
 * session used to cascade into many fabricated blocked boards this way.
 * Boards a worker never got to claim come back as `undefined` slots in the
 * returned array; {@link harvestWithSessions}'s own doc and
 * harvestPostings.ts's `runHarvest` are responsible for filling those in
 * with a serial fallback, not this module.
 */

import { stringifyContent } from '../mcp/client.js';
import type { BrowserSession, BrowserSessionPool } from '../mcp/sessionPool.js';
import { errorMessage, harvestOneBoardSafely } from './harvestBoard.js';
import type {
  BrowserToolCall,
  BrowserToolPermissionCheck,
  BrowserToolResult,
  HarvestBoardRequest,
  HarvestBoardResult,
} from './harvestTypes.js';

/** Permits every tool — the default `isPermitted` when a caller (an existing
 * test, or any other caller that predates the allow-list check) passes none,
 * so nothing that worked before this fix stops working. Production always
 * passes tools.ts's real `isBrowserToolCallPermitted` instead. */
const permitAll: BrowserToolPermissionCheck = () => undefined;

/**
 * Adapt one leased session's raw MCP client into a {@link BrowserToolCall}.
 * Flattens content exactly like `mcp/client.ts`'s own `dispatch` does (via
 * the shared {@link stringifyContent}), and — like every other
 * `BrowserToolCall` in this tool — NEVER throws: a transport failure comes
 * back as an `isError` result instead of a rejection.
 *
 * Every call is first checked against `isPermitted` (tools.ts's
 * `isBrowserToolCallPermitted` in production) — this path dispatches on
 * `session.client.callTool` directly rather than through tools.ts's
 * `browserToolCall` closure, so without this check nothing would ever
 * consult the allow-list for a session-leased call.
 *
 * A THROWN transport failure — as opposed to a normal `isError` tool result
 * — also sets `outcome.dead = true`, so {@link harvestWithSessions}'s worker
 * loop can discard this session afterward instead of returning it to the
 * pool.
 *
 * @param session The leased session to dispatch calls through.
 * @param isPermitted The allow-list check for this call's bare tool name.
 * @param outcome Mutated to record a thrown transport failure.
 */
function toolCallFor(session: BrowserSession, isPermitted: BrowserToolPermissionCheck, outcome: { dead: boolean }): BrowserToolCall {
  return async (toolName, args): Promise<BrowserToolResult> => {
    const refusal = isPermitted(toolName);
    if (refusal) return { content: refusal, isError: true };
    try {
      const res = await session.client.callTool({ name: toolName, arguments: args });
      return { content: stringifyContent(res.content), isError: res.isError === true };
    } catch (err) {
      outcome.dead = true;
      return { content: `browser tool call failed: ${errorMessage(err)}`, isError: true };
    }
  };
}

/**
 * Harvest every board with a bounded worker pool: at most `sessionCount`
 * workers run at once, each LEASING ONE SESSION UP FRONT and keeping it
 * across every board it claims (see this module's own doc for why — a
 * per-board re-lease is what let one dead session fabricate a cascade of
 * fake `blocked` boards). Results land at each board's own request index,
 * matching request order regardless of completion order — mirrors
 * {@link harvestBounded}'s own contract exactly, just over sessions instead
 * of tabs.
 *
 * A board index a worker never got to claim — because it could not lease
 * even its first session, or because its session died and no replacement
 * was available — comes back `undefined` in the returned array rather than
 * a fabricated `blocked` result. Callers (harvestPostings.ts's `runHarvest`)
 * are responsible for filling those in, e.g. via a serial fallback.
 *
 * @param pool The browser session pool boards lease sessions from.
 * @param boards The boards to harvest.
 * @param sessionCount How many sessions are actually available — bounds
 *   worker count. Callers should pass the pool's own
 *   `availableSessionCount()`, already resolved before calling this.
 * @param isPermitted The allow-list check every dispatched call is
 *   consulted against — tools.ts's `isBrowserToolCallPermitted` in
 *   production. Defaults to permitting everything, so an existing caller
 *   that predates this check keeps working unchanged.
 */
export async function harvestWithSessions(
  pool: BrowserSessionPool,
  boards: HarvestBoardRequest[],
  sessionCount: number,
  isPermitted: BrowserToolPermissionCheck = permitAll,
): Promise<(HarvestBoardResult | undefined)[]> {
  const results: (HarvestBoardResult | undefined)[] = new Array(boards.length);
  let next = 0;
  async function worker(): Promise<void> {
    let session = await pool.lease();
    if (!session) return;
    try {
      while (next < boards.length) {
        const i = next++;
        const outcome = { dead: false };
        results[i] = await harvestOneBoardSafely(toolCallFor(session, isPermitted, outcome), boards[i]);
        if (outcome.dead) {
          await pool.discard(session);
          session = await pool.lease();
          if (!session) return;
        }
      }
    } finally {
      if (session) pool.release(session);
    }
  }
  const workerCount = Math.min(sessionCount, boards.length);
  await Promise.all(Array.from({ length: workerCount }, worker));
  return results;
}
