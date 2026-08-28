import { describe, it, expect } from 'vitest';

import { secondsUntilNextSlot } from '../schedule.mjs';

/**
 * Build a fixed epoch (ms) from UTC calendar fields. Thin wrapper over
 * Date.UTC so the tests read in wall-clock terms; `month` is 1-based here
 * (unlike Date.UTC's 0-based month) to match how humans write dates.
 */
function utc(
  year: number,
  month: number,
  day: number,
  hour = 0,
  minute = 0,
  second = 0,
): number {
  return Date.UTC(year, month - 1, day, hour, minute, second);
}

const ALL_DAYS = '1,2,3,4,5,6,7';
const HOUR = 3600;

describe('secondsUntilNextSlot — UTC parity', () => {
  // 2026-01-01 is a Thursday (ISO weekday 4). A single 09:00 slot one hour
  // ahead of an 08:00 "now" is exactly 3600 seconds away.
  it('returns the exact second delta to a single same-day UTC slot', () => {
    const now = utc(2026, 1, 1, 8, 0, 0);
    expect(secondsUntilNextSlot(now, '09:00', '4', 'UTC')).toBe(HOUR);
  });
});

describe('secondsUntilNextSlot — nearest future slot from an unsorted list', () => {
  const SLOTS = '09:00,15:00,03:00,18:00,07:00';

  it('picks 09:00 when now is 08:00', () => {
    const now = utc(2026, 1, 1, 8, 0, 0);
    expect(secondsUntilNextSlot(now, SLOTS, ALL_DAYS, 'UTC')).toBe(1 * HOUR);
  });

  it('picks 07:00 when now is 06:30', () => {
    const now = utc(2026, 1, 1, 6, 30, 0);
    expect(secondsUntilNextSlot(now, SLOTS, ALL_DAYS, 'UTC')).toBe(30 * 60);
  });

  it('picks 18:00 when now is 16:00 (skipping the earlier passed slots)', () => {
    const now = utc(2026, 1, 1, 16, 0, 0);
    expect(secondsUntilNextSlot(now, SLOTS, ALL_DAYS, 'UTC')).toBe(2 * HOUR);
  });

  it('rolls over to the next day 03:00 when now is 20:00 (all today passed)', () => {
    const now = utc(2026, 1, 1, 20, 0, 0);
    // 20:00 -> next day 03:00 = 7 hours.
    expect(secondsUntilNextSlot(now, SLOTS, ALL_DAYS, 'UTC')).toBe(7 * HOUR);
  });
});

describe('secondsUntilNextSlot — weekday filter uses the ZONE-local weekday', () => {
  // 2026-01-01 23:00 UTC is still Thursday in UTC, but in Europe/Berlin
  // (UTC+1 in winter) it is already 2026-01-02 00:00 — a Friday (ISO 5).
  const now = utc(2026, 1, 1, 23, 0, 0);

  it('treats the Berlin-local Friday as "today"', () => {
    // Slot 06:00 Berlin on 2026-01-02 = 05:00 UTC; 6 hours after now.
    expect(secondsUntilNextSlot(now, '06:00', '5', 'Europe/Berlin')).toBe(6 * HOUR);
  });

  it('does not treat the UTC Thursday as "today" (skips to next Berlin Thursday)', () => {
    // Berlin-local dates: Jan 2 (Fri) ... next Thursday is Jan 8.
    // Jan 8 06:00 Berlin = 05:00 UTC; from Jan 1 23:00 UTC that is 540000 s.
    expect(secondsUntilNextSlot(now, '06:00', '4', 'Europe/Berlin')).toBe(540_000);
  });
});

describe('secondsUntilNextSlot — spring-forward (DST gap)', () => {
  // 2026-03-29 (Sunday, ISO 7) Europe/Berlin springs forward: 02:00 CET jumps
  // to 03:00 CEST, so local 02:30 never occurs. The transition instant is
  // 01:00 UTC. The 02:30 slot must fire exactly once, at that instant.
  it('fires the 02:30 slot at the first valid instant after the gap', () => {
    const now = utc(2026, 3, 29, 0, 0, 0); // 01:00 CET, one hour before the jump
    // Transition instant is 01:00 UTC = one hour after now.
    expect(secondsUntilNextSlot(now, '02:30', '7', 'Europe/Berlin')).toBe(1 * HOUR);
  });

  it('does not fire the 02:30 slot a second time once now is past the transition', () => {
    const now = utc(2026, 3, 29, 1, 0, 0); // exactly the transition instant
    // Next fire is the following Sunday 2026-04-05 02:30 CEST = 00:30 UTC.
    // From 2026-03-29 01:00 UTC that is 7 days minus 30 minutes = 603000 s.
    expect(secondsUntilNextSlot(now, '02:30', '7', 'Europe/Berlin')).toBe(603_000);
  });
});

describe('secondsUntilNextSlot — fall-back (ambiguous local time)', () => {
  // 2026-10-25 (Sunday, ISO 7) Europe/Berlin falls back: 03:00 CEST returns to
  // 02:00 CET, so local 02:30 occurs twice — first at 00:30 UTC (CEST), then at
  // 01:30 UTC (CET). The slot must fire once, at the EARLIER occurrence.
  it('fires the ambiguous 02:30 slot at the earlier occurrence', () => {
    const now = utc(2026, 10, 25, 0, 0, 0); // 02:00 CEST, before either 02:30
    // Earlier occurrence is 00:30 UTC = 30 minutes after now.
    expect(secondsUntilNextSlot(now, '02:30', '7', 'Europe/Berlin')).toBe(30 * 60);
  });

  it('does not fire again at the later occurrence once now is past the earlier one', () => {
    const now = utc(2026, 10, 25, 0, 30, 0); // exactly the earlier occurrence
    // Next fire is the following Sunday 2026-11-01 02:30 CET = 01:30 UTC.
    // From 2026-10-25 00:30 UTC that is 7 days + 1 hour = 608400 s — NOT the
    // 01:30 UTC later occurrence on the same day.
    expect(secondsUntilNextSlot(now, '02:30', '7', 'Europe/Berlin')).toBe(608_400);
  });
});

describe('secondsUntilNextSlot — degenerate inputs', () => {
  it('falls back to UTC for an unresolvable time zone instead of throwing', () => {
    const now = utc(2026, 1, 1, 8, 0, 0); // Thursday (ISO 4)
    let result: number | undefined;
    expect(() => {
      result = secondsUntilNextSlot(now, '09:00', '4', 'Not/AZone');
    }).not.toThrow();
    // Same answer as the UTC parity case: 09:00 UTC is one hour ahead.
    expect(result).toBe(1 * HOUR);
  });

  it('returns -1 when runDays is empty', () => {
    const now = utc(2026, 1, 1, 8, 0, 0);
    expect(secondsUntilNextSlot(now, '09:00', '', 'UTC')).toBe(-1);
  });
});
