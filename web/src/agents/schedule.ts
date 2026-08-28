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

/** The zone assumed when an agent config carries none, matching the backend's
 * `run_timezone` default so the UI and server agree on what "no zone" means. */
export const DEFAULT_TIMEZONE = "UTC";

/** The zones offered in the schedule picker. Sourced from the engine's own
 * `Intl.supportedValuesOf('timeZone')` when available so the list stays current,
 * with a small curated fallback for older engines and test environments where
 * that API is absent. `'UTC'` is always first and never duplicated, since it is
 * the default and the most common choice. */
export const TIMEZONES: string[] = buildTimezones();

function buildTimezones(): string[] {
  const fallback = [
    "UTC",
    "Europe/London",
    "Europe/Berlin",
    "Europe/Paris",
    "Europe/Madrid",
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "Asia/Tokyo",
    "Asia/Singapore",
    "Australia/Sydney",
  ];
  // `supportedValuesOf` may not be in the configured lib typings, so narrow it
  // through a typed local rather than reaching for `any` or `@ts-ignore`.
  const intl = Intl as unknown as {
    supportedValuesOf?: (key: string) => string[];
  };
  let zones = fallback;
  if (typeof intl.supportedValuesOf === "function") {
    try {
      const supported = intl.supportedValuesOf("timeZone");
      if (Array.isArray(supported) && supported.length > 0) {
        zones = supported;
      }
    } catch {
      zones = fallback;
    }
  }
  // UTC first, exactly once.
  return ["UTC", ...zones.filter((z) => z !== "UTC")];
}

/** Whether `tz` names a zone this engine can actually format in. A stored zone
 * can be anything, and a bad one must disable Save rather than throw during
 * render, so we probe it here instead of trusting the string. */
export function isValidTimezone(tz: string): boolean {
  if (!tz) return false;
  try {
    new Intl.DateTimeFormat(undefined, { timeZone: tz });
    return true;
  } catch {
    return false;
  }
}

/** Render an ISO timestamp as a locale date-time string IN `tz`, including the
 * short zone name, so a displayed run time can never be mistaken for the
 * viewer's local clock. Falls back to DEFAULT_TIMEZONE when `tz` is missing or
 * invalid, and returns the raw input (or "") for an unparseable timestamp — it
 * must never throw during render. */
export function formatInZone(iso: string, tz?: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso ?? "";
  const timeZone = tz && isValidTimezone(tz) ? tz : DEFAULT_TIMEZONE;
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone,
    timeZoneName: "short",
  });
}
