/**
 * The screening stage: for each candidate, fetch + extract, then screen and
 * persist one record per profile (one per posting per profile), stopping at
 * the first actionable pass or when the server reports the posting already
 * covered. Unreadable postings record a screening_blocker instead of a verdict.
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

/** Profile identity as the store compares it: stripped and casefolded. */
function normProfile(p: string): string {
  return p.trim().toLowerCase();
}

/**
 * Whether a stored result shows the posting is already covered: created:false
 * with a URL-wide record (different profile) or a queueing (passed/deferred) one.
 */
function isCovered(content: string, sentProfile: string): boolean {
  try {
    const s = JSON.parse(content) as { created?: boolean; profile?: string; verdict?: string };
    if (s.created !== false) return false;
    const differs = normProfile(s.profile ?? '') !== normProfile(sentProfile);
    return differs || s.verdict === 'passed' || s.verdict === 'deferred';
  } catch {
    return false;
  }
}

/** Screen one profile and persist its evidence; true when the posting needs no further profiles. */
async function screenProfile(d: ScreenStageDeps, c: Candidate, text: string, meta: Meta, profile: string, res: ScreenStageResult): Promise<boolean> {
  const args: Record<string, unknown> = {
    url: c.url, role: meta.role, company: meta.company, postingText: text, profile, criteria: d.criteria[profile],
    run_id: d.runId, source: c.channel,
  };
  if (meta.posted_date) args.posted_date = meta.posted_date;
  const screened = await screenPosting(args, d.screeningAdapter);
  let evidence: Record<string, unknown>;
  try {
    if (screened.isError) throw new Error(screened.content);
    evidence = JSON.parse(screened.content) as Record<string, unknown>;
  } catch (err) {
    res.errors.push(`${c.url} [${profile}]: ${screened.isError && err instanceof Error ? err.message : 'invalid screening evidence'}`);
    return false;
  }
  const out = await persistEvidence(args, evidence, d.record);
  if (out.isError) {
    res.errors.push(`${c.url} [${profile}]: ${out.content}`);
    return false;
  }
  if (!isActionable(out.content)) return isCovered(out.content, profile);
  res.passes.push({ url: c.url, title: c.title, ...meta, profile, channel: c.channel });
  return true;
}

/** Screen and record each profile with criteria in order, until a pass or existing coverage. */
async function screenProfiles(d: ScreenStageDeps, c: Candidate, text: string, meta: Meta, res: ScreenStageResult): Promise<void> {
  for (const profile of c.profiles) {
    if (!d.criteria[profile]) continue;
    if (await screenProfile(d, c, text, meta, profile, res)) return;
  }
}

/** Process one candidate end to end. */
async function processCandidate(d: ScreenStageDeps, fetchOne: ScreenStageDeps['fetch'], c: Candidate, res: ScreenStageResult): Promise<void> {
  const fetched = await fetchOne(c.url);
  if (fetched.unreadable) return recordBlocker(d, c, fetched.blocker, res);
  const meta = await extractMeta(d.extractAdapter, fetched.text, c.title);
  if (!meta.ok) return recordBlocker(d, c, meta.screening_blocker, res);
  await screenProfiles(d, c, fetched.text, meta.meta, res);
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
