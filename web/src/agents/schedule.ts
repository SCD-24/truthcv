/** Pure helpers for the Agents page's schedule section, split out so they
 * can be unit-tested without rendering React. */

/** Whether `s` is a 24-hour HH:MM time (00:00–23:59), the shape the agent's
 * `runAt` config and this page's Add control both expect. */
export function isValidRunTime(s: string): boolean {
  return /^([01]\d|2[0-3]):[0-5]\d$/.test(s);
}

/** The seven weekdays, Monday-first, keyed the way `AgentConfig.runDays`
 * stores them and labelled the way the checkbox row displays them. */
export const WEEKDAYS: { key: string; label: string }[] = [
  { key: "mon", label: "Mon" },
  { key: "tue", label: "Tue" },
  { key: "wed", label: "Wed" },
  { key: "thu", label: "Thu" },
  { key: "fri", label: "Fri" },
  { key: "sat", label: "Sat" },
  { key: "sun", label: "Sun" },
];

/** Render a list of run times as prose, e.g. "09:00 and 15:00". */
export function formatRunTimes(times: string[]): string {
  return times.join(" and ");
}
