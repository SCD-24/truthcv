/**
 * Code-driven discovery: turns the `job_config` JSON into harvest requests
 * (one per dork query and per direct board), runs them through the
 * harvestPostings core, records one `record_discovery_coverage` per composed
 * entry, and returns deduplicated, not-yet-screened candidates.
 */
import { harvestPostings } from '../builtins/harvestPostings.js';
import type { BrowserToolCall, HarvestBoardRequest, HarvestBoardResult } from '../builtins/harvestPostings.js';
import { isGoogleInterstitial } from '../builtins/harvestClassify.js';
import type { Candidate, DiscoveryChannel, McpCall } from './types.js';

/** Max keywords typed into a direct board's search box. */
const MAX_DIRECT_KEYWORDS = 5;
/** Pause between consecutive dork searches, to avoid tripping Google's rate limiting. */
const DORK_PACING_MS = 4000;
/** Consecutive Google-blocked dorks after which the remaining dorks are skipped. */
const MAX_CONSECUTIVE_GOOGLE_BLOCKS = 2;
/** Marker of Google's CAPTCHA interstitial. */
const GOOGLE_SORRY = 'google.com/sorry';

/** One composed unit of discovery work and the profiles it serves. */
interface Entry {
  channel: 'dork' | 'direct';
  request: HarvestBoardRequest;
  profiles: string[];
  /** Board name coverage is recorded under (a direct board shares one across its profiles). */
  coverageBoard: string;
}

type Coverage = ReturnType<typeof coverageFor>;

/** Coverage statuses from least to most severe (used to aggregate a board's profiles). */
const SEVERITY = ['skipped', 'empty', 'extraction_failed', 'login_walled', 'blocked'];
/** Board name the feed channel's failure is recorded under. */
const FEED_BOARD = 'feed';

/** Harvest outcome for one entry; `skipped` when never searched. */
interface Harvested {
  r?: HarvestBoardResult;
  skipped?: boolean;
}

/** Options for {@link discover}. */
export interface DiscoverOptions {
  /** Delay function (injectable for tests). */
  sleep?: (ms: number) => Promise<void>;
}

/** Default setTimeout-based sleep. */
const defaultSleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

/** Coverage recorded for a dork never searched because Google kept blocking. */
const SKIPPED_COVERAGE: Coverage = {
  status: 'skipped',
  reason: `not searched: Google blocked ${MAX_CONSECUTIVE_GOOGLE_BLOCKS} consecutive dorks; stopped to avoid further rate-limiting`,
  tier: '',
  found: 0,
};

/** True when a harvest result is a Google block/CAPTCHA interstitial. */
function isGoogleBlock(r: HarvestBoardResult | undefined): boolean {
  return r?.outcome === 'blocked' && (isGoogleInterstitial(r.url) || r.url.includes(GOOGLE_SORRY) || /google/i.test(r.note ?? ''));
}

/** Result of {@link discover}. */
export interface DiscoveryOutcome {
  candidates: Candidate[];
  /** True when every composed entry had its coverage recorded. */
  coverageComplete: boolean;
  errors: string[];
}

/** Read a field that may be snake_case or camelCase. */
function pick(o: Record<string, unknown>, a: string, b: string): unknown {
  return o[a] ?? o[b];
}

function str(v: unknown): string | undefined {
  return typeof v === 'string' && v.trim() ? v : undefined;
}

function strList(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : [];
}

function objs(v: unknown): Record<string, unknown>[] {
  return Array.isArray(v) ? v.filter((x): x is Record<string, unknown> => !!x && typeof x === 'object') : [];
}

/** Dork entries: one harvest request per `searchQueries` item. */
function dorkEntries(cfg: Record<string, unknown>): Entry[] {
  const out: Entry[] = [];
  for (const q of objs(cfg.searchQueries)) {
    const url = str(q.url);
    if (!url) continue;
    const board = `${str(q.source) ?? 'google'}: ${str(q.query) ?? url}`;
    out.push({ channel: 'dork', coverageBoard: board, request: { board, url }, profiles: strList(q.profiles).length ? strList(q.profiles) : strList([q.profile]) });
  }
  return out;
}

/** One harvest entry for a direct board searched with one profile's criteria and one location. */
function directEntry(b: Record<string, unknown>, url: string, p: Record<string, unknown>, location?: string): Entry {
  const name = str(p.profile);
  const label = [name ? `[${name}]` : '', location ? `@ ${location}` : ''].filter(Boolean).join(' ');
  return {
    channel: 'direct',
    coverageBoard: url,
    profiles: name ? [name] : [],
    request: {
      board: label ? `${url} ${label}` : url,
      url,
      keywords: strList(p.keywords).slice(0, MAX_DIRECT_KEYWORDS).join(' ') || undefined,
      location,
      searchUrl: str(pick(b, 'search_url', 'searchUrl')),
      postingUrlPattern: str(pick(b, 'posting_url_pattern', 'postingUrlPattern')),
    },
  };
}

