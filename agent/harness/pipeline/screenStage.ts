/**
 * The screening stage: for each candidate, fetch + extract, then screen it
 * against each of its profiles' criteria (stopping at the first actionable
 * pass). Unreadable postings record a screening_blocker instead of a verdict.
 */
import { screenAndRecordPosting, type RecordScreeningCall } from '../builtins/screenAndRecordPosting.js';
import type { ProviderAdapter } from '../providers/types.js';
import { extractMeta } from './extractMeta.js';
import type { FetchedPosting } from './fetchPosting.js';
import type { Candidate } from './types.js';

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

/** Record a screening_blocker for a posting we could not use. */
async function recordBlocker(d: ScreenStageDeps, c: Candidate, blocker: string, res: ScreenStageResult): Promise<void> {
  try {
    const out = await d.record({
      run_id: d.runId, url: c.url, role: c.title || 'unknown', company: 'unknown',
      profile: c.profiles.find((p) => d.criteria[p]) ?? c.profiles[0] ?? '',
      verdict: '', screening_blocker: blocker,
    });
    if (out.isError) res.errors.push(`record_screening failed for ${c.url}`);
    else res.blockers += 1;
  } catch (err) {
    res.errors.push(`record_screening failed for ${c.url}: ${err instanceof Error ? err.message : String(err)}`);
  }
}

/** Whether a screenAndRecordPosting result reports an actionable stored pass. */
function isActionable(content: string): boolean {
  try {
    return (JSON.parse(content) as { actionable?: boolean }).actionable === true;
  } catch {
    return false;
  }
}

/** Screen one usable posting per profile until one is actionable. */
async function screenProfiles(d: ScreenStageDeps, c: Candidate, text: string, meta: { role: string; company: string; posted_date: string }, res: ScreenStageResult): Promise<void> {
  for (const profile of c.profiles) {
    const criteria = d.criteria[profile];
    if (!criteria) continue;
    const args: Record<string, unknown> = {
      url: c.url, role: meta.role, company: meta.company, postingText: text, profile, criteria,
      run_id: d.runId, source: c.channel,
    };
    if (meta.posted_date) args.posted_date = meta.posted_date;
    const out = await screenAndRecordPosting(args, d.screeningAdapter, d.record);
    if (out.isError) {
      res.errors.push(`${c.url} [${profile}]: ${out.content.slice(0, 200)}`);
      continue;
    }
    if (isActionable(out.content)) {
      res.passes.push({ url: c.url, title: c.title, ...meta, profile, channel: c.channel });
      return;
    }
  }
}

/** Process one candidate end to end. */
async function processCandidate(d: ScreenStageDeps, c: Candidate, res: ScreenStageResult): Promise<void> {
  const fetched = await d.fetch(c.url);
  if (fetched.unreadable) return recordBlocker(d, c, fetched.blocker, res);
  const meta = await extractMeta(d.extractAdapter, fetched.text, c.title);
  if (!meta.ok) return recordBlocker(d, c, meta.screening_blocker, res);
  await screenProfiles(d, c, fetched.text, meta.meta, res);
}

/**
 * Screen all candidates with bounded concurrency.
 *
 * @returns Actionable passes (in candidate order), blocker count and errors.
 */
export async function screenCandidates(candidates: Candidate[], d: ScreenStageDeps): Promise<ScreenStageResult> {
  const perCandidate: ScreenStageResult[] = candidates.map(() => ({ passes: [], blockers: 0, errors: [] }));
  let next = 0;
  const worker = async (): Promise<void> => {
    while (next < candidates.length) {
      const i = next++;
      try {
        await processCandidate(d, candidates[i], perCandidate[i]);
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
