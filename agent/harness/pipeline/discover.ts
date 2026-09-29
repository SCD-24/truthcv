/**
 * Code-driven discovery: turns the `job_config` JSON into harvest requests
 * (one per dork query and per direct board), runs them through the
 * harvestPostings core, records one `record_discovery_coverage` per composed
 * entry, and returns deduplicated, not-yet-screened candidates.
 */
import { harvestPostings } from '../builtins/harvestPostings.js';
import type { BrowserToolCall, HarvestBoardRequest, HarvestBoardResult } from '../builtins/harvestPostings.js';
import type { Candidate, DiscoveryChannel, McpCall } from './types.js';

/** Max keywords typed into a direct board's search box. */
const MAX_DIRECT_KEYWORDS = 5;
/** Marker of Google's CAPTCHA interstitial. */
const GOOGLE_SORRY = 'google.com/sorry';

/** One composed unit of discovery work and the profiles it serves. */
interface Entry {
  channel: 'dork' | 'direct';
  request: HarvestBoardRequest;
  profiles: string[];
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
    out.push({ channel: 'dork', request: { board, url }, profiles: strList(q.profiles).length ? strList(q.profiles) : strList([q.profile]) });
  }
  return out;
}

/** Direct-board entries: keywords/location come from the board's profiles. */
function directEntries(cfg: Record<string, unknown>): Entry[] {
  const out: Entry[] = [];
  for (const b of objs(cfg.directBoards)) {
    const url = str(b.url);
    if (!url) continue;
    const profiles = objs(b.profiles);
    const first = profiles.find((p) => strList(p.keywords).length) ?? profiles[0] ?? {};
    const keywords = strList(first.keywords).slice(0, MAX_DIRECT_KEYWORDS).join(' ') || undefined;
    out.push({
      channel: 'direct',
      profiles: profiles.map((p) => str(p.profile) ?? '').filter(Boolean),
      request: {
        board: url,
        url,
        keywords,
        location: strList(first.locations)[0],
        searchUrl: str(pick(b, 'search_url', 'searchUrl')),
        postingUrlPattern: str(pick(b, 'posting_url_pattern', 'postingUrlPattern')),
      },
    });
  }
  return out;
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
async function recordCoverage(mcp: McpCall, runId: string, channel: DiscoveryChannel, board: string, c: ReturnType<typeof coverageFor>): Promise<string | undefined> {
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

/** Feed postings: candidates plus one api-tier coverage entry per source. */
async function runFeed(cfg: Record<string, unknown>, mcp: McpCall, runId: string, map: Map<string, Candidate>, errors: string[]): Promise<void> {
  const bySource = new Map<string, number>();
  for (const p of objs(cfg.feedPostings)) {
    const url = str(p.url);
    if (!url) continue;
    const source = str(p.source) ?? 'feed';
    bySource.set(source, (bySource.get(source) ?? 0) + 1);
    addCandidate(map, url, str(p.title) ?? '', 'feed', strList([p.profile]));
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
 * Run discovery for one run.
 *
 * @param jobConfig Parsed `agent-config.js job_config` JSON.
 * @param runId The run to attribute coverage to.
 * @param call Browser tool caller used by the harvest core.
 * @param mcp MCP tool caller (coverage, dedupe filter).
 */
export async function discover(jobConfig: Record<string, unknown>, runId: string, call: BrowserToolCall, mcp: McpCall): Promise<DiscoveryOutcome> {
  const entries = [...dorkEntries(jobConfig), ...directEntries(jobConfig)];
  const map = new Map<string, Candidate>();
  const errors: string[] = [];
  let results: HarvestBoardResult[] = [];
  if (entries.length) {
    const res = await harvestPostings({ boards: entries.map((e) => e.request) }, call, false);
    results = res.isError ? [] : parseResults(res.content);
    if (res.isError) errors.push(res.content);
  }
  for (let i = 0; i < entries.length; i++) {
    const e = entries[i];
    const r = results[i];
    const cov = coverageFor(r);
    const err = await recordCoverage(mcp, runId, e.channel, e.request.board, cov);
    if (err) errors.push(err);
    for (const p of r?.postings ?? []) addCandidate(map, p.url, p.title, e.channel, e.profiles);
  }
  await runFeed(jobConfig, mcp, runId, map, errors);
  return { candidates: await filterUnscreened(mcp, map), coverageComplete: errors.length === 0, errors };
}
