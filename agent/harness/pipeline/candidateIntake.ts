/**
 * Turns discovery batches into screening work: dedupes postings across all
 * batches by posting key (tracking which profiles each was queued for), asks
 * the server which are unscreened (fail-open), queues those, and keeps the
 * dropped URLs (with sources) for the funnel.
 */
import type { CandidateQueue } from './candidateQueue.js';
import { postingKey } from './postingKey.js';
import type { Candidate, DroppedUrl, McpCall } from './types.js';

/** Intake handle. */
export interface CandidateIntake {
  /** Accept one discovery batch. */
  push: (batch: Candidate[]) => Promise<void>;
  /** URLs the server dropped before screening (plus cross-batch duplicates). */
  dropped: DroppedUrl[];
  /** Every first-seen candidate the intake accepted, profiles/sources merged. */
  accepted: Candidate[];
}

interface DroppedRow { url?: unknown; reason?: unknown; duplicate_of?: unknown }

/** Map server dropped rows to DroppedUrl (unknown URLs are skipped). */
function droppedFrom(rows: unknown, byUrl: Map<string, Candidate>): DroppedUrl[] {
  const out: DroppedUrl[] = [];
  for (const r of Array.isArray(rows) ? (rows as DroppedRow[]) : []) {
    const c = r && byUrl.get(String(r.url));
    if (!c) continue;
    const row: DroppedUrl = { url: c.url, reason: r.reason as DroppedUrl['reason'], sources: c.sources };
    if (typeof r.duplicate_of === 'string') row.duplicate_of = r.duplicate_of;
    out.push(row);
  }
  return out;
}

/** Ask the server which of `fresh` are unscreened; on any failure keep all. */
async function filterBatch(mcp: McpCall, fresh: Candidate[], dropped: DroppedUrl[]): Promise<Candidate[]> {
  try {
    const res = await mcp('filter_unscreened_urls', { urls: fresh.map((c) => c.url) });
    if (res.isError) return fresh;
    const parsed = JSON.parse(res.content) as { unscreened?: string[]; dropped?: unknown };
    const keep = new Set(parsed.unscreened ?? fresh.map((c) => c.url));
    dropped.push(...droppedFrom(parsed.dropped, new Map(fresh.map((c) => [c.url, c]))));
    return fresh.filter((c) => keep.has(c.url));
  } catch {
    return fresh;
  }
}

/** Merge a repeat sighting's profiles and sources into the intake's own record. */
function merge(prev: Candidate, c: Candidate): void {
  for (const p of c.profiles) if (!prev.profiles.includes(p)) prev.profiles.push(p);
  for (const s of c.sources) {
    if (!prev.sources.some((x) => x.source === s.source && x.channel === s.channel)) prev.sources.push(s);
  }
}

/**
 * Classify one candidate against what was already seen: the candidate to
 * queue (first sighting only), a duplicate drop (other URL, same posting), or
 * neither (identical URL repeated). Repeats never queue; they only merge.
 */
function classify(c: Candidate, seen: Map<string, Candidate>): { queue?: Candidate; duplicate?: DroppedUrl } {
  const key = postingKey(c.url) || c.url;
  const prev = seen.get(key);
  if (!prev) {
    seen.set(key, { ...c, profiles: [...c.profiles], sources: [...c.sources] });
    return { queue: c };
  }
  merge(prev, c);
  if (c.url === prev.url) return {};
  return { duplicate: { url: c.url, reason: 'duplicate', duplicate_of: prev.url, sources: c.sources } };
}

/**
 * Create the intake feeding `queue`.
 *
 * @param mcp MCP tool caller (filter_unscreened_urls).
 * @param queue Queue the unscreened candidates are pushed to.
 */
export function createIntake(mcp: McpCall, queue: CandidateQueue): CandidateIntake {
  const seen = new Map<string, Candidate>();
  const dropped: DroppedUrl[] = [];
  const push = async (batch: Candidate[]): Promise<void> => {
    const fresh: Candidate[] = [];
    for (const c of batch) {
      const r = classify(c, seen);
      if (r.queue) fresh.push(r.queue);
      if (r.duplicate) dropped.push(r.duplicate);
    }
    if (fresh.length === 0) return;
    queue.push(await filterBatch(mcp, fresh, dropped));
  };
  return { push, dropped, get accepted() { return [...seen.values()]; } };
}
