/**
 * Per-URL screening outcomes: classifies what the store reported for one
 * profile's record and resolves several profiles into one outcome per posting.
 */

/** Final fate of one screened candidate URL. */
export type Outcome = 'for_review' | 'blocked' | 'rejected' | 'previously_screened' | 'failed';

/** An outcome with a human-readable explanation. */
export interface Classified {
  outcome: Outcome;
  detail: string;
}

/** The outcome of one candidate URL. */
export interface UrlOutcome extends Classified {
  url: string;
}

/** Detail recorded when another record already covers the posting. */
export const COVERED_DETAIL = 'screened by another record during this run';

/**
 * Outcomes from strongest to weakest, used to merge several profiles' results.
 * previously_screened ranks last: nothing new happened this run, so any outcome
 * produced this run, including a failure, is more accurate.
 */
const PRECEDENCE: Outcome[] = ['for_review', 'blocked', 'rejected', 'failed', 'previously_screened'];

/** A classified result tagged with the profile that produced it. */
export type ProfileClassified = Classified & { profile: string };

/** The shape of a stored-outcome result (as built by persistEvidence). */
interface Stored {
  created?: boolean;
  profile?: string;
  verdict?: string;
  screening_blocker?: string;
  actionable?: boolean;
}

/** Parse a stored-outcome result; `{}` when it is not JSON. */
function parseStored(content: string): Stored {
  try {
    return (JSON.parse(content) ?? {}) as Stored;
  } catch {
    return {};
  }
}

/** Whether a stored-outcome result reports an actionable stored pass. */
export function isActionable(content: string): boolean {
  return parseStored(content).actionable === true;
}

/** Profile identity as the store compares it: stripped and casefolded. */
function normProfile(p: string): string {
  return p.trim().toLowerCase();
}

/**
 * Whether a stored result shows the posting is already covered: created:false
 * with a URL-wide record (different profile) or a queueing (passed/deferred) one.
 */
export function isCovered(content: string, sentProfile: string): boolean {
  const s = parseStored(content);
  if (s.created !== false) return false;
  const differs = normProfile(s.profile ?? '') !== normProfile(sentProfile);
  return differs || s.verdict === 'passed' || s.verdict === 'deferred';
}

/** Classify a successfully persisted result for one profile; never drops a result. */
export function classifyStored(content: string, profile: string): Classified {
  const s = parseStored(content);
  if (isActionable(content)) return { outcome: 'for_review', detail: profile };
  if (isCovered(content, profile)) return { outcome: 'previously_screened', detail: COVERED_DETAIL };
  if (s.screening_blocker) return { outcome: 'blocked', detail: s.screening_blocker };
  if (s.verdict === 'rejected') return { outcome: 'rejected', detail: `rejected for profile ${profile}` };
  return { outcome: 'failed', detail: `stored verdict '${s.verdict ?? ''}' for profile ${profile} is not actionable` };
}

/** Merge per-profile results into one outcome; `emptyDetail` explains an empty list. */
export function pickOutcome(results: ProfileClassified[], emptyDetail: string): Classified {
  if (results.length === 0) return { outcome: 'failed', detail: emptyDetail };
  const rank = (c: Classified): number => PRECEDENCE.indexOf(c.outcome);
  const picked = results.reduce((best, c) => (rank(c) < rank(best) ? c : best));
  if (results.length === 1) return { outcome: picked.outcome, detail: picked.detail };
  const list = results.map((r) => `${r.profile}: ${r.outcome}`).join('; ');
  return { outcome: picked.outcome, detail: `${picked.detail} (${list})` };
}
