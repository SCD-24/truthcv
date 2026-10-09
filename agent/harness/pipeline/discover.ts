/**
 * Code-driven discovery: turns the `job_config` JSON into harvest requests
 * (one per dork query and per direct board), runs them through the
 * harvestPostings core, records one `record_discovery_coverage` per composed
 * entry, and returns deduplicated, not-yet-screened candidates.
 */
import { harvestPostings } from '../builtins/harvestPostings.js';
import type { BrowserToolCall, HarvestBoardRequest, HarvestBoardResult } from '../builtins/harvestPostings.js';
import { GOOGLE_SORRY, noLock, parseResults, searchDorks, type DorkOutcome, type Lock } from './dorkSearch.js';
import { defaultDorkState, type DorkState } from './dorkState.js';
import type { Candidate, DiscoveryChannel, DroppedUrl, McpCall } from './types.js';

/** Max keywords typed into a direct board's search box. */
const MAX_DIRECT_KEYWORDS = 5;

/** One composed unit of discovery work and the profiles it serves. */
interface Entry {
  channel: 'dork' | 'direct';
  request: HarvestBoardRequest;
  profiles: string[];
  /** Source name the entry's postings are attributed to in the funnel. */
  source: string;
  /** Board name coverage is recorded under (a direct board shares one across its profiles). */
  coverageBoard: string;
}

type Coverage = ReturnType<typeof coverageFor>;

/** Coverage statuses from least to most severe (used to aggregate a board's profiles). */
const SEVERITY = ['empty', 'extraction_failed', 'login_walled', 'blocked'];
/** Board name the feed channel's failure is recorded under. */
const FEED_BOARD = 'feed';

/** Options for {@link discover}. */
export interface DiscoverOptions {
  /** Delay function (injectable for tests). */
  sleep?: (ms: number) => Promise<void>;
  /** Random source in [0, 1) (injectable for tests). Defaults to Math.random. */
  random?: () => number;
  /** Clock in epoch ms (injectable for tests). Defaults to Date.now. */
  now?: () => number;
  /** Persisted dork state (pacing, cooldown, deferred queries); absent means defaults and no persistence. */
  dorkState?: DorkState;
  /** Persists the dork state; returns an error string on failure. */
  saveDorkState?: (state: DorkState) => Promise<string | undefined>;
  /** Serializes browser use with other callers (e.g. posting fetches); sleeping never happens under it. */
  browserLock?: Lock;
  /** Called with each batch of candidates as it is discovered (feed, direct boards, then each dork). */
  onCandidates?: (batch: Candidate[]) => Promise<void>;
}

/** Default setTimeout-based sleep. */
const defaultSleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

/** Result of {@link discover}. */
export interface DiscoveryOutcome {
  candidates: Candidate[];
  /** Every discovered candidate (before the unscreened filter). */
  allCandidates: Candidate[];
  /** URLs the server dropped before screening, with reasons. */
  dropped: DroppedUrl[];
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
    out.push({ channel: 'dork', source: str(q.source) ?? 'google', coverageBoard: board, request: { board, url }, profiles: strList(q.profiles).length ? strList(q.profiles) : strList([q.profile]) });
  }
  return out;
}

/** Search keywords for a direct board: the first title keyword when present, else the leading generic keywords. */
function directKeywords(p: Record<string, unknown>): string | undefined {
  const title = strList(pick(p, 'title_keywords', 'titleKeywords'))[0];
  if (title) return title;
  return strList(p.keywords).slice(0, MAX_DIRECT_KEYWORDS).join(' ') || undefined;
}

