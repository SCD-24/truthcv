// agent/schedule.mjs — zone-aware "seconds until the next scheduled slot"
// maths, extracted from supervisor.js so it can be unit-tested in isolation.
// Node 22, ESM, zero dependencies.
//
// WHY this exists: the original inline version resolved each HH:MM slot with
// Date.setHours, which silently uses the HOST's local time zone. A container
// scheduled for "09:00 in Europe/Berlin" would fire at 09:00 UTC unless the
// host happened to be Berlin. This module resolves every wall-clock slot in an
// explicit IANA zone via Intl.DateTimeFormat, so the answer no longer depends
// on where the process runs.

const DAY_MS = 86_400_000;

// Intl.DateTimeFormat construction is comparatively expensive and the scan loop
// touches the same zone hundreds of times, so cache one formatter per zone.
const _formatters = new Map();

/**
 * The formatter used to read an instant back as zone-local calendar fields.
 * 'en-US' + hour12:false gives stable 24-hour numeric parts; we never parse the
 * locale's weekday text (that would be locale-dependent), we derive the weekday
 * from the Y/M/D instead.
 * @param {string} timeZone - IANA zone name, already validated by resolveZone.
 * @returns {Intl.DateTimeFormat}
 */
function formatterFor(timeZone) {
  let fmt = _formatters.get(timeZone);
  if (!fmt) {
    fmt = new Intl.DateTimeFormat("en-US", {
      timeZone,
      hour12: false,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
    _formatters.set(timeZone, fmt);
  }
  return fmt;
}

/**
 * Return null-safe zone name: an unresolvable zone falls back to 'UTC' rather
 * than throwing, so a bad config value degrades to a sane default instead of
 * crashing the scheduler. Resolution is attempted once here and the result is
 * threaded through every helper.
 * @param {string} timeZone
 * @returns {string} the requested zone, or 'UTC' if Intl rejects it.
 */
function resolveZone(timeZone) {
  try {
    // Constructing the formatter throws for an unknown zone; do it now so the
    // rest of the module can assume the zone is usable.
    new Intl.DateTimeFormat("en-US", { timeZone });
    return timeZone;
  } catch {
    return "UTC";
  }
}

/**
 * Convert an instant into its zone-local calendar parts.
 * @param {number} ms - epoch milliseconds.
 * @param {string} timeZone - validated IANA zone name.
 * @returns {{year:number, month:number, day:number, hour:number, minute:number, second:number, isoDow:number}}
 *   month is 1-12; isoDow is the ISO weekday (Mon=1 … Sun=7) of the local date.
 */
function zonedParts(ms, timeZone) {
  const parts = {};
  for (const { type, value } of formatterFor(timeZone).formatToParts(ms)) {
    if (type !== "literal") parts[type] = value;
  }
  const year = +parts.year;
  const month = +parts.month;
  const day = +parts.day;
  // Some engines render midnight as hour "24"; normalise it to 0.
  let hour = +parts.hour;
  if (hour === 24) hour = 0;
  const minute = +parts.minute;
  const second = +parts.second;
  // Derive the weekday from the local Y/M/D (a UTC calendar walk) so it never
  // depends on the host zone or on locale weekday text.
  const jsDay = new Date(Date.UTC(year, month - 1, day)).getUTCDay();
  const isoDow = ((jsDay + 6) % 7) + 1;
  return { year, month, day, hour, minute, second, isoDow };
}

/**
 * Signed offset (local-minus-UTC) in ms that the zone was applying at `ms`,
 * i.e. Date.UTC(local parts) - ms. Positive east of UTC.
 * @param {number} ms
 * @param {string} timeZone
 * @returns {number}
 */
function zoneOffsetMs(ms, timeZone) {
  const p = zonedParts(ms, timeZone);
  return Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second) - ms;
}

/**
 * Does `ms` land on exactly the requested zone-local wall clock (to the minute)?
 * Used to reject a candidate instant whose requested local time does not exist
 * (spring-forward gap) — the round-trip parts will differ.
 * @returns {boolean}
 */
function localMatches(ms, y, m, d, hh, mm, timeZone) {
  const p = zonedParts(ms, timeZone);
  return p.year === y && p.month === m && p.day === d && p.hour === hh && p.minute === mm;
}

/**
 * Spring-forward gap: the requested local time never occurs, so fire at the
 * transition instant — the first instant whose local wall clock has passed the
 * requested time (i.e. the moment the offset shifts forward). Found by bisecting
 * between the two invalid candidates, which bracket the transition.
 * @param {number} guess - Date.UTC(local fields), the requested time as if UTC.
 * @param {number} a - one invalid candidate instant.
 * @param {number} b - the other invalid candidate instant.
 * @returns {number} the transition instant, to the millisecond.
 */
function gapTransitionMs(guess, a, b, timeZone) {
  let lo = Math.min(a, b); // local-as-UTC < guess
  let hi = Math.max(a, b); // local-as-UTC >= guess
  while (hi - lo > 1) {
    const mid = lo + Math.floor((hi - lo) / 2);
    if (mid + zoneOffsetMs(mid, timeZone) >= guess) hi = mid;
    else lo = mid;
  }
  return hi;
}

/**
 * Resolve "zone-local Y-M-D at HH:MM" to a single epoch-ms instant, DST and all.
 *
 * Start from a guess that treats the wall-clock fields as if they were UTC, then
 * subtract the zone offset to land on the real instant. Because a DST boundary
 * can change the offset between the guess and the corrected instant, we probe
 * the offset a day either side of the boundary (offBefore / offAfter) and test
 * both corrected candidates:
 *   - normal day: both candidates coincide and are valid.
 *   - fall-back (time occurs twice): both candidates are valid; return the
 *     EARLIER one (the pre-transition offset) so the slot fires exactly once.
 *   - spring-forward (time does not exist): neither candidate round-trips to the
 *     requested wall clock, so fire at the first valid instant after the gap.
 * @returns {number} epoch milliseconds for the slot.
 */
function resolveSlotInstant(y, m, d, hh, mm, timeZone) {
  const guess = Date.UTC(y, m - 1, d, hh, mm);
  const candBefore = guess - zoneOffsetMs(guess - DAY_MS, timeZone);
  const candAfter = guess - zoneOffsetMs(guess + DAY_MS, timeZone);
  const beforeOk = localMatches(candBefore, y, m, d, hh, mm, timeZone);
  const afterOk = localMatches(candAfter, y, m, d, hh, mm, timeZone);
  if (beforeOk && afterOk) return Math.min(candBefore, candAfter);
  if (beforeOk) return candBefore;
  if (afterOk) return candAfter;
  return gapTransitionMs(guess, candBefore, candAfter, timeZone);
}

/**
 * Parse a single "HH:MM" entry. Malformed entries (no colon, NaN hour/minute)
 * return null and are skipped by the caller — matching the original behaviour.
 * @param {string} t
 * @returns {{hh:number, mm:number}|null}
 */
function parseHhmm(t) {
  const parts = t.split(":");
  if (parts.length < 2) return null;
  const hh = parseInt(parts[0], 10);
  const mm = parseInt(parts[1], 10);
  if (Number.isNaN(hh) || Number.isNaN(mm)) return null;
  return { hh, mm };
}

/**
 * Seconds until the next scheduled slot, resolved as wall-clock times in an
 * explicit IANA zone.
 *
 * Scans calendar day offsets 0..8 from today's ZONE-LOCAL date, considers every
 * slot on each allowed weekday, and returns the SMALLEST strictly-positive delta
 * in seconds, or -1 when no slot falls inside the window. For timeZone 'UTC'
 * this returns exactly what the original host-local implementation returned when
 * the host itself was UTC.
 *
 * DST handling (see resolveSlotInstant for the mechanics):
 *   - Spring forward — a slot on a local time that does not exist fires ONCE, at
 *     the first valid instant after the gap (the moment the clock jumps forward).
 *   - Fall back — a slot on a local time that occurs twice fires ONCE, at the
 *     EARLIER occurrence.
 * The weekday filter uses the ZONE-LOCAL weekday of the candidate calendar date,
 * not the host's and not the UTC weekday of the resulting instant.
 *
 * An unresolvable timeZone falls back to 'UTC' instead of throwing.
 *
 * @param {number} nowMs - epoch milliseconds representing "now".
 * @param {string} runAt - comma-separated HH:MM wall-clock times (unsorted;
 *   malformed entries are skipped), e.g. "09:00,15:00,03:00".
 * @param {string} runDays - comma-separated ISO weekdays 1-7 (Mon=1 … Sun=7).
 * @param {string} [timeZone='UTC'] - IANA zone name; falls back to 'UTC'.
 * @returns {number} seconds until the next slot (> 0), or -1 if none found.
 */
export function secondsUntilNextSlot(nowMs, runAt, runDays, timeZone = "UTC") {
  const tz = resolveZone(timeZone);
  const nowSec = Math.floor(nowMs / 1000);
  const slots = String(runAt)
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  const allowedDays = String(runDays)
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

  const today = zonedParts(nowMs, tz);
  let best = -1;

  for (let offset = 0; offset <= 8; offset++) {
    // Walk zone-local calendar dates (a UTC calendar walk is correct here: we
    // are advancing the DATE, not shifting an instant across DST).
    const cal = new Date(Date.UTC(today.year, today.month - 1, today.day + offset));
    const isoDow = ((cal.getUTCDay() + 6) % 7) + 1;
    if (!allowedDays.includes(String(isoDow))) continue;

    const y = cal.getUTCFullYear();
    const m = cal.getUTCMonth() + 1;
    const d = cal.getUTCDate();
    for (const t of slots) {
      const hm = parseHhmm(t);
      if (!hm) continue;
      const targetSec = Math.floor(resolveSlotInstant(y, m, d, hm.hh, hm.mm, tz) / 1000);
      const delta = targetSec - nowSec;
      if (delta <= 0) continue;
      if (best === -1 || delta < best) best = delta;
    }
  }

  return best;
}
