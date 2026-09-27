/**
 * Shared location-aware search-and-classify flow for `harvest_postings`' two
 * navigation strategies (the degraded single-shared-tab path in
 * harvestBoard.ts's `harvestOneBoard`, and the tab-per-board path in its
 * `harvestInTab`) — split out here because it is IDENTICAL in both.
 *
 * A board entry's `location` is typed into the board's own detected
 * location field, NEVER folded into `keywords`. When no `location` is given,
 * or the page shows no location field at all, behaviour is byte-for-byte
 * today's: keywords typed (if any), one classification, done — no extra
 * browser calls. Only once a location field IS found does this retry a
 * zero-result combined search against a location-only CONTROL search (a
 * fresh re-navigation of `board.url` typing just the location, no keywords)
 * across the board's known local-language aliases (see harvestLocation.ts),
 * to tell a board that never recognised the location apart from one that
 * merely has nothing to show for it. The control is deliberately NOT
 * required to classify `'searched'` — many boards list their own posting
 * links in a shape that classifies `needs_review`, not `'searched'` — only
 * that it neither rejects the location nor explicitly reports zero matches.
 * Any browser error mid-flow falls back to classifying the best snapshot
 * obtained so far; this never throws.
 */

import { blockedResult, classifySnapshot, isExplicitlyEmpty } from './harvestClassify.js';
import { findLocationFieldRef, locationCandidates, showsLocationRejected } from './harvestLocation.js';
import { navigateAndSnapshot, searchAndSnapshot, type KeywordSearchResult } from './harvestNavigate.js';
import type { BrowserToolCall, HarvestBoardRequest, HarvestBoardResult } from './harvestTypes.js';

/** Type `location` into the location field at `ref` and, when `keywords` is
 * given, then into the keyword box too — location submitted only once
 * keywords (if any) have also been typed, matching a real user filling both
 * fields before submitting. THROWS on a `browser_type`/`browser_snapshot`
 * error rather than silently returning `snapshot` unchanged — a silent
 * fallback here previously let a failed control-search type get read as a
 * confirmed empty result; the caller's location-control flow aborts on this
 * and falls back to the best snapshot seen so far instead. */
async function typeLocationAndKeywords(
  call: BrowserToolCall,
  snapshot: string,
  ref: string,
  location: string,
  keywords: string | undefined,
): Promise<string> {
  const typed = await call('browser_type', { element: 'location box', ref, text: location, submit: !keywords });
  if (typed.isError) throw new Error(`location box: browser_type failed: ${typed.content}`);
  if (!keywords) {
    const snap = await call('browser_snapshot', {});
    if (snap.isError) throw new Error(`location box: browser_snapshot failed: ${snap.content}`);
    return snap.content;
  }
  return (await searchAndSnapshot(call, snapshot, keywords)).snapshot;
}

/** Run the combined keywords+location search for `candidate` against the
 * given `snapshot`, or `undefined` when `snapshot` has no location field at
 * all (e.g. the freshly re-navigated page for a later candidate lost it). */
async function combinedSearchAttempt(
  call: BrowserToolCall,
  board: HarvestBoardRequest,
  snapshot: string,
  candidate: string,
): Promise<string | undefined> {
  const ref = findLocationFieldRef(snapshot);
  if (!ref) return undefined;
  return typeLocationAndKeywords(call, snapshot, ref, candidate, board.keywords);
}

/** Outcome of one control-search attempt for a single candidate: `result` is
 * set when the control resolved the board outright (either a confirmed
 * empty location match, or a wall/login block found on the control page —
 * see bug fix in {@link controlSearchAttempt}); `ran` is true whenever the
 * control search actually executed and produced a snapshot to classify, so
 * the caller can tell an executed-but-inconclusive attempt (worth counting
 * as "tried") from one that never ran at all (no location field found). */
interface ControlAttempt {
  result?: HarvestBoardResult;
  ran: boolean;
}

/** Re-navigate fresh to `board.url` and run a LOCATION-ONLY control search
 * for `candidate` — no keywords at all. Classifies the control snapshot
 * FIRST: a control page that shows a login/consent/bot wall resolves
 * straight to that `blocked` result rather than ever being read as a
 * confirmed empty match. Otherwise resolves to a confirmed `'empty'` result
 * only if the board neither rejected `candidate` nor explicitly reported
 * zero matches for it. A navigation error THROWS, aborting the caller's
 * whole location-control loop rather than being silently read as "location
 * not recognised". */
async function controlSearchAttempt(call: BrowserToolCall, board: HarvestBoardRequest, candidate: string): Promise<ControlAttempt> {
  const navigated = await navigateAndSnapshot(call, board.url);
  if ('error' in navigated) throw new Error(navigated.error);
  const ref = findLocationFieldRef(navigated.snapshot);
  if (!ref) return { ran: false };
  const snap = await typeLocationAndKeywords(call, navigated.snapshot, ref, candidate, undefined);
  const classified = classifySnapshot(board, snap);
  if (classified.outcome === 'blocked') return { ran: true, result: classified };
  if (isExplicitlyEmpty(snap) || showsLocationRejected(snap)) return { ran: true };
  const note = `search ran; zero matches; location "${candidate}" confirmed recognised by a location-only control search`;
  return { ran: true, result: { board: board.board, url: board.url, outcome: 'empty', tier: '', postings: [], note } };
}

