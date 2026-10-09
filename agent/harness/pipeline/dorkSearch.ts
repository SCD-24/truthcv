/**
 * Paced Google dork search: one search at a time, 15-30 s apart (measured from
 * the persisted previous search, so pacing holds across runs), a 30-minute
 * cooldown after consecutive Google blocks, and deferral (never skipping) of
 * the queries that could not be searched. Sleeping happens outside the browser
 * lock; the lock is held only while a query is harvested.
 */
import { harvestPostings } from '../builtins/harvestPostings.js';
import type { BrowserToolCall, HarvestBoardRequest, HarvestBoardResult } from '../builtins/harvestPostings.js';
import { isGoogleInterstitial } from '../builtins/harvestClassify.js';
import { tryPassGoogleConsent } from './googleConsent.js';
import type { DorkState } from './dorkState.js';

/** Minimum pause (ms) between consecutive Google searches. */
export const DORK_PACING_MIN_MS = 15000;
/** Maximum pause (ms) between consecutive Google searches. */
export const DORK_PACING_MAX_MS = 30000;
/** Consecutive Google-blocked searches after which searching pauses. */
export const MAX_CONSECUTIVE_GOOGLE_BLOCKS = 2;
/** How long (ms) searching pauses after too many consecutive blocks. */
export const GOOGLE_COOLDOWN_MS = 30 * 60 * 1000;
/** Marker of Google's CAPTCHA interstitial. */
export const GOOGLE_SORRY = 'google.com/sorry';

/** Serializes async work (one shared browser tab must never interleave). */
export type Lock = <T>(fn: () => Promise<T>) => Promise<T>;

/** A lock that does not serialize. */
export const noLock: Lock = (fn) => fn();

/** Outcome of one dork: a harvest result, or the reason it was deferred (not searched). */
export interface DorkOutcome {
  r?: HarvestBoardResult;
  deferredReason?: string;
}

/** Everything the search loop needs, injected for tests. */
export interface DorkSearchDeps {
  call: BrowserToolCall;
  sleep: (ms: number) => Promise<void>;
  random: () => number;
  now: () => number;
  lock: Lock;
  /** Mutated in place (lastSearchAt, block counter, cooldown, deferred). */
  state: DorkState;
  /** Persists the state; returns an error string on failure. */
  saveState?: (state: DorkState) => Promise<string | undefined>;
  /** Collects harvest and persistence errors. */
  errors: string[];
  /** Called as soon as each dork's outcome is known (outside the lock). */
  onOutcome?: (index: number, outcome: DorkOutcome) => Promise<void>;
}

/**
 * Draw a pacing delay in [DORK_PACING_MIN_MS, DORK_PACING_MAX_MS] inclusive.
 *
 * @param random Random source in [0, 1).
 */
export function dorkPacingMs(random: () => number): number {
  const ms = DORK_PACING_MIN_MS + Math.floor(random() * (DORK_PACING_MAX_MS - DORK_PACING_MIN_MS + 1));
  if (Number.isNaN(ms)) return DORK_PACING_MIN_MS;
  return Math.min(DORK_PACING_MAX_MS, Math.max(DORK_PACING_MIN_MS, ms));
}

/** True when a harvest result is a Google block/CAPTCHA interstitial. */
export function isGoogleBlock(r: HarvestBoardResult | undefined): boolean {
  return r?.outcome === 'blocked' && (isGoogleInterstitial(r.url) || r.url.includes(GOOGLE_SORRY) || /google/i.test(r.note ?? ''));
}

/** Parse the harvest tool's JSON into results (empty on failure). */
export function parseResults(content: string): HarvestBoardResult[] {
  try {
    const parsed = JSON.parse(content) as { results?: HarvestBoardResult[] };
    return Array.isArray(parsed.results) ? parsed.results : [];
  } catch {
    return [];
  }
}

/** Whether `url` is Google's consent host. */
function isConsentPage(url: string): boolean {
  try {
    return new URL(url).hostname.toLowerCase().startsWith('consent.');
  } catch {
    return false;
  }
}

/** Harvest one dork; harvest tool errors are pushed to `errors`. */
async function harvestOne(req: HarvestBoardRequest, call: BrowserToolCall, errors: string[]): Promise<HarvestBoardResult | undefined> {
  const res = await harvestPostings({ boards: [req] }, call, false);
  if (res.isError) errors.push(res.content);
  return res.isError ? undefined : parseResults(res.content)[0];
}

