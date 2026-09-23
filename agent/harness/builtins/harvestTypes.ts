/**
 * Shared types for the `harvest_postings` built-in tool — split out from
 * harvestPostings.ts (agent/harness/builtins/) so each sibling module
 * (classification, navigation, tab lifecycle, per-board orchestration) can
 * import them without pulling in the whole tool. See harvestPostings.ts's
 * own module doc for the tool's behaviour as a whole.
 */

/** One board to harvest: its display name, search URL, and optional keywords. */
export interface HarvestBoardRequest {
  /** The board's name, for reporting. */
  board: string;
  /** The board's search or listing URL to open. */
  url: string;
  /** Keywords to type into the board's own detected search box, if any. */
  keywords?: string;
}

/** One posting extracted by URL-shape heuristics. */
export interface HarvestedPosting {
  /** The posting's own URL, exactly as found in the accessibility tree. */
  url: string;
  /** The link's accessible name, as the posting's title. */
  title: string;
  /** Which known ATS's URL shape matched (`ashby`, `greenhouse`, `lever`, `personio`). */
  ats: string;
}

/** `needs_review` is internal only, NEVER a coverage status. Resolve its
 * rawSnapshot to searched/llm if postings are recovered, empty only with
 * explicit zero-result evidence, otherwise blocked with extraction detail.
 * A blocked login maps to login_walled after report_apply_failure. */
export type HarvestOutcome = 'searched' | 'empty' | 'blocked' | 'needs_review';

/** Which kind of `blocked` a result is, for a `blocked` outcome only —
 * `'login'` a sign-in wall (or a sign-in URL refused before navigating),
 * `'wall'` a CAPTCHA/bot-check or consent interstitial page that shows no
 * substantive content of its own, `'unreachable'` a CONFIRMED DNS/
 * connection-class navigation failure — distinct from `'wall'`, since a dead
 * board and a bot wall need different operator follow-up, and distinct from
 * a merely slow page (see harvestNavigate.ts's `isUnreachableNavigationError`).
 * A `blocked` result's `blockKind` can also be `undefined` — see
 * {@link HarvestBoardResult.blockKind}. */
export type BlockKind = 'login' | 'wall' | 'unreachable';

/** One board's harvest result. */
export interface HarvestBoardResult {
  board: string;
  url: string;
  outcome: HarvestOutcome;
  /** `'harvest'` when `postings` is non-empty; `''` otherwise — mirrors
   * `record_discovery_coverage`'s own `tier` argument. */
  tier: 'harvest' | '';
  postings: HarvestedPosting[];
  /** One-line human-readable explanation of the outcome. */
  note: string;
  /** Present only when `outcome` is `'blocked'` AND the block was decided
   * from a signal read from the page or from navigation itself (login/wall/
   * unreachable). `undefined` on a `blocked` result that instead came from
   * an INTERNAL tool failure — a thrown transport error, a `browser_snapshot`
   * call that itself errored, or a navigation failure too generic to
   * confidently call a dead URL — rather than any signal read from the page;
   * `note` always explains that case, so an absent `blockKind` is never a
   * silent gap. */
  blockKind?: BlockKind;
  /** Present only for the tier-3 last-resort case: content existed but
   * extraction matched nothing (including a consent/bot-check phrase seen
   * alongside real content). Never present on a `blocked` result. */
  rawSnapshot?: string;
}

/** The result shape this handler returns, mirroring every other built-in's `{ content, isError }`. */
export interface HarvestPostingsResult {
  content: string;
  isError: boolean;
}

/** One flattened browser MCP tool result — mirrors `mcp/client.ts`'s `ToolCallResult`. */
export interface BrowserToolResult {
  content: string;
  isError: boolean;
}

/**
 * Call one allow-listed browser tool by its bare name. Supplied by tools.ts,
 * bound to the live `McpClientPool` and re-checking the allow-list on every
 * call — this module never talks to the pool directly.
 */
export type BrowserToolCall = (toolName: string, args: Record<string, unknown>) => Promise<BrowserToolResult>;

/**
 * Check whether a bare browser tool name may be called at all — tools.ts's
 * `isBrowserToolCallPermitted` in production, reused by harvestSessions.ts's
 * session-per-worker path (which dispatches on each leased session's own MCP
 * client directly, never through the `BrowserToolCall` closure above, so it
 * needs its OWN allow-list check rather than inheriting one).
 *
 * @returns The refusal message when the tool is not permitted; `undefined`
 *   when it is.
 */
export type BrowserToolPermissionCheck = (toolName: string) => string | undefined;
