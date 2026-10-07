import type { BoardBreakdown, BoardBreakdownTotal, RunRecord, RunUrlOutcome } from "../api/types";

/** Count columns of the funnel table, in display order. */
export type FunnelKey = Exclude<keyof BoardBreakdownTotal, never>;

export interface FunnelColumn {
  key: FunnelKey;
  label: string;
  tooltip: string;
  /** Ledger outcome for this column; undefined for "Postings seen". */
  outcome?: RunUrlOutcome;
}

export const FUNNEL_COLUMNS: FunnelColumn[] = [
  { key: "postingsSeen", label: "Postings seen", tooltip: "Unique links found from this source" },
  { key: "previouslyScreened", label: "Previously screened", outcome: "previously_screened", tooltip: "Screened in an earlier run, so skipped" },
  { key: "notAPosting", label: "Not a job page", outcome: "not_a_posting", tooltip: "Link isn't a job posting, e.g. a search or listing page" },
  { key: "duplicate", label: "Duplicate", outcome: "duplicate", tooltip: "Same job already found this run under another link" },
  { key: "failed", label: "Failed", outcome: "failed", tooltip: "Tried but no result could be saved" },
  { key: "forReview", label: "For review", outcome: "for_review", tooltip: "Passed screening; waiting for your approval" },
  { key: "rejected", label: "Rejected", outcome: "rejected", tooltip: "Screened and didn't match your criteria" },
  { key: "blocked", label: "Blocked", outcome: "blocked", tooltip: "Opened but couldn't be screened: expired, unreadable or not a job" },
];

/** Order in which outcome sections appear under an expanded source row. */
export const OUTCOME_SECTION_ORDER: FunnelColumn[] = ["failed", "blocked", "notAPosting", "duplicate", "forReview", "rejected", "previouslyScreened"].map(
  (key) => FUNNEL_COLUMNS.find((c) => c.key === key) as FunnelColumn,
);

/** Human label for a source row: host for direct, "<host> (search)" for dork, "<name> (feed)" for feed. */
export function sourceLabel(row: Pick<BoardBreakdown, "board" | "channel">): string {
  if (row.channel === "dork") return `${row.board} (search)`;
  if (row.channel === "feed") return `${row.board} (feed)`;
  return row.board.replace(/^[a-z][a-z0-9+.-]*:\/\//i, "").replace(/\/+$/, "");
}

/** The Total row: stored totals, or for a legacy run a sum with null for unknown columns. */
export function funnelTotals(run: RunRecord): Record<FunnelKey, number | null> {
  if (run.boardBreakdownTotal) return { ...run.boardBreakdownTotal };
  const sum = (key: FunnelKey): number | null =>
    run.boardBreakdown.some((r) => r[key] === null)
      ? null
      : run.boardBreakdown.reduce((acc, r) => acc + (r[key] ?? 0), 0);
  return Object.fromEntries(FUNNEL_COLUMNS.map((c) => [c.key, sum(c.key)])) as Record<FunnelKey, number | null>;
}

/** Warning text naming the sources whose counts did not add up, or null. */
export function mismatchMessage(run: RunRecord): string | null {
  if (!run.funnelMismatches.length) return null;
  const names = run.funnelMismatches.map((m) => (m === "totals" ? "the totals" : m));
  return `Some counts don't add up for: ${names.join(", ")}.`;
}

/** Format a count cell: null becomes an em dash. */
export function formatCount(value: number | null): string {
  return value === null ? "—" : String(value);
}