/** Harvest one dork under the browser lock, retrying once after a passed consent page (first time only). */
async function searchOne(req: HarvestBoardRequest, d: DorkSearchDeps, ctx: { consentTried: boolean }): Promise<HarvestBoardResult | undefined> {
  return d.lock(async () => {
    let r = await harvestOne(req, d.call, d.errors);
    if (!ctx.consentTried && r && isGoogleBlock(r) && isConsentPage(r.url)) {
      ctx.consentTried = true;
      if (await tryPassGoogleConsent(d.call, r.url)) r = await harvestOne(req, d.call, d.errors);
    }
    return r;
  });
}

/** Wait until a random 15-30 s has passed since the previous search (none on the very first). */
async function pace(d: DorkSearchDeps): Promise<void> {
  if (d.state.lastSearchAt <= 0) return;
  const wait = d.state.lastSearchAt + dorkPacingMs(d.random) - d.now();
  if (wait > 0) await d.sleep(wait);
}

/** Update the block counter; returns true when this result starts a cooldown. */
function trackBlock(state: DorkState, r: HarvestBoardResult | undefined, now: number): boolean {
  if (!isGoogleBlock(r)) {
    state.consecutiveBlocks = 0;
    return false;
  }
  state.consecutiveBlocks += 1;
  if (state.consecutiveBlocks < MAX_CONSECUTIVE_GOOGLE_BLOCKS) return false;
  state.cooldownUntil = now + GOOGLE_COOLDOWN_MS;
  state.consecutiveBlocks = 0;
  return true;
}

/** Name of the Google block a result was: the CAPTCHA/sorry page, else the consent page. */
function blockKind(r: HarvestBoardResult | undefined): string {
  const sorry = !!r && (r.url.includes(GOOGLE_SORRY) || (r.note ?? '').includes(GOOGLE_SORRY) || (r.rawSnapshot ?? '').includes(GOOGLE_SORRY));
  return sorry ? 'Google CAPTCHA (/sorry)' : 'Google consent page could not be passed';
}

/** Reason recorded for a dork not searched; `kind` is set when the cooldown started this run. */
function deferReason(state: DorkState, kind: string | undefined): string {
  const until = new Date(state.cooldownUntil).toISOString();
  if (kind) return `not searched: ${kind} on ${MAX_CONSECUTIVE_GOOGLE_BLOCKS} searches in a row; Google search paused until ${until}; queued first for the next run`;
  return `not searched: Google search paused until ${until} after repeated blocks; queued first for the next run`;
}

async function persist(d: DorkSearchDeps): Promise<void> {
  const err = d.saveState ? await d.saveState(d.state) : undefined;
  if (err) d.errors.push(err);
}

/**
 * Search dorks in order, paced and cooldown-aware. Dorks not searched because
 * of a cooldown are returned as `deferredReason` outcomes (never skipped) and
 * remembered in `state.deferred` so the next run searches them first.
 *
 * @param dorks Dork requests in priority order (`board` is the coverage board name).
 * @param d Injected dependencies.
 */
export async function searchDorks(dorks: HarvestBoardRequest[], d: DorkSearchDeps): Promise<DorkOutcome[]> {
  const out: DorkOutcome[] = [];
  const pending = new Set(dorks.map((_, i) => i));
  const pendingBoards = (): string[] => dorks.filter((_, i) => pending.has(i)).map((x) => x.board);
  const ctx = { consentTried: false };
  let kind: string | undefined;
  for (let i = 0; i < dorks.length; i++) {
    let outcome: DorkOutcome;
    if (d.state.cooldownUntil > d.now()) {
      outcome = { deferredReason: deferReason(d.state, kind) };
    } else {
      await pace(d);
      d.state.lastSearchAt = d.now();
      const r = await searchOne(dorks[i], d, ctx);
      kind = trackBlock(d.state, r, d.now()) ? blockKind(r) : undefined;
      if (!isGoogleBlock(r)) pending.delete(i);
      d.state.deferred = pendingBoards();
      outcome = { r };
      await persist(d);
    }
    out.push(outcome);
    if (d.onOutcome) await d.onOutcome(i, outcome);
  }
  d.state.deferred = pendingBoards();
  await persist(d);
  return out;
}
