/**
 * The harness's `harvest_postings` built-in tool: harvests one or more
 * direct-search boards' results in ONE tool call, instead of the
 * navigate/snapshot/type/snapshot sequence `agent/RUNBOOK.md` §5 used to
 * prescribe step by step.
 *
 * Extraction is deterministic, never a hand-written CSS selector — boards
 * restyle constantly, but a posting URL on a given ATS has a STABLE shape.
 * This tool matches the accessibility tree `browser_snapshot` returns against
 * the four ATS URL shapes `agent/RUNBOOK.md` and `jobfeeds/ats.py` already
 * name (Ashby, Greenhouse, Lever, Personio) and reports, per board, one of
 * three outcomes: `searched` (postings found), `empty` (the search ran and
 * genuinely matched nothing), or `blocked` (the page was reachable but
 * unreadable — a CAPTCHA/bot-check, a consent wall, or a sign-in wall; see
 * `HarvestBoardResult.blockKind` — usually present, but absent for an
 * internal tool failure rather than a page signal). Extraction always runs
 * FIRST: postings found always win over any blocked or empty signal, so an
 * incidental reCAPTCHA footer notice on an otherwise readable page can never
 * suppress real results (see harvestClassify.ts).
 *
 * When a board's page plainly has content but URL-shape extraction matched
 * nothing — including a consent/bot-check phrase seen alongside real
 * content, which must never on its own discard that content — the result
 * also carries the raw snapshot text: the tier-3, LAST RESORT fallback the
 * calling model reads itself only in that one ambiguous case, rather than
 * this tool ever guessing at a selector.
 *
 * `harvest_postings` NEVER drives a sign-in flow through a tab: a board whose
 * URL is itself an obvious sign-in/login/auth URL (or whose query string
 * names one, e.g. `?action=login`) is refused before it is ever navigated
 * (see harvestNavigate.ts's `refuseSignInUrl`), and a wall discovered only
 * once the page loads is reported `blocked` with `blockKind: 'login'`, never
 * `empty` and never carrying a raw snapshot.
 *
 * Production dispatch in tools.ts passes `false` with no session pool, so
 * boards run serially through the primary MCP connection and saved profile,
 * with no tab management. The optional helper modes below remain dormant in
 * production, retaining their signatures and tests. Direct helper callers
 * can select the FIRST usable strategy of three, tried in this order:
 *  1. One independent MCP session per board (harvestSessions.ts), when the
 *     browser session pool (agent/harness/mcp/sessionPool.ts) has at least
 *     two sessions available. No tab tools at all in this path — each
 *     session already has its own "current tab".
 *  2. Failing that, one browser tab per board, all sharing the one Chromium
 *     profile and MCP connection, but ONLY once this invocation has
 *     confirmed, at runtime, that it can actually parse the browser server's
 *     tab listing (harvestTabs.ts's `probeTabListing`) — the upstream
 *     `@playwright/mcp` server's exact tab-list text format is not vendored
 *     in this workspace and was never a verified fact, only a guess, so
 *     resting live behaviour on it being right was the wrong default.
 *  3. Failing that too — the probe fails, or `tabToolsAvailable` is false
 *     because the tab-management tools are not advertised at all — every
 *     board is harvested SERIALLY, one at a time, in the single shared tab.
 *
 * All three report the same per-board classification and result shape; the
 * degraded (2→3) path names why it degraded rather than reporting every
 * board blocked. A single board's failure — thrown, not just returned as an
 * error result — is confined to that board in every path; it never discards
 * every other board's already-harvested results.
 *
 * Split across sibling modules in this directory: harvestTypes.ts (shared
 * types), harvestClassify.ts (extraction/classification), harvestNavigate.ts
 * (sign-in refusal, navigation-failure classification, search-box typing),
 * harvestTabs.ts (tab lifecycle: the async lock, tab-list parsing/probing,
 * create/select/close), harvestBoard.ts (per-board orchestration, serial and
 * tab-per-board), and harvestSessions.ts (per-board orchestration over
 * leased sessions). This module is the public entry point: the tool
 * definition and {@link harvestPostings} itself.
 *
 * This is dispatched exactly like `screen_posting` and `read_runbook_section`
 * — registered under the synthetic `builtin` server in tools.ts, BEFORE the
 * allow-list — but tools.ts hands this module a {@link BrowserToolCall}
 * closure that re-checks the allow-list and resolves the live namespaced tool
 * name for every underlying browser call this tool makes.
 */

