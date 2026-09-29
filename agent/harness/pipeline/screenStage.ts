/**
 * The screening stage: for each candidate, fetch + extract, evaluate it
 * against each of its profiles' criteria WITHOUT persisting (stopping at the
 * first actionable pass), then persist exactly one outcome per URL: the pass,
 * or, when no profile passed, a single rejection. Unreadable postings record
 * a screening_blocker instead of a verdict.
 */
import { persistEvidence, type RecordScreeningCall } from '../builtins/screenAndRecordPosting.js';
import { screenPosting } from '../builtins/screenPosting.js';
import type { ProviderAdapter } from '../providers/types.js';
import { extractMeta } from './extractMeta.js';
import type { FetchedPosting } from './fetchPosting.js';
import type { Candidate } from './types.js';
import { BLOCKER_COMPANY_FALLBACK, BLOCKER_ROLE_FALLBACK, companyFromUrl, roleForBlocker } from './blockerIdentity.js';

export { BLOCKER_COMPANY_FALLBACK, BLOCKER_ROLE_FALLBACK, companyFromUrl };

/** How many candidates are screened at once. */
export const SCREEN_CONCURRENCY = 3;

/** A posting that passed screening and awaits an apply session. */
export interface ActionablePass {
  url: string;
  title: string;
  role: string;
  company: string;
  profile: string;
  posted_date: string;
  channel: string;
}

/** Everything the stage needs, injected so tests can mock each piece. */
export interface ScreenStageDeps {
  runId: string;
  /** Profile name to its full criteria text. */
  criteria: Record<string, string>;
  fetch: (url: string) => Promise<FetchedPosting>;
  extractAdapter: ProviderAdapter;
  screeningAdapter: ProviderAdapter;
  record: RecordScreeningCall;
  concurrency?: number;
}

/** Stage outcome. */
export interface ScreenStageResult {
  passes: ActionablePass[];
  blockers: number;
  /** Screening/recording errors; a non-empty list means the stage was not clean. */
  errors: string[];
}

interface Meta { role: string; company: string; posted_date: string }
/** One profile's unpersisted evaluation. */
interface Evaluation { args: Record<string, unknown>; evidence: Record<string, unknown>; profile: string }

/** Serialize async work (one shared browser tab must never interleave). */
function createMutex(): <T>(fn: () => Promise<T>) => Promise<T> {
  let tail: Promise<unknown> = Promise.resolve();
  return <T>(fn: () => Promise<T>): Promise<T> => {
    const run = tail.then(fn);
    tail = run.catch(() => undefined);
    return run;
  };
}

/** Record a screening_blocker for a posting we could not use. */
async function recordBlocker(d: ScreenStageDeps, c: Candidate, blocker: string, res: ScreenStageResult): Promise<void> {
  try {
    const out = await d.record({
      run_id: d.runId, url: c.url, role: roleForBlocker(c.title), company: companyFromUrl(c.url),
      profile: c.profiles.find((p) => d.criteria[p]) ?? c.profiles[0] ?? '',
      verdict: '', screening_blocker: blocker,
    });
    if (out.isError) res.errors.push(`record_screening failed for ${c.url}`);
    else res.blockers += 1;
  } catch (err) {
    res.errors.push(`record_screening failed for ${c.url}: ${err instanceof Error ? err.message : String(err)}`);
  }
}

/** Whether a stored-outcome result reports an actionable stored pass. */
function isActionable(content: string): boolean {
  try {
    return (JSON.parse(content) as { actionable?: boolean }).actionable === true;
  } catch {
    return false;
  }
}

function isPass(evidence: Record<string, unknown>): boolean {
  return evidence.verdict === 'passed' && !evidence.screening_blocker;
}

/** Evaluate profiles in order without persisting; stop at the first pass. */
async function evaluateProfiles(d: ScreenStageDeps, c: Candidate, text: string, meta: Meta, res: ScreenStageResult): Promise<Evaluation[]> {
  const evals: Evaluation[] = [];
  for (const profile of c.profiles) {
    const criteria = d.criteria[profile];
    if (!criteria) continue;
    const args: Record<string, unknown> = {
      url: c.url, role: meta.role, company: meta.company, postingText: text, profile, criteria,
      run_id: d.runId, source: c.channel,
    };
    if (meta.posted_date) args.posted_date = meta.posted_date;
    const out = await screenPosting(args, d.screeningAdapter);
    if (out.isError) {
      res.errors.push(`${c.url} [${profile}]: ${out.content.slice(0, 200)}`);
      continue;
    }
    try {
      evals.push({ args, profile, evidence: JSON.parse(out.content) as Record<string, unknown> });
    } catch {
      res.errors.push(`${c.url} [${profile}]: invalid screening evidence`);
      continue;
    }
    if (isPass(evals[evals.length - 1].evidence)) break;
  }
  return evals;
}

/** Persist exactly one outcome: the pass if any, else the first evaluation. */
async function persistOutcome(d: ScreenStageDeps, c: Candidate, meta: Meta, evals: Evaluation[], res: ScreenStageResult): Promise<void> {
  const chosen = evals.find((e) => isPass(e.evidence)) ?? evals[0];
  if (!chosen) return;
  const out = await persistEvidence(chosen.args, chosen.evidence, d.record);
  if (out.isError) {
    res.errors.push(`${c.url} [${chosen.profile}]: ${out.content.slice(0, 200)}`);
    return;
  }
  if (isActionable(out.content)) {
    res.passes.push({ url: c.url, title: c.title, ...meta, profile: chosen.profile, channel: c.channel });
  }
}

/** Process one candidate end to end. */
async function processCandidate(d: ScreenStageDeps, fetchOne: ScreenStageDeps['fetch'], c: Candidate, res: ScreenStageResult): Promise<void> {
  const fetched = await fetchOne(c.url);
  if (fetched.unreadable) return recordBlocker(d, c, fetched.blocker, res);
  const meta = await extractMeta(d.extractAdapter, fetched.text, c.title);
  if (!meta.ok) return recordBlocker(d, c, meta.screening_blocker, res);
  const evals = await evaluateProfiles(d, c, fetched.text, meta.meta, res);
  await persistOutcome(d, c, meta.meta, evals, res);
}

/**
 * Screen all candidates with bounded concurrency. Browser fetches are
 * serialized; extraction/screening LLM calls run concurrently.
 *
 * @returns Actionable passes (in candidate order), blocker count and errors.
 */
export async function screenCandidates(candidates: Candidate[], d: ScreenStageDeps): Promise<ScreenStageResult> {
  const perCandidate: ScreenStageResult[] = candidates.map(() => ({ passes: [], blockers: 0, errors: [] }));
  const exclusive = createMutex();
  const fetchOne = (url: string): Promise<FetchedPosting> => exclusive(() => d.fetch(url));
  let next = 0;
  const worker = async (): Promise<void> => {
    while (next < candidates.length) {
      const i = next++;
      try {
        await processCandidate(d, fetchOne, candidates[i], perCandidate[i]);
      } catch (err) {
        perCandidate[i].errors.push(`${candidates[i].url}: ${err instanceof Error ? err.message : String(err)}`);
      }
    }
  };
  const width = Math.max(1, Math.min(d.concurrency ?? SCREEN_CONCURRENCY, candidates.length));
  await Promise.all(Array.from({ length: width }, worker));
  return {
    passes: perCandidate.flatMap((r) => r.passes),
    blockers: perCandidate.reduce((n, r) => n + r.blockers, 0),
    errors: perCandidate.flatMap((r) => r.errors),
  };
}
