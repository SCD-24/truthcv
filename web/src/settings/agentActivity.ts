import type { ScreeningRecord } from "../api/types";

/**
 * The newest date TruthCV can honestly attribute to the unattended agent's
 * activity, derived from the screening ledger — the agent is the only writer
 * of screening records, so the newest one is a genuine (if indirect) signal
 * that it recently did something. Split out from the Settings modal so it
 * can be unit-tested without rendering React.
 *
 * Prefers each record's `screenedDate`; falls back to `createdAt` when that
 * field is empty. Returns the raw (unformatted) date string of the newest
 * usable record, or `null` when there are no records or none of their dates
 * parse — deliberately so an absent or unparseable date reads as "hasn't run
 * yet" rather than risking a wrong or misleading date being displayed.
 */
export function lastAgentActivity(screenings: ScreeningRecord[]): string | null {
  let best: { raw: string; time: number } | null = null;
  for (const record of screenings) {
    const raw = record.screenedDate || record.createdAt;
    if (!raw) continue;
    const time = new Date(raw).getTime();
    if (Number.isNaN(time)) continue;
    if (!best || time > best.time) {
      best = { raw, time };
    }
  }
  return best ? best.raw : null;
}