import type { ToolDefinition } from '../providers/types.js';
import { errorMessage, harvestBounded, harvestOneBoardSafely, harvestSerial } from './harvestBoard.js';
import { harvestWithSessions } from './harvestSessions.js';
import { probeTabListing } from './harvestTabs.js';
import type { BrowserToolCall, BrowserToolPermissionCheck, HarvestBoardRequest, HarvestBoardResult, HarvestPostingsResult } from './harvestTypes.js';
import { MIN_SESSIONS_FOR_PARALLEL_HARVEST, type BrowserSessionPool } from '../mcp/sessionPool.js';

export type {
  BlockKind,
  BrowserToolCall,
  BrowserToolResult,
  HarvestBoardRequest,
  HarvestBoardResult,
  HarvestedPosting,
  HarvestOutcome,
  HarvestPostingsResult,
} from './harvestTypes.js';

/** The provider-facing definition advertised to the main loop's model. */
export const harvestPostingsTool: ToolDefinition = {
  name: 'harvest_postings',
  description:
    "Harvest one or more direct-search boards' results in ONE call, instead of driving " +
    'browser_navigate/browser_snapshot/browser_type yourself. Extracts posting URLs by ' +
    "matching each known ATS's stable URL shape against the page's accessibility tree — " +
    'never a CSS selector. Returns, per board, an outcome: "searched" (postings found — this ' +
    'value matches record_discovery_coverage\'s own status vocabulary, so pass it straight ' +
    'through as status) plus tier "harvest"; "empty" (the search ran and genuinely matched ' +
    'nothing); or "blocked" (the page was reachable but unreadable), which usually also carries ' +
    'a blockKind — "login" means call report_apply_failure with blocker="login_required" then ' +
    'record status "login_walled", never "blocked"; "wall" (a CAPTCHA/consent interstitial with ' +
    'no substantive content of its own) or "unreachable" (a confirmed DNS/connection failure, ' +
    'never just a slow page) both map to status "blocked" as-is; an ABSENT blockKind means an ' +
    'internal tool failure rather than a page signal — still record status "blocked", using note ' +
    'for detail. A board whose url looks like a sign-in page (by path or query string) is refused ' +
    'and never navigated — harvest never drives a sign-in flow through a tab. ' +
    "A board's result carries a raw snapshot ONLY when its page had content but extraction " +
    'matched nothing (including a consent/bot-check phrase seen alongside real content) — read ' +
    'that yourself as the last resort. Production harvests boards serially, one at a time, ' +
    'through the primary browser MCP connection and saved signed-in profile; it never opens ' +
    'extra sessions or manages tabs, regardless of advertised tab tools.',
  inputSchema: {
    type: 'object',
    properties: {
      boards: {
        type: 'array',
        description: 'One or more boards to harvest in order, serially on the primary browser connection.',
        items: {
          type: 'object',
          properties: {
            board: { type: 'string', description: "The board's name, for reporting." },
            url: { type: 'string', description: "The board's search or listing URL to open." },
            keywords: { type: 'string', description: 'Keywords to type into the detected search box, if any.' },
          },
          required: ['board', 'url'],
          additionalProperties: false,
        },
      },
    },
    required: ['boards'],
    additionalProperties: false,
  },
};

/**
 * Emit one structured stderr line naming which harvesting mode ran, how many
 * boards it covers, and (when it degraded) why — NEVER page content, only
 * the mode, count and reason.
 *
 * @param mode Which harvesting mode ran.
 * @param boardCount How many boards were harvested.
 * @param reason Present only when the concurrent-tabs path was abandoned for
 *   the serial fallback after a failed tab-listing probe.
 */
function logHarvestMode(mode: 'sessions' | 'concurrent-tabs' | 'serial', boardCount: number, reason?: string): void {
  const line = { event: 'harvest_postings.mode', mode, boards: boardCount, ...(reason ? { reason } : {}) };
  process.stderr.write(`${JSON.stringify(line)}\n`);
}

/** Human-readable explanation attached to the result (not just logged) when
 * the concurrent path is abandoned for the serial fallback, so the operator
 * reading the tool result — not only the run's stderr — can see why. */
const TAB_LIST_UNPARSEABLE_REASON =
  "the browser server's tab-listing text did not match any recognised format; harvested every board serially in the single shared tab instead of concurrently";

/**
 * Fill every board index the session-per-worker path left unclaimed —
 * `undefined` in `sessionResults`, because a worker either could not lease
 * even its first session or lost its session mid-harvest with no
 * replacement available (see harvestSessions.ts's own doc) — by harvesting
 * that board SERIALLY on the shared `call`, in request order. A dead session
 * this way costs at most its own board's failure; every other board is
 * still genuinely harvested, by a surviving worker or this fallback.
 */
async function fillUnclaimedBoards(
  call: BrowserToolCall,
  boards: HarvestBoardRequest[],
  sessionResults: (HarvestBoardResult | undefined)[],
): Promise<HarvestBoardResult[]> {
  const results: HarvestBoardResult[] = new Array(boards.length);
  for (let i = 0; i < boards.length; i++) {
    results[i] = sessionResults[i] ?? (await harvestOneBoardSafely(call, boards[i]));
  }
  return results;
}