/** Append a parenthetical naming `candidate` to a non-empty result's note,
 * when it has one, so the caller can tell which location alias succeeded. */
function withLocationNote(result: HarvestBoardResult, candidate: string): HarvestBoardResult {
  if (!result.note) return result;
  return { ...result, note: `${result.note} (location: "${candidate}")` };
}

/** Resolve a zero-result combined search that had a detected location field:
 * for each candidate location (the board's own value, then its known
 * aliases), retry the combined search, falling back to a location-only
 * control search on an explicit zero. Stops at the first candidate either
 * one confirms; falls back to classifying the best snapshot seen so far on
 * any unexpected browser error, and reports `blocked`/`'location'` if no
 * candidate is ever confirmed. */
async function resolveLocationControl(call: BrowserToolCall, board: HarvestBoardRequest, snapshot: string): Promise<HarvestBoardResult> {
  const state: CandidateState = { best: snapshot, tried: [] };
  try {
    const candidates = locationCandidates(board.location as string);
    for (let i = 0; i < candidates.length; i++) {
      const page = i === 0 ? snapshot : await freshPage(call, board);
      const resolved = await tryCandidate(call, board, page, candidates[i], state);
      if (resolved) return resolved;
    }
  } catch {
    return classifySnapshot(board, state.best);
  }
  // No candidate's control search ever actually ran: there is no evidence the
  // board failed to recognise the location, so the combined result stands.
  if (state.tried.length === 0) return classifySnapshot(board, state.best);
  return blockedResult(board, `location not recognised by the board: tried ${state.tried.join(', ')} — location-only control searches returned zero results`, 'location');
}

/** Mutable progress across candidates: `best` is the most recent completed
 * combined-search snapshot (the fallback on a mid-flow browser error), and
 * `tried` the candidates whose rejection or control search actually ran. */
interface CandidateState {
  best: string;
  tried: string[];
}

/** Re-navigate fresh to `board.url`; THROWS on a navigation error so the
 * caller falls back rather than reading it as "location not recognised". */
async function freshPage(call: BrowserToolCall, board: HarvestBoardRequest): Promise<string> {
  const navigated = await navigateAndSnapshot(call, board.url);
  if ('error' in navigated) throw new Error(navigated.error);
  return navigated.snapshot;
}

/** Run one candidate's combined search and, on an explicit zero, its
 * control search. Returns a result when the candidate resolves the board,
 * or `undefined` to move on to the next candidate. */
async function tryCandidate(
  call: BrowserToolCall,
  board: HarvestBoardRequest,
  page: string,
  candidate: string,
  state: CandidateState,
): Promise<HarvestBoardResult | undefined> {
  const combined = await combinedSearchAttempt(call, board, page, candidate);
  if (!combined) return undefined;
  state.best = combined;
  const classified = classifySnapshot(board, combined);
  if (classified.outcome === 'searched') return withLocationNote(classified, candidate);
  if (showsLocationRejected(combined)) {
    state.tried.push(candidate);
    return undefined;
  }
  if (classified.outcome !== 'empty') return withLocationNote(classified, candidate);
  const control = await controlSearchAttempt(call, board, candidate);
  if (control.ran) state.tried.push(candidate);
  return control.result;
}

/**
 * Type a board's keywords and, when given, its location into its own
 * detected fields, classify the result, and — only on a detected location
 * field — resolve a zero-result combined search against the board's own
 * location control. Never throws: any browser error falls back to
 * classifying the best snapshot obtained so far.
 */
export async function searchAndClassify(call: BrowserToolCall, board: HarvestBoardRequest, snapshot: string): Promise<HarvestBoardResult> {
  try {
    const locationRef = board.location ? findLocationFieldRef(snapshot) : undefined;
    if (!locationRef) {
      if (!board.keywords) return classifySnapshot(board, snapshot);
      const search = await searchAndSnapshot(call, snapshot, board.keywords);
      return annotateUnsubmitted(classifySnapshot(board, search.snapshot), search);
    }
    return await resolveLocationControl(call, board, snapshot);
  } catch {
    return classifySnapshot(board, snapshot);
  }
}

/** When `result` is `needs_review` and the keyword search never confirmed
 * being submitted, append the search's own `reason` to `result.note` so an
 * operator reviewing it can tell an unconfirmed search apart from a
 * genuinely unrecognised page. Returns `result` unchanged otherwise. */
function annotateUnsubmitted(result: HarvestBoardResult, search: KeywordSearchResult): HarvestBoardResult {
  if (result.outcome !== 'needs_review' || search.submitted) return result;
  const suffix = `search not submitted: ${search.reason}`;
  return { ...result, note: result.note ? `${result.note}; ${suffix}` : suffix };
}
