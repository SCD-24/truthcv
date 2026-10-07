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
import { classifyStored, pickOutcome, type Classified, type ProfileClassified, type UrlOutcome } from './outcomes.js';
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
  /** Exactly one outcome per candidate screened. */
  outcomes: UrlOutcome[];
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
    const profile = c.profiles.find((p) => d.criteria[p]) ?? c.profiles[0] ?? '';
    const out = await d.record({
      run_id: d.runId, url: c.url, role: roleForBlocker(c.title), company: companyFromUrl(c.url),
      profile, verdict: '', screening_blocker: blocker,
    });
    if (out.isError) failOutcome(res, c, `record_screening failed for ${c.url}`);
    else {
      res.blockers += 1;
      const created = !createdFalse(out.content);
      const verdict: Classified = created ? { outcome: 'blocked', detail: blocker } : classifyStored(out.content, profile);
      res.outcomes.push({ url: c.url, ...verdict });
    }
  } catch (err) {
    failOutcome(res, c, `record_screening failed for ${c.url}: ${err instanceof Error ? err.message : String(err)}`);
  }
}

/** True when a record_screening reply reports an existing record (`created: false`), parsed not pattern-matched. */
function createdFalse(content: string): boolean {
  try {
    const parsed: unknown = JSON.parse(content);
    return typeof parsed === 'object' && parsed !== null && (parsed as { created?: unknown }).created === false;
  } catch {
    return false;
  }
}

/** Record a candidate-level failure as both an error and the candidate's outcome. */
function failOutcome(res: ScreenStageResult, c: Candidate, text: string): void {
  res.errors.push(text);
  res.outcomes.push({ url: c.url, outcome: 'failed', detail: text });
}

/** One profile's result: its classified outcome and whether later profiles are unnecessary. */
interface ProfileResult {
  stop: boolean;
  verdict: Classified;
}

/** A failed profile result; the text is also pushed to the stage errors. */
function failedProfile(res: ScreenStageResult, text: string): ProfileResult {
  res.errors.push(text);
  return { stop: false, verdict: { outcome: 'failed', detail: text } };
}

/** Parse the screening result into evidence, or return the error text. */
function parseEvidence(screened: { content: string; isError: boolean }): Record<string, unknown> | string {
  if (screened.isError) return screened.content;
  try {
    return JSON.parse(screened.content) as Record<string, unknown>;
  } catch {
    return 'invalid screening evidence';
  }
}

/** Screen one profile and persist its evidence; `stop` is true when no further profiles are needed. */
async function screenProfile(d: ScreenStageDeps, c: Candidate, text: string, meta: Meta, profile: string, res: ScreenStageResult): Promise<ProfileResult> {
  const args: Record<string, unknown> = {
    url: c.url, role: meta.role, company: meta.company, postingText: text, profile, criteria: d.criteria[profile],
    run_id: d.runId, source: c.channel,
  };
  if (meta.posted_date) args.posted_date = meta.posted_date;
  const screened = await screenPosting(args, d.screeningAdapter);
  const evidence = parseEvidence(screened);
  if (typeof evidence === 'string') return failedProfile(res, `${c.url} [${profile}]: ${evidence}`);
  const out = await persistEvidence(args, evidence, d.record);
  if (out.isError) return failedProfile(res, `${c.url} [${profile}]: ${out.content}`);
  const verdict = classifyStored(out.content, profile);
  if (verdict.outcome === 'for_review') res.passes.push({ url: c.url, title: c.title, ...meta, profile, channel: c.channel });
  return { stop: verdict.outcome === 'for_review' || verdict.outcome === 'previously_screened', verdict };
}

/** Screen and record each profile with criteria in order, until a pass or existing coverage. */
async function screenProfiles(d: ScreenStageDeps, c: Candidate, text: string, meta: Meta, res: ScreenStageResult): Promise<void> {
  const results: ProfileClassified[] = [];
  let current = '';
  try {
    for (const profile of c.profiles) {
      if (!d.criteria[profile]) continue;
      current = profile;
      const r = await screenProfile(d, c, text, meta, profile, res);
      results.push({ ...r.verdict, profile });
      if (r.stop) break;
    }
  } catch (err) {
    results.push({ ...failedProfile(res, `${c.url}: ${err instanceof Error ? err.message : String(err)}`).verdict, profile: current });
  }
  const picked = pickOutcome(results, `no criteria for profiles: ${c.profiles.join(', ')}`);
  res.outcomes.push({ url: c.url, ...picked });
}

/** Process one candidate end to end. */
async function processCandidate(d: ScreenStageDeps, fetchOne: ScreenStageDeps['fetch'], c: Candidate, res: ScreenStageResult): Promise<void> {
  const fetched = await fetchOne(c.url);
  if ('failed' in fetched) {
    failOutcome(res, c, `${c.url}: posting could not be loaded: ${fetched.reason}`);
    return;
  }
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
  const perCandidate: ScreenStageResult[] = candidates.map(() => ({ passes: [], blockers: 0, errors: [], outcomes: [] }));
  const exclusive = createMutex();
  const fetchOne = (url: string): Promise<FetchedPosting> => exclusive(() => d.fetch(url));
  let next = 0;
  const worker = async (): Promise<void> => {
    while (next < candidates.length) {
      const i = next++;
      try {
        await processCandidate(d, fetchOne, candidates[i], perCandidate[i]);
      } catch (err) {
        const text = `${candidates[i].url}: ${err instanceof Error ? err.message : String(err)}`;
        if (perCandidate[i].outcomes.length) perCandidate[i].errors.push(text);
        else failOutcome(perCandidate[i], candidates[i], text);
      }
    }
  };
  const width = Math.max(1, Math.min(d.concurrency ?? SCREEN_CONCURRENCY, candidates.length));
  await Promise.all(Array.from({ length: width }, worker));
  return {
    passes: perCandidate.flatMap((r) => r.passes),
    blockers: perCandidate.reduce((n, r) => n + r.blockers, 0),
    errors: perCandidate.flatMap((r) => r.errors),
    outcomes: perCandidate.flatMap((r) => r.outcomes),
  };
}
