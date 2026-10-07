/**
 * Per-source run funnel: assigns every discovered URL exactly one outcome
 * (dropped before screening, or the screening stage's result) and rolls the
 * outcomes up per discovery source and in total.
 */
import type { Candidate, CandidateSource, DiscoveryChannel, DroppedUrl, McpCall } from './types.js';
import type { UrlOutcome } from './outcomes.js';

/** Detail for a URL that reached no outcome. */
export const NO_OUTCOME_DETAIL = 'no outcome recorded';

/** Every outcome column, in funnel order. */
export const FUNNEL_OUTCOMES = ['previously_screened', 'not_a_posting', 'duplicate', 'failed', 'for_review', 'rejected', 'blocked'] as const;

/** One funnel outcome. */
export type FunnelOutcome = (typeof FUNNEL_OUTCOMES)[number];

/** Outcome counts shared by source rows and the totals. */
export type FunnelCounts = Record<FunnelOutcome, number> & { postings_seen: number };

/** One discovery source's funnel row. */
export interface FunnelRow extends FunnelCounts {
  source: string;
  channel: DiscoveryChannel;
}

/** One URL's single outcome and the sources that found it. */
export interface FunnelUrl {
  url: string;
  outcome: FunnelOutcome;
  detail: string;
  sources: CandidateSource[];
}

/** The payload of `record_source_funnel` (minus run_id). */
export interface Funnel {
  sources: FunnelRow[];
  totals: FunnelCounts;
  urls: FunnelUrl[];
}

/** A zeroed counts record. */
function emptyCounts(): FunnelCounts {
  const counts = { postings_seen: 0 } as FunnelCounts;
  for (const k of FUNNEL_OUTCOMES) counts[k] = 0;
  return counts;
}

/** Detail text for a URL dropped by the server. */
function droppedDetail(d: DroppedUrl): string {
  return d.reason === 'duplicate' && d.duplicate_of ? `duplicate of ${d.duplicate_of}` : d.reason;
}

/** The single outcome of each URL: dropped reason, else screening outcome, else failed. */
function outcomeOf(c: Candidate, dropped: Map<string, DroppedUrl>, screened: Map<string, UrlOutcome>): { outcome: FunnelOutcome; detail: string } {
  const d = dropped.get(c.url);
  if (d) return { outcome: d.reason, detail: droppedDetail(d) };
  const s = screened.get(c.url);
  if (s) return { outcome: s.outcome, detail: s.detail };
  return { outcome: 'failed', detail: NO_OUTCOME_DETAIL };
}

/** Count one URL into a source's row (created on first sight). */
function bump(rows: Map<string, FunnelRow>, s: CandidateSource, outcome: FunnelOutcome): void {
  const key = `${s.channel}\u0000${s.source}`;
  const row = rows.get(key) ?? { source: s.source, channel: s.channel, ...emptyCounts() };
  row.postings_seen += 1;
  row[outcome] += 1;
  rows.set(key, row);
}

/** Parse the tool's reply: whether it recorded, and mismatch descriptions ([] when none or unparseable). */
function parseReply(content: string): { recorded: boolean; mismatches: string[] } {
  try {
    const parsed = JSON.parse(content) as { recorded?: unknown; mismatches?: unknown };
    return { recorded: parsed.recorded === true, mismatches: Array.isArray(parsed.mismatches) ? parsed.mismatches.map(String) : [] };
  } catch {
    return { recorded: false, mismatches: [] };
  }
}

/**
 * Store the funnel via `record_source_funnel`.
 *
 * @returns Error strings: a failed call, or each mismatch the server flagged (truncation is not an error).
 */
export async function recordFunnel(mcp: McpCall, runId: string, funnel: Funnel): Promise<string[]> {
  try {
    const res = await mcp('record_source_funnel', { run_id: runId, ...funnel });
    if (res.isError) return [`source funnel not recorded: ${res.content}`];
    const reply = parseReply(res.content);
    if (!reply.recorded) return ['source funnel not recorded: server refused (recorded:false)'];
    return reply.mismatches.map((m) => `source funnel mismatch: ${m}`);
  } catch (err) {
    return [`source funnel failed: ${err instanceof Error ? err.message : String(err)}`];
  }
}

/**
 * Build the funnel from discovery and screening results.
 *
 * @param allCandidates Every unique discovered URL.
 * @param dropped URLs the server dropped before screening.
 * @param outcomes Screening outcomes (one per screened candidate).
 */
export function buildFunnel(allCandidates: Candidate[], dropped: DroppedUrl[], outcomes: UrlOutcome[]): Funnel {
  const droppedBy = new Map(dropped.map((d) => [d.url, d]));
  const screenedBy = new Map(outcomes.map((o) => [o.url, o]));
  const rows = new Map<string, FunnelRow>();
  const totals = emptyCounts();
  const urls: FunnelUrl[] = [];
  for (const c of allCandidates) {
    const { outcome, detail } = outcomeOf(c, droppedBy, screenedBy);
    totals.postings_seen += 1;
    totals[outcome] += 1;
    for (const s of c.sources) bump(rows, s, outcome);
    urls.push({ url: c.url, outcome, detail, sources: c.sources });
  }
  return { sources: [...rows.values()], totals, urls };
}
