/**
 * Analytics for the outbound application ledger.
 *
 * A pure, side-effect-free layer over the existing `Application[]` (as returned
 * by `listApplications()`): it derives every metric the analytics page shows,
 * so the page itself stays a thin renderer and the maths is unit-testable in
 * isolation. No React, no API calls, no I/O.
 *
 * All rates are guarded against divide-by-zero (an empty or zero-denominator
 * segment reports a rate of 0), matching the ledger's "quiet until it means
 * something" register.
 */

import type { Application } from "../api/types";

/** How old (in days) a submitted-but-silent application must be to be flagged. */
export const NEEDS_ATTENTION_DAYS = 14;

/** Raw counts over the whole ledger. */
export interface Totals {
  total: number;
  submitted: number;
  drafts: number;
  docsAttached: number;
}

/** Headline rates, each already guarded against a zero denominator. */
export interface Rates {
  responseRate: number;
  outreachRate: number;
  docAttachRate: number;
}

/** Response rate split by whether the user reached out. */
export interface ResponseByOutreach {
  withOutreach: SegmentRate;
  withoutOutreach: SegmentRate;
}

/** One categorical segment (a status, submission type, or method) with its
 * per-segment response rate inputs. */
export interface Breakdown {
  label: string;
  count: number;
  submitted: number;
  responded: number;
}

/** One month bucket of the applications-over-time series. */
export interface MonthBucket {
  month: string;
  applied: number;
  responded: number;
  cumulativeApplied: number;
  cumulativeResponded: number;
}

/** A data-quality gap: an application missing a field worth filling in. */
export interface DataGap {
  id: string;
  company: string;
  missing: string[];
}

/** The full analytics snapshot for one ledger. */
export interface Insights {
  totals: Totals;
  rates: Rates;
  responseByOutreach: ResponseByOutreach;
  byStatus: Breakdown[];
  bySubmissionType: Breakdown[];
  byMethod: Breakdown[];
  timeSeries: MonthBucket[];
  needsAttention: Application[];
  dataGaps: DataGap[];
}

/** A per-segment response rate, guarded against a zero denominator. */
export interface SegmentRate {
  submitted: number;
  responded: number;
  rate: number;
}

/** Divide guarded against a zero (or missing) denominator. */
function rate(numerator: number, denominator: number): number {
  return denominator > 0 ? numerator / denominator : 0;
}

/** True when the application counts as attached to at least one document. */
function hasDocument(app: Application): boolean {
  return app.cvDocument != null || app.coverLetterDocument != null;
}

/** Raw counts over the whole ledger. */
function computeTotals(apps: Application[]): Totals {
  const submitted = apps.filter((a) => a.submitted).length;
  return {
    total: apps.length,
    submitted,
    drafts: apps.length - submitted,
    docsAttached: apps.filter(hasDocument).length,
  };
}

/** Headline rates derived from the totals and the raw list. */
function computeRates(apps: Application[], totals: Totals): Rates {
  const responded = apps.filter((a) => a.responseReceived).length;
  const reachedOut = apps.filter((a) => a.reachedOut).length;
  return {
    responseRate: rate(responded, totals.submitted),
    outreachRate: rate(reachedOut, totals.total),
    docAttachRate: rate(totals.docsAttached, totals.total),
  };
}

/** Response rate for a subset, as a guarded {submitted, responded, rate}. */
function segmentRate(apps: Application[]): SegmentRate {
  const submitted = apps.filter((a) => a.submitted).length;
  const responded = apps.filter((a) => a.responseReceived).length;
  return { submitted, responded, rate: rate(responded, submitted) };
}

/** Response rate split by whether the user reached out. */
function computeResponseByOutreach(apps: Application[]): ResponseByOutreach {
  return {
    withOutreach: segmentRate(apps.filter((a) => a.reachedOut)),
    withoutOutreach: segmentRate(apps.filter((a) => !a.reachedOut)),
  };
}

/** Group applications into labelled breakdowns keyed by one field. */
function breakdownBy(
  apps: Application[],
  key: (app: Application) => string,
): Breakdown[] {
  const groups = new Map<string, Application[]>();
  for (const app of apps) {
    const label = key(app) || "—";
    const bucket = groups.get(label) ?? [];
    bucket.push(app);
    groups.set(label, bucket);
  }
  return [...groups.entries()]
    .map(([label, rows]) => toBreakdown(label, rows))
    .sort((a, b) => b.count - a.count);
}

