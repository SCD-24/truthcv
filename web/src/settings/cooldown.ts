/**
 * Pure cooldown predicate for screening records, split out from the Settings
 * modal so it can be unit-tested without rendering React.
 *
 * A record with no `cooldownExpires`, or one the browser can't parse as a
 * date, deliberately reads as NOT in cooldown rather than throwing or
 * treating it as indefinitely blocked — a malformed or missing timestamp
 * must never silently keep a company off-limits forever.
 */
export function isCooldownActive(
  cooldownExpires: string,
  now: Date = new Date(),
): boolean {
  if (!cooldownExpires) return false;
  const expires = new Date(cooldownExpires);
  if (Number.isNaN(expires.getTime())) return false;
  return expires.getTime() > now.getTime();
}
