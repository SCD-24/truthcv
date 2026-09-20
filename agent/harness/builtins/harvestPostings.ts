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
 * Several boards are harvested CONCURRENTLY, each in its own browser tab
 * sharing the one Chromium profile, but ONLY once this invocation has
 * confirmed, at runtime, that it can actually parse the browser server's tab
 * listing (harvestTabs.ts's `probeTabListing`) — the upstream
 * `@playwright/mcp` server's exact tab-list text format is not vendored in
 * this workspace and was never a verified fact, only a guess, so resting
 * live behaviour on it being right was the wrong default. When the probe
 * fails (an errored call, or text this build cannot parse at all), every
 * board is instead harvested SERIALLY, one at a time, in the single shared
 * tab — same per-board classification and result shape, just no concurrency
 * and no tab tool calls — and the result names why it degraded rather than
 * reporting every board blocked. The same serial fallback is also taken
 * outright when `tabToolsAvailable` is false (the tab-management tools are
 * not advertised at all). A single board's failure — thrown, not just
 * returned as an error result — is confined to that board; it never
 * discards every other board's already-harvested results.
 *
 * Split across sibling modules in this directory: harvestTypes.ts (shared
 * types), harvestClassify.ts (extraction/classification), harvestNavigate.ts
 * (sign-in refusal, navigation-failure classification, search-box typing),
 * harvestTabs.ts (tab lifecycle: the async lock, tab-list parsing/probing,
 * create/select/close), and harvestBoard.ts (per-board orchestration, serial
 * and concurrent). This module is the public entry point: the tool
 * definition and {@link harvestPostings} itself.
 *
 * This is dispatched exactly like `screen_posting` and `read_runbook_section`
 * — registered under the synthetic `builtin` server in tools.ts, BEFORE the
 * allow-list — but tools.ts hands this module a {@link BrowserToolCall}
 * closure that re-checks the allow-list and resolves the live namespaced tool
 * name for every underlying browser call this tool makes.
 */

import type { ToolDefinition } from '../providers/types.js';
import { errorMessage, harvestBounded, harvestSerial } from './harvestBoard.js';
import { probeTabListing } from './harvestTabs.js';
import type { BrowserToolCall, HarvestBoardRequest, HarvestPostingsResult } from './harvestTypes.js';

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
    'that yourself as the last resort. Boards harvest concurrently, each in its own browser tab, ' +
    'when the browser server’s tab listing can be parsed; otherwise every board is harvested ' +
    'serially instead, one at a time, with the same result shape.',
  inputSchema: {
    type: 'object',
    properties: {
      boards: {
        type: 'array',
        description: 'One or more boards to harvest, each opened and searched in its own tab.',
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
 * @param reason Present only when the concurrent path was abandoned for the
 *   serial fallback after a failed tab-listing probe.
 */
function logHarvestMode(mode: 'concurrent-tabs' | 'serial', boardCount: number, reason?: string): void {
  const line = { event: 'harvest_postings.mode', mode, boards: boardCount, ...(reason ? { reason } : {}) };
  process.stderr.write(`${JSON.stringify(line)}\n`);
}

/** Human-readable explanation attached to the result (not just logged) when
 * the concurrent path is abandoned for the serial fallback, so the operator
 * reading the tool result — not only the run's stderr — can see why. */
const TAB_LIST_UNPARSEABLE_REASON =
  "the browser server's tab-listing text did not match any recognised format; harvested every board serially in the single shared tab instead of concurrently";

/**
 * Decide the harvesting mode and run it: concurrent tab-per-board when
 * `tabToolsAvailable` AND a live probe confirms the tab listing can be
 * parsed; serial otherwise — either because the tools are not advertised at
 * all, or because the probe failed. See this module's own doc for why the
 * probe exists.
 */
async function runHarvest(call: BrowserToolCall, boards: HarvestBoardRequest[], tabToolsAvailable: boolean): Promise<HarvestPostingsResult> {
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
 * Harvest one or more boards. Each in its own browser tab, bounded
 * concurrently, when `tabToolsAvailable` is true AND this invocation's own
 * tab-listing probe succeeds; serially in the single shared tab otherwise
 * (see the module doc). Never throws: a missing/invalid `boards` argument,
 * or any failure raised while harvesting, is returned as an `isError`
 * result.
 *
 * @param rawArgs The raw tool-call arguments.
 * @param call Drives the allow-listed browser tools, supplied by tools.ts.
 * @param tabToolsAvailable Whether the browser server advertises its
 *   tab-management tools, as decided by tools.ts's `browserTabToolsAvailable`.
 *   Defaults to true so every existing caller/test keeps today's concurrent
 *   behaviour unless it says otherwise.
 * @returns The per-board results as JSON, or an error message, with `isError` set.
 */
export async function harvestPostings(
  rawArgs: Record<string, unknown>,
  call: BrowserToolCall,
  tabToolsAvailable = true,
): Promise<HarvestPostingsResult> {
  const boards = coerceBoards(rawArgs.boards);
  if (boards.length === 0) {
    return { content: 'harvest_postings requires a non-empty boards array, each with board and url.', isError: true };
  }
  try {
    return await runHarvest(call, boards, tabToolsAvailable);
  } catch (err) {
    return { content: `harvest_postings failed: ${errorMessage(err)}`, isError: true };
  }
}