/** One harvest entry for a direct board searched with one profile's criteria and one location. */
function directEntry(b: Record<string, unknown>, url: string, p: Record<string, unknown>, location?: string): Entry {
  const name = str(p.profile);
  const label = [name ? `[${name}]` : '', location ? `@ ${location}` : ''].filter(Boolean).join(' ');
  return {
    channel: 'direct',
    source: url,
    coverageBoard: url,
    profiles: name ? [name] : [],
    request: {
      board: label ? `${url} ${label}` : url,
      url,
      keywords: directKeywords(p),
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

/** Add candidates, deduplicating by URL and merging profile names and sources. */
function addCandidate(map: Map<string, Candidate>, url: string, title: string, channel: DiscoveryChannel, profiles: string[], source: string): void {
  const key = url.split('#')[0].trim();
  if (!key) return;
  const existing = map.get(key);
  if (!existing) {
    map.set(key, { url: key, title, channel, profiles: [...new Set(profiles)], sources: [{ source, channel }] });
    return;
  }
  existing.profiles = [...new Set([...existing.profiles, ...profiles])];
  if (!existing.sources.some((s) => s.source === source)) existing.sources.push({ source, channel });
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
    addCandidate(map, url, str(p.title) ?? '', 'feed', own.length ? own : all, source);
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

/** Record how many unique postings were seen; returns an error string on failure. */
async function recordPostingsSeen(mcp: McpCall, runId: string, count: number): Promise<string | undefined> {
  try {
    const res = await mcp('record_postings_seen', { run_id: runId, count });
    if (res.isError) return 'postings seen count not recorded';
    try {
      if ((JSON.parse(res.content) as { recorded?: boolean }).recorded === false) return 'postings seen count not recorded';
    } catch { /* non-JSON ok payload: treat as recorded */ }
    return undefined;
  } catch (err) {
    return `postings seen failed: ${err instanceof Error ? err.message : String(err)}`;
  }
}

/** Candidates kept for screening plus the URLs the server dropped. */
interface Filtered {
  candidates: Candidate[];
  dropped: DroppedUrl[];
}

/** Attach each dropped URL's discovery sources (unknown URLs are skipped). */
function withSources(rows: unknown, byUrl: Map<string, Candidate>): DroppedUrl[] {
  const out: DroppedUrl[] = [];
  for (const r of objs(rows)) {
    const c = byUrl.get(String(r.url));
    if (!c) continue;
    const d: DroppedUrl = { url: c.url, reason: r.reason as DroppedUrl['reason'], sources: c.sources };
    if (typeof r.duplicate_of === 'string') d.duplicate_of = r.duplicate_of;
    out.push(d);
  }
  return out;
}

/** Keep only URLs the server says are unscreened (all, if the call fails). */
async function filterUnscreened(mcp: McpCall, map: Map<string, Candidate>): Promise<Filtered> {
  const all = [...map.values()];
  if (all.length === 0) return { candidates: all, dropped: [] };
  try {
    const res = await mcp('filter_unscreened_urls', { urls: all.map((c) => c.url) });
    if (res.isError) return { candidates: all, dropped: [] };
    const parsed = JSON.parse(res.content) as { unscreened?: string[]; dropped?: unknown };
    const keep = new Set(parsed.unscreened ?? all.map((c) => c.url));
    return { candidates: all.filter((c) => keep.has(c.url)), dropped: withSources(parsed.dropped, map) };
  } catch {
    return { candidates: all, dropped: [] };
  }
}

/** Coverage for a dork: `deferred` when it was not searched, else mapped from the harvest result. */
function coverageOf(h: DorkOutcome): Coverage {
  if (h.deferredReason) return { status: 'deferred', reason: h.deferredReason, tier: '', found: 0 };
  return coverageFor(h.r);
}

/** Dorks deferred by the previous run first (stable within each group). */
function pendingFirst(dorks: Entry[], deferred: string[]): Entry[] {
  const pending = new Set(deferred);
  return [...dorks.filter((e) => pending.has(e.coverageBoard)), ...dorks.filter((e) => !pending.has(e.coverageBoard))];
}

/** Add one entry's postings to the run map and to a fresh batch, then hand the batch to `onCandidates`. */
async function ingest(e: Entry, r: HarvestBoardResult | undefined, map: Map<string, Candidate>, options: DiscoverOptions, errors: string[]): Promise<void> {
  const batch = new Map<string, Candidate>();
  for (const p of r?.postings ?? []) {
    addCandidate(map, p.url, p.title, e.channel, e.profiles, e.source);
    addCandidate(batch, p.url, p.title, e.channel, e.profiles, e.source);
  }
  await emit(batch, options, errors);
}

/** Hand a batch to `onCandidates` (errors are collected, never thrown). */
async function emit(batch: Map<string, Candidate>, options: DiscoverOptions, errors: string[]): Promise<void> {
  if (!options.onCandidates || batch.size === 0) return;
  try {
    await options.onCandidates([...batch.values()]);
  } catch (err) {
    errors.push(`candidate handler failed: ${err instanceof Error ? err.message : String(err)}`);
  }
}

/** Harvest all direct boards in one call under the browser lock. */
async function harvestDirects(directs: Entry[], call: BrowserToolCall, lock: Lock, errors: string[]): Promise<DorkOutcome[]> {
  if (!directs.length) return [];
  const res = await lock(() => harvestPostings({ boards: directs.map((e) => e.request) }, call, false));
  if (res.isError) errors.push(res.content);
  const parsed = res.isError ? [] : parseResults(res.content);
  return directs.map((_, i) => ({ r: parsed[i] }));
}

/** Record coverage for every entry (direct boards aggregated per board); errors are collected. */
async function recordAllCoverage(entries: Entry[], results: DorkOutcome[], mcp: McpCall, runId: string, errors: string[]): Promise<void> {
  const direct = new Map<string, Coverage[]>();
  for (let i = 0; i < entries.length; i++) {
    const e = entries[i];
    const cov = coverageOf(results[i] ?? {});
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
  const lock = options.browserLock ?? noLock;
  const state = options.dorkState ?? defaultDorkState();
  const directs = directEntries(jobConfig);
  const dorks = pendingFirst(dorkEntries(jobConfig), state.deferred);
  const map = new Map<string, Candidate>();
  const errors: string[] = [];
  await runFeed(jobConfig, mcp, runId, map, errors);
  await emit(new Map(map), options, errors);
  const directResults = await harvestDirects(directs, call, lock, errors);
  for (let i = 0; i < directs.length; i++) await ingest(directs[i], directResults[i].r, map, options, errors);
  const dorkResults = await searchDorks(dorks.map((e) => e.request), {
    call, lock, state, errors, saveState: options.saveDorkState,
    sleep: options.sleep ?? defaultSleep, random: options.random ?? Math.random, now: options.now ?? Date.now,
    onOutcome: (i, o) => ingest(dorks[i], o.r, map, options, errors),
  });
  await recordAllCoverage([...directs, ...dorks], [...directResults, ...dorkResults], mcp, runId, errors);
  if (map.size > 0) {
    const err = await recordPostingsSeen(mcp, runId, map.size);
    if (err) errors.push(err);
  }
  const filtered = options.onCandidates ? { candidates: [], dropped: [] } : await filterUnscreened(mcp, map);
  return { ...filtered, allCandidates: [...map.values()], coverageComplete: errors.length === 0, errors };
}