/** Direct-board entries: one harvest per (board, profile, location); no location = one harvest without. */
function directEntries(cfg: Record<string, unknown>): Entry[] {
  const out: Entry[] = [];
  for (const b of objs(cfg.directBoards)) {
    const url = str(b.url);
    if (!url) continue;
    const profiles = objs(b.profiles);
    for (const p of profiles.length ? profiles : [{}]) {
      const locations = strList(p.locations);
      for (const loc of locations.length ? locations : [undefined]) out.push(directEntry(b, url, p, loc));
    }
  }
  return out;
}

/** Aggregate one direct board's per-profile coverage: searched if any searched, else the worst status. */
export function aggregateCoverage(covs: Coverage[]): Coverage {
  const searched = covs.filter((c) => c.status === 'searched');
  if (searched.length) return { ...searched[0], found: searched.reduce((n, c) => n + c.found, 0) };
  return covs.reduce((worst, c) => (SEVERITY.indexOf(c.status) > SEVERITY.indexOf(worst.status) ? c : worst), covs[0]);
}

/** Map a harvest result to a coverage status/reason. */
export function coverageFor(r: HarvestBoardResult | undefined): { status: string; reason: string; tier: string; found: number } {
  if (!r) return { status: 'extraction_failed', reason: 'harvest returned no result', tier: '', found: 0 };
  const sorry = r.url.includes(GOOGLE_SORRY) || r.note.includes(GOOGLE_SORRY) || (r.rawSnapshot ?? '').includes(GOOGLE_SORRY);
  if (sorry) return { status: 'blocked', reason: 'Google CAPTCHA (/sorry)', tier: '', found: 0 };
  if (r.outcome === 'searched') return { status: 'searched', reason: '', tier: 'harvest', found: r.postings.length };
  if (r.outcome === 'empty') return { status: 'empty', reason: r.note, tier: '', found: 0 };
  if (r.outcome === 'blocked') {
    return { status: r.blockKind === 'login' ? 'login_walled' : 'blocked', reason: r.note, tier: '', found: 0 };
  }
  return { status: 'extraction_failed', reason: r.note || 'extraction matched nothing', tier: '', found: 0 };
}

/** Record one coverage entry; returns an error string when recording failed. */
async function recordCoverage(mcp: McpCall, runId: string, channel: DiscoveryChannel, board: string, c: Coverage): Promise<string | undefined> {
  try {
    const res = await mcp('record_discovery_coverage', {
      run_id: runId, channel, board, status: c.status, postings_found: c.found, reason: c.reason, tier: c.tier,
    });
    return res.isError || /"recorded"\s*:\s*false/.test(res.content) ? `coverage not recorded for ${board}` : undefined;
  } catch (err) {
    return `coverage failed for ${board}: ${err instanceof Error ? err.message : String(err)}`;
  }
}

/** Parse the harvest tool's JSON into results (empty on failure). */
function parseResults(content: string): HarvestBoardResult[] {
  try {
    const parsed = JSON.parse(content) as { results?: HarvestBoardResult[] };
    return Array.isArray(parsed.results) ? parsed.results : [];
  } catch {
    return [];
  }
}

/** Add candidates, deduplicating by URL and merging profile names. */
function addCandidate(map: Map<string, Candidate>, url: string, title: string, channel: DiscoveryChannel, profiles: string[]): void {
  const key = url.split('#')[0].trim();
  if (!key) return;
  const existing = map.get(key);
  if (!existing) {
    map.set(key, { url: key, title, channel, profiles: [...new Set(profiles)] });
    return;
  }
  existing.profiles = [...new Set([...existing.profiles, ...profiles])];
}

/** Names of the enabled profiles in job_config.profiles. */
function enabledProfiles(cfg: Record<string, unknown>): string[] {
  return objs(cfg.profiles).filter((p) => p.enabled === true).map((p) => str(p.name) ?? '').filter(Boolean);
}