/**
 * Decide the harvesting mode and run it, in the precedence this module's own
 * doc names: session-per-worker when the pool yields at least two sessions;
 * else concurrent tab-per-board when `tabToolsAvailable` AND a live probe
 * confirms the tab listing can be parsed; else serial.
 */
async function runHarvest(
  call: BrowserToolCall,
  boards: HarvestBoardRequest[],
  tabToolsAvailable: boolean,
  sessionPool?: BrowserSessionPool,
  isSessionToolPermitted?: BrowserToolPermissionCheck,
): Promise<HarvestPostingsResult> {
  const sessionCount = sessionPool ? await sessionPool.availableSessionCount() : 0;
  if (sessionPool && sessionCount >= MIN_SESSIONS_FOR_PARALLEL_HARVEST) {
    logHarvestMode('sessions', boards.length);
    const sessionResults = await harvestWithSessions(sessionPool, boards, sessionCount, isSessionToolPermitted);
    const results = await fillUnclaimedBoards(call, boards, sessionResults);
    return { content: JSON.stringify({ results }), isError: false };
  }
  if (!tabToolsAvailable) {
    logHarvestMode('serial', boards.length);
    return { content: JSON.stringify({ results: await harvestSerial(call, boards) }), isError: false };
  }
  const tabsParseable = await probeTabListing(call);
  if (!tabsParseable) {
    logHarvestMode('serial', boards.length, 'tab-list-unparseable');
    const results = await harvestSerial(call, boards);
    return { content: JSON.stringify({ results, degradedReason: TAB_LIST_UNPARSEABLE_REASON }), isError: false };
  }
  logHarvestMode('concurrent-tabs', boards.length);
  return { content: JSON.stringify({ results: await harvestBounded(call, boards) }), isError: false };
}

/** Whether `value` is a well-formed {@link HarvestBoardRequest} object. */
function isBoardLike(value: unknown): value is Record<string, unknown> {
  if (typeof value !== 'object' || value === null) return false;
  const v = value as Record<string, unknown>;
  return typeof v.board === 'string' && v.board.trim() !== '' && typeof v.url === 'string' && v.url.trim() !== '';
}

/** Coerce one raw board object, already validated by {@link isBoardLike}. */
function coerceBoard(v: Record<string, unknown>): HarvestBoardRequest {
  return {
    board: v.board as string,
    url: v.url as string,
    keywords: typeof v.keywords === 'string' ? v.keywords : undefined,
  };
}

/** Coerce the raw `boards` argument into a list of valid requests, dropping
 * any malformed entries rather than failing the whole call. */
function coerceBoards(raw: unknown): HarvestBoardRequest[] {
  if (!Array.isArray(raw)) return [];
  return raw.filter(isBoardLike).map(coerceBoard);
}

/**
 * Harvest one or more boards. Production passes `false` without a session
 * pool, forcing serial work in the primary tab; direct helper callers may
 * still exercise the optional tab/session paths (see the module doc).
 * Never throws: a missing/invalid `boards` argument,
 * or any failure raised while harvesting, is returned as an `isError`
 * result.
 *
 * @param rawArgs The raw tool-call arguments.
 * @param call Drives the allow-listed browser tools, supplied by tools.ts.
 * @param tabToolsAvailable Whether to try the dormant tab-management path;
 *   production explicitly passes false. The default retains helper behavior.
 * @param sessionPool Optional pool for dormant session-per-worker helpers;
 *   production never supplies one.
 * @param isSessionToolPermitted The allow-list check used only by the dormant
 *   session-per-worker path. `undefined` falls back to
 *   permitting everything (see harvestSessions.ts's `harvestWithSessions`),
 *   so an existing caller/test keeps working unchanged.
 * @returns The per-board results as JSON, or an error message, with `isError` set.
 */
export async function harvestPostings(
  rawArgs: Record<string, unknown>,
  call: BrowserToolCall,
  tabToolsAvailable = true,
  sessionPool?: BrowserSessionPool,
  isSessionToolPermitted?: BrowserToolPermissionCheck,
): Promise<HarvestPostingsResult> {
  const boards = coerceBoards(rawArgs.boards);
  if (boards.length === 0) {
    return { content: 'harvest_postings requires a non-empty boards array, each with board and url.', isError: true };
  }
  try {
    return await runHarvest(call, boards, tabToolsAvailable, sessionPool, isSessionToolPermitted);
  } catch (err) {
    return { content: `harvest_postings failed: ${errorMessage(err)}`, isError: true };
  }
}