/** Turn a labelled group of rows into a Breakdown with its response counts. */
function toBreakdown(label: string, rows: Application[]): Breakdown {
  return {
    label,
    count: rows.length,
    submitted: rows.filter((a) => a.submitted).length,
    responded: rows.filter((a) => a.responseReceived).length,
  };
}

/** The `YYYY-MM` bucket for a date, or null when blank/unparseable. */
function monthKey(date: string): string | null {
  if (!date) return null;
  const d = new Date(date);
  if (Number.isNaN(d.getTime())) return null;
  const month = `${d.getMonth() + 1}`.padStart(2, "0");
  return `${d.getFullYear()}-${month}`;
}

/** Count applied/responded per month, skipping blank/invalid dates. */
function tallyMonths(apps: Application[]): Map<string, MonthBucket> {
  const buckets = new Map<string, MonthBucket>();
  for (const app of apps) {
    const key = monthKey(app.applicationDate);
    if (!key) continue;
    const b = buckets.get(key) ?? emptyBucket(key);
    b.applied += 1;
    if (app.responseReceived) b.responded += 1;
    buckets.set(key, b);
  }
  return buckets;
}

/** A zero-filled month bucket for the given `YYYY-MM` key. */
function emptyBucket(month: string): MonthBucket {
  return {
    month,
    applied: 0,
    responded: 0,
    cumulativeApplied: 0,
    cumulativeResponded: 0,
  };
}

/**
 * Applications-per-month time series, chronologically ordered, with running
 * cumulative applied and responded totals. Rows with a blank or invalid
 * `applicationDate` are skipped rather than bucketed under an "unknown" month.
 */
function computeTimeSeries(apps: Application[]): MonthBucket[] {
  const ordered = [...tallyMonths(apps).values()].sort((a, b) =>
    a.month.localeCompare(b.month),
  );
  let applied = 0;
  let responded = 0;
  for (const bucket of ordered) {
    applied += bucket.applied;
    responded += bucket.responded;
    bucket.cumulativeApplied = applied;
    bucket.cumulativeResponded = responded;
  }
  return ordered;
}

/** Whole days elapsed since a date; null when blank/invalid. */
function daysSince(date: string, now: number): number | null {
  if (!date) return null;
  const then = new Date(date).getTime();
  if (Number.isNaN(then)) return null;
  return Math.floor((now - then) / (1000 * 60 * 60 * 24));
}

/**
 * Submitted applications that have gone silent: no response received and the
 * application date is at least NEEDS_ATTENTION_DAYS old.
 */
function computeNeedsAttention(apps: Application[], now: number): Application[] {
  return apps.filter((app) => {
    if (!app.submitted || app.responseReceived) return false;
    const age = daysSince(app.applicationDate, now);
    return age != null && age >= NEEDS_ATTENTION_DAYS;
  });
}

/** The missing-field labels for one application (empty when complete). */
function gapFields(app: Application): string[] {
  const missing: string[] = [];
  if (!app.website) missing.push("website");
  if (!app.applicationUrl || app.applicationUrl === "N/A")
    missing.push("application URL");
  if (!hasDocument(app)) missing.push("document");
  return missing;
}

/** Applications missing a website, application URL, or attached document. */
function computeDataGaps(apps: Application[]): DataGap[] {
  return apps
    .map((app) => ({
      id: app.id,
      company: app.company || "—",
      missing: gapFields(app),
    }))
    .filter((gap) => gap.missing.length > 0);
}

/**
 * Derive the full analytics snapshot from the application ledger.
 *
 * Pure: the same input always yields the same output for a fixed `now`. `now`
 * is injectable (defaulting to the current time) so age-based logic — the
 * needs-attention window — is deterministic under test.
 */
export function computeInsights(
  apps: Application[],
  now: number = Date.now(),
): Insights {
  const totals = computeTotals(apps);
  return {
    totals,
    rates: computeRates(apps, totals),
    responseByOutreach: computeResponseByOutreach(apps),
    byStatus: breakdownBy(apps, (a) => a.status),
    bySubmissionType: breakdownBy(apps, (a) => a.submissionType),
    byMethod: breakdownBy(apps, (a) => a.method),
    timeSeries: computeTimeSeries(apps),
    needsAttention: computeNeedsAttention(apps, now),
    dataGaps: computeDataGaps(apps),
  };
}