/** Feed postings: candidates plus one api-tier coverage entry per source (or a failed one on a feed error). */
async function runFeed(cfg: Record<string, unknown>, mcp: McpCall, runId: string, map: Map<string, Candidate>, errors: string[]): Promise<void> {
  const bySource = new Map<string, number>();
  const all = enabledProfiles(cfg);
  for (const p of objs(cfg.feedPostings)) {
    const url = str(p.url);
    if (!url) continue;
    const source = str(p.source) ?? 'feed';
    bySource.set(source, (bySource.get(source) ?? 0) + 1);
    const own = strList([p.profile]);
    addCandidate(map, url, str(p.title) ?? '', 'feed', own.length ? own : all);
  }
  const feedError = str(cfg.feedError);
  if (feedError) {
    // Also for a PARTIAL failure: surface it (run not complete) without dropping the postings that did arrive.
    errors.push(`feed ${bySource.size === 0 ? 'failed' : 'partially failed'}: ${feedError}`);
    const err = await recordCoverage(mcp, runId, 'feed', FEED_BOARD, { status: 'extraction_failed', reason: feedError, tier: 'api', found: 0 });
    if (err) errors.push(err);
  }
  for (const [source, found] of bySource) {
    const err = await recordCoverage(mcp, runId, 'feed', source, { status: 'searched', reason: '', tier: 'api', found });
    if (err) errors.push(err);
  }
}

/** Keep only URLs the server says are unscreened (all, if the call fails). */
async function filterUnscreened(mcp: McpCall, map: Map<string, Candidate>): Promise<Candidate[]> {
  const all = [...map.values()];
  if (all.length === 0) return all;
  try {
    const res = await mcp('filter_unscreened_urls', { urls: all.map((c) => c.url) });
    if (res.isError) return all;
    const keep = new Set((JSON.parse(res.content) as { unscreened?: string[] }).unscreened ?? all.map((c) => c.url));
    return all.filter((c) => keep.has(c.url));
  } catch {
    return all;
  }
}

/**
 * Harvest dork entries sequentially with pacing; after too many consecutive Google blocks the rest are skipped.
 *
 * @param dorks Dork entries in order.
 * @param call Browser tool caller.
 * @param sleep Delay function.
 * @param errors Collects harvest tool errors.
 */
async function harvestDorks(dorks: Entry[], call: BrowserToolCall, sleep: (ms: number) => Promise<void>, errors: string[]): Promise<Harvested[]> {
  const out: Harvested[] = [];
  let blocks = 0;
  for (let i = 0; i < dorks.length; i++) {
    if (blocks >= MAX_CONSECUTIVE_GOOGLE_BLOCKS) { out.push({ skipped: true }); continue; }
    if (i > 0) await sleep(DORK_PACING_MS);
    const res = await harvestPostings({ boards: [dorks[i].request] }, call, false);
    if (res.isError) errors.push(res.content);
    const r = res.isError ? undefined : parseResults(res.content)[0];
    blocks = isGoogleBlock(r) ? blocks + 1 : 0;
    out.push({ r });
  }
  return out;
}

/**
 * Run discovery for one run.
 *
 * @param jobConfig Parsed `agent-config.js job_config` JSON.
 * @param runId The run to attribute coverage to.
 * @param call Browser tool caller used by the harvest core.
 * @param mcp MCP tool caller (coverage, dedupe filter).
 * @param options Optional overrides (sleep).
 */
export async function discover(jobConfig: Record<string, unknown>, runId: string, call: BrowserToolCall, mcp: McpCall, options: DiscoverOptions = {}): Promise<DiscoveryOutcome> {
  const sleep = options.sleep ?? defaultSleep;
  const entries = [...directEntries(jobConfig), ...dorkEntries(jobConfig)];
  const map = new Map<string, Candidate>();
  const errors: string[] = [];
  await runFeed(jobConfig, mcp, runId, map, errors);
  const directs = entries.filter((e) => e.channel === 'direct');
  let results: Harvested[] = [];
  if (directs.length) {
    const res = await harvestPostings({ boards: directs.map((e) => e.request) }, call, false);
    if (res.isError) errors.push(res.content);
    const parsed = res.isError ? [] : parseResults(res.content);
    results = directs.map((_, i) => ({ r: parsed[i] }));
  }
  results.push(...(await harvestDorks(entries.filter((e) => e.channel === 'dork'), call, sleep, errors)));
  const direct = new Map<string, Coverage[]>();
  for (let i = 0; i < entries.length; i++) {
    const e = entries[i];
    const { r, skipped } = results[i] ?? {};
    const cov = skipped ? SKIPPED_COVERAGE : coverageFor(r);
    for (const p of r?.postings ?? []) addCandidate(map, p.url, p.title, e.channel, e.profiles);
    if (e.channel === 'direct') {
      direct.set(e.coverageBoard, [...(direct.get(e.coverageBoard) ?? []), cov]);
      continue;
    }
    const err = await recordCoverage(mcp, runId, e.channel, e.coverageBoard, cov);
    if (err) errors.push(err);
  }
  for (const [board, covs] of direct) {
    const err = await recordCoverage(mcp, runId, 'direct', board, aggregateCoverage(covs));
    if (err) errors.push(err);
  }
  return { candidates: await filterUnscreened(mcp, map), coverageComplete: errors.length === 0, errors };
}
